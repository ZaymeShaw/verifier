from __future__ import annotations

import importlib.util
import inspect
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .adapter import ProjectAdapter
from .interaction_protocol import resolve_ready
from .live_stub import generate_live_output_with_check
from .mock_agent import load_live_schema
from .schema import (
    ExecutionTraceEvent,
    FallbackDecision,
    LiveExecutionResult,
    LiveMultiTurnResult,
    LiveMultiTurnState,
    LiveRequest,
    MultiTurnCase,
    MultiTurnInteraction,
    MultiTurnPolicy,
    MultiTurnTurnExpectation,
    ProjectSpec,
    RunTrace,
    SingleTurnCase,
    normalize_live_execution_result,
    normalize_live_multi_turn_result,
    normalize_mock_case,
    normalize_run_trace,
    to_dict,
)


class ProjectLiveCompat:
    """项目 live 投递兼容层。

    新协议中 adapter 负责语义翻译，项目 live.py 负责投递、响应解释和 live 证据构造。
    没有 live.py 的旧项目仍走 adapter legacy hooks；active 项目不应依赖该路径。
    """

    supports_stub = False

    def __init__(self, spec: ProjectSpec, adapter: ProjectAdapter):
        self.spec = spec
        self.adapter = adapter

    def deliver_real(self, request: LiveRequest) -> Any:
        try:
            return self.adapter.call_or_prepare(request)
        except TypeError:
            return self.adapter.call_or_prepare(request.normalized_request)  # type: ignore[arg-type]

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        return self.adapter.provided_output_raw(case, request)

    def deliver_stub(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Optional[Dict[str, Any]]:
        if not self.supports_stub:
            return None
        intent = {
            "input": dict(request.normalized_request or request.raw_input or {}),
            "expected_intent": getattr(case, "expected_intent", ""),
            "scenario": getattr(case, "scenario", ""),
        }
        return generate_live_output_with_check(self.spec, intent, self.spec.project_id)

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return self.adapter.extract_output(raw_response)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return self.adapter.application_boundary(raw_response, extracted_output)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return self.adapter.project_fields(raw_response, extracted_output)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list[ExecutionTraceEvent]:
        return self.adapter.build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output)


