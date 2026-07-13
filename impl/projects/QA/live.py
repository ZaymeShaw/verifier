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


from impl.core.live_protocol import ProvidedOutputLive


class QALive(ProvidedOutputLive):
    """QA 项目 Live 实现（新协议）：只读取 case 中的预制输出，不调用外部服务。

    复用模块级函数，扩展点签名统一使用 LiveRequest。
    """

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        # 方案 A：mock 直接对接 live_schema，build_request 不做形状翻译。
        # case.input 已是 QAInput 形状（= REQUEST_SCHEMA），直接透传作为 normalized_request。
        input_data = dict(case.input or {}) if hasattr(case, "input") else {}
        # 补默认值，保持 QAInput 形状完整，不改形状
        normalized = {
            "question": str(input_data.get("question") or ""),
            "contexts": list(input_data.get("contexts") or []),
            "reference": dict(input_data.get("reference") or {}),
            "metadata": dict(input_data.get("metadata") or {}),
            "scenario": str(input_data.get("scenario") or "qa_default"),
            "data_quality_flags": list(input_data.get("data_quality_flags") or []),
            "output": dict(input_data.get("output") or getattr(case, "output", {}) or {}),
        }
        return normalized

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        return provided_output_raw(case, request)

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return application_boundary(raw_response, extracted_output)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, request.normalized_request)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list[ExecutionTraceEvent]:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output)
