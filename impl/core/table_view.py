from __future__ import annotations

import json
import importlib
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .schema import AttributeResult, CheckReport, FallbackDecision, FrontendViewModel, JudgeResult, RunTrace, normalize_attribute_result, normalize_check_report, normalize_frontend_view, normalize_judge_result, normalize_run_trace, to_dict, trace_conversation_transcript, trace_extracted_output, trace_output_source
from .schema.accessors import trace_input as get_trace_input
from .schema.table import CasePoolTable, ConversationTurn, TraceTableRow
from .summary import summary_from_attribution, summary_from_fulfillment


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        user_intent = value.get("user_intent")
        if isinstance(user_intent, dict) and user_intent.get("goal"):
            return str(user_intent.get("goal"))
        for item in value.values():
            if isinstance(item, (str, int, float, bool)) and str(item):
                return str(item)
    return _short_value(value)


def display_input_for_project(project_id: str, input_payload: Any) -> str:
    if not isinstance(input_payload, dict):
        return _first_scalar(input_payload)
    for field in _required_input_fields(project_id):
        value = input_payload.get(field)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            return str(value)
    return _first_scalar(input_payload)


def _display_input(trace: RunTrace, input_payload: Any) -> str:
    return display_input_for_project(trace.project_id, input_payload)


def _required_input_fields(project_id: str) -> list[str]:
    if not project_id:
        return []
    try:
        live_schema = importlib.import_module(f"impl.projects.{project_id}.live_schema")
    except ModuleNotFoundError:
        return []
    fields = getattr(live_schema, "REQUIRED_INPUT_FIELDS", [])
    return [str(field) for field in fields if isinstance(field, str)]


def _short_value(value: Any, limit: int = 160) -> str:
    if value is None or value == "":
        return ""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _scenario(trace: RunTrace, case_context: Dict[str, Any], input_payload: Any) -> str:
    if case_context.get("scenario"):
        return str(case_context.get("scenario"))
    if trace.scenario:
        return str(trace.scenario)
    if isinstance(input_payload, dict):
        if input_payload.get("scenario"):
            return str(input_payload.get("scenario"))
        metadata = _as_dict(input_payload.get("metadata"))
        if metadata.get("scenario"):
            return str(metadata.get("scenario"))
    return ""


def _reference(trace: RunTrace, view: Optional[FrontendViewModel], judge: Optional[JudgeResult], case_context: Dict[str, Any], input_payload: Any) -> Any:
    reference_panel = view.reference_panel if view else {}
    if reference_panel.get("reference") not in (None, {}, [], ""):
        return reference_panel.get("reference")
    if trace.reference_contract not in (None, {}, [], ""):
        return trace.reference_contract
    if case_context.get("reference") not in (None, {}, [], ""):
        return case_context.get("reference")
    if isinstance(input_payload, dict):
        if input_payload.get("reference") not in (None, {}, [], ""):
            return input_payload.get("reference")
        if input_payload.get("golden_answer") or input_payload.get("gold_answer"):
            return {"actual_answer": input_payload.get("golden_answer") or input_payload.get("gold_answer")}
    return judge.expected if judge else None


def _output(trace: RunTrace, view: Optional[FrontendViewModel], judge: Optional[JudgeResult], case_context: Dict[str, Any]) -> Any:
    run_trace_summary = view.run_trace_summary if view else {}
    if run_trace_summary.get("extracted_output") not in (None, {}, [], ""):
        return run_trace_summary.get("extracted_output")
    output = trace_extracted_output(trace)
    if output not in (None, {}, [], ""):
        return output
    if case_context.get("output") not in (None, {}, [], ""):
        return case_context.get("output")
    return judge.actual if judge else None


def _fulfillment_status(judge: Optional[JudgeResult], judge_summary: Dict[str, Any], status: str) -> str:
    overall = judge.overall_fulfillment if judge else {}
    return str(judge_summary.get("fulfillment_status") or overall.get("status") or status or "")


def _conversation_detail(trace: RunTrace) -> Optional[List[ConversationTurn]]:
    turns = trace_conversation_transcript(trace)
    if not isinstance(turns, list) or not turns:
        return None
    detail: List[ConversationTurn] = []
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            detail.append(ConversationTurn(turn_index=index, role="unknown", content=_short_value(turn), extracted_summary=""))
            continue
        content = turn.get("content") or turn.get("input") or turn.get("user_input") or ""
        content_text = _first_scalar(content) if isinstance(content, dict) else str(content or "")
        extracted = turn.get("extracted_summary") or turn.get("stage") or ""
        detail.append(
            ConversationTurn(
                turn_index=int(turn.get("turn_index") or turn.get("turn") or index),
                role=str(turn.get("role") or "unknown"),
                content=content_text,
                stage=str(turn.get("stage") or ""),
                extracted_summary=str(extracted),
            )
        )
    return detail


