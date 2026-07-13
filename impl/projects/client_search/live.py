from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urljoin

import yaml as _yaml

from impl.core.http_client import call_project_api
from impl.core.interaction_protocol import ready_from_spec
from impl.core.live_protocol import RealServiceLive
from impl.core.schema import (
    ExecutionTraceEvent,
    JudgeResult,
    LiveExecutionResult,
    LiveRequest,
    MultiTurnCase,
    ProjectSpec,
    RunTrace,
    SingleTurnCase,
    TraceExecutionContext,
)
from impl.projects.client_search.capability_manifest import build_capability_manifest

_SERVICE_LOCK = threading.Lock()

FIELD_PATTERNS = {
    "clientAge": {
        "field": "clientAge",
        "operator": "RANGE/GTE/LTE/MATCH",
        "value_type": "number",
        "definition": "客户年龄字段，用于年龄精确值或边界条件筛选。",
        "examples": ["45岁女性保费10万以上", "大于50岁的客户"],
    },
    "clientSex": {
        "field": "clientSex",
        "operator": "MATCH",
        "value_type": "enum",
        "enums": ["男", "女"],
        "definition": "客户性别字段。",
        "examples": ["45岁女性保费10万以上"],
    },
    "annPremSegNum": {
        "field": "annPremSegNum",
        "operator": "GTE/LTE/RANGE/MATCH",
        "value_type": "number",
        "definition": "年缴保费金额字段，中文金额单位需要换算成数值。",
        "examples": ["45岁女性保费10万以上", "年缴保费一万以上的客户"],
    },
    "polNoInfo.payamountdue": {
        "field": "polNoInfo.payamountdue",
        "operator": "MATCH",
        "value_type": "enum",
        "enums": ["是", "否"],
        "definition": "生存金未领取金额是否大于0；是表示存在未领取生存金。",
        "examples": ["有未领生存金的", "有生存金未领取的客户"],
    },
    "pCategorys": {
        "field": "pCategorys",
        "operator": "CONTAINS/NOT_CONTAINS",
        "value_type": "list",
        "definition": "险种大类字段，用于年金险、两全险、重疾险等保险类别筛选。",
        "examples": ["买了年金险或两全险的客户", "只有重疾险的客户"],
    },
}


def source_config_paths(spec: ProjectSpec) -> Dict[str, str]:
    paths = {}
    root = Path(spec.root)
    for key, rel in (spec.documents or {}).items():
        if key.startswith("source_") and "config/" in str(rel):
            paths[key] = str((root / str(rel)).resolve())
    return paths


def external_boundary_sources(spec: ProjectSpec) -> Dict[str, Any]:
    return {"config_paths": source_config_paths(spec)}


def capability_manifest(spec: ProjectSpec) -> dict:
    try:
        config_paths = source_config_paths(spec)
        return build_capability_manifest(config_paths.get("source_field_definitions"))
    except Exception:
        return {}



def value_mappings(spec: ProjectSpec) -> dict:
    try:
        config_paths = source_config_paths(spec)
        path = config_paths.get("source_value_mappings")
        if not path or not Path(path).exists():
            return {}
        with open(path) as f:
            data = _yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}



def enhanced_rules(spec: ProjectSpec) -> dict:
    try:
        config_paths = source_config_paths(spec)
        path = config_paths.get("source_enhanced_rules")
        if not path or not Path(path).exists():
            return {}
        with open(path) as f:
            data = _yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}



