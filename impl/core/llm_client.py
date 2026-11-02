from __future__ import annotations

import contextvars
import os
from types import MethodType
import json
import re
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import json_repair
from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.db.in_memory import InMemoryDb
from agno.run.agent import RunErrorEvent, RunOutput, RunPausedEvent
from agno.tools.function import Function, FunctionCall
from .llm_router import DEFAULT_PROBE_WAIT_SECONDS, LlmEndpoint, LlmRouter
from openai import Omit, OpenAI

from .llm_tracing import trace_headers, trace_scope, traced_model_call
from .config import get_llm_config
from .config_schema import ConfigError, openai_compatible_base_url
from .portable_artifact import redact_forbidden_paths

if TYPE_CHECKING:
    from .structured_output import StructuredOutputSpec
    from .tool_loop import Step

# Session start timestamp: ensures sessions from different runs don't share context
SESSION_START_TIME = int(time.time())
_USE_CONFIG = object()
_ROUTER_REGISTRY_LOCK = threading.Lock()
_ROUTER_REGISTRY: dict[tuple[tuple[str, str, str, str], ...], LlmRouter] = {}
_LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost", "::1")


def _bypass_proxy_for_loopback() -> None:
    """httpx 认系统 HTTP_PROXY，但不认 macOS 的 127.* 例外。

    本机 LLM 中转（127.0.0.1:8060）会被 Clash 之类拦成空 502，探活失败后整池冷却。
    只把回环地址写入 NO_PROXY，远程 fallback 仍走代理。
    """
    for key in ("NO_PROXY", "no_proxy"):
        existing = [part.strip() for part in os.environ.get(key, "").split(",") if part.strip()]
        os.environ[key] = ",".join(dict.fromkeys([*existing, *_LOOPBACK_NO_PROXY]))


_bypass_proxy_for_loopback()


def _parse_tool_calls_with_aliases(self, tool_calls_data):
    # agno>=2.3 的 OpenAIChat.parse_tool_calls 是 @staticmethod，不能传 self。
    parsed = OpenAILike.parse_tool_calls(tool_calls_data)
    aliases = getattr(self, "logical_tool_aliases", {})
    for call in parsed:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and function.get("name") in aliases:
            function["name"] = aliases[function["name"]]
    return parsed


def _json_context_tools(tools: List[Any]) -> List[Any]:
    """Wrap tool entrypoints so tool results enter the model context as JSON text.

    Agno stringifies non-string tool returns with str(), which leaks Python repr
    (single quotes, True/False/None) into the model context. Wrapping at the LLM
    boundary keeps the model view byte-identical to the audit log, and leaves the
    tool layer's structured return contract intact for programmatic consumers.
    """
    from agno.tools import Function
    from ..tools.protocol import json_tool

    wrapped: List[Any] = []
    for tool in tools or []:
        if isinstance(tool, Function):
            copy = tool.model_copy(deep=False)
            if copy.entrypoint is not None:
                copy.entrypoint = json_tool(copy.entrypoint)
            wrapped.append(copy)
        elif callable(tool):
            wrapped.append(json_tool(tool))
        else:
            wrapped.append(tool)
    return wrapped


class JsonExtractionError(ValueError):
    """Raised when an LLM response cannot be parsed into a JSON value."""


def with_output_constraint(user: str, output_spec: "StructuredOutputSpec") -> str:
    """输出结构约束放在本轮 user 末尾时的确切文本。

    多轮追加里，后一轮把前一轮 user 原样放进 history；前一轮发出去的就是这个文本，必须逐字一致。
    """
    from .structured_output import render_output_constraint
    return user + "\n\n" + render_output_constraint(output_spec)


class OutputRejected(ValueError):
    """complete_json 拒收了一次模型产出（解析失败或结构化强校验不通过）。

    `content` 是被拒收的模型原文：调用方的纠错轮把它作为上一轮 assistant 消息带回，
    纠错请求才是"新一轮追加"，前缀能命中缓存（report/process-axes-compare-20261009/CACHE-FINDINGS.md）。
    """

    def __init__(self, message: str, content: str):
        super().__init__(message)
        self.content = content


def _json_error_summary(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} at line {exc.lineno} column {exc.colno} (char {exc.pos})"


def _escape_stray_quotes(text: str) -> str:
    """Escape unescaped ``"`` inside JSON strings (typically quoted Chinese prose).

    Lexical only: inside a string, a ``"`` closes it iff what follows is a JSON continuation:
    ``:``; ``,`` then the start of a value; ``}``/``]`` then ``, } ]`` or the end. Any other ``"``
    is content and gets a backslash. The string content is unchanged, and the result is still
    parsed and schema-validated strictly.
    """
    def follows(j: int) -> int:
        while j < n and text[j] in " \t\r\n":
            j += 1
        return j

    def continues(j: int) -> bool:
        j = follows(j)
        if j >= n:
            return True
        if text[j] == ":":
            return True
        if text[j] == ",":
            k = follows(j + 1)
            return k < n and (text[k] in '"{[-' or text[k].isdigit() or text.startswith(("true", "false", "null"), k))
        if text[j] in "}]":
            k = follows(j + 1)
            return k >= n or text[k] in ",}]"
        return False

    out, in_str, i, n = [], False, 0, len(text)
    while i < n:
        c = text[i]
        if not in_str:
            out.append(c)
            in_str = c == '"'
        elif c == "\\":
            out.append(text[i:i + 2])
            i += 1
        elif c == '"':
            closes = continues(i + 1)
            out.append(c if closes else '\\"')
            in_str = not closes
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _loads_with_stray_quotes(text: str) -> Any:
    return json.loads(_escape_stray_quotes(text))


def _strict_json_error(text: str) -> str:
    """整段回复（去掉代码围栏）不是严格 JSON 时，给出语法错误位置与附近原文。"""
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.S)
    if fenced:
        body = fenced.group(1)
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        try:
            _loads_with_stray_quotes(body)
            return ""  # only stray quotes: extract_json reads it as the model meant
        except json.JSONDecodeError:
            pass
        near = body[max(0, exc.pos - 80):exc.pos + 40].replace("\n", " ")
        return (f"原始输出不是合法 JSON（{_json_error_summary(exc)}），附近原文：…{near}…；"
                "上面的结构错误来自自动修复的猜测。字符串里的英文双引号必须转义为 \\\" 或改用中文引号“”。")
    return ""


