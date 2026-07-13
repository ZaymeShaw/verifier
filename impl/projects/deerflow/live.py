"""deerflow 项目 Live 实现（新协议）。

通过 HTTP 调 deer-flow Gateway 完成多轮营销规划对话。
- 创建 thread → 逐轮 POST /api/threads/{tid}/runs/wait → GET /api/threads/{tid}/messages
- thread_id + checkpointer 由 Gateway 续上下文，客户端只发新消息
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from impl.core.live_protocol import RealServiceLive
from impl.core.schema import (
    ExecutionTraceEvent,
    LiveExecutionResult,
    LiveMultiTurnState,
    LiveRequest,
    MultiTurnCase,
    ProjectSpec,
    SingleTurnCase,
)


NBEV_MARKERS = (
    "/mnt/skills/custom/nbev_",
    "run_planning.py",
    "run_profile.py",
    "run_playbook.py",
    "run_modify.py",
)

NBEV_SCRIPTS = (
    "run_planning.py",
    "run_profile.py",
    "run_playbook.py",
    "run_modify.py",
)


def _list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_turns(turns: Any) -> List[Dict[str, Any]]:
    if not isinstance(turns, list):
        return []
    normalized = []
    for item in turns:
        if isinstance(item, dict):
            normalized.append({
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or item.get("query") or item.get("text") or ""),
            })
        else:
            normalized.append({"role": "user", "content": str(item)})
    return normalized


def _last_user_content(turns: List[Dict[str, Any]]) -> str:
    for turn in reversed(turns):
        if turn.get("role") == "user" and turn.get("content"):
            return str(turn.get("content"))
    return ""


def _extract_query(input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
    for value in (input_data.get("query"), _last_user_content(turns)):
        if isinstance(value, dict):
            value = value.get("content") or value.get("query") or value.get("text")
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _current_turn(turns: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    if turns:
        for turn in reversed(turns):
            if turn.get("role") == "user" and turn.get("content"):
                return turn
        return turns[-1]
    return {"role": "user", "content": str(query)} if query else {}


def _normalize_boundary(boundary: Any) -> Dict[str, Any]:
    data = dict(boundary or {}) if isinstance(boundary, dict) else {}
    return {
        "dependency_status": data.get("dependency_status") or "available",
        "allow_fallback": bool(data.get("allow_fallback") or data.get("fallback_allowed")),
        "excluded_evidence": _list(data.get("excluded_evidence")),
        "notes": str(data.get("notes") or ""),
    }


def _normalize_reference(reference: Any, input_data: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    ref = dict(reference or {}) if isinstance(reference, dict) else {}
    if input_data.get("expected_stage") and "expected_stage" not in ref:
        ref["expected_stage"] = input_data.get("expected_stage")
    if input_data.get("expected_dimensions") and "required_dimensions" not in ref:
        ref["required_dimensions"] = _list(input_data.get("expected_dimensions"))
    if scenario and "scenario" not in ref:
        ref["scenario"] = scenario
    return ref


def _infer_scenario(input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
    text = " ".join(
        [str(input_data.get("query") or input_data.get("user_intent") or "")] +
        [str(turn.get("content") or "") for turn in turns]
    )
    if any(word in text for word in ["缺", "补充", "澄清", "需要"]):
        return "clarification"
    if any(word in text for word in ["天气", "闲聊", "讲个", "诗"]):
        return "non_agent_intent"
    if any(word in text for word in ["不可用", "兜底", "fallback", "失败"]):
        return "service_unavailable"
    if len(turns) > 1:
        return "multi_turn_dimension_accumulation"
    return "single_turn_planning"


def build_request(case: SingleTurnCase | MultiTurnCase, project_id: str) -> Dict[str, Any]:
    """把 case.input 翻译成 normalized_request（= REQUEST_SCHEMA 形状）。"""
    input_data = dict(case.input or {})
    turns = _normalize_turns(input_data.get("turns"))
    query = _extract_query(input_data, turns)
    if not turns and query:
        turns = [{"role": "user", "content": str(query)}]
    elif turns and not query:
        query = _last_user_content(turns)
    case_id = str(case.id or input_data.get("case_id") or input_data.get("id") or f"deerflow-case-{int(time.time() * 1000)}")
    scenario = str(input_data.get("scenario") or case.scenario or _infer_scenario(input_data, turns))
    boundary = _normalize_boundary(input_data.get("boundary") or {})
    case_reference = case.reference if isinstance(case.reference, dict) else {}
    reference = _normalize_reference(input_data.get("reference") or case_reference or {}, input_data, scenario)
    return {
        "query": str(query or _current_turn(turns, query).get("content") or ""),
        "user_intent": str(input_data.get("user_intent") or query or scenario),
        "turns": turns,
        "scenario": scenario,
        "expected_stage": str(input_data.get("expected_stage") or reference.get("expected_stage") or ""),
        "expected_dimensions": _list(input_data.get("expected_dimensions") or reference.get("required_dimensions")),
        "boundary": boundary,
        "reference": reference,
        "metadata": dict(input_data.get("metadata") or {}),
    }


def _attach_request(raw: Any, request: Dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        return {**raw, "_normalized_request": request}
    return {"raw": raw, "_normalized_request": request}


def _request_from_raw(raw: Any) -> dict[str, Any]:
    return dict(raw.get("_normalized_request") or {}) if isinstance(raw, dict) else {}


def _raw_payload(raw: Any) -> Any:
    if isinstance(raw, dict) and "raw" in raw:
        return raw.get("raw")
    return raw


def _post_json(url: str, body: Dict[str, Any], timeout: float) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _health_check(base_url: str, timeout: float = 5.0) -> bool:
    try:
        _get_json(f"{base_url.rstrip('/')}/health", timeout)
        return True
    except Exception:
        return False


def _create_thread(base_url: str, timeout: float) -> str:
    result = _post_json(f"{base_url.rstrip('/')}/api/threads", {}, timeout)
    if isinstance(result, dict) and result.get("thread_id"):
        return str(result["thread_id"])
    raise RuntimeError(f"create thread failed: {result}")


def _send_turn_wait(base_url: str, thread_id: str, message: str, timeout: float, model: str = "minimax-m3") -> None:
    body = {
        "input": {"messages": [{"role": "user", "content": message}]},
        "config": {"configurable": {"model_name": model}},
    }
    _post_json(f"{base_url.rstrip('/')}/api/threads/{thread_id}/runs/wait", body, timeout)


def _read_messages(base_url: str, thread_id: str, timeout: float) -> list[dict[str, Any]]:
    result = _get_json(f"{base_url.rstrip('/')}/api/threads/{thread_id}/messages", timeout)
    if isinstance(result, list):
        return result
    return []


def _extract_reply_and_tool_calls(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """从历史消息中取最新 AI 回复文本 + tool_calls。"""
    reply = ""
    tool_calls: list[dict[str, Any]] = []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("type") != "ai":
            continue
        if not reply and content.get("content"):
            value = content["content"]
            reply = value if isinstance(value, str) else str(value)
        for tc in content.get("tool_calls") or []:
            if isinstance(tc, dict):
                tool_calls.append({
                    "name": str(tc.get("name") or ""),
                    "args": dict(tc.get("args") or {}) or {},
                })
        if reply and tool_calls:
            break
    return reply, tool_calls


def _is_nbev_tool_call(tool_call: dict[str, Any]) -> bool:
    if tool_call.get("name") != "bash":
        return False
    args_str = str(tool_call.get("args") or "")
    return any(marker in args_str for marker in NBEV_MARKERS)


def _scripts_called(tool_calls: list[dict[str, Any]]) -> list[str]:
    found = []
    for tool_call in tool_calls:
        args_str = str(tool_call.get("args") or "")
        for script in NBEV_SCRIPTS:
            if script in args_str and script not in found:
                found.append(script)
    return found


def _stage_from_output(reply: str, tool_calls: list[dict[str, Any]], scripts: list[str]) -> str:
    if scripts:
        return "planning"
    has_nbev = any(_is_nbev_tool_call(tc) for tc in tool_calls)
    if has_nbev:
        return "planning"
    reply_lower = (reply or "").lower()
    if any(word in reply_lower for word in ["澄清", "需要", "请提供", "请问", "缺", "补充"]):
        return "clarification"
    if any(word in reply_lower for word in ["无法", "sorry", "不能", "不支持", "闲聊"]):
        return "non_agent"
    if reply:
        return "intent"
    return "unknown"


def _session_summary(normalized_request: dict[str, Any], turn_index: int) -> dict[str, Any]:
    expected_dimensions = _list(normalized_request.get("expected_dimensions"))
    return {
        "thread_id": str(normalized_request.get("case_id") or ""),
        "turn_index": turn_index,
        "expected_dimensions": expected_dimensions,
        "accumulated_dimensions": [],
        "missing_dimensions": list(expected_dimensions),
        "evidence_declared": False,
        "evidence_status": "missing",
    }


def _fallback_summary(call_status: str, call_error: Optional[str]) -> dict[str, Any]:
    if call_status != "succeeded":
        return {
            "used": True,
            "allowed": True,
            "reason": str(call_error or "live service unavailable"),
        }
    return {"used": False, "allowed": False, "reason": ""}


def _errors_from_call(call_status: str, call_error: Optional[str]) -> list[str]:
    if call_status != "succeeded" and call_error:
        return [str(call_error)[:300]]
    return []


def _input_turn_for_index(request: LiveRequest, index: int) -> dict[str, Any]:
    turns = request.normalized_request.get("turns") if isinstance(request.normalized_request, dict) else request.turns
    if isinstance(turns, list) and index < len(turns) and isinstance(turns[index], dict):
        return dict(turns[index])
    return {}


def extract_output(raw_response: Any, request: LiveRequest | None = None, index: int | None = None) -> dict[str, Any]:
    """从 raw_response 中提取本轮输出。raw_response 形如 {"thread_id":..., "reply":..., "tool_calls":..., "messages":...}。"""
    data = _raw_payload(raw_response)
    if not isinstance(data, dict):
        data = {}
    reply = str(data.get("reply") or "")
    tool_calls_raw = data.get("tool_calls") or []
    if not isinstance(tool_calls_raw, list):
        tool_calls_raw = []
    tool_calls = [
        {
            "name": str(tc.get("name") or ""),
            "args": dict(tc.get("args") or {}) or {},
            "is_nbev_script": _is_nbev_tool_call(tc) if isinstance(tc, dict) else False,
        }
        for tc in tool_calls_raw if isinstance(tc, dict)
    ]
    scripts = _scripts_called(tool_calls)
    stage = _stage_from_output(reply, tool_calls, scripts)
    nbev_count = sum(1 for tc in tool_calls if tc.get("is_nbev_script"))
    normalized_request = request.normalized_request if request is not None else {}
    turn_index = index if index is not None else max(len(getattr(request, "turns", []) or []) - 1, 0)
    output = {
        "turn_index": turn_index,
        "reply_text": reply,
        "tool_calls": tool_calls,
        "stage": stage,
        "nbev_tool_count": nbev_count,
        "scripts_called": scripts,
        "session_summary": _session_summary(normalized_request if isinstance(normalized_request, dict) else {}, turn_index),
        "fallback": _fallback_summary(str(data.get("call_status") or "succeeded"), data.get("call_error")),
        "errors": _errors_from_call(str(data.get("call_status") or "succeeded"), data.get("call_error")),
        "input_turn": _input_turn_for_index(request, turn_index) if request is not None else {},
    }
    if index is None and request is not None:
        return {"turns": [output]}
    return output


def _application_boundary(normalized_request: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    boundary = dict(normalized_request.get("boundary") or {}) if isinstance(normalized_request.get("boundary"), dict) else {}
    fallback = output.get("fallback") or {}
    return {
        "dependency_status": boundary.get("dependency_status") or "available",
        "allow_fallback": bool(boundary.get("allow_fallback")),
        "fallback_used": bool(fallback.get("used")),
        "judge_scope": "system_responsibility_with_declared_external_boundary",
        "excluded_evidence": _list(boundary.get("excluded_evidence")),
    }


def _latest_turn_output(extracted_output: dict[str, Any]) -> dict[str, Any]:
    turns = extracted_output.get("turns") if isinstance(extracted_output, dict) else None
    if isinstance(turns, list) and turns and isinstance(turns[-1], dict):
        return turns[-1]
    return extracted_output if isinstance(extracted_output, dict) else {}


def application_boundary(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None, request: LiveRequest | dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
    latest = _latest_turn_output(extracted_output or {})
    return _application_boundary(normalized_request or {}, latest)


def build_execution_trace(input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any]) -> list[ExecutionTraceEvent]:
    latest = _latest_turn_output(extracted_output or {})
    expected_stage = request.get("expected_stage") or (request.get("reference") or {}).get("expected_stage")
    expected_dimensions = _list(request.get("expected_dimensions"))
    actual_scripts = _list(latest.get("scripts_called"))
    return [
        ExecutionTraceEvent(stage="request_normalization", status="ok" if request.get("turns") else "suspicious", evidence={"turn_count": len(request.get("turns") or []), "thread_id": request.get("case_id")}),
        ExecutionTraceEvent(stage="thread_creation", status="ok" if latest else "suspicious", evidence={"thread_id": request.get("case_id")}),
        ExecutionTraceEvent(stage="turn_delivery", status="ok" if latest.get("reply_text") or latest.get("tool_calls") else "failed", evidence={"turn_index": latest.get("turn_index")}),
        ExecutionTraceEvent(stage="message_history_read", status="ok" if latest.get("reply_text") else "suspicious", evidence={"reply_present": bool(latest.get("reply_text"))}),
        ExecutionTraceEvent(stage="reply_extraction", status="ok", evidence={"reply_length": len(str(latest.get("reply_text") or ""))}),
        ExecutionTraceEvent(stage="tool_call_extraction", status="ok", evidence={"tool_call_count": len(latest.get("tool_calls") or []), "nbev_count": latest.get("nbev_tool_count")}),
        ExecutionTraceEvent(stage="stage_inference", status="ok" if latest.get("stage") in {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"} else "suspicious", evidence={"actual_stage": latest.get("stage"), "expected_stage": expected_stage}),
        ExecutionTraceEvent(stage="multi_turn_accumulation", status="ok", evidence={"expected_dimensions": expected_dimensions, "actual_scripts": actual_scripts}),
    ]


def project_fields(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None, request: LiveRequest | dict[str, Any] | None = None, application_boundary: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
    normalized_request = normalized_request if isinstance(normalized_request, dict) else {}
    output = extracted_output if isinstance(extracted_output, dict) else {}
    latest = _latest_turn_output(output)
    return {
        "scenario": normalized_request.get("scenario") or "",
        "case_id": normalized_request.get("case_id") or "",
        "thread_id": normalized_request.get("case_id") or "",
        "expected_stage": normalized_request.get("expected_stage"),
        "expected_dimensions": _list(normalized_request.get("expected_dimensions")),
        "planning_summary": {key: latest.get(key) for key in ("stage", "reply_text", "tool_calls", "scripts_called", "session_summary", "fallback", "errors")},
        "application_boundary": application_boundary or {},
        "compact_summary_only": True,
    }


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    for key in ("raw_response", "response", "output"):
        if key in input_data:
            return _attach_request(input_data[key], request.normalized_request)
    return _attach_request({}, request.normalized_request)


def deliver_raw_response(spec: ProjectSpec, request: LiveRequest) -> Any:
    """真实投递：创建 thread → 发送每一轮 → 回看消息取本轮 AI 回复 + tool_calls。

    返回 {thread_id, reply, tool_calls, messages, call_status, call_error}。
    """
    base_url = str(spec.api.get("base_url") or "http://localhost:8001")
    timeout = float(spec.api.get("timeout") or 600)
    model = str((spec.api.get("model")) or (request.normalized_request.get("metadata") or {}).get("model_name") or "minimax-m3")
    turns = list(request.turns or [])
    if not turns:
        normalized_query = str(request.normalized_request.get("query") or "")
        if normalized_query:
            turns = [{"role": "user", "content": normalized_query}]

    if not _health_check(base_url):
        raise urllib.error.URLError(f"deer-flow Gateway 不可用: {base_url}/health")

    thread_id = _create_thread(base_url, timeout)
    reply = ""
    tool_calls: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if turn.get("role") != "user":
            continue
        message = str(turn.get("content") or "")
        if not message:
            continue
        _send_turn_wait(base_url, thread_id, message, timeout, model=model)
        messages = _read_messages(base_url, thread_id, timeout)
        reply, tool_calls = _extract_reply_and_tool_calls(messages)

    return _attach_request({
        "thread_id": thread_id,
        "reply": reply,
        "tool_calls": tool_calls,
        "messages": messages,
        "call_status": "succeeded",
        "call_error": None,
    }, request.normalized_request)


class DeerflowLive(RealServiceLive):
    """deerflow 项目 Live 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter=None):
        super().__init__(spec)
        self._adapter = adapter

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        return build_request(case, self.spec.project_id)

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        return provided_output_raw(case, request)

    def deliver_real(self, request: LiveRequest) -> Any:
        start = time.time()
        try:
            raw_response = deliver_raw_response(self.spec, request)
            call_status = "succeeded"
            call_error = None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raw_response = None
            call_status = "failed"
            call_error = f"deer-flow Gateway unavailable: {exc}"
        except Exception as exc:
            raw_response = None
            call_status = "failed"
            call_error = f"deer-flow delivery error: {exc}"

        turn_index = max(len(request.turns or []) - 1, 0)
        if call_status == "succeeded":
            extracted_output = {"turns": [extract_output(raw_response, request, turn_index)]}
        else:
            extracted_output = {}
        latest_output = extracted_output["turns"][-1] if extracted_output.get("turns") else {}
        app_boundary = _application_boundary(request.normalized_request, latest_output)

        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id or request.case_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status=call_status,
            raw_response=raw_response,
            call_error=call_error,
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output) if call_status == "succeeded" else [],
            project_fields=project_fields(raw_response, extracted_output, request, app_boundary) if call_status == "succeeded" else {},
            application_boundary=app_boundary,
            interaction_mode="interactive_intent" if request.turns else "single_turn",
        )

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response, request, max(len(request.turns or []) - 1, 0))

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, request, application_boundary)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output, request)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output)
