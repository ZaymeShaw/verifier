from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urljoin

from impl.core.http_client import call_project_api
from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveRequest, MultiTurnCase, ProjectSpec, SingleTurnCase

_SERVICE_LOCK = threading.Lock()


def _probe_downstream_search(spec: ProjectSpec, raw_response: Dict[str, Any]) -> Dict[str, Any]:
    config = spec.application.get("downstream_search") if isinstance(spec.application, dict) else None
    if not isinstance(config, dict) or not config.get("enabled", True):
        return {"status": "not_configured"}
    extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
    conditions = list(extra.get("conditions") or [])
    query_logic = str(extra.get("query_logic") or "AND")
    payload = {
        "header": {"agent_id": "eval-user", "page": 1, "size": 20},
        "query_logic": query_logic,
        "conditions": conditions,
    }
    if not conditions:
        return {"status": "skipped", "reason": "parse returned no conditions", "payload": payload}
    base_url = str(config.get("base_url") or "").rstrip("/") + "/"
    endpoint = str(config.get("endpoint") or "").lstrip("/")
    if not base_url.strip("/") or not endpoint:
        return {"status": "not_configured", "payload": payload}
    url = urljoin(base_url, endpoint)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    search_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(config.get("method") or "POST").upper())
    try:
        with urllib.request.urlopen(search_request, timeout=float(config.get("timeout") or 3)) as response:
            text = response.read().decode("utf-8")
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = {"text": text}
        return {"status": "ok", "url": url, "payload": payload, "result": result}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "unavailable", "url": url, "payload": payload, "error": str(exc)}


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    if "raw_response" in input_data:
        return input_data["raw_response"]
    if "response" in input_data:
        return input_data["response"]
    output = input_data.get("output") or {}
    if not isinstance(output, dict):
        return output
    if "data" in output:
        return output
    conditions = output.get("conditions") or output.get("structured_output") or []
    logic = output.get("query_logic") or output.get("logic") or "AND"
    query = request.normalized_request.get("user_text") or output.get("source_query") or output.get("query") or ""
    return {
        "code": output.get("code", output.get("status_code", 0)),
        "msg": output.get("msg") or output.get("message") or "provided client_search output",
        "data": {
            "robot_text": output.get("robot_text") or output.get("user_visible_text") or output.get("summary") or "provided output",
            "extra_output_params": {
                "query": query,
                "query_logic": logic,
                "conditions": conditions,
                "matched_level": output.get("matched_level"),
                "intent_summary": output.get("intent_summary") or output.get("summary") or "provided output",
                "matched_patterns": output.get("matched_patterns") or [],
                "rewritten_query": output.get("rewritten_query") or output.get("source_query") or query,
            },
        },
    }


def application_boundary(raw_response: Any, extracted_output: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not isinstance(raw_response, dict):
        return _application_boundary({})
    downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response.get("_downstream_search"), dict) else {}
    return _application_boundary(downstream_search)


def _application_boundary(downstream: Any) -> Dict[str, Any]:
    status = downstream.get("status") if isinstance(downstream, dict) else None
    if status == "ok":
        return {"downstream_result_set_available": True, "judge_scope": "parser_and_result_set", "result_set_verified": True}
    return {
        "downstream_result_set_available": False,
        "downstream_status": status or "not_verified",
        "judge_scope": "parser_condition_semantics_only",
        "result_set_verified": False,
        "reason": "application live layer probed downstream customer search before judge/attribute and constrained evaluation scope to parser output semantics.",
    }


def _response_query(raw_response: Dict[str, Any], extra: Dict[str, Any]) -> str:
    data = raw_response.get("data") or {}
    return extra.get("rewritten_query") or extra.get("query") or data.get("query") or ""


def _empty_result_reason(query: str, extra: Dict[str, Any]) -> str:
    if extra.get("conditions"):
        return ""
    if not query:
        return "empty_query"
    return "service_returned_no_conditions"