def extract_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return {}
    parse_errors: list[str] = []
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        parse_errors.append(f"whole response: {_json_error_summary(exc)}")
    # Try every fenced block in order. Many LLM outputs embed non-JSON
    # snippets (yaml configs, regex examples) inside ``` fences BEFORE the
    # actual JSON block — a non-greedy single match would silently grab the
    # first fence and drop the real JSON. Prefer json-tagged fences, then
    # any fence, then a bare-object fallback.
    fence_matches = list(re.finditer(r"```(\w+)?\s*(.*?)```", text, re.S))
    json_tagged = [m for m in fence_matches if (m.group(1) or "").lower() == "json"]
    untagged = [m for m in fence_matches if (m.group(1) or "").lower() not in {"json", ""}]
    any_tagged = fence_matches
    for group_name, group in (("json fenced block", json_tagged), ("non-json fenced block", untagged), ("any fenced block", any_tagged)):
        for m in group:
            body = m.group(2)
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"{group_name}: {_json_error_summary(exc)}")
            try:
                return _loads_with_stray_quotes(body)
            except json.JSONDecodeError:
                continue
    start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError as exc:
            parse_errors.append(f"bare JSON from first bracket: {_json_error_summary(exc)}")
    for candidate in ([text[start:]] if start >= 0 else []) + [text]:
        try:
            return _loads_with_stray_quotes(candidate)
        except json.JSONDecodeError:
            continue
    try:
        return json_repair.repair_json(text, return_objects=True)
    except Exception as exc:
        parse_errors.append(f"json_repair: {type(exc).__name__}: {exc}")
    preview = text[:500]
    detail = "; ".join(parse_errors[-4:]) if parse_errors else "no JSON object or array found"
    raise JsonExtractionError(
        "LLM 输出不是合法 JSON，且标准 JSON repair 未能修复，无法进入结构化校验。"
        f"解析错误：{detail}\n原始输出预览：{preview}"
    )


def _exact_json_objects(text: str) -> list[Dict[str, Any]]:
    """Return verbatim JSON objects embedded in a mixed model response."""
    decoder = json.JSONDecoder()
    objects: list[Dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        span = (start, start + consumed)
        if span in seen:
            continue
        seen.add(span)
        objects.append(value)
    return objects


def _usable_structured(content: str, output_spec: "StructuredOutputSpec") -> str:
    """端点这次的产出能不能当结构化输出来用；不能就返回原因。

    空产出、纯散文、以及「解析出来但不是对象」的内容都算不可用。不在这里判定 schema 是否
    完全合规（那是 enforce_output 的事），只判定「这份产出根本没法用」——否则端点会被记为成功、
    调用方在同一个坏端点上重试到耗尽，最后静默降级成空结果。
    """
    if output_spec is None:
        return ""
    try:
        parsed = extract_json(content)
    except JsonExtractionError as exc:
        return str(exc)
    parsed = _select_schema_matching_object(content, parsed, output_spec)
    if not isinstance(parsed, (dict, list)):
        return f"产出不是 JSON 对象，而是 {type(parsed).__name__}"
    return ""


def _select_schema_matching_object(
    text: str,
    parsed: Any,
    output_spec: "StructuredOutputSpec",
) -> Any:
    """Prefer an exact embedded object only when it already passes the spec.

    This does not repair or mutate a candidate. It only prevents unrelated
    leading prose/tool facts such as ``[10, 14]`` from becoming the top-level
    value when the response also contains the requested valid JSON object.
    """
    from .schema_validator import SchemaValidator

    validator = SchemaValidator(output_spec)
    if validator.is_valid(parsed, strict=True, allow_extra=False):
        return parsed
    for candidate in _exact_json_objects(text):
        if validator.is_valid(candidate, strict=True, allow_extra=False):
            return candidate
    return parsed


def _response_content(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    return str(content or "")


def _agno_input(messages: List[Dict[str, Any]]) -> tuple[str, List[Message]]:
    """OpenAI messages → (Agent.system_message, agno 输入消息)。

    system 交给 Agent 渲染，避免 agno 再拼一条；其余只保留回放需要的字段。
    """
    system = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    rest = [
        Message(**{key: m[key] for key in ("role", "content", "tool_calls", "tool_call_id") if key in m})
        for m in messages
        if m.get("role") != "system"
    ]
    return system, rest


def _run_agent(agent: Any, user: Any, *, stream: bool, wall_deadline: Optional[float] = None) -> Any:
    """跑一次 agent，返回完整的 RunOutput。

    stream=True 时走 SSE：中转站前面的网关（ALB 60s / Cloudflare 100s）超时看的是两次收包间隔，
    非流式要等整段生成完才回第一个字节，大 prompt 必撞超时。这里把事件流完整消费掉，
    只取最后那个完整的 RunOutput（yield_run_output=True），对下游来说和非流式返回的是同一种对象。
    流式出错时 agno 以 RunErrorEvent 收尾、不给 RunOutput：原样抛出，交给端点重试（否则错误文本会被
    当成模型回复）。流式暂停（外部执行的工具）也不给 RunOutput：从 agent 的 db 取回（见 _run_turn）。

    wall_deadline：整次调用的总时长上限（monotonic 时刻）。SDK 的 timeout 是读超时——流式连接只要
    不停滴字节（代理 keep-alive、上游排队时的心跳）就不算超时，总时长可以无限拖；实测出现过挂
    2497 秒才失败的连接。这里卡总时长兜底，到点抛 TimeoutError 走既有的端点切换重试。
    """
    if not stream:
        return agent.run(user)
    outcome = agent.run(user, stream=True, yield_run_output=True)
    if not isinstance(outcome, Iterator):
        # 不支持流式参数的 agent（测试替身/旧版本）直接给结果
        return outcome
    final = None
    last_event = None
    for event in _events_until(outcome, wall_deadline):
        last_event = event
        if isinstance(event, RunOutput):
            final = event
    if final is not None:
        return final
    if last_event is None:
        raise RuntimeError("streamed agent run produced no events")
    if isinstance(last_event, RunErrorEvent):
        raise RuntimeError(f"streamed agent run failed: {last_event.content or 'unknown error'}")
    if isinstance(last_event, RunPausedEvent):
        paused = agent.get_last_run_output()
        if paused is None:
            raise RuntimeError("streamed agent run paused but its RunOutput was not stored")
        return paused
    return last_event


def _events_until(events: Iterator[Any], wall_deadline: Optional[float]) -> Iterator[Any]:
    """逐个取事件，到 wall_deadline 就抛 TimeoutError。

    只在事件之间检查时间抓不住“连接没断、一个字节都不再来”的挂死（实测单次挂过 93 分钟）：
    next() 本身阻塞，检查永远轮不到。所以在守护线程里取事件，主线程按剩余时间等队列。
    超时后放弃该线程（守护线程，随连接最终断开退出），调用方走既有的端点切换重试。
    """
    if wall_deadline is None:
        yield from events
        return
    import queue

    box: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
    stop = threading.Event()

    def pump() -> None:
        try:
            for item in events:
                while not stop.is_set():
                    try:
                        box.put(("event", item), timeout=0.5)
                        break
                    except queue.Full:
                        continue
                if stop.is_set():
                    return
            box.put(("done", None))
        except BaseException as exc:  # 生成器里的异常原样交回主线程
            box.put(("error", exc))

    # 生成器在 pump 线程里推进（agno 自动执行的工具也在那里跑），带上调用方的 contextvars。
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(pump,), name="llm-stream", daemon=True).start()
    try:
        while True:
            remaining = wall_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("streamed llm call exceeded wall-clock deadline")
            try:
                kind, item = box.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("streamed llm call exceeded wall-clock deadline") from None
            if kind == "done":
                return
            if kind == "error":
                raise item
            yield item
    finally:
        stop.set()


def _external(function: Function) -> Function:
    """标成外部执行的副本（不改调用方的 Function）；和 _pause_every_call 一起保证工具不在请求里执行。"""
    copy = function.model_copy()
    copy.external_execution = True
    return copy


def _pause_every_call(model: Any) -> None:
    """让模型的每个工具调用都走外部执行暂停：一次 run 恰好一次模型请求，调用原样交回调用方。

    agno 对未知工具名/参数解析失败的调用会自己写错误结果并继续请求模型（一批全是这种调用时暂停
    条件不成立，run 会多发请求）。所以把整批都换成外部执行的占位调用；调用方从 assistant 消息的
    tool_calls 读原始调用，自己校验名字和参数。
    """
    placeholder = Function(name="external_tool_call", external_execution=True)

    def get_function_calls_to_run(assistant_message: Message, messages: List[Message],
                                  functions: Any = None) -> List[FunctionCall]:
        return [FunctionCall(function=placeholder, arguments={}, call_id=call.get("id"))
                for call in assistant_message.tool_calls or []]

    object.__setattr__(model, "get_function_calls_to_run", get_function_calls_to_run)


def _run_status(result: Any) -> str:
    status = getattr(result, "status", None)
    return str(getattr(status, "value", status) or "").strip().upper()


def _run_failed(result: Any) -> bool:
    return _run_status(result) in {"ERROR", "CANCELLED"}


def _endpoint_problem(result: Any) -> Optional[str]:
    """端点级不可用：run 失败 / 无产出 / 网关错误体。各壳在此之上叠加自己的验收。"""
    content = _response_content(result).strip()
    if _run_failed(result) or not content:
        return content or f"Agno run ended with status {_run_status(result)} and no response content"
    error_body = provider_error_body(content)
    if error_body:
        return f"endpoint returned provider error body: {error_body}"
    return None


# 端点级错误体：部分网关/中转站把上游错误（超长、欠费、限流）以 HTTP 200 纯文本返回，
# 内容非空但根本不是模型输出。这类响应必须计端点失败，否则 record_success 会把
# 死端点永久保持“健康”、永远不进探测（实测 8060 的 `Prompt too large (N chars)`
# 曾让 94% 调用打到欠费端点仍被记为 success）。
_PROVIDER_ERROR_BODY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^prompt too large \(\d+\s*chars?\)",
        r"maximum context length",
        r"context length exceeded",
        r"exceeded your current quota",
        r"insufficient (?:quota|balance|credit)",
        r"quota (?:exceeded|exhausted)",
        r"rate limit",
        r"too many requests",
        r"invalid api key",
        r"account (?:is )?(?:not active|in arrears)",
        r"余额不足",
        r"账户欠费",
        r"配额(?:不足|已用尽|超限)",
    )
)
_PROVIDER_ERROR_BODY_MAX_CHARS = 2000
_PROVIDER_ERROR_BODY_INLINE_MAX_CHARS = 200


