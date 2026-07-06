from __future__ import annotations

from typing import Any, Dict, List

from .evidence import ExecutionTraceEvent
from .trace import RunTrace
from .judge import JudgeResult
from .attribute import AttributeResult


def trace_input(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    live = trace.live_result
    if live and isinstance(live.raw_input, dict) and live.raw_input:
        return live.raw_input
    return trace.input if isinstance(trace.input, dict) else {}


def trace_normalized_request(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    live = trace.live_result
    if live and isinstance(live.normalized_request, dict) and live.normalized_request:
        return live.normalized_request
    return trace.normalized_request if isinstance(trace.normalized_request, dict) else {}


def trace_raw_response(trace: RunTrace | None) -> Any:
    if not trace:
        return None
    live = trace.live_result
    if live and live.raw_response is not None:
        return live.raw_response
    return trace.raw_response


def trace_extracted_output(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    live = trace.live_result
    if live and isinstance(live.extracted_output, dict) and live.extracted_output:
        return live.extracted_output
    return trace.extracted_output if isinstance(trace.extracted_output, dict) else {}


def trace_output_source(trace: RunTrace | None) -> str:
    if not trace:
        return ""
    live = trace.live_result
    if live and live.output_source:
        return str(live.output_source)
    return str(trace.output_source or "")


def trace_application_boundary(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    live = trace.live_result
    if live and isinstance(live.application_boundary, dict) and live.application_boundary:
        return live.application_boundary
    return trace.application_boundary if isinstance(trace.application_boundary, dict) else {}


def trace_project_fields(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    live = trace.live_result
    if live and isinstance(live.project_fields, dict) and live.project_fields:
        return live.project_fields
    return trace.project_fields if isinstance(trace.project_fields, dict) else {}


def trace_execution_trace(trace: RunTrace | None) -> List[ExecutionTraceEvent | Any]:
    if not trace:
        return []
    live = trace.live_result
    if live and live.execution_trace:
        return list(live.execution_trace or [])
    return list(trace.execution_trace or [])


def trace_conversation_transcript(trace: RunTrace | None) -> List[Dict[str, Any]]:
    if not trace:
        return []
    live = trace.live_result
    state = live.multi_turn_state if live else None
    if state and state.transcript:
        return list(state.transcript or [])
    return list(trace.conversation_transcript or [])


def trace_stop_reason(trace: RunTrace | None) -> str:
    if not trace:
        return ""
    live = trace.live_result
    state = live.multi_turn_state if live else None
    if state and state.stop_reason:
        return str(state.stop_reason)
    return str(trace.stop_reason or "")


def judge_expected_actual_gaps(judge: JudgeResult | None) -> Dict[str, List[Any]]:
    if not judge:
        return {"missing": [], "wrong": [], "extra": []}
    return {
        "missing": list(judge.missing or []),
        "wrong": list(judge.wrong or []),
        "extra": list(judge.extra or []),
    }


def judge_primary_signal(judge: JudgeResult | None) -> Dict[str, Any]:
    if not judge:
        return {"business_expectations": [], "fulfillment_assessments": [], "overall_fulfillment": {}}
    return {
        "business_expectations": list(judge.business_expectations or []),
        "fulfillment_assessments": list(judge.fulfillment_assessments or []),
        "overall_fulfillment": dict(judge.overall_fulfillment or {}),
    }


def attribute_causal_category(attribute: AttributeResult | None) -> str:
    if not attribute:
        return ""
    return str(attribute.causal_category or "")


def attribute_failure_stage(attribute: AttributeResult | None) -> str:
    if not attribute:
        return ""
    earliest = attribute.earliest_divergence if isinstance(attribute.earliest_divergence, dict) else {}
    return str(earliest.get("stage") or earliest.get("node") or "")


def attribute_probe_evidence(attribute: AttributeResult | None) -> List[Any]:
    if not attribute:
        return []
    return list(attribute.probe_results or [])


def attribute_chain_evidence(attribute: AttributeResult | None) -> List[Any]:
    if not attribute:
        return []
    return list(attribute.chain_nodes or [])
