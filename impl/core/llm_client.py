from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import json_repair
import time

ROOT = Path(__file__).resolve().parents[2]
MODEL_DEFAULT = "deepseek-v4-pro"
BASE_URL_DEFAULT = "https://api.deepseek.com/v1/chat/completions"

# Session start timestamp: ensures sessions from different runs don't share context
SESSION_START_TIME = int(time.time())


# REMOVED: _project_memory_path() - this function creates impl/knowledge directory
# which triggers Agno's auto-persistence. We don't use it anymore.


def load_env_md_key() -> str:
    path = ROOT / "env.md"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.lower().startswith("deepseek key") and "：" in line:
            return line.split("：", 1)[1].strip()
        if line.lower().startswith("deepseek key") and ":" in line:
            return line.split(":", 1)[1].strip()
    return ""


# CRITICAL: Set OPENAI_API_KEY before importing Agno modules.
# Agno's DeepSeek inherits from OpenAILike, which uses OpenAI SDK internally.
# The OpenAI SDK may cache environment variables at import time, so we must
# set OPENAI_API_KEY to DeepSeek key BEFORE any Agno imports.
_deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or load_env_md_key()
if _deepseek_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _deepseek_key

from agno.agent import Agent
from agno.models.deepseek import DeepSeek


class JsonExtractionError(ValueError):
    """Raised when an LLM response cannot be parsed into a JSON value."""


def _json_error_summary(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} at line {exc.lineno} column {exc.colno} (char {exc.pos})"


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
                continue
    start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError as exc:
            parse_errors.append(f"bare JSON from first bracket: {_json_error_summary(exc)}")
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


