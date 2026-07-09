from __future__ import annotations

from typing import Any, Dict

from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveRequest, MultiTurnCase, ProjectSpec, SingleTurnCase

APPLICATION_BOUNDARY = {"scope": "qa_semantic_answer_evaluation", "external_service_required": False}


def _attach_request(raw_response: Any, request: Dict[str, Any]) -> Any:
    if isinstance(raw_response, dict):
        return {**raw_response, "_normalized_request": request}
    return {"actual_answer": str(raw_response or ""), "_normalized_request": request}


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    raw_response = input_data.get("output") or getattr(case, "output", None) or {"actual_answer": ""}
    return _attach_request(raw_response, request.normalized_request)


def extract_output(raw_response: Any) -> Dict[str, Any]:
    if isinstance(raw_response, dict):
        return {"actual_answer": str(raw_response.get("actual_answer") or raw_response.get("answer") or raw_response.get("text") or "")}
    return {"actual_answer": str(raw_response or "")}


def project_fields(raw_response: Any, extracted_output: Dict[str, Any], request: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized_request = request if isinstance(request, dict) else None
    if normalized_request is None and isinstance(raw_response, dict):
        embedded = raw_response.get("_normalized_request")
        normalized_request = embedded if isinstance(embedded, dict) else None
    if not isinstance(normalized_request, dict):
        return {}
    sample_input = normalized_request.get("input") if isinstance(normalized_request.get("input"), dict) else {}
    return {
        "scenario": normalized_request.get("scenario") or "",
        "data_quality_flags": list(normalized_request.get("data_quality_flags") or []),
        "contexts": list(sample_input.get("contexts") or []),
        "reference": dict(normalized_request.get("reference") or {}),
        "metadata": dict(normalized_request.get("metadata") or {}),
        "estimated_quality_only": normalized_request.get("scenario") == "qa_weak_quality",
    }


def application_boundary(raw_response: Any | None = None, extracted_output: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return dict(APPLICATION_BOUNDARY)


def build_execution_trace(input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
    return [
        ExecutionTraceEvent(stage="qa.sample.normalize", status="ok" if request.get("scenario") != "invalid_sample" else "suspicious", evidence={"scenario": request.get("scenario"), "flags": request.get("data_quality_flags")}),
        ExecutionTraceEvent(stage="qa.output.read", status="ok" if extracted_output.get("actual_answer") else "suspicious", evidence="evaluated output read from uploaded sample"),
        ExecutionTraceEvent(stage="qa.output.extract", status="ok", evidence={"actual_answer_present": bool(extracted_output.get("actual_answer"))}),
    ]


class LiveDelivery:
    """QA 项目的 live 投递层：只读取 case 中的预制输出，不调用外部服务。"""

    def deliver_provided(self, spec: ProjectSpec, adapter: Any, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        return provided_output_raw(case, request)

    def deliver_real(self, spec: ProjectSpec, adapter: Any, request: LiveRequest) -> LiveExecutionResult:
        call_error = "QA project is provided-output only; no real live service is configured."
        boundary = {**application_boundary(), "live_service_available": False, "sample_replay_only": True}
        trace = [
            ExecutionTraceEvent(stage="qa.live_service", status="failed", evidence={"reason": call_error}),
        ]
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status="failed",
            raw_response=None,
            call_error=call_error,
            extracted_output={},
            output_source="live_service_unavailable",
            execution_trace=trace,
            project_fields=project_fields(None, {}, request.normalized_request),
            application_boundary=boundary,
        )
