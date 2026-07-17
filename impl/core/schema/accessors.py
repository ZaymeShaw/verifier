from __future__ import annotations

from typing import Any, Dict, List

from .evidence import ExecutionTraceEvent
from .trace import RunTrace
from .judge import JudgeResult
from .attribute import AttributeResult


def trace_input(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    return trace.input if isinstance(trace.input, dict) else {}


def trace_normalized_request(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    return trace.normalized_request if isinstance(trace.normalized_request, dict) else {}


def trace_raw_response(trace: RunTrace | None) -> Any:
    if not trace:
        return None
    return trace.raw_response


def trace_extracted_output(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    return trace.extracted_output if isinstance(trace.extracted_output, dict) else {}


def trace_output_source(trace: RunTrace | None) -> str:
    if not trace:
        return ""
    return str(trace.output_source or "")


def trace_application_boundary(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    return trace.application_boundary if isinstance(trace.application_boundary, dict) else {}


def trace_project_fields(trace: RunTrace | None) -> Dict[str, Any]:
    if not trace:
        return {}
    return trace.project_fields if isinstance(trace.project_fields, dict) else {}


def trace_execution_trace(trace: RunTrace | None) -> List[ExecutionTraceEvent | Any]:
    if not trace:
        return []
    return list(trace.execution_trace or [])


def trace_conversation_transcript(trace: RunTrace | None) -> List[Dict[str, Any]]:
    if not trace:
        return []
    return list(trace.conversation_transcript or [])


def trace_conversation_summary(trace: RunTrace | None) -> Dict[str, Any]:
    """多轮会话摘要只读 RunTrace；项目 output 不承载 trace 聚合字段。"""
    if not trace:
        return {}
    if isinstance(trace.conversation_summary, dict) and trace.conversation_summary:
        return dict(trace.conversation_summary)
    return {}


def trace_stop_reason(trace: RunTrace | None) -> str:
    if not trace:
        return ""
    return str(trace.stop_reason or "")


def trace_turn_records(trace: RunTrace | None) -> List[Dict[str, Any]]:
    """完整轮次事实只读 RunTrace。"""
    if not trace:
        return []
    return list(trace.turn_records or [])


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