def _conversation_summary(trace: RunTrace) -> Dict[str, Any]:
    multi_turn = trace.multi_turn_input if isinstance(trace.multi_turn_input, dict) and trace.multi_turn_input else {}
    if isinstance(trace.conversation_summary, dict) and trace.conversation_summary:
        return dict(trace.conversation_summary)
    if isinstance(multi_turn.get("conversation_summary"), dict):
        return dict(multi_turn.get("conversation_summary") or {})
    extracted = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    if isinstance(extracted.get("conversation_summary"), dict):
        return dict(extracted.get("conversation_summary") or {})
    return {}


def _status(trace: RunTrace, judge: Optional[JudgeResult], judge_summary: Dict[str, Any], case_context: Dict[str, Any]) -> str:
    if judge_summary.get("status"):
        return str(judge_summary.get("status"))
    if judge and judge.overall_fulfillment and isinstance(judge.overall_fulfillment, dict) and judge.overall_fulfillment.get("status"):
        return str(judge.overall_fulfillment.get("status"))
    return str(trace.status or ("error" if trace.error or case_context.get("error") else ""))


def _root_cause(attribute: Optional[AttributeResult]) -> str:
    if not attribute:
        return ""
    return str(attribute.root_cause_hypothesis or "")


def _judge_summary(trace: RunTrace, judge: Optional[JudgeResult], case_context: Dict[str, Any]) -> Dict[str, Any]:
    if not judge:
        return {}
    if trace.error or case_context.get("error"):
        return {
            "status": trace.error or str(case_context.get("error") or ""),
            "fulfillment_status": "",
            "score": None,
            "reason": trace.error or str(case_context.get("error") or ""),
            "reason_source": "execution_error",
            "reason_stage": "execution",
            "is_formal_attribution": False,
            "assessment_count": 0,
            "blocking_count": 0,
            "primary_failure_dimensions": [],
        }
    if judge.summary:
        return {
            "status": (judge.overall_fulfillment or {}).get("status") or trace.status or "",
            "fulfillment_status": judge.summary.get("fulfillment_status") or "",
            "score": judge.summary.get("score"),
            "reason": judge.summary.get("reason") or "",
            "reason_source": judge.summary.get("reason_source") or "",
            "reason_stage": "judge",
            "is_formal_attribution": judge.summary.get("is_formal_attribution", False),
            "assessment_count": judge.summary.get("assessment_count", 0),
            "blocking_count": judge.summary.get("blocking_count", 0),
            "primary_failure_dimensions": judge.summary.get("primary_failure_dimensions") or [],
        }
    summary = summary_from_fulfillment(to_dict(judge))
    return {
        "status": (judge.overall_fulfillment or {}).get("status") or trace.status or "",
        "fulfillment_status": summary.get("fulfillment_status") or "",
        "score": summary.get("score"),
        "reason": summary.get("reason") or "",
        "reason_source": summary.get("reason_source") or "",
        "reason_stage": "judge",
        "is_formal_attribution": summary.get("is_formal_attribution", False),
        "assessment_count": summary.get("assessment_count", 0),
        "blocking_count": summary.get("blocking_count", 0),
        "primary_failure_dimensions": summary.get("primary_failure_dimensions") or [],
    }


def _attribution_summary(attribute: Optional[AttributeResult]) -> Dict[str, Any]:
    if not attribute:
        return {}
    if attribute.summary:
        return dict(attribute.summary)
    return summary_from_attribution(to_dict(attribute))


def _fallbacks(*items: Any) -> List[FallbackDecision]:
    fallbacks: List[FallbackDecision] = []
    for item in items:
        fallbacks.extend(list(getattr(item, "fallbacks", []) or []))
    return fallbacks


def _fallback_summary(fallbacks: List[FallbackDecision]) -> Dict[str, Any]:
    by_stage = Counter(item.source_stage or "unknown" for item in fallbacks)
    return {
        "count": len(fallbacks),
        "needs_human_review": any(item.needs_human_review for item in fallbacks),
        "quality_flags": sorted({flag for item in fallbacks for flag in (item.quality_flags or [])}),
        "by_stage": dict(by_stage),
        "reasons": [item.reason for item in fallbacks if item.reason],
    }


def _check_summary(check: Optional[CheckReport]) -> Dict[str, Any]:
    if not check:
        return {}
    return {
        "passed": check.passed,
        "issue_count": len(check.issues or []) + len(check.protocol_gaps or []) + len(check.consistency_gaps or []),
    }


