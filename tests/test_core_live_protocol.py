from __future__ import annotations

from typing import Any

from impl.core import live
from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveRequest, ProjectSpec, SingleTurnCase


class _Checker:
    def __init__(self, request_ok: bool = True, output_ok: bool = True):
        self.request_ok = request_ok
        self.output_ok = output_ok

    def request(self, payload: Any) -> bool:
        return self.request_ok

    def output(self, payload: Any) -> bool:
        return self.output_ok


class _LiveSchema:
    def __init__(self, checker: _Checker):
        self.check = checker


class _Adapter:
    def __init__(self):
        self.real_called = False

    def build_request(self, case: SingleTurnCase) -> LiveRequest:
        return LiveRequest(
            project_id="demo",
            raw_input=dict(case.input or {}),
            case_id=str(case.id or "case-1"),
            normalized_request=dict(case.input or {}),
        )

    def call_or_prepare(self, request: LiveRequest) -> Any:
        self.real_called = True
        return {"answer": "real"}

    def provided_output_raw(self, case: SingleTurnCase, request: LiveRequest) -> Any:
        return case.output or {}

    def extract_output(self, raw_response: Any) -> dict[str, Any]:
        if isinstance(raw_response, dict):
            return {"answer": raw_response.get("answer") or raw_response.get("actual_answer") or ""}
        return {"answer": str(raw_response)}

    def build_execution_trace(self, input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any]) -> list[ExecutionTraceEvent]:
        return [ExecutionTraceEvent(stage="adapter.extract_output", status="ok", evidence=extracted_output)]

    def project_fields(self, raw_response: Any, extracted_output: dict[str, Any]) -> dict[str, Any]:
        return {}

    def application_boundary(self, raw_response: Any, extracted_output: dict[str, Any]) -> dict[str, Any]:
        return {}


class _FailingAdapter(_Adapter):
    def call_or_prepare(self, request: LiveRequest) -> Any:
        self.real_called = True
        raise RuntimeError("service unavailable")


class _FailedResultAdapter(_Adapter):
    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        self.real_called = True
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status="failed",
            call_error="returned failure",
            output_source="live_service_unavailable",
        )


class _ProtocolFailureAdapter(_Adapter):
    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        self.real_called = True
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status="failed",
            call_error="invalid live payload",
        )


def _spec(ready: list[str] | None = None) -> ProjectSpec:
    return ProjectSpec(project_id="demo", name="demo", common={"ready": ready or []}, root="/path/that/does/not/exist")


def _patch_schema(monkeypatch, request_ok: bool = True, output_ok: bool = True) -> None:
    monkeypatch.setattr(live, "load_live_schema", lambda project_id: _LiveSchema(_Checker(request_ok=request_ok, output_ok=output_ok)))


def _stages(result: LiveExecutionResult) -> list[str]:
    return [event.stage for event in result.execution_trace]


def test_provided_mode_does_not_call_real_service(monkeypatch):
    _patch_schema(monkeypatch)
    adapter = _Adapter()
    case = SingleTurnCase(id="case-1", input={"question": "q"}, output={"answer": "provided"})
    request = live.build_live_request(adapter, case, "demo")

    result = live.run_live(_spec(ready=["output"]), adapter, case, request)

    assert not adapter.real_called
    assert result.call_status == "succeeded"
    assert result.output_source == "provided_output"
    assert result.extracted_output == {"answer": "provided"}
    assert "live_schema.validate_request" in _stages(result)
    assert "live_schema.validate_output" in _stages(result)


def test_schema_mismatch_is_diagnostic_not_fallback(monkeypatch):
    _patch_schema(monkeypatch, request_ok=False, output_ok=False)
    adapter = _Adapter()
    case = SingleTurnCase(id="case-1", input={"question": "q"})
    request = live.build_live_request(adapter, case, "demo")

    result = live.run_live(_spec(), adapter, case, request)

    assert adapter.real_called
    assert result.call_status == "succeeded"
    assert result.fallbacks == []
    assert result.extracted_output == {"answer": "real"}
    validation = result.project_fields.get("live_schema_validation")
    assert validation
    assert {item["stage"] for item in validation} == {"live_schema.validate_request", "live_schema.validate_output"}
    assert all(item["status"] == "failed" for item in validation)


def test_real_exception_creates_fallback_without_output_validation(monkeypatch):
    _patch_schema(monkeypatch)
    adapter = _FailingAdapter()
    case = SingleTurnCase(id="case-1", input={"question": "q"})
    request = live.build_live_request(adapter, case, "demo")

    result = live.run_live(_spec(), adapter, case, request)

    assert adapter.real_called
    assert result.call_status == "failed"
    assert result.output_source == "live_service_unavailable"
    assert result.fallbacks
    assert "live_schema.validate_request" in _stages(result)
    assert "live_schema.validate_output" not in _stages(result)


def test_failed_live_result_keeps_request_validation_visible(monkeypatch):
    _patch_schema(monkeypatch, request_ok=False, output_ok=True)
    adapter = _FailedResultAdapter()
    case = SingleTurnCase(id="case-1", input={"question": "q"})
    request = live.build_live_request(adapter, case, "demo")

    result = live.run_live(_spec(), adapter, case, request)

    assert result.call_status == "failed"
    assert result.output_source == "live_service_unavailable"
    assert result.fallbacks
    assert "live_service_unavailable" in result.fallbacks[0].quality_flags
    assert "live_schema.validate_request" in _stages(result)
    assert "live_schema.validate_output" not in _stages(result)


def test_failed_protocol_result_is_not_reported_as_service_unavailable(monkeypatch):
    _patch_schema(monkeypatch)
    adapter = _ProtocolFailureAdapter()
    case = SingleTurnCase(id="case-1", input={"question": "q"})
    request = live.build_live_request(adapter, case, "demo")

    result = live.run_live(_spec(), adapter, case, request)

    assert result.call_status == "failed"
    assert result.output_source == "live_protocol_error"
    assert result.fallbacks
    fallback = result.fallbacks[0]
    assert "live_protocol_error" in fallback.quality_flags
    assert fallback.recoverable is False
    assert fallback.missing_evidence == ["valid_live_response"]
    assert "live_service_unavailable" not in fallback.quality_flags
    assert "live_schema.validate_request" in _stages(result)
    assert "live_schema.validate_output" not in _stages(result)
