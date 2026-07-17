from __future__ import annotations

from typing import Any, Dict

from impl.core.schema import ExecutionTraceEvent, LiveRequest, MultiTurnCase, ProjectSpec, SingleTurnCase

APPLICATION_BOUNDARY = {"scope": "qa_semantic_answer_evaluation", "external_service_required": False}


def _attach_request(raw_response: Any, request: Dict[str, Any]) -> Any:
    if isinstance(raw_response, dict):
        return {**raw_response, "_normalized_request": request}
    return {"actual_answer": str(raw_response or ""), "_normalized_request": request}


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    raw_response = input_data.get("output") or getattr(case, "output", None) or {"actual_answer": ""}
    return _attach_request(raw_response, request.normalized_request)


def provided_output_from_request(normalized: Dict[str, Any]) -> Any:
    """从已归一化的请求中提取 provided output（normalized 已包含 output 字段）。"""
    raw_response = normalized.get("output") or {"actual_answer": ""}
    return _attach_request(raw_response, normalized)


def extract_output(raw_response: Any) -> Dict[str, Any]:
    if isinstance(raw_response, dict):
        supported_keys = ("actual_answer", "answer", "text")
        if not any(key in raw_response for key in supported_keys):
            raise ValueError("QA provided output must contain one of: actual_answer, answer, text")
        answer = next((raw_response.get(key) for key in supported_keys if raw_response.get(key) not in (None, "")), "")
    else:
        answer = raw_response
    normalized = str(answer or "").strip()
    if not normalized:
        raise ValueError("QA provided output actual_answer must be non-empty")
    return {"actual_answer": normalized}


def project_fields(raw_response: Any, extracted_output: Dict[str, Any], request: Dict[str, Any] | None = None) -> Dict[str, Any]:
    # normalized_request 现在是 QAInput 形状（flat），contexts 在顶层
    normalized_request = request if isinstance(request, dict) else None
    if normalized_request is None and isinstance(raw_response, dict):
        embedded = raw_response.get("_normalized_request")
        normalized_request = embedded if isinstance(embedded, dict) else None
    if not isinstance(normalized_request, dict):
        return {}
    return {
        "scenario": normalized_request.get("scenario") or "",
        "data_quality_flags": list(normalized_request.get("data_quality_flags") or []),
        "contexts": list(normalized_request.get("contexts") or []),
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


from impl.core.live_protocol import ProvidedOutputLive, SingleTurnLive


class QALive(ProvidedOutputLive, SingleTurnLive):
    """QA 项目 Live 实现（新协议）：只读取 case 中的预制输出，不调用外部服务。

    复用模块级函数，扩展点签名统一使用 LiveRequest。
    """

    def deliver_provided(self, request: LiveRequest) -> Any:
        normalized = request.normalized_request if isinstance(request.normalized_request, dict) else {}
        return provided_output_from_request(normalized)

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, request.normalized_request)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list[ExecutionTraceEvent]:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output)
