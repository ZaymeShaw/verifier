from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict

from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveRequest, MultiTurnCase, ProjectSpec, SingleTurnCase

APPLICATION_BOUNDARY = {"scope": "single_turn_intent_recognition", "excludes": ["multi_turn_planning", "sse_card_generation"]}


def build_request(case: SingleTurnCase | MultiTurnCase) -> dict[str, Any]:
    input_data = dict(case.input or {})
    query = input_data.get("query") or ""
    reference = input_data.get("reference") or {}
    expected_intent = input_data.get("expected_intent") or (reference.get("intent") if isinstance(reference, dict) else None)
    session_id = str(input_data.get("session_id") or f"eval-{case.id or input_data.get('case_id') or input_data.get('id') or int(time.time() * 1000)}")
    return {
        "case_id": str(case.id or input_data.get("case_id") or input_data.get("id") or f"intent-case-{int(time.time() * 1000)}"),
        "session_id": session_id,
        "query": str(query),
        "scenario": str(input_data.get("scenario") or "intent_recognition"),
        "expected_intent": expected_intent,
        "reference": reference if isinstance(reference, dict) else {"intent": reference},
        "metadata": dict(input_data.get("metadata") or {}),
    }


def _live_request_body(request: LiveRequest | dict[str, Any]) -> dict[str, Any]:
    payload = request.normalized_request if isinstance(request, LiveRequest) else request
    query = str(payload.get("query") or "")
    session_id = str(payload.get("session_id") or f"eval-{payload.get('case_id') or int(time.time() * 1000)}")
    return {
        "session_id": session_id,
        "trace_id": str(payload.get("case_id") or session_id),
        "org_id": str((payload.get("metadata") or {}).get("org_id") or "eval-org"),
        "user_text": query,
        "extra_input_params": {
            "agent_args": {"conversation_id": session_id, "message": {"content": query, "content_type": "text"}},
            "args": {"extensions": {}, "contexts": []},
        },
    }


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    for key in ("raw_response", "response", "output"):
        if key in input_data:
            return {"raw": input_data[key], "request": request.normalized_request}
    return {"raw": {}, "request": request.normalized_request}


def _parse_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"raw_text": value}
    return value


