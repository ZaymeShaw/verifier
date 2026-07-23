"""deerflow 项目 Live 实现（新协议）。

通过 HTTP 调 deer-flow Gateway 完成多轮营销规划对话。
- 创建 thread → 逐轮 POST /api/threads/{tid}/runs/wait → GET /api/threads/{tid}/messages
- thread_id + checkpointer 由 Gateway 续上下文，客户端只发新消息
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from impl.core.live_protocol import LiveServiceUnavailableError, MultiTurnInteractiveLive, RealServiceLive
from impl.core.live_transport import LiveTransport
from impl.core.schema import (
    ExecutionTraceEvent,
    LiveMultiTurnState,
    LiveRequest,
    MultiTurnCase,
    ProjectSpec,
    SingleTurnCase,
)
from impl.core.config_schema import ConfigError


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
    if "澄清" in text or _looks_like_clarification_reply(text):
        return "clarification"
    if any(word in text for word in ["天气", "闲聊", "讲个", "诗"]):
        return "non_agent_intent"
    if any(word in text for word in ["不可用", "兜底", "fallback", "失败"]):
        return "service_unavailable"
    if len(turns) > 1:
        return "multi_turn_dimension_accumulation"
    return "single_turn_planning"


def _attach_request(raw: Any, request: Dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        return {**raw, "_normalized_request": request}
    return {"raw": raw, "_normalized_request": request}


def _request_from_raw(raw: Any) -> dict[str, Any]:
    return dict(raw.get("_normalized_request") or {}) if isinstance(raw, dict) else {}


def _raw_payload(raw: Any) -> Any:
    if isinstance(raw, list):
        for item in reversed(raw):
            if isinstance(item, list):
                return item
        return raw[-1] if raw else {}
    if isinstance(raw, dict) and "raw" in raw:
        return raw.get("raw")
    return raw


def _extract_reply_and_tool_calls(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """从同一条最新业务 AI 消息提取回复和工具调用，禁止跨轮拼接。"""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        caller = str((message.get("metadata") or {}).get("caller") or "")
        if caller.startswith("middleware:"):
            continue
        content = message.get("content")
        if not isinstance(content, dict) or content.get("type") != "ai":
            continue
        value = content.get("content")
        reply = value if isinstance(value, str) else str(value or "")
        tool_calls = [
            {
                "name": str(tc.get("name") or ""),
                "args": dict(tc.get("args") or {}) or {},
            }
            for tc in content.get("tool_calls") or []
            if isinstance(tc, dict)
        ]
        return reply, tool_calls
    return "", []


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


def _looks_like_planning_reply(reply: str) -> bool:
    text = str(reply or "").strip()
    if not text:
        return False
    artifact_marker = any(
        marker in text
        for marker in ("执行计划", "营销规划", "行动方案", "实施方案", "推进计划", "时间表", "里程碑")
    )
    nbev_result = (
        "nbev" in text.lower()
        and any(marker in text for marker in ("贡献", "达成率", "预测", "拆分", "路径", "方案"))
        and sum(marker in text for marker in ("产品", "队伍", "客户", "目标", "达成")) >= 2
    )
    dimensions = sum(
        marker in text
        for marker in ("目标", "策略", "步骤", "阶段", "执行", "时间", "预算", "指标", "风险", "负责人")
    )
    structured = bool(re.search(r"(?:^|\n)\s*(?:#{1,6}\s*|[-*]\s+|\d+[.、])", text))
    # “为了制定执行计划，请补充……”只是请求信息，不是已经交付规划产物。
    return structured and (artifact_marker or nbev_result or dimensions >= 3)


def _looks_like_clarification_reply(reply: str) -> bool:
    text = str(reply or "").strip()
    if not text:
        return False
    patterns = (
        r"请(?:先)?提供",
        r"请(?:再)?补充",
        r"请确认",
        r"需要先(?:了解|确认|补充|提供)",
        r"还缺少",
        r"缺少.{0,12}(?:信息|资料|参数|维度)",
        r"为了.{0,24}(?:请提供|请补充|需要提供)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _stage_inference(reply: str, tool_calls: list[dict[str, Any]], scripts: list[str]) -> tuple[str, str]:
    tool_names = {str(tc.get("name") or "") for tc in tool_calls if isinstance(tc, dict)}
    if "ask_clarification" in tool_names:
        return "clarification", "current_message_ask_clarification"
    if scripts:
        return "planning", "nbev_script"
    if any(_is_nbev_tool_call(tc) for tc in tool_calls):
        return "planning", "nbev_tool_call"
    if _looks_like_planning_reply(reply):
        return "planning", "structured_planning_reply"
    if _looks_like_clarification_reply(reply):
        return "clarification", "explicit_missing_information_request"
    reply_lower = (reply or "").lower()
    if any(word in reply_lower for word in ["无法", "sorry", "不能", "不支持", "闲聊"]):
        return "non_agent", "non_agent_reply"
    if reply:
        return "intent", "nonempty_business_reply"
    return "unknown", "empty_reply"


def _stage_from_output(reply: str, tool_calls: list[dict[str, Any]], scripts: list[str]) -> str:
    return _stage_inference(reply, tool_calls, scripts)[0]


def _session_summary(normalized_request: dict[str, Any]) -> dict[str, Any]:
    expected_dimensions = _list(normalized_request.get("expected_dimensions"))
    return {
        "thread_id": str(normalized_request.get("case_id") or ""),
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


def _extract_thread_id(
    responses: list[Any],
    messages: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Resolve the thread id from Deerflow-owned response evidence.

    A create-thread response only exists on the first turn. Reused turns still
    expose the same id on every message returned by the Gateway, so those
    message records are the canonical fallback. Conflicting response evidence
    is surfaced instead of silently selecting one id.
    """
    create_ids = {
        str(item.get("thread_id"))
        for item in responses
        if isinstance(item, dict) and item.get("thread_id")
    }
    message_ids = {
        str(item.get("thread_id"))
        for item in messages
        if isinstance(item, dict) and item.get("thread_id")
    }
    evidence_ids = create_ids | message_ids
    if len(evidence_ids) > 1:
        return "", [
            "deerflow response contains conflicting thread_id evidence: "
            + ", ".join(sorted(evidence_ids))
        ]
    return (next(iter(evidence_ids), ""), [])