def provider_error_body(content: str) -> str:
    """返回命中的端点错误体原文；不是端点错误时返回空串。

    两类：短纯文本错误体（配额/超长/欠费），以及**只有一个 error 键的 JSON 错误体**——
    中转站把上游 4xx 当 HTTP 200 回吐时就是后者（实测主端点回过
    `{"error": {"code": 400, "message": "User location is not supported for the API use."}}`，
    被当成模型产出、又因 schema 不符被阻断，整轴降级成空选段）。
    多键的结构化产出不在这里判：那是模型输出，交给结构化约束。
    """
    text = (content or "").strip()
    if not text or len(text) > _PROVIDER_ERROR_BODY_MAX_CHARS:
        return ""
    if text.startswith(("{", "[")):
        return _json_error_body(text)
    for pattern in _PROVIDER_ERROR_BODY_PATTERNS:
        match = pattern.search(text)
        if match and (match.start() == 0 or len(text) <= _PROVIDER_ERROR_BODY_INLINE_MAX_CHARS):
            return text[:_PROVIDER_ERROR_BODY_INLINE_MAX_CHARS]
    return ""


def _json_error_body(text: str) -> str:
    """只认「就一个 error 键」的 JSON 错误体；嵌套结构取两层内的 message/code 做摘要。"""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parsed, dict) or set(parsed) != {"error"}:
        return ""
    detail = parsed["error"]
    if isinstance(detail, dict):
        parts = [str(detail.get(key)) for key in ("code", "type", "status", "message") if detail.get(key)]
        summary = " ".join(parts)
    else:
        summary = str(detail)
    if not summary.strip():
        return ""
    return ("json error body: " + summary)[:_PROVIDER_ERROR_BODY_INLINE_MAX_CHARS]


def _raw_response(result: Any) -> Any:
    raw = getattr(result, "raw_response", None)
    if raw is not None:
        return raw
    if hasattr(result, "model_dump"):
        try:
            dump = result.model_dump()
            # Preserve metrics if available
            if hasattr(result, "metrics") and "metrics" not in dump:
                metrics = getattr(result, "metrics")
                if hasattr(metrics, "model_dump"):
                    dump["metrics"] = metrics.model_dump()
                elif isinstance(metrics, dict):
                    dump["metrics"] = metrics
            return dump
        except Exception:
            pass
    if hasattr(result, "to_dict"):
        try:
            dump = result.to_dict()
            if isinstance(dump, dict):
                # RunOutput can contain the entire prompt/message history.  Only keep
                # provider/run diagnostics here; ContextStore already records messages.
                return {
                    key: dump[key]
                    for key in ("content", "status", "model", "model_provider", "model_provider_data", "events", "metrics")
                    if key in dump and dump[key] not in (None, "", [], {})
                }
        except Exception:
            pass
    if isinstance(result, dict):
        return result
    response = {"content": _response_content(result)}
    # Try to extract metrics from Agno RunOutput
    if hasattr(result, "metrics"):
        metrics = getattr(result, "metrics")
        if hasattr(metrics, "model_dump"):
            response["metrics"] = metrics.model_dump()
        elif isinstance(metrics, dict):
            response["metrics"] = metrics
    return response


def chat_completions_url(base_url: str) -> str:
    """Build the raw Chat Completions endpoint from a validated API root."""
    root = openai_compatible_base_url(base_url, "llm.base_url")
    return f"{root}/chat/completions"


