from __future__ import annotations

import json
import urllib.error
from typing import Any, Dict

from impl.core.schema import ExecutionTraceEvent, LiveRequest, MultiTurnCase, ProjectSpec, SingleTurnCase
from impl.core.live_transport import LiveTransport

APPLICATION_BOUNDARY = {"scope": "single_turn_intent_recognition", "excludes": ["multi_turn_planning", "sse_card_generation"]}


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
    if isinstance(raw_response, list):
        raw_response = raw_response[0] if raw_response else {}
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


def project_fields(raw_response: Any, extracted_output: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    return {
        "scenario": request.get("scenario") or "intent_recognition",
        "trace_id": request.get("trace_id") or "",
        "session_id": request.get("session_id") or "",
        "intent_evidence": intent_evidence(raw_response, extracted_output),
        "application_boundary": application_boundary(raw_response, extracted_output),
    }


def application_boundary(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(APPLICATION_BOUNDARY)


def _api_status(raw_response: Any, extracted_output: dict[str, Any]) -> str:
    if not _raw_payload(raw_response):
        return "failed"
    if extracted_output.get("intent") and extracted_output.get("intent") != "unknown":
        return "ok"
    return "suspicious"


def build_execution_trace(input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any], spec: ProjectSpec | None = None) -> list[ExecutionTraceEvent]:
    endpoint = spec.api.get("endpoint") if spec is not None else None
    return [
        ExecutionTraceEvent(stage="request_normalization", status="ok" if request.get("user_text") else "suspicious", evidence={"user_text": request.get("user_text")}),
        ExecutionTraceEvent(stage="intent_api_call", status=_api_status(raw_response, extracted_output), evidence={"endpoint": endpoint, "raw_response_present": bool(_raw_payload(raw_response))}),
        ExecutionTraceEvent(stage="adapter_extraction", status="ok" if extracted_output.get("intent") else "failed", evidence=extracted_output),
        ExecutionTraceEvent(stage="label_mapping", status="ok" if extracted_output.get("intent") != "unknown" else "suspicious", evidence={"intent": extracted_output.get("intent")}),
    ]


from impl.core.live_protocol import LiveServiceUnavailableError, RealServiceLive, SingleTurnLive


class MarketingIntentLive(RealServiceLive, SingleTurnLive):
    """marketting-planning-intent 项目 Live 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        try:
            url = str(self.spec.api.get("base_url") or "").rstrip("/") + "/" + str(self.spec.api.get("endpoint") or "").lstrip("/")
            transport.request(
                str(self.spec.api.get("method") or "POST"), url,
                json_body=request,
                timeout=float(self.spec.api.get("timeout") or 60),
                carries_live_request=True,
                contributes_raw_response=True,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LiveServiceUnavailableError(f"marketing-planning intent service unavailable: {exc}") from exc
        return transport

    def extract_output(self, raw_response: list[Any]) -> Dict[str, Any]:
        return extract_output(raw_response)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        normalized = request.normalized_request if isinstance(request, LiveRequest) else request
        return project_fields(raw_response, extracted_output, normalized)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
        normalized_request = normalized_request if isinstance(normalized_request, dict) else {}
        return build_execution_trace(normalized_request, normalized_request, raw_response, extracted_output, self.spec)