def _first_value(value: Any, keys: list[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for nested_key in ("data", "result", "output", "extra_output_params", "card_result", "extensions"):
            nested = value.get(nested_key)
            found = _first_value(nested, keys)
            if found is not None:
                return found
    return None


def _raw_payload(raw_response: Any) -> Any:
    return raw_response.get("raw") if isinstance(raw_response, dict) and "raw" in raw_response else raw_response


def extract_output(raw_response: Any) -> dict[str, Any]:
    data = _raw_payload(raw_response)
    parsed = _parse_payload(data)
    nlu_info = _first_value(parsed, ["nlu_info"])
    if not isinstance(nlu_info, dict):
        nlu_info = {}
    raw_intent = _first_value(parsed, ["intent", "intent_type", "intent_label", "label", "type"])
    intent = nlu_info.get("intent") or raw_intent
    confidence = nlu_info.get("confidence") if "confidence" in nlu_info else _first_value(parsed, ["confidence", "score", "probability"])
    target_value = nlu_info.get("target_value") if isinstance(nlu_info, dict) else None
    path_types = nlu_info.get("path_types") if isinstance(nlu_info, dict) else None
    return {
        "intent": intent or "unknown",
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        "target_value": target_value,
        "path_types": path_types if isinstance(path_types, list) else None,
        "subIntent": nlu_info.get("subIntent") if isinstance(nlu_info, dict) else None,
    }


def intent_evidence(raw_response: Any, extracted_output: dict[str, Any]) -> dict[str, Any]:
    data = _raw_payload(raw_response)
    parsed = _parse_payload(data)
    nlu_info = _first_value(parsed, ["nlu_info"])
    if not isinstance(nlu_info, dict):
        nlu_info = {}
    slots = {key: value for key, value in nlu_info.items() if key not in {"intent", "confidence", "subIntent", "target_value", "path_types"} and value is not None} if nlu_info else (_first_value(parsed, ["slots", "slot", "slot_values"]) or {})
    entities = _first_value(parsed, ["entities", "entity", "extracted_entities"]) or []
    ambiguous = bool(_first_value(parsed, ["ambiguous", "is_ambiguous"]))
    fallback = bool(_first_value(parsed, ["fallback", "is_fallback"])) or str(extracted_output.get("intent") or "").lower() in {"unknown", "fallback"}
    errors = _first_value(parsed, ["error", "errors", "message"])
    if errors and not isinstance(errors, list):
        errors = [errors]
    return {
        "raw_intent": _first_value(parsed, ["intent", "intent_type", "intent_label", "label", "type"]),
        "slots": slots if isinstance(slots, dict) else {},
        "entities": entities if isinstance(entities, list) else [entities],
        "ambiguous": ambiguous,
        "fallback": fallback,
        "errors": errors or [],
    }


def project_fields(raw_response: Any, extracted_output: dict[str, Any]) -> dict[str, Any]:
    request = raw_response.get("request") if isinstance(raw_response, dict) else {}
    return {
        "scenario": request.get("scenario") or "intent_recognition",
        "case_id": request.get("case_id") or "",
        "session_id": request.get("session_id") or "",
        "reference": request.get("reference") or {},
        "expected_intent": request.get("expected_intent"),
        "intent_evidence": intent_evidence(raw_response, extracted_output),
        "application_boundary": application_boundary(raw_response, extracted_output),
    }


def application_boundary(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(APPLICATION_BOUNDARY)


def _api_status(raw_response: Any, extracted_output: dict[str, Any]) -> str:
    if not isinstance(raw_response, dict) or not raw_response.get("raw"):
        return "failed"
    if extracted_output.get("intent") and extracted_output.get("intent") != "unknown":
        return "ok"
    return "suspicious"


def build_execution_trace(input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any], spec: ProjectSpec | None = None) -> list[ExecutionTraceEvent]:
    endpoint = spec.api.get("endpoint") if spec is not None else None
    return [
        ExecutionTraceEvent(stage="request_normalization", status="ok" if request.get("query") else "suspicious", evidence={"query": request.get("query")}),
        ExecutionTraceEvent(stage="intent_api_call", status=_api_status(raw_response, extracted_output), evidence={"endpoint": endpoint, "raw_response_present": isinstance(raw_response, dict) and bool(raw_response.get("raw"))}),
        ExecutionTraceEvent(stage="adapter_extraction", status="ok" if extracted_output.get("intent") else "failed", evidence=extracted_output),
        ExecutionTraceEvent(stage="label_mapping", status="ok" if extracted_output.get("intent") != "unknown" else "suspicious", evidence={"intent": extracted_output.get("intent")}),
    ]


from impl.core.live_protocol import RealServiceLive


class MarketingIntentLive(RealServiceLive):
    """marketting-planning-intent 项目 Live 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        return build_request(case)

    def deliver_real(self, request: LiveRequest) -> Any:
        import time as _time
        start = _time.time()
        try:
            body = json.dumps(_live_request_body(request), ensure_ascii=False).encode("utf-8")
            url = str(self.spec.api.get("base_url") or "").rstrip("/") + "/" + str(self.spec.api.get("endpoint") or "").lstrip("/")
            api_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(self.spec.api.get("method") or "POST").upper())
            with urllib.request.urlopen(api_request, timeout=float(self.spec.api.get("timeout") or 60)) as response:
                raw_response = {"raw": response.read().decode("utf-8"), "request": request.normalized_request}
            call_status = "succeeded"
            call_error = None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raw_response = None
            call_status = "failed"
            call_error = f"marketing-planning intent service unavailable: {exc}"
        extracted_output = extract_output(raw_response) if call_status == "succeeded" else {}
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status=call_status,
            raw_response=raw_response,
            call_error=call_error,
            runtime_ms=int((_time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output, self.spec),
            project_fields=project_fields(raw_response, extracted_output),
            application_boundary=application_boundary(raw_response, extracted_output),
        )

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output, self.spec)