class ProjectLiveModule(ProjectLiveCompat):
    def __init__(self, spec: ProjectSpec, adapter: ProjectAdapter, module: Any, impl: Any):
        super().__init__(spec, adapter)
        self.module = module
        self.impl = impl
        self.supports_stub = bool(getattr(impl, "supports_stub", False) or getattr(module, "supports_stub", False))

    def _fn(self, name: str) -> Any:
        return getattr(self.impl, name, None) or getattr(self.module, name, None)

    def _call_live_fn(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        signature = inspect.signature(fn)
        parameters = signature.parameters
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        if accepts_kwargs:
            accepted = kwargs
        else:
            positional_names = [
                name
                for name, parameter in parameters.items()
                if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ][:len(args)]
            accepted = {key: value for key, value in kwargs.items() if key in parameters and key not in positional_names}
        return fn(*args, **accepted)

    def deliver_real(self, request: LiveRequest) -> Any:
        fn = self._fn("deliver_real")
        if fn is None:
            return super().deliver_real(request)
        return fn(self.spec, self.adapter, request)

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        fn = self._fn("deliver_provided")
        if fn is None:
            return super().deliver_provided(case, request)
        return fn(self.spec, self.adapter, case, request)

    def deliver_stub(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Optional[Dict[str, Any]]:
        fn = self._fn("deliver_stub")
        if fn is None:
            return super().deliver_stub(case, request)
        return fn(self.spec, self.adapter, case, request)

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        fn = self._fn("extract_output")
        if fn is None:
            return super().extract_output(raw_response, request)
        return self._call_live_fn(fn, raw_response, request=request, spec=self.spec)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        fn = self._fn("application_boundary")
        if fn is None:
            return super().application_boundary(raw_response, extracted_output, request)
        return self._call_live_fn(fn, raw_response, extracted_output, request=request, spec=self.spec)

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        fn = self._fn("project_fields")
        if fn is None:
            return super().project_fields(raw_response, extracted_output, request, application_boundary)
        return self._call_live_fn(fn, raw_response, extracted_output, request=request, spec=self.spec, application_boundary=application_boundary)

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list[ExecutionTraceEvent]:
        fn = self._fn("build_execution_trace")
        if fn is None:
            return super().build_execution_trace(raw_response, extracted_output, request)
        return self._call_live_fn(fn, request.raw_input, request.normalized_request, raw_response, extracted_output, request=request, spec=self.spec)


def load_project_live(spec: ProjectSpec, adapter: ProjectAdapter) -> ProjectLiveCompat:
    live_path = Path(spec.root) / "live.py"
    if not live_path.exists():
        return ProjectLiveCompat(spec, adapter)
    module_name = f"impl_project_{spec.project_id.replace('-', '_')}_live"
    module_spec = importlib.util.spec_from_file_location(module_name, live_path)
    if module_spec is None or module_spec.loader is None:
        return ProjectLiveCompat(spec, adapter)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    impl_cls = getattr(module, "LiveDelivery", None)
    impl = impl_cls() if impl_cls is not None else module
    return ProjectLiveModule(spec, adapter, module, impl)


def fallback_decision(
    fallback_id: str,
    source_stage: str,
    fallback_type: str,
    status: str,
    reason: str,
    missing_evidence: Optional[list[str]] = None,
    recoverable: bool = False,
    needs_human_review: bool = False,
    quality_flags: Optional[list[str]] = None,
    evidence_refs: Optional[list[Dict[str, Any]]] = None,
    failed_gate_ids: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FallbackDecision:
    return FallbackDecision(
        fallback_id=fallback_id,
        source_stage=source_stage,
        fallback_type=fallback_type,
        status=status,
        reason=reason,
        missing_evidence=list(missing_evidence or []),
        recoverable=recoverable,
        needs_human_review=needs_human_review,
        quality_flags=list(quality_flags or []),
        evidence_refs=list(evidence_refs or []),
        failed_gate_ids=list(failed_gate_ids or []),
        metadata=dict(metadata or {}),
    )


def build_live_request(adapter: ProjectAdapter, case: SingleTurnCase | MultiTurnCase, project_id: str) -> LiveRequest:
    try:
        request = adapter.build_request(case)
    except (AttributeError, TypeError):
        request = adapter.build_request(case.input)  # type: ignore[arg-type]
    if isinstance(request, LiveRequest):
        setattr(request, "_live_schema_request_validation", _validate_request(project_id, request.normalized_request))
        return request
    live_request = LiveRequest(project_id=project_id, raw_input=dict(case.input or {}), case_id=case.id, normalized_request=request if isinstance(request, dict) else {})
    setattr(live_request, "_live_schema_request_validation", _validate_request(project_id, live_request.normalized_request))
    return live_request


def trace_from_live_result(adapter: ProjectAdapter, result: LiveExecutionResult) -> RunTrace:
    try:
        trace = adapter.to_run_trace(result)
    except TypeError:
        trace = ProjectAdapter.to_run_trace(adapter, result)
    return normalize_run_trace(trace)


def interaction_contract(case: SingleTurnCase) -> MultiTurnInteraction | None:
    if not case.metadata.get("interaction"):
        return None
    interaction = normalize_mock_case({**to_dict(case), "interaction": case.metadata.get("interaction")})
    if hasattr(interaction, "interaction"):
        return interaction.interaction
    return MultiTurnInteraction(policy=MultiTurnPolicy(), turn_expectations=[MultiTurnTurnExpectation(turn=1)])


def live_multi_turn_result(result: LiveExecutionResult) -> LiveMultiTurnResult | None:
    if result.interaction_mode != "interactive_intent" and result.multi_turn_state is None:
        return None
    state = result.multi_turn_state or LiveMultiTurnState(
        session_id=result.session_id,
        transcript=result.execution_trace,
        accumulated_fields={},
    )
    result.multi_turn_state = state
    return normalize_live_multi_turn_result({
        "project_id": result.project_id,
        "case_id": result.case_id,
        "session_id": result.session_id,
        "turn_results": [result],
        "conversation_transcript": state.transcript,
        "stop_reason": state.stop_reason,
        "final_output": result.extracted_output,
    })


def run_live(
    spec: ProjectSpec,
    adapter: ProjectAdapter,
    case: SingleTurnCase | MultiTurnCase,
    request: LiveRequest,
    contract: MultiTurnInteraction | None = None,
) -> LiveExecutionResult:
    project_live = load_project_live(spec, adapter)
    if _has_provided_output(spec, case, request):
        result = _run_provided(spec, adapter, project_live, case, request)
    else:
        result = _run_real_or_fallback(spec, adapter, project_live, case, request)
    _apply_interaction_state(result, request, contract)
    return result


def _has_provided_output(spec: ProjectSpec, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> bool:
    if not resolve_ready(spec, case).output:
        return False
    output = getattr(case, "output", None)
    if isinstance(output, dict) and output:
        return True
    input_data = dict(getattr(case, "input", {}) or {})
    return any(key in input_data for key in ("raw_response", "response", "output"))


def _run_provided(
    spec: ProjectSpec,
    adapter: ProjectAdapter,
    project_live: ProjectLiveCompat,
    case: SingleTurnCase | MultiTurnCase,
    request: LiveRequest,
) -> LiveExecutionResult:
    raw_response = project_live.deliver_provided(case, request)
    extracted_output = project_live.extract_output(raw_response, request)
    application_boundary = project_live.application_boundary(raw_response, extracted_output, request)
    result = LiveExecutionResult(
        project_id=spec.project_id,
        case_id=request.case_id,
        session_id=request.session_id,
        raw_input=request.raw_input,
        normalized_request=request.normalized_request,
        raw_response=raw_response,
        extracted_output=extracted_output,
        output_source="provided_output",
        call_status="succeeded",
        execution_trace=project_live.build_execution_trace(raw_response, extracted_output, request),
        project_fields=project_live.project_fields(raw_response, extracted_output, request, application_boundary),
        application_boundary=application_boundary,
        interaction_mode="interactive_intent" if request.turns else "single_turn",
    )
    setattr(result, "_live_schema_request_validation", getattr(request, "_live_schema_request_validation", None))
    _append_validation(result, _validate_output(spec.project_id, extracted_output))
    return result


def _run_real_or_fallback(
    spec: ProjectSpec,
    adapter: ProjectAdapter,
    project_live: ProjectLiveCompat,
    case: SingleTurnCase | MultiTurnCase,
    request: LiveRequest,
) -> LiveExecutionResult:
    start = time.time()
    try:
        candidate = project_live.deliver_real(request)
    except Exception as exc:
        stub = project_live.deliver_stub(case, request)
        if stub is not None:
            result = _result_from_raw(spec, adapter, project_live, request, stub, "stub", start)
            setattr(result, "_live_schema_request_validation", getattr(request, "_live_schema_request_validation", None))
            _append_validation(result, _validate_output(spec.project_id, result.extracted_output))
            return result
        return _failed_live_result(spec.project_id, request, str(exc))

    result = _candidate_to_result(spec, adapter, project_live, request, candidate, start)
    setattr(result, "_live_schema_request_validation", getattr(request, "_live_schema_request_validation", None))
    if result.call_status != "succeeded":
        unavailable = result.output_source == "live_service_unavailable"
        if not unavailable and result.output_source in ("", "live_service"):
            result.output_source = "live_protocol_error"
        if not result.fallbacks:
            result.fallbacks = [_make_live_error_fallback(spec.project_id, request, result.call_error or "business service call failed", unavailable=unavailable)]
        _append_validation(result, None)
        return result
    _append_validation(result, _validate_output(spec.project_id, result.extracted_output))
    return result


def _candidate_to_result(
    spec: ProjectSpec,
    adapter: ProjectAdapter,
    project_live: ProjectLiveCompat,
    request: LiveRequest,
    candidate: Any,
    start: float,
) -> LiveExecutionResult:
    if isinstance(candidate, LiveExecutionResult):
        result = candidate
    elif isinstance(candidate, dict) and {"project_id", "raw_input", "normalized_request", "extracted_output"}.intersection(candidate):
        result = normalize_live_execution_result(candidate)
        if result is None:
            result = _result_from_raw(spec, adapter, project_live, request, candidate, request.execution_mode, start)
    else:
        result = _result_from_raw(spec, adapter, project_live, request, candidate, request.execution_mode, start)
    if result.project_id != spec.project_id:
        result.project_id = spec.project_id
    if not result.case_id:
        result.case_id = request.case_id
    if not result.session_id:
        result.session_id = request.session_id
    if not result.raw_input:
        result.raw_input = request.raw_input
    if not result.normalized_request:
        result.normalized_request = request.normalized_request
    if result.runtime_ms is None:
        result.runtime_ms = int((time.time() - start) * 1000)
    return result


def _result_from_raw(
    spec: ProjectSpec,
    adapter: ProjectAdapter,
    project_live: ProjectLiveCompat,
    request: LiveRequest,
    raw_response: Any,
    output_source: str,
    start: float,
) -> LiveExecutionResult:
    extracted_output = project_live.extract_output(raw_response, request)
    application_boundary = project_live.application_boundary(raw_response, extracted_output, request)
    return LiveExecutionResult(
        project_id=spec.project_id,
        case_id=request.case_id,
        session_id=request.session_id,
        raw_input=request.raw_input,
        normalized_request=request.normalized_request,
        raw_response=raw_response,
        runtime_ms=int((time.time() - start) * 1000),
        extracted_output=extracted_output,
        output_source=output_source,
        execution_trace=project_live.build_execution_trace(raw_response, extracted_output, request),
        project_fields=project_live.project_fields(raw_response, extracted_output, request, application_boundary),
        application_boundary=application_boundary,
        interaction_mode="interactive_intent" if request.turns else "single_turn",
    )


def _failed_live_result(project_id: str, request: LiveRequest, reason: str) -> LiveExecutionResult:
    fallback = _make_live_error_fallback(project_id, request, reason)
    result = LiveExecutionResult(
        project_id=project_id,
        case_id=request.case_id,
        session_id=request.session_id,
        raw_input=request.raw_input,
        normalized_request=request.normalized_request,
        call_status="failed",
        call_error=reason,
        output_source="live_service_unavailable",
        execution_trace=[ExecutionTraceEvent(stage="project.call", status="failed", evidence=reason)],
        interaction_mode="interactive_intent" if request.turns else "single_turn",
        fallbacks=[fallback],
    )
    setattr(result, "_live_schema_request_validation", getattr(request, "_live_schema_request_validation", None))
    _append_validation(result, None)
    return result


def _make_live_error_fallback(project_id: str, request: LiveRequest, reason: str, unavailable: bool = True) -> FallbackDecision:
    failure_type = "live_service_unavailable" if unavailable else "live_protocol_error"
    return fallback_decision(
        fallback_id=f"live-error-{request.case_id or project_id}",
        source_stage="live",
        fallback_type="live_error",
        status="error",
        reason=reason,
        missing_evidence=["live_response"] if unavailable else ["valid_live_response"],
        recoverable=unavailable,
        needs_human_review=True,
        quality_flags=[failure_type],
        metadata={"case_id": request.case_id, "session_id": request.session_id, "failure_type": failure_type},
    )


def _multi_turn_accumulated_fields(extracted_output: Any) -> Dict[str, Any]:
    if not isinstance(extracted_output, dict):
        return {}
    candidates: list[dict[str, Any]] = []
    turns = extracted_output.get("turns")
    if isinstance(turns, list):
        candidates.extend(turn for turn in reversed(turns) if isinstance(turn, dict))
    candidates.append(extracted_output)
    for candidate in candidates:
        session_summary = candidate.get("session_summary") if isinstance(candidate, dict) else None
        if isinstance(session_summary, dict) and isinstance(session_summary.get("accumulated_fields"), dict):
            return dict(session_summary.get("accumulated_fields") or {})
    return {}


def _apply_interaction_state(result: LiveExecutionResult, request: LiveRequest, contract: MultiTurnInteraction | None) -> None:
    if contract is not None:
        result.interaction_mode = contract.mode
    elif request.turns or (isinstance(request.normalized_request, dict) and isinstance(request.normalized_request.get("turns"), list)):
        result.interaction_mode = "interactive_intent"
    if result.interaction_mode == "interactive_intent" or contract is not None:
        turns = request.normalized_request.get("turns") if isinstance(request.normalized_request, dict) else request.turns
        result.multi_turn_state = LiveMultiTurnState(
            session_id=request.session_id,
            transcript=list(turns or request.turns or []),
            accumulated_fields=_multi_turn_accumulated_fields(result.extracted_output),
            stop_reason="live_error" if result.call_status != "succeeded" else "",
        )
        live_multi_turn_result(result)


def _validate_request(project_id: str, payload: Any) -> Optional[ExecutionTraceEvent]:
    return _validate_live_schema(project_id, "request", payload)


def _validate_output(project_id: str, payload: Any) -> Optional[ExecutionTraceEvent]:
    return _validate_live_schema(project_id, "output", payload)


def _validate_live_schema(project_id: str, kind: str, payload: Any) -> Optional[ExecutionTraceEvent]:
    try:
        live_schema = load_live_schema(project_id)
        checker = getattr(live_schema, "check", None) if live_schema is not None else None
        if checker is None:
            return None
        check_fn = getattr(checker, kind)
        ok = bool(check_fn(payload))
        if ok:
            return ExecutionTraceEvent(stage=f"live_schema.validate_{kind}", status="ok", evidence={"project_id": project_id})
        evidence = {"project_id": project_id, "kind": kind, "error": f"{kind} 不符合 live_schema"}
        print(f"[live_schema] WARNING: {kind} check failed for {project_id}: {evidence['error']}", file=sys.stderr)
        return ExecutionTraceEvent(stage=f"live_schema.validate_{kind}", status="failed", evidence=evidence)
    except Exception as exc:
        print(f"[live_schema] WARNING: {kind} check exception for {project_id}: {exc}", file=sys.stderr)
        return ExecutionTraceEvent(stage=f"live_schema.validate_{kind}", status="failed", evidence={"project_id": project_id, "kind": kind, "error": str(exc)})


def _append_validation(target: LiveRequest | LiveExecutionResult, event: Optional[ExecutionTraceEvent]) -> None:
    if isinstance(target, LiveRequest):
        setattr(target, "_live_schema_request_validation", event)
        return
    request_event = getattr(target, "_live_schema_request_validation", None)
    if request_event is None and isinstance(target.normalized_request, dict):
        request_event = _validate_request(target.project_id, target.normalized_request)
    if isinstance(request_event, ExecutionTraceEvent):
        target.execution_trace.append(request_event)
    if event is not None:
        target.execution_trace.append(event)
    diagnostics = [to_dict(item) for item in target.execution_trace if getattr(item, "stage", "").startswith("live_schema.validate_")]
    if diagnostics:
        fields = dict(target.project_fields or {})
        fields["live_schema_validation"] = diagnostics
        target.project_fields = fields