def build_trace_table_row(
    trace: RunTrace,
    judge: Optional[JudgeResult],
    attribute: Optional[AttributeResult],
    view: Optional[FrontendViewModel],
    check: Optional[CheckReport],
    case_context: Optional[Dict[str, Any]] = None,
) -> TraceTableRow:
    case_context = case_context or {}
    judge_summary = _judge_summary(trace, judge, case_context)
    if not judge_summary:
        judge_summary = summary_from_fulfillment(to_dict(judge) if judge else {})
    else:
        judge_summary = dict(judge_summary)
    attribution_summary = _attribution_summary(attribute)
    if not attribution_summary:
        attribution_summary = summary_from_attribution(to_dict(attribute) if attribute else {})
    else:
        attribution_summary = dict(attribution_summary)
    input_payload = get_trace_input(trace) if get_trace_input(trace) not in (None, {}, "") else case_context.get("input") or case_context.get("case_input") or ""
    status = _status(trace, judge, judge_summary, case_context)
    fulfillment_status = _fulfillment_status(judge, judge_summary, status)
    fallbacks = _fallbacks(trace, trace.live_result, judge, attribute, check)
    fallback_summary = _fallback_summary(fallbacks)
    check_summary = _check_summary(check)
    quality_flags = list(judge_summary.get("quality_flags") or []) + list(attribution_summary.get("quality_flags") or []) + list(fallback_summary.get("quality_flags") or [])
    conversation_detail = _conversation_detail(trace)
    divergence_stage = ""
    issue_count = len(check.issues or []) + len(check.protocol_gaps or []) + len(check.consistency_gaps or []) if check else 0

    return TraceTableRow(
        id=_row_id(trace, case_context),
        input=_display_input(trace, input_payload),
        scenario=_scenario(trace, case_context, input_payload),
        output_summary=_short_value(_output(trace, view, judge, case_context)),
        reference_summary=_short_value(_reference(trace, view, judge, case_context, input_payload)),
        status=status,
        execution_mode=str(case_context.get("execution_mode") or trace.execution_mode or ""),
        output_source=str(case_context.get("output_source") or trace_output_source(trace) or ""),
        score=judge_summary.get("score"),
        fulfillment_status=fulfillment_status,
        judge_summary=judge_summary,
        attribution_summary=attribution_summary,
        check_summary=check_summary,
        fallback_summary=fallback_summary,
        needs_human_review=bool(fallback_summary.get("needs_human_review")),
        quality_flags=quality_flags,
        check_passed=check.passed if check else None,
        issue_count=issue_count,
        fallback_count=len(fallbacks),
        divergence_stage=divergence_stage,
        root_cause_summary=_short_value(_root_cause(attribute), 900),
        created_at=str(trace.created_at or ""),
        stop_reason=str(trace.stop_reason or ""),
        interaction_mode=str(trace.interaction_mode or ("interactive_intent" if conversation_detail else "single_turn")),
        conversation_summary=_conversation_summary(trace),
        conversation_detail=conversation_detail,
        trace_id=str(trace.trace_id or case_context.get("trace_id") or ""),
    )


def _row_id(trace: RunTrace, case_context: Dict[str, Any]) -> str:
    if case_context.get("id"):
        return str(case_context.get("id"))
    if trace.case_id:
        return str(trace.case_id)
    return str(trace.trace_id or "")


def _trace_from_run(run: Dict[str, Any]) -> RunTrace:
    trace = normalize_run_trace(run.get("trace"))
    if trace is not None:
        return trace
    return RunTrace(trace_id=str(run.get("trace_id") or ""), project_id=str(run.get("project_id") or ""), input={}, normalized_request={})


def build_trace_table_row_from_run(run: Dict[str, Any]) -> TraceTableRow:
    existing_row = run.get("table_row")
    if isinstance(existing_row, TraceTableRow):
        return existing_row
    trace = _trace_from_run(run)
    judge = normalize_judge_result(run.get("judge"))
    attribute = normalize_attribute_result(run.get("attribute"))
    view = normalize_frontend_view(run.get("frontend_view"))
    check = normalize_check_report(run.get("check"))
    case_context = {key: run.get(key) for key in ("id", "scenario", "execution_mode", "output_source", "reference", "output") if run.get(key) is not None}
    return build_trace_table_row(trace, judge, attribute, view, check, case_context=case_context)


def build_case_pool_table_from_runs(project_id: str, runs: Iterable[Dict[str, Any]]) -> CasePoolTable:
    rows = [build_trace_table_row_from_run(run) for run in runs]
    return CasePoolTable(project_id=project_id, rows=rows, total=len(rows), summary={})


def build_case_pool_table(project_id: str, runs: Iterable[Dict[str, Any]]) -> CasePoolTable:
    return build_case_pool_table_from_runs(project_id, runs)