def extract_output(raw_response: Any) -> Dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {"code": -1, "msg": str(raw_response), "query": "", "conditions": []}
    extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
    data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
    return {
        "code": int(raw_response.get("code") or 0),
        "msg": str(raw_response.get("msg") or ""),
        "robot_text": data.get("robot_text"),
        "end_flag": data.get("end_flag"),
        "trace_id": data.get("trace_id"),
        "query": _response_query(raw_response, extra),
        "query_logic": extra.get("query_logic"),
        "conditions": extra.get("conditions") or [],
        "matched_level": extra.get("matched_level"),
        "matched_patterns": extra.get("matched_patterns"),
        "rewritten_query": extra.get("rewritten_query"),
        "intent_summary": extra.get("intent_summary"),
        "confidence": extra.get("confidence"),
        "cost_times": extra.get("cost_times"),
    }


def _external_boundary_sources(spec: ProjectSpec) -> Dict[str, Any]:
    paths = {}
    root = Path(spec.root)
    for key, rel in (spec.documents or {}).items():
        if key.startswith("source_") and "config/" in str(rel):
            paths[key] = str((root / str(rel)).resolve())
    return {"config_paths": paths}


def project_fields(raw_response: Any, extracted_output: Dict[str, Any], spec: ProjectSpec | None = None) -> Dict[str, Any]:
    extra = {}
    if isinstance(raw_response, dict):
        data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
        extra = data.get("extra_output_params") if isinstance(data.get("extra_output_params"), dict) else {}
    empty_result_reason = _empty_result_reason(extracted_output.get("query", ""), extra)
    return {
        "downstream_search": raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {},
        "external_boundary_sources": _external_boundary_sources(spec) if spec is not None else {"config_paths": {}},
        "empty_result_reason": empty_result_reason,
        "is_empty_result": bool(empty_result_reason),
    }


def build_execution_trace(input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
    extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {}) if isinstance(raw_response, dict) else {}
    downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {}
    return [
        ExecutionTraceEvent(stage="client_search.request_normalization", status="ok", evidence={"user_text": request.get("user_text"), "source": request.get("source")}),
        ExecutionTraceEvent(stage="client_search.api", status="ok" if isinstance(raw_response, dict) and raw_response.get("code") == 0 else "suspicious", evidence={"code": raw_response.get("code") if isinstance(raw_response, dict) else None}),
        ExecutionTraceEvent(stage="client_search.routing", status="ok" if extra.get("matched_level") is not None else "not_verified", evidence={"matched_level": extra.get("matched_level"), "matched_patterns": extra.get("matched_patterns")}),
        ExecutionTraceEvent(stage="client_search.downstream_search", status=downstream_search.get("status") or "not_verified", evidence=downstream_search),
        ExecutionTraceEvent(stage="client_search.output_extract", status="ok", evidence={"logic": extracted_output.get("query_logic"), "condition_count": len(extracted_output.get("conditions") or [])}),
    ]


from impl.core.live_protocol import RealServiceLive


class ClientSearchLive(RealServiceLive):
    """client_search 项目 Live 实现（新协议）。

    迁移过渡期：扩展点委托模块级函数和 adapter 现有方法。
    """

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        # adapter.build_request 返回 LiveRequest，取其 normalized_request
        live_request = self._adapter.build_request(case)
        return live_request.normalized_request

    def deliver_real(self, request: LiveRequest) -> Any:
        # 调用 call_project_api + 构建完整 LiveExecutionResult
        with _SERVICE_LOCK:
            raw_response = call_project_api(self.spec, request.normalized_request)
        if isinstance(raw_response, dict):
            raw_response = {**raw_response, "_downstream_search": _probe_downstream_search(self.spec, raw_response)}
        extracted_output = extract_output(raw_response)
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output),
            project_fields=project_fields(raw_response, extracted_output, self.spec),
            application_boundary=application_boundary(raw_response, extracted_output),
        )

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, self.spec)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output)