def extract_output(raw_response: Any) -> dict[str, Any]:
    """只从公共层生成的真实响应列表提取本轮输出。"""
    responses = list(raw_response) if isinstance(raw_response, list) else [raw_response]
    messages = next((item for item in reversed(responses) if isinstance(item, list)), [])
    thread_id, thread_errors = _extract_thread_id(responses, messages)
    reply, tool_calls_raw = _extract_reply_and_tool_calls(messages)
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
    output = {
        "reply_text": reply,
        "tool_calls": tool_calls,
        "stage": stage,
        "nbev_tool_count": nbev_count,
        "scripts_called": scripts,
        "session_summary": {
            "thread_id": thread_id,
            "expected_dimensions": [],
            "accumulated_dimensions": [],
            "missing_dimensions": [],
            "evidence_declared": bool(messages),
            "evidence_status": "declared" if messages else "missing",
        },
        "fallback": _fallback_summary("succeeded", None),
        "errors": thread_errors,
    }
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


def application_boundary(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None, request: LiveRequest | dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
    output = extracted_output if isinstance(extracted_output, dict) else {}
    return _application_boundary(normalized_request or {}, output)


def build_execution_trace(input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any]) -> list[ExecutionTraceEvent]:
    latest = extracted_output if isinstance(extracted_output, dict) else {}
    expected_stage = request.get("expected_stage") or (request.get("reference") or {}).get("expected_stage")
    expected_dimensions = _list(request.get("expected_dimensions"))
    actual_scripts = _list(latest.get("scripts_called"))
    thread_id = str(((latest.get("session_summary") or {}).get("thread_id")) or "")
    return [
        ExecutionTraceEvent(stage="request_normalization", status="ok" if request.get("turns") else "suspicious", evidence={"turn_count": len(request.get("turns") or [])}),
        ExecutionTraceEvent(stage="thread_resolution", status="ok" if thread_id else "suspicious", evidence={"thread_id": thread_id}),
        ExecutionTraceEvent(stage="turn_delivery", status="ok" if latest.get("reply_text") or latest.get("tool_calls") else "failed", evidence={"delivered": bool(latest.get("reply_text") or latest.get("tool_calls"))}),
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
    latest = output
    return {
        "scenario": normalized_request.get("scenario") or "",
        "case_id": normalized_request.get("case_id") or "",
        # thread_id 只能来自真实业务响应（或业务输出中的同源提取），不能以 case_id 冒充。
        "thread_id": str(((latest.get("session_summary") or {}).get("thread_id")) or ""),
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


class DeerflowLive(RealServiceLive, MultiTurnInteractiveLive):
    """deerflow 项目 Live 实现。

    继承 RealServiceLive（投递模式=真实服务）+ MultiTurnInteractiveLive（交互模式=多轮）。
    多轮主循环现在在 execute_live 内部（spec 第十一节 2），不再通过独立的 deliver_multi_turn。
    """

    def __init__(self, spec: ProjectSpec, adapter=None):
        super().__init__(spec)
        self._adapter = adapter

    def deliver_provided(self, request: LiveRequest) -> Any:
        return provided_output_raw(None, request)

    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        configurable: dict[str, Any] = {}
        thread_collection_url = ""
        thread_id = ""
        try:
            normalized_request = request if isinstance(request, dict) else {}
            service = self.spec.require_service("primary")
            base_url = str(service["base_url"]).rstrip("/")
            timeout = float(service["timeout_seconds"])
            healthcheck = service.get("healthcheck") or {}
            health_endpoint = healthcheck.get("endpoint")
            health_timeout = healthcheck.get("request_timeout_seconds")
            if health_endpoint in (None, "") or health_timeout in (None, ""):
                raise ConfigError(
                    "deerflow runtime.services.primary.healthcheck.endpoint and "
                    "request_timeout_seconds are required"
                )
            thread_collection_url = urljoin(
                f"{base_url}/",
                str(service["endpoint"]).lstrip("/"),
            ).rstrip("/")
            health_url = urljoin(f"{base_url}/", str(health_endpoint).lstrip("/"))
            transport.get(health_url, timeout=float(health_timeout))
            configurable = ((normalized_request.get("config") or {}).get("configurable") or {}) if isinstance(normalized_request, dict) else {}
            thread_id = str(configurable.get("thread_id") or "")
            if not thread_id:
                created = transport.post(
                    thread_collection_url, json_body={}, timeout=timeout,
                    contributes_raw_response=True,
                )
                created_payload = created.response if isinstance(created.response, dict) else {}
                thread_id = str(created_payload.get("thread_id") or "")
                if not thread_id:
                    raise RuntimeError(f"create thread failed: {created.response}")
            transport.post(
                f"{thread_collection_url}/{thread_id}/runs/wait",
                json_body=normalized_request,
                timeout=timeout,
                carries_live_request=True,
            )
            transport.get(
                f"{thread_collection_url}/{thread_id}/messages",
                timeout=timeout,
                contributes_raw_response=True,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failed = transport.exchanges[-1] if transport.exchanges else None
            if (
                failed is not None
                and failed.status_code == 404
                and bool(thread_id)
                and failed.url.startswith(f"{thread_collection_url}/{thread_id}/")
            ):
                stale_thread_id = str(configurable.get("thread_id") or thread_id or "")
                raise RuntimeError(
                    f"deer-flow thread_not_found: {stale_thread_id or failed.url}"
                ) from exc
            raise LiveServiceUnavailableError(f"deer-flow Gateway unavailable: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"deer-flow delivery error: {exc}") from exc
        return transport

    def extract_output(self, raw_response: list[Any]) -> Dict[str, Any]:
        return extract_output(raw_response)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, request, application_boundary)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output, request)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any) -> list:
        return build_execution_trace(request.raw_input if hasattr(request, "raw_input") else {}, request.normalized_request if hasattr(request, "normalized_request") else request, raw_response, extracted_output)

    def _summarize_assistant(self, extracted):
        """deerflow 助手摘要：stage + tool_calls 概要。"""
        stage = extracted.get("stage") or "unknown"
        tool_count = len(extracted.get("tool_calls") or [])
        parts = [f"stage={stage}"]
        if tool_count:
            parts.append(f"tools={tool_count}")
        return " · ".join(parts)