def _extract_tool_call_log(result: Any) -> list:
    """
    Extract tool-call records from an Agno RunOutput.

    Agno stores the conversation as `result.messages`, a list of Message objects.
    Each assistant Message may carry `.tool_calls` (a list of ToolCall objects with
    .function.name / .function.arguments). Each tool Message carries `.tool_call_id`
    and `.content` (the tool's return value). We pair them by tool_call_id.

    The function is defensive: it handles pydantic Messages, dict-shaped messages,
    and missing attributes, returning [] when nothing is found.
    """
    logs: list = []

    # 1. Locate the messages list on the result object.
    messages = getattr(result, "messages", None)
    if not messages:
        return []

    # 2. Build a tool_call_id -> tool_result map from tool messages.
    tool_results: Dict[str, Any] = {}
    for msg in messages:
        # Normalize to dict once for cheap attribute access.
        try:
            md = msg.model_dump() if hasattr(msg, "model_dump") else (
                msg if isinstance(msg, dict) else None
            )
        except Exception:
            md = None
        role = (md or {}).get("role") if isinstance(md, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        tcid = (md or {}).get("tool_call_id") if isinstance(md, dict) else getattr(msg, "tool_call_id", None)
        if not tcid:
            continue
        content = (md or {}).get("content") if isinstance(md, dict) else getattr(msg, "content", None)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        tool_results[tcid] = content

    # 3. Walk assistant messages, emit one log entry per tool_call.
    for msg in messages:
        try:
            md = msg.model_dump() if hasattr(msg, "model_dump") else (
                msg if isinstance(msg, dict) else None
            )
        except Exception:
            md = None
        role = (md or {}).get("role") if isinstance(md, dict) else getattr(msg, "role", None)
        if role != "assistant":
            continue
        tool_calls = (md or {}).get("tool_calls") if isinstance(md, dict) else getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            # tc may be a pydantic ToolCall or a dict.
            tcd = tc.model_dump() if hasattr(tc, "model_dump") else (
                tc if isinstance(tc, dict) else None
            )
            if not isinstance(tcd, dict):
                continue
            fn = tcd.get("function") or {}
            name = fn.get("name") or tcd.get("name") or ""
            args = fn.get("arguments") or tcd.get("arguments")
            tcid = tcd.get("id") or tcd.get("tool_call_id") or ""
            # arguments may arrive as a JSON string; parse it for readability.
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            entry = {
                "tool_name": name,
                "tool_call_id": tcid,
                "arguments": args,
                "result": tool_results.get(tcid),
            }
            logs.append(entry)
    return logs


_TOOL_LIMIT_REFUSAL = "Tool call limit reached."


def _executed_tool_calls(tool_call_log: list) -> int:
    """只数 SDK 真正执行了的调用。

    agno 到达 tool_call_limit 后不再执行，而是以固定文案回给模型；模型一轮并发发 2 个调用时，
    最后一轮常常多要 1–2 个被拒的。它们没花预算，也不该让随后给出的合法答案作废。
    """
    return sum(
        1 for entry in tool_call_log
        if not (isinstance(entry, dict) and isinstance(entry.get("result"), str)
                and entry["result"].startswith(_TOOL_LIMIT_REFUSAL))
    )


def _tool_budget_error(tool_call_log: list, limit: Optional[int]) -> Optional[str]:
    """Return a deterministic protocol error when an SDK run exceeds its budget."""
    if limit is None:
        return None
    executed = _executed_tool_calls(tool_call_log)
    if executed <= int(limit):
        return None
    return f"actual tool calls {executed} exceed configured limit {int(limit)}"


def _json_safe(value: Any) -> Any:
    """把消息里不可 JSON 序列化的子对象（如 pydantic ToolCall）拍成字符串。

    带工具调用的 RunOutput.messages 里藏着 ToolCall/Function 对象，直接存会让 save_context
    报错；而 _track_context 的异常是被吞掉的——实测用了工具的整理阶段整条调用记录会凭空消失，
    成本审计看不到。
    """
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _portable(value: Any) -> Any:
    """落档前按路径契约隐去本机绝对路径（规则在 portable_artifact，同一套谓词）。

    `_track_context` 的异常过去是被吞掉的，结果是「凡内容里带绝对路径的调用，记录静默消失」：
    实测整理阶段用了工具、模型把记录编号写成文件路径（tool_args.path），整条调用记录就没了。
    隐去而不是绕过契约：契约的目的是让产物可搬运，绕过去就把它废了；
    隐去后仍能看出「模型把路径当编号用了」。
    """
    return redact_forbidden_paths(value)


def _extract_messages(result: Any) -> List[Dict[str, Any]]:
    """从 Agno RunOutput 提取其返回的完整对话消息列表。

    该列表可能包含本次新增的 assistant/tool 消息，不等于发出的请求；
    context_store 将它另存到 response.run_messages。每个消息 {role, content, ...}。
    """
    messages = getattr(result, "messages", None)
    if not messages:
        return []
    out: List[Dict[str, Any]] = []
    for msg in messages:
        try:
            md = msg.model_dump() if hasattr(msg, "model_dump") else (
                msg if isinstance(msg, dict) else None
            )
        except Exception:
            md = None
        if isinstance(md, dict):
            out.append(_json_safe(md))
        else:
            # 退化兜底：直接按属性取
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", None)
            if role is not None or content is not None:
                out.append(_json_safe({"role": role, "content": content}))
    return out


def _track_context(self: "LlmClient", request: List[Dict[str, Any]], result: Any,
                   trace_id: str, token_metrics: Dict[str, Any],
                   elapsed_ms: int, error: Optional[str],
                   *, runtime: Optional[Dict[str, Any]] = None,
                   governance: Optional[Dict[str, Any]] = None) -> None:
    """把本次调用的请求消息与 Agno 返回的会话消息分别落档。

    messages 只记录发出的 request；response.run_messages 是 SDK 返回的会话视图，
    可能含本次新生成的消息，不能当作模型输入。
    只做记录，不阻断主流程；任何异常都吞掉。
    """
    try:
        from .context_store import save_context
        from .schema.context import ContextRecord
        messages = _portable([dict(m) for m in request])
        response: Dict[str, Any] = {}
        run_messages = _extract_messages(result) if result is not None else []
        if run_messages:
            response["run_messages"] = _portable(run_messages)
        content = _response_content(result) if result is not None else ""
        if content:
            response["content"] = content
        if token_metrics:
            response["metrics"] = token_metrics
        if runtime:
            response["runtime"] = runtime
        if error and result is not None:
            response["raw_response"] = _raw_response(result)
        prompt_size = sum(len(str(m.get("content") or "")) for m in messages)
        runtime_model = str((runtime or {}).get("selected_model") or "")
        if not runtime_model:
            attempts = list((runtime or {}).get("attempts") or [])
            if attempts:
                last_attempt_model = attempts[-1].get("model")
                runtime_model = str(last_attempt_model) if last_attempt_model else ""
        record = ContextRecord(
            record_id=str(uuid.uuid4()),
            trace_id=str(trace_id or ""),
            project_id=str(getattr(self, "_project_id", "") or ""),
            caller=str(getattr(self, "_caller", "") or "llm"),
            messages=messages,
            response=_portable(response) or None,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            prompt_size=int(prompt_size),
            llm_model=runtime_model or str(self.model or ""),
            elapsed_ms=int(elapsed_ms),
            error=_portable(error),
            governance=dict(governance or {}),
        )
        save_context(record)
    except Exception as exc:
        # 静默吞异常会把「记录失败」伪装成「没发生过」：实测工具调用记录整条消失就是这样
        # 藏了两轮的。不阻断主流程，但必须留痕。
        print(f"[context store] 调用记录落档失败: {type(exc).__name__}: {exc}")


def project_llm_client(spec: Any, role: str, knowledge: Any = None, tools: list = None,
                       tool_call_limit: Optional[int] = None,
                       compress_tool_results: bool = False,
                       max_tool_calls_from_history: Optional[int] = None) -> "LlmClient":
    """
    Create a stateless LLM client for one project role.

    Each call builds a fresh Agent with no db / memory / knowledge; information
    enters only through the prompt and tools.

    Args:
        spec: Project specification
        role: Role name (e.g., "judge", "attribute")
        knowledge: 不使用；调用方（含 eval_axes）仍传 knowledge=None，待其清理后删除
        tools: Optional list of tools to provide to the agent
        tool_call_limit: Cap on tool calls within one agent.run()
        compress_tool_results: If True, compress prior tool results
        max_tool_calls_from_history: Prune tool messages from history
    """
    project_id = str(getattr(spec, "project_id", "default") or "default")
    client = LlmClient(
        role=role,
        tools=tools,
        tool_call_limit=tool_call_limit,
        compress_tool_results=compress_tool_results,
        max_tool_calls_from_history=max_tool_calls_from_history,
    )
    client._project_id = project_id
    client._caller = role
    return client


class LlmClient:
    def __init__(
        self,
        role: str = "",
        config: Any = None,
        tools: list = None,
        tool_call_limit: Optional[int] = None,
        compress_tool_results: bool = False,
        max_tool_calls_from_history: Optional[int] = None,
    ):
        llm_config = config or get_llm_config()
        policy = llm_config.policy_for(role)
        self.role = role
        self.protocol = policy.protocol
        self.provider = policy.provider
        self.api_key = llm_config.api_key
        self.base_url = openai_compatible_base_url(policy.base_url, "llm.base_url")
        self.model = policy.model
        self.temperature = policy.temperature
        self.reasoning_effort = policy.reasoning_effort
        self.request_timeout_seconds = llm_config.request_timeout_seconds
        self.stream = bool(getattr(llm_config, "stream", True))
        self.capabilities = llm_config.capabilities
        self.llm_router = self._build_router(llm_config)
        self.tools = tools or []
        self.tool_call_limit = tool_call_limit
        self.compress_tool_results = compress_tool_results
        self.max_tool_calls_from_history = max_tool_calls_from_history
        # 没有可用端点时的退避等待（秒）。默认不等：生产请求快速失败；扩展轴等离线调用方按需设置。
        self.endpoint_wait_seconds: tuple[float, ...] = ()


    def _build_router(self, llm_config) -> LlmRouter:
        """构建端点到路由器：主端点 + 已配置的 fallback 端点。"""
        endpoints = [
            LlmEndpoint(
                name="primary",
                base_url=self.base_url,
                model=self.model,
                api_key=self.api_key,
                temperature=self.temperature,
                max_prompt_chars=getattr(llm_config, "max_prompt_chars", None),
                tool_calls=bool(getattr(llm_config, "tool_calls", True)),
            )
        ]
        for index, fb in enumerate(getattr(llm_config, "fallbacks", ()) or (), start=1):
            endpoints.append(
                LlmEndpoint(
                    name=f"fallback{index}",
                    base_url=fb.base_url,
                    model=fb.model,
                    api_key=fb.api_key,
                    temperature=self.temperature,
                    max_prompt_chars=getattr(fb, "max_prompt_chars", None),
                    tool_calls=bool(getattr(fb, "tool_calls", True)),
                )
            )
        registry_key = tuple(
            (endpoint.name, endpoint.base_url, endpoint.model, endpoint.api_key,
             endpoint.max_prompt_chars, endpoint.tool_calls, endpoint.temperature)
            for endpoint in endpoints
        )
        with _ROUTER_REGISTRY_LOCK:
            router = _ROUTER_REGISTRY.get(registry_key)
            if router is None:
                router = LlmRouter(endpoints, probe_fn=self._endpoint_probe)
                _ROUTER_REGISTRY[registry_key] = router
            return router

    @staticmethod
    def _endpoint_probe(endpoint: LlmEndpoint) -> bool:
        """用同一模型发送极短生成请求，验证真实调用链是否可用。"""
        probe_nonce = uuid.uuid4().hex[:12]
        with trace_scope(case_id="__health_probe__", independent=True):
            probe_headers = trace_headers(role="health_probe", stage=endpoint.name)
        client = OpenAI(
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            # 与路由器等待探活结果的时长一致，否则 HTTP 层先超时仍会被记成端点不健康。
            timeout=DEFAULT_PROBE_WAIT_SECONDS,
            max_retries=0,
            default_headers={"User-Agent": "verifier/1.0", **probe_headers},
        )
        try:
            response = client.chat.completions.create(
                model=endpoint.model,
                messages=[
                    {
                        "role": "user",
                        "content": f"Health probe {probe_nonce}. Reply with OK.",
                    }
                ],
                temperature=endpoint.temperature,
                max_tokens=4,
            )
            choices = getattr(response, "choices", None) or []
            if not choices:
                raise RuntimeError('供应商探活响应缺少 choices，无法确认生成成功')
            choice = choices[0]
            message = getattr(choice, "message", None)
            content = str(getattr(message, "content", "") or "").strip()
            reasoning_content = str(
                getattr(message, "reasoning_content", "") or ""
            ).strip()
            finish_reason = str(getattr(choice, "finish_reason", "") or "").strip()
            if not (content or reasoning_content or finish_reason):
                raise RuntimeError('供应商探活响应没有内容、推理内容或结束标记，无法确认生成成功')
            return True
        finally:
            # 异常交给 router 保留脱敏诊断；不能吞成 False，掩盖 HTTP/协议错误。
            client.close()
    def _validate_config(self, tools: Any = _USE_CONFIG) -> None:
        """配置/编程错误必须在重试、降级循环之外直接抛出。

        build_model 与各调用壳都先过这道校验：缺凭证、协议不支持等属于
        部署/编程错误，不能当作普通请求失败被吞掉后返回 llm_request_failed。
        """
        if self.protocol != "openai_compatible":
            raise ConfigError(f"unsupported LLM protocol: {self.protocol}")
        if not self.api_key:
            raise ConfigError("missing required configuration for llm: llm.api_key")
        if (self.tools if tools is _USE_CONFIG else tools) and not self.capabilities.tool_calls:
            raise ConfigError("configured LLM does not declare tool_calls capability")

    def build_model(
        self,
        *,
        reasoning_effort: Any = _USE_CONFIG,
        endpoint: Optional[LlmEndpoint] = None,
        trace_identity_headers: Optional[Dict[str, str]] = None,
    ) -> OpenAILike:
        """Build the single supported OpenAI-compatible model adapter."""
        self._validate_config()
        endpoint = endpoint or self.llm_router.select()
        model_kwargs = {
            "id": endpoint.model if endpoint else self.model,
            "provider": self.provider,
            "api_key": endpoint.api_key if endpoint else self.api_key,
            "base_url": endpoint.base_url if endpoint else self.base_url,
            "temperature": self.temperature,
            "timeout": self.request_timeout_seconds,
            # Some OpenAI-compatible gateways reject requests that identify as the
            # official OpenAI SDK (User-Agent + X-Stainless-* telemetry headers).
            # Send a neutral User-Agent and strip those SDK headers so the same
            # client works across DeepSeek, private gateways, and local proxies.
            "extra_headers": {
                **(trace_identity_headers or {}),
                "User-Agent": "verifier/1.0",
                "X-Stainless-Lang": Omit(),
                "X-Stainless-Package-Version": Omit(),
                "X-Stainless-Os": Omit(),
                "X-Stainless-Arch": Omit(),
                "X-Stainless-Runtime": Omit(),
                "X-Stainless-Runtime-Version": Omit(),
                "X-Stainless-Async": Omit(),
                "X-Stainless-Retry-Count": Omit(),
                "X-Stainless-Read-Timeout": Omit(),
            },
            # Keep one retry owner.  The verifier records and governs attempts
            # below; OpenAI SDK retries would otherwise be invisible and multiply
            # the configured wall-clock budget.
            "max_retries": 0,
            "supports_native_structured_outputs": False,
            "supports_json_schema_outputs": False,
        }
        effective_reasoning_effort = (
            self.reasoning_effort if reasoning_effort is _USE_CONFIG else reasoning_effort
        )
        if effective_reasoning_effort:
            model_kwargs["reasoning_effort"] = effective_reasoning_effort
        return OpenAILike(**model_kwargs)

    @traced_model_call
    def complete_json(self, system: str, user: str, trace_id: Optional[str] = None,
                      reasoning_effort: Any = _USE_CONFIG,
                      output_spec: "StructuredOutputSpec" = None,
                      stage: str = "",
                      tools_override: Any = _USE_CONFIG,
                      history: Optional[List[Dict[str, str]]] = None,
                      constraint_in_user: bool = False) -> Dict[str, Any]:
        """
        Complete JSON request with isolated session per trace.

        Args:
            system: System prompt
            user: User prompt
            trace_id: Optional trace ID for session isolation. If provided, creates a unique
                     session for this specific case/trace, preventing cross-case contamination.
            reasoning_effort: Reasoning effort level. Omitted values inherit the selected
                              role policy; explicit None disables deep reasoning.
            output_spec: spec/struct_output.md 结构化输出约束，**必填**。
                所有 LLM 调用都必须过结构化输出协议。如果实在没有明确输出结构（如自由文本分析），
                传 FREE_TEXT_OUTPUT（单字段 result: str）。
                协议层内部：
                - 注入 render_output_constraint 文案到 system prompt（兜底强化）
                - response_format 传 {"type":"json_object"}（DeepSeek 不支持 json_schema）
                - LLM 返回后跑 enforce_output，不合规直接抛 ValueError 阻断
            history: 夹在 system 与本轮 user 之间的前几轮消息（[{role, content}]）。纠错轮把原题与被拒收的
                产出放这里、更正说明作为本轮 user，前缀才能命中缓存。不合规的拒收抛 OutputRejected（带原文）。
            constraint_in_user: 输出结构约束放到本轮 user 末尾（with_output_constraint），system 保持逐字不变；
                同一会话里各轮输出结构不同、又要共享前缀缓存时使用。
        """
        if output_spec is None:
            raise TypeError(
                "complete_json 缺少 output_spec 参数。"
                "spec/struct_output.md 要求所有 LLM 调用必须传结构化输出约束。"
                "如果确实没有明确输出结构（如自由文本分析），请传 structured_output.FREE_TEXT_OUTPUT。"
            )
        if not self.capabilities.json_mode:
            raise ConfigError("configured LLM does not declare json_mode capability")
        self._validate_config()
        effective_tools = (
            self.tools
            if tools_override is _USE_CONFIG
            else list(tools_override or [])
        )
        model_tools = _json_context_tools(effective_tools)
        effective_tool_call_limit = (
            self.tool_call_limit if model_tools else None
        )
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        from .context_governance import ensure_call_context_governance
        ensure_call_context_governance(
            self,
            project_id=str(getattr(self, "_project_id", "") or "default"),
            role=str(
                getattr(self, "_caller", "")
                or getattr(self, "role", "")
                or "llm"
            ),
            stage=str(stage or "complete_json"),
            trace_id=str(trace_id),
            system=system,
            user="\n\n".join([str(m.get("content") or "") for m in history or []] + [user]),
            output_spec=output_spec,
            tools=effective_tools,
        )
        governance = dict(getattr(self, "_context_governance_report", {}) or {})

        # spec/struct_output.md：注入约束文案 + 返回后强校验阻断
        enforce_spec = output_spec
        from .structured_output import render_output_constraint
        request = [
            {"role": "system",
             "content": system if constraint_in_user else system + "\n\n" + render_output_constraint(enforce_spec)},
            *[{"role": m["role"], "content": m["content"]} for m in history or []],
            {"role": "user", "content": with_output_constraint(user, enforce_spec) if constraint_in_user else user},
        ]

        def problem(result: Any) -> Optional[str]:
            found = _endpoint_problem(result)
            if found:
                return found
            unusable = _usable_structured(_response_content(result).strip(), enforce_spec)
            return f"endpoint output unusable: {unusable}" if unusable else None

        try:
            outcome = self._run_turn(
                request,
                tools=model_tools,
                trace_id=trace_id,
                stage=stage,
                reasoning_effort=reasoning_effort,
                use_json_mode=True,
                tool_call_limit=effective_tool_call_limit,
                governance=governance,
                problem=problem,
            )
        except Exception as exc:
            return {"error": "llm_request_failed", "raw_text": str(exc)}
        result, runtime, token_metrics = outcome.result, outcome.runtime, outcome.token_metrics

        def track(error: Optional[str]) -> None:
            _track_context(
                self, request, result, trace_id, token_metrics, outcome.elapsed_ms(), error,
                runtime=runtime, governance=governance,
            )

        content = _response_content(result)
        status = _run_status(result)
        if _run_failed(result) or not content.strip():
            if _run_failed(result):
                error_code = "llm_request_failed"
                detail = content.strip() or f"Agno run ended with status {status} and no response content"
            else:
                error_code = "llm_empty_response"
                detail = "LLM run completed without response content"
            track(detail)
            return {
                "error": error_code,
                "raw_text": detail,
                "raw_model_response": _raw_response(result),
            }

        tool_call_log = _extract_tool_call_log(result)
        tool_budget_error = _tool_budget_error(
            tool_call_log, effective_tool_call_limit
        )
        if tool_budget_error:
            runtime["tool_budget"] = {
                "configured_limit": int(effective_tool_call_limit),
                "actual_calls": _executed_tool_calls(tool_call_log),
                "requested_calls": len(tool_call_log),
                "status": "exceeded",
            }
            track(tool_budget_error)
            return {
                "error": "tool_budget_exceeded",
                "raw_text": tool_budget_error,
                "tool_call_log": tool_call_log,
            }

        try:
            try:
                parsed = extract_json(content)
            except JsonExtractionError:
                parsed = None
            parsed = _select_schema_matching_object(content, parsed, enforce_spec)
            if parsed is None:
                # Re-run to preserve the full user-facing parse diagnostics.
                parsed = extract_json(content)
        except JsonExtractionError as exc:
            track(str(exc))
            raise OutputRejected(f"[{getattr(self, '_caller', '') or 'llm'}] {exc}", content) from exc
        raw_response = _raw_response(result)

        # spec/struct_output.md：强校验阻断，不放行假货
        from .structured_output import enforce_output
        caller = getattr(self, "_caller", "") or ""
        try:
            enforce_output(parsed, enforce_spec, caller=caller)
        except ValueError as exc:
            # 阻断的这次调用同样花了钱、产出了内容，必须留档：否则 context 页看不到
            # 首轮失败（reprompt 的来源），也看不到被丢弃的那份产出。
            # 原文本身不是合法 JSON 时，json_repair 的猜测结构不是模型的意图：把真正的语法错误告诉调用方，
            # 否则纠错反馈只会说"不是对象/多出字段"，模型无从修正。
            syntax = _strict_json_error(content)
            message = f"{exc}\n{syntax}" if syntax else str(exc)
            track(message)
            raise OutputRejected(message, content) from exc

        # Add token metrics to raw_response if available
        if token_metrics:
            if isinstance(raw_response, dict):
                raw_response["metrics"] = token_metrics

        track(None)
        if isinstance(parsed, dict):
            parsed.setdefault("raw_model_response", raw_response)
            if token_metrics:
                parsed.setdefault("metrics", token_metrics)
            if tool_call_log:
                parsed.setdefault("_tool_call_log", tool_call_log)
            return parsed
        return {"value": parsed, "raw_model_response": raw_response}

    @traced_model_call
    def complete_step(self, messages: List[Dict[str, Any]], functions: List[Any], *,
                      trace_id: str, stage: str) -> "Step":
        """ToolLoop 的一步：恰好一次模型请求（spec/adapter/tool-loop-plan §8.2）。

        模型给出的工具调用一律不执行（全部走 agno 的外部执行暂停），原样交回调用方，由 ToolLoop
        执行并回放。所以端点重试、超时、验收都只覆盖这一次请求，重试不会重复执行工具。
        没有输出契约；一次请求一条 context 记录。空产出（无文本也无工具调用）判端点问题重试。
        """
        from .tool_loop import Step

        self._validate_config(tools=functions)
        sent = sum(1 for m in messages if m.get("role") == "assistant")

        def reply(result: Any) -> Optional[Dict[str, Any]]:
            produced = [m for m in _extract_messages(result) if m.get("role") == "assistant"]
            return produced[-1] if len(produced) > sent else None

        def problem(result: Any) -> Optional[str]:
            if _run_failed(result):
                return _response_content(result).strip() or f"Agno run ended with status {_run_status(result)}"
            message = reply(result)
            if message is None or not (str(message.get("content") or "").strip() or message.get("tool_calls")):
                return f"Agno run ended with status {_run_status(result)} and no response content"
            error_body = provider_error_body(str(message.get("content") or ""))
            return f"endpoint returned provider error body: {error_body}" if error_body else None

        def prepare(model: OpenAILike) -> None:
            model.request_params = {**(model.request_params or {}), "parallel_tool_calls": True}
            _pause_every_call(model)

        outcome = self._run_turn(
            messages,
            tools=[_external(function) for function in functions],
            trace_id=trace_id,
            stage=stage,
            problem=problem,
            prepare_model=prepare,
            pause_tools=True,
        )
        result = outcome.result
        failure = problem(result)
        _track_context(
            self, messages, result, trace_id, outcome.token_metrics, outcome.elapsed_ms(),
            failure, runtime=outcome.runtime,
        )
        if failure:
            raise RuntimeError(failure)
        message = reply(result)
        return Step(message={key: message[key] for key in ("role", "content", "tool_calls") if message.get(key) is not None})

    def _run_turn(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Any],
        trace_id: str,
        stage: str,
        problem: Callable[[Any], Optional[str]],
        reasoning_effort: Any = _USE_CONFIG,
        use_json_mode: bool = False,
        tool_call_limit: Optional[int] = None,
        prepare_model: Optional[Callable[[OpenAILike], None]] = None,
        pause_tools: bool = False,
        governance: Optional[Dict[str, Any]] = None,
    ) -> "_TurnOutcome":
        """执行内核：端点路由/降级/重试 + 一次 agno run。

        problem(result) 是调用壳的验收：返回非空即判这次尝试失败、换端点重试。
        pause_tools：工具调用走 agno 的外部执行暂停。每次尝试给 agent 一个新的内存 db，流式暂停时
        只能从 db 取回 RunOutput（见 _run_agent）；db 不跨尝试，不累积历史。
        全部尝试都没有结果时抛最后一次异常（抛前先落 context 记录）；有结果就交回
        调用壳，由壳决定落档与返回。
        """
        start_ts = time.time()
        attempt_records: list[Dict[str, Any]] = []
        runtime: Dict[str, Any] = {
            "stage": str(stage or ""),
            "attempts": attempt_records,
            "sdk_max_retries": 0,
        }
        try:
            self.llm_router.refresh_health_if_stale()
            # 每个 trace 独立 session；无 db，不跨调用累积历史。
            effective_session_id = f"{trace_id}:{SESSION_START_TIME}"
            system, inputs = _agno_input(messages)

            # 声明了 prompt 上限的端点只服务装得下的请求；声明了不支持工具调用的端点不服务
            # 带工具的请求；超限/不服务就不发给它，避免白花一次调用并把「发出即被拒」当故障。
            # 全部端点都不服务时立即失败，不发请求。
            prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
            needs_tools = bool(tools)
            tried_endpoints: set[str] = {
                endpoint.name
                for endpoint in self.llm_router.endpoints
                if not endpoint.serves(prompt_chars, needs_tools=needs_tools)
            }
            if len(tried_endpoints) == len(self.llm_router.endpoints):
                raise RuntimeError(
                    f"prompt of {prompt_chars} chars (needs_tools={needs_tools}) exceeds every "
                    f"candidate endpoint's declared llm.max_prompt_chars / llm.*.tool_calls; "
                    f"refusing to send"
                )
            aliases = {}
            for function in tools:
                entrypoint = getattr(function, "entrypoint", None)
                logical_id = getattr(entrypoint, "logical_tool_id", None)
                runtime_name = getattr(function, "name", None)
                if logical_id and runtime_name and logical_id != runtime_name:
                    aliases[logical_id] = runtime_name
            last_exc: Optional[Exception] = None
            result = None
            attempt = 0
            waits_used = 0
            # 每端点「首试 + 兜底重试」再加每次等待后的一次重试；防止并发成功不断清零失败计数导致无限重试。
            max_attempts = 2 * len(self.llm_router.endpoints) + len(self.endpoint_wait_seconds)
            while attempt < max_attempts:
                endpoint = None
                if any(ep.name not in tried_endpoints for ep in self.llm_router.endpoints):
                    # 降级：每个配置端点在单次请求中最多尝试一次，失败立即切换。
                    # 未试过的端点都在冷却时不能直接失败，要落到下面的兜底重试。
                    try:
                        endpoint = self.llm_router.select(exclude=tried_endpoints)
                    except RuntimeError:
                        endpoint = None
                if endpoint is None:
                    # 兜底：全部端点都试过之后，再给「未进冷却」的端点各一次机会
                    # （一次性瞬时故障不该杀掉整次请求，实测因此丢过整轴）；
                    # 连续失败已进冷却的不再撞，也不发给装不下/不支持工具的端点。
                    endpoint = self.llm_router.retry_candidate(
                        tried_endpoints, prompt_chars=prompt_chars, needs_tools=needs_tools
                    )
                if endpoint is None:
                    if waits_used < len(self.endpoint_wait_seconds):
                        wait = float(self.endpoint_wait_seconds[waits_used])
                        waits_used += 1
                        print(f"[LLM retry] no endpoint available, waiting {wait:g}s ({waits_used}/{len(self.endpoint_wait_seconds)})")
                        time.sleep(wait)
                        continue
                    if last_exc is None:
                        raise RuntimeError(self.llm_router.unavailable_reason())
                    break
                attempt_started = time.monotonic()
                model_client = self.build_model(
                    reasoning_effort=reasoning_effort, endpoint=endpoint,
                    trace_identity_headers=trace_headers(role=getattr(self, "_caller", self.role),
                                                         stage=stage, trace_id=trace_id),
                )
                if aliases:
                    object.__setattr__(model_client, "logical_tool_aliases", aliases)
                    object.__setattr__(model_client, "parse_tool_calls", MethodType(_parse_tool_calls_with_aliases, model_client))
                if prepare_model is not None:
                    prepare_model(model_client)
                try:
                    agent = Agent(
                        model=model_client,
                        system_message=system,
                        use_json_mode=use_json_mode,
                        tools=tools,
                        db=InMemoryDb() if pause_tools else None,
                        session_id=(
                            f"{effective_session_id}:retry{attempt}"
                            if attempt
                            else effective_session_id
                        ),
                        enable_user_memories=False,
                        enable_agentic_memory=False,
                        num_history_runs=0,
                        tool_call_limit=tool_call_limit,
                        compress_tool_results=self.compress_tool_results,
                        max_tool_calls_from_history=self.max_tool_calls_from_history,
                    )
                    result = _run_agent(
                        agent,
                        inputs,
                        stream=self.stream,
                        wall_deadline=time.monotonic() + self.request_timeout_seconds,
                    )
                    found = problem(result)
                    if found:
                        raise RuntimeError(found)
                    self.llm_router.record_success(endpoint)
                    attempt_records.append({
                        "attempt": attempt + 1,
                        "endpoint": endpoint.name,
                        "model": endpoint.model,
                        "status": "succeeded",
                        "prompt_chars": prompt_chars,
                        "elapsed_ms": int(
                            (time.monotonic() - attempt_started) * 1000
                        ),
                    })
                    runtime["selected_endpoint"] = endpoint.name
                    runtime["selected_model"] = endpoint.model
                    last_exc = None
                    break
                except Exception as exc:
                    self.llm_router.record_failure(endpoint)
                    tried_endpoints.add(endpoint.name)
                    attempt_records.append({
                        "attempt": attempt + 1,
                        "endpoint": endpoint.name,
                        "model": endpoint.model,
                        "status": "failed",
                        "prompt_chars": prompt_chars,
                        "elapsed_ms": int(
                            (time.monotonic() - attempt_started) * 1000
                        ),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    })
                    last_exc = exc
                    print(f"[LLM retry] attempt {attempt + 1} failed: {exc}")
                attempt += 1
            if last_exc is not None and result is None:
                raise last_exc

            # Extract metrics for token tracking
            token_metrics: Dict[str, Any] = {}
            if hasattr(result, "metrics") and result.metrics:
                metrics = result.metrics
                token_metrics = {
                    "input_tokens": getattr(metrics, "input_tokens", 0),
                    "output_tokens": getattr(metrics, "output_tokens", 0),
                    "cache_read_tokens": getattr(metrics, "cache_read_tokens", 0),
                    "cache_write_tokens": getattr(metrics, "cache_write_tokens", 0),
                    "reasoning_tokens": getattr(metrics, "reasoning_tokens", 0),
                    "total_tokens": getattr(metrics, "total_tokens", 0),
                }
                print(f"[Token usage] {token_metrics['input_tokens']:,} in + {token_metrics['output_tokens']:,} out + {token_metrics['cache_read_tokens']:,} cache = {token_metrics['total_tokens']:,} total")
        except Exception as exc:
            _track_context(
                self, messages, None, trace_id or "", {},
                int((time.time() - start_ts) * 1000), str(exc),
                runtime=runtime, governance=governance,
            )
            raise
        return _TurnOutcome(result=result, runtime=runtime, token_metrics=token_metrics, start_ts=start_ts)


@dataclass
class _TurnOutcome:
    result: Any
    runtime: Dict[str, Any]
    token_metrics: Dict[str, Any]
    start_ts: float

    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_ts) * 1000)
