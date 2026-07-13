from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .schema import (
    ExecutionTraceEvent,
    FallbackDecision,
    LiveExecutionResult,
    LiveMultiTurnResult,
    LiveMultiTurnState,
    MultiTurnInteraction,
    MultiTurnPolicy,
    MultiTurnTurnExpectation,
    RunTrace,
    SingleTurnCase,
    normalize_live_multi_turn_result,
    normalize_mock_case,
    normalize_run_trace,
    to_dict,
)



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



def trace_from_live_result(result: LiveExecutionResult) -> RunTrace:
    project_fields = dict(result.project_fields or {})
    raw_input = result.raw_input if isinstance(result.raw_input, dict) else {}
    normalized_request = result.normalized_request if isinstance(result.normalized_request, dict) else {}
    reference_contract = raw_input.get("reference") if isinstance(raw_input.get("reference"), dict) else normalized_request.get("reference") if isinstance(normalized_request.get("reference"), dict) else {}
    scenario = str(raw_input.get("scenario") or normalized_request.get("scenario") or "")
    trace = RunTrace(
        trace_id=result.trace_id if hasattr(result, "trace_id") else f"{result.project_id}:{result.case_id}:{int(time.time()*1000)}",
        project_id=result.project_id,
        case_id=result.case_id,
        input=raw_input,
        normalized_request=normalized_request,
        raw_response=result.raw_response,
        extracted_output=result.extracted_output or {},
        live_result=result,
        execution_mode=result.output_source or "live_service",
        output_source=result.output_source or "live_service",
        scenario=scenario,
        reference_contract=dict(reference_contract or {}),
        application_boundary=dict(result.application_boundary or {}),
        project_fields=project_fields,
        runtime_logs=[],
        evidence_refs=[],
        execution_trace=list(result.execution_trace or []),
        status="ok" if result.call_status == "succeeded" else "error",
        error=result.call_error or "",
        interaction_mode=getattr(result, "interaction_mode", "single_turn") or "single_turn",
        multi_turn_input=None,
        fallbacks=list(getattr(result, "fallbacks", []) or []),
        ready=[],
    )
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