def _response_content(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    return str(content or "")


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


def _normalize_base_url(base_url: str) -> str:
    return base_url.rsplit("/v1/chat/completions", 1)[0] if base_url.endswith("/v1/chat/completions") else base_url


def _extract_tool_call_log(result: Any) -> list:
    """
    Extract tool-call records from an Agno RunResponse.

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
        # Some Agno versions nest under run_response / raw_response
        for attr in ("run_response", "raw_response"):
            inner = getattr(result, attr, None)
            if inner is not None:
                messages = getattr(inner, "messages", None)
                if messages:
                    break
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


def _extract_messages(result: Any) -> List[Dict[str, Any]]:
    """从 Agno RunResponse 提取 OpenAI messages 协议的完整消息列表。

    供 context_store 记录实际 LLM 调用的输入输出。每个消息 {role, content, ...}，
    role 不限定 system/user/assistant/tool——按 agno 实际返回的原样保留。
    """
    messages = getattr(result, "messages", None)
    if not messages:
        for attr in ("run_response", "raw_response"):
            inner = getattr(result, attr, None)
            if inner is not None:
                messages = getattr(inner, "messages", None)
                if messages:
                    break
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
            out.append(md)
        else:
            # 退化兜底：直接按属性取
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", None)
            if role is not None or content is not None:
                out.append({"role": role, "content": content})
    return out


def _track_context(self: "LlmClient", system: str, user: str, result: Any,
                   trace_id: str, token_metrics: Dict[str, Any],
                   elapsed_ms: int, error: Optional[str]) -> None:
    """把本次 LLM 调用的实际 messages 上传到 context_store，供 context.html 检索。

    只做记录，不阻断主流程；任何异常都吞掉。
    """
    try:
        from .context_store import save_context
        from .schema.context import ContextRecord
        messages = _extract_messages(result)
        if not messages:
            # result 为 None（调用失败）时，至少把 system/user 请求记下来
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        response: Dict[str, Any] = {}
        content = _response_content(result) if result is not None else ""
        if content:
            response["content"] = content
        if token_metrics:
            response["metrics"] = token_metrics
        prompt_size = sum(len(str(m.get("content") or "")) for m in messages)
        record = ContextRecord(
            record_id=str(uuid.uuid4()),
            trace_id=str(trace_id or ""),
            project_id=str(getattr(self, "_project_id", "") or ""),
            caller=str(getattr(self, "_caller", "") or "llm"),
            messages=messages,
            response=response or None,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            prompt_size=int(prompt_size),
            llm_model=str(self.model or ""),
            elapsed_ms=int(elapsed_ms),
            error=error,
        )
        save_context(record)
    except Exception:
        pass


def project_llm_client(spec: Any, role: str, knowledge: Any = None, tools: list = None,
                       tool_call_limit: Optional[int] = None,
                       compress_tool_results: bool = False,
                       max_tool_calls_from_history: Optional[int] = None) -> "LlmClient":
    """
    Create LLM client for judge/attribute with NO persistence, NO memories, NO sessions.

    Context engineering strategy:
    - Knowledge: NO - use tools for on-demand retrieval
    - User memories: NO - each case should be independent
    - Session history: NO - each judge call is stateless
    - DB persistence: NO - no session/memory storage
    - Tool call budget: only set for roles that actually use tools (attribute).

    Args:
        spec: Project specification
        role: Role name (e.g., "judge", "attribute")
        knowledge: Optional knowledge base (DEPRECATED - use tools instead)
        tools: Optional list of tools to provide to the agent
        tool_call_limit: Cap on tool calls within one agent.run() (attribute only)
        compress_tool_results: If True, compress prior tool results (attribute only)
        max_tool_calls_from_history: Prune tool messages from history (attribute only)
    """
    project_id = str(getattr(spec, "project_id", "default") or "default")
    # CRITICAL: Do NOT create JsonDb or MemoryManager
    # CRITICAL: Do NOT set user_id - it triggers Agno to auto-create impl/knowledge/{user_id}/ directory
    client = LlmClient(
        memory_db=None,  # NO persistence
        memory_manager=None,  # NO memories
        knowledge=knowledge,  # Will be set to None by caller
        knowledge_retriever=None,
        tools=tools,
        user_id=None,  # CRITICAL: None to prevent auto directory creation
        session_id=None,  # NO session persistence
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
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = MODEL_DEFAULT,
        memory_manager: Any = None,
        memory_db: Any = None,
        knowledge: Any = None,
        knowledge_retriever: Any = None,
        tools: list = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        compress_tool_results: bool = False,
        max_tool_calls_from_history: Optional[int] = None,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or load_env_md_key()
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("LLM_BASE_URL") or BASE_URL_DEFAULT
        self.model = model
        self.memory_manager = memory_manager
        self.memory_db = memory_db
        self.knowledge = knowledge
        self.knowledge_retriever = knowledge_retriever
        self.tools = tools or []
        self.user_id = user_id
        self.session_id = session_id
        self.tool_call_limit = tool_call_limit
        self.compress_tool_results = compress_tool_results
        self.max_tool_calls_from_history = max_tool_calls_from_history

    def complete_json(self, system: str, user: str, trace_id: Optional[str] = None,
                      model: Optional[str] = None,
                      reasoning_effort: Optional[str] = "max",
                      output_spec: "StructuredOutputSpec" = None) -> Dict[str, Any]:
        """
        Complete JSON request with isolated session per trace.

        Args:
            system: System prompt
            user: User prompt
            trace_id: Optional trace ID for session isolation. If provided, creates a unique
                     session for this specific case/trace, preventing cross-case contamination.
            model: Optional model override (e.g. "deepseek-chat" for lightweight output stub).
                   Defaults to self.model.
            reasoning_effort: Reasoning effort level. Defaults to "max" (judge/attribute 需要).
                              output 扮演等轻量场景可传 "low" 或 None 关闭深度思考。
            output_spec: spec/struct_output.md 结构化输出约束，**必填**。
                所有 LLM 调用都必须过结构化输出协议。如果实在没有明确输出结构（如自由文本分析），
                传 FREE_TEXT_OUTPUT（单字段 result: str）。
                协议层内部：
                - 注入 render_output_constraint 文案到 system prompt（兜底强化）
                - response_format 传 {"type":"json_object"}（DeepSeek 不支持 json_schema）
                - LLM 返回后跑 enforce_output，不合规直接抛 ValueError 阻断
        """
        if output_spec is None:
            raise TypeError(
                "complete_json 缺少 output_spec 参数。"
                "spec/struct_output.md 要求所有 LLM 调用必须传结构化输出约束。"
                "如果确实没有明确输出结构（如自由文本分析），请传 structured_output.FREE_TEXT_OUTPUT。"
            )
        if not self.api_key:
            return {"error": "missing_api_key", "raw_text": "No DeepSeek API key configured."}

        # spec/struct_output.md：注入约束文案 + 返回后强校验阻断
        enforce_spec = output_spec
        from .structured_output import render_output_constraint
        system = system + "\n\n" + render_output_constraint(enforce_spec)

        start_ts = time.time()
        # OPENAI_API_KEY is initialized once before Agno import above. Do not
        # mutate process-global env per request: api-check runs LLM-heavy routes
        # concurrently, and per-call restore can corrupt other in-flight calls.

        try:
            model_kwargs = {
                "id": model or self.model,
                "api_key": self.api_key,
                "base_url": _normalize_base_url(self.base_url),
                "temperature": 0,
            }
            if reasoning_effort:
                model_kwargs["reasoning_effort"] = reasoning_effort
            model = DeepSeek(**model_kwargs)

            # CRITICAL: Use trace-specific session ID to isolate different cases
            # BUT: Prevent conversation history accumulation within same session
            if trace_id is None:
                import uuid
                trace_id = str(uuid.uuid4())

            # Each trace gets unique session, prevents cross-case contamination
            effective_session_id = f"{trace_id}:{SESSION_START_TIME}"

            # Retry once on transient LLM failure (network/timeout/rate-limit).
            # Without this, a single hiccup yields verdict=uncertain for the case.
            last_exc: Optional[Exception] = None
            result = None
            for attempt in range(2):
                try:
                    agent = Agent(
                        model=model,
                        system_message=system,
                        use_json_mode=True,
                        tools=self.tools,
                        knowledge=None,
                        user_id=self.user_id,
                        session_id=f"{effective_session_id}:retry{attempt}" if attempt else effective_session_id,
                        enable_user_memories=False,
                        enable_agentic_memory=False,
                        num_history_runs=0,
                        tool_call_limit=self.tool_call_limit,
                        compress_tool_results=self.compress_tool_results,
                        max_tool_calls_from_history=self.max_tool_calls_from_history,
                    )
                    result = agent.run(user)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    print(f"[LLM retry] attempt {attempt + 1} failed: {exc}")
                    if attempt == 0:
                        time.sleep(2)
            if last_exc is not None:
                raise last_exc

            # Extract metrics for token tracking
            token_metrics = {}
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
            _track_context(self, system, user, None, trace_id or "", {}, int((time.time() - start_ts) * 1000), str(exc))
            return {"error": "llm_request_failed", "raw_text": str(exc)}

        try:
            content = _response_content(result)
            parsed = extract_json(content)
        except JsonExtractionError as exc:
            raw_response = _raw_response(result)
            elapsed_ms = int((time.time() - start_ts) * 1000)
            _track_context(self, system, user, result, trace_id or "", token_metrics, elapsed_ms, str(exc))
            raise ValueError(f"[{getattr(self, '_caller', '') or 'llm'}] {exc}") from exc
        raw_response = _raw_response(result)
        elapsed_ms = int((time.time() - start_ts) * 1000)

        # spec/struct_output.md：强校验阻断，不放行假货
        from .structured_output import enforce_output
        caller = getattr(self, "_caller", "") or ""
        enforce_output(parsed, enforce_spec, caller=caller)

        # Add token metrics to raw_response if available
        if token_metrics:
            if isinstance(raw_response, dict):
                raw_response["metrics"] = token_metrics

        if isinstance(parsed, dict):
            parsed.setdefault("raw_model_response", raw_response)
            # 从 agno RunOutput 提取 tool call log
            if token_metrics:
                parsed.setdefault("metrics", token_metrics)
            tool_call_log = _extract_tool_call_log(result)
            if tool_call_log:
                parsed.setdefault("_tool_call_log", tool_call_log)
            _track_context(self, system, user, result, trace_id, token_metrics, elapsed_ms, None)
            return parsed
        _track_context(self, system, user, result, trace_id or "", token_metrics, elapsed_ms, None)
        return {"value": parsed, "raw_model_response": raw_response}