def build_request(spec: ProjectSpec, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
    input_data = dict(case.input or {})
    normalized_request = {
        "user_text": input_data.get("user_text"),
        "user_id": input_data.get("user_id") or "eval-user",
        "trace_id": input_data.get("trace_id") or f"general-eval-{int(time.time() * 1000)}",
        "session_id": input_data.get("session_id") or "general-eval-session",
        "source": input_data.get("source") or "askbob",
        "extra_input_params": dict(input_data.get("extra_input_params") or {}),
    }
    return LiveRequest(
        project_id=spec.project_id,
        raw_input=input_data,
        case_id=str(case.id or ""),
        normalized_request=normalized_request,
        execution_mode="live_service",
        session_id=input_data.get("session_id") or "general-eval-session",
    )



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



def project_fields(raw_response: Any, extracted_output: Dict[str, Any], spec: ProjectSpec | None = None) -> Dict[str, Any]:
    extra = {}
    if isinstance(raw_response, dict):
        data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
        extra = data.get("extra_output_params") if isinstance(data.get("extra_output_params"), dict) else {}
    empty_result_reason = _empty_result_reason(extracted_output.get("query", ""), extra)
    return {
        "downstream_search": raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {},
        "external_boundary_sources": external_boundary_sources(spec) if spec is not None else {"config_paths": {}},
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



def boundary_from_trace(trace: RunTrace, downstream: dict[str, Any] | None = None) -> dict[str, Any]:
    live_result = getattr(trace, "live_result", None)
    if live_result and isinstance(getattr(live_result, "application_boundary", None), dict) and live_result.application_boundary:
        return live_result.application_boundary
    return _application_boundary(downstream or {})



def client_search_boundary_evidence(spec: ProjectSpec, context: TraceExecutionContext) -> Dict[str, Any]:
    trace = context.get("trace")
    if not trace:
        return {"status": "failed", "missing_evidence": ["trace"]}
    project_output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    project_fields_map = trace.project_fields if isinstance(trace.project_fields, dict) else {}
    downstream_search = project_fields_map.get("downstream_search") if isinstance(project_fields_map.get("downstream_search"), dict) else {}
    evidence = {
        "condition_count": len(project_output.get("conditions") or []),
        "query_logic": project_output.get("query_logic"),
        "downstream_status": downstream_search.get("status"),
        "application_boundary": boundary_from_trace(trace),
        "source_config_paths": (project_fields_map.get("external_boundary_sources") or {}).get("config_paths") or {},
    }
    return {
        "status": "succeeded",
        "outputs": evidence,
        "evidence_refs": [{"type": "client_search_boundary", "evidence": evidence}],
        "claims": [{"client_search_boundary": evidence}],
    }



def collect_state_evidence(trace: RunTrace, state_id: str) -> list[Dict[str, Any]]:
    project_fields_map = trace.project_fields if isinstance(trace.project_fields, dict) else {}
    return [{"type": "client_search_state_boundary", "state_id": state_id, "application_boundary": boundary_from_trace(trace), "external_boundary_sources": project_fields_map.get("external_boundary_sources") or {}}]



def trace_state_graph(spec: ProjectSpec) -> Dict[str, Any]:
    from copy import deepcopy

    from impl.core.state_machine import DEFAULT_TRACE_GRAPH

    graph = deepcopy(DEFAULT_TRACE_GRAPH)
    graph["graph_id"] = f"{spec.project_id}_trace_state_machine"
    refs = [{"executor_id": "collect_evidence", "executor_type": "deterministic", "role": "generic_evidence_collector"}]
    refs.extend(
        {"executor_id": executor_id, "executor_type": "adapter_hook", "role": executor_id}
        for executor_id in ["client_search_boundary_evidence"]
    )
    graph["states"]["collect_evidence"] = {
        **graph["states"].get("collect_evidence", {}),
        "executor_refs": refs,
        "merge_policy": "sequential_accumulation",
    }
    return graph



def state_executors(spec: ProjectSpec) -> Dict[str, Any]:
    return {"client_search_boundary_evidence": lambda context: client_search_boundary_evidence(spec, context)}



def strip_non_ready_fields(spec: ProjectSpec, case: Dict[str, Any]) -> Dict[str, Any]:
    ready = ready_from_spec(spec)
    if not isinstance(case, dict):
        return case
    if "output" not in ready and "output" in case:
        case = {k: v for k, v in case.items() if k != "output"}
    if "reference" not in ready and "reference" in case:
        case = {k: v for k, v in case.items() if k != "reference"}
    return case


class ClientSearchLive(RealServiceLive):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        return build_request(self.spec, case).normalized_request

    def deliver_real(self, request: LiveRequest) -> Any:
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
