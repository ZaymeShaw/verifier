from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .schema import AttributeResult, CheckReport, FallbackDecision, FrontendViewModel, JudgeResult, RunTrace, attribute_causal_category, attribute_failure_stage, normalize_attribute_result, normalize_check_report, normalize_frontend_view, normalize_judge_result, normalize_run_trace, to_dict, trace_conversation_transcript, trace_extracted_output, trace_output_source
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
                extracted_summary=_short_value(extracted),
            )
        )
    return detail


def _conversation_summary(trace: RunTrace) -> Dict[str, Any]:
    if isinstance(trace.conversation_summary, dict) and trace.conversation_summary:
        return dict(trace.conversation_summary)
    multi_turn_input = trace.multi_turn_input if isinstance(trace.multi_turn_input, dict) else {}
    if isinstance(multi_turn_input.get("conversation_summary"), dict):
        return dict(multi_turn_input.get("conversation_summary") or {})
    output = trace_extracted_output(trace)
    if isinstance(output, dict) and isinstance(output.get("conversation_summary"), dict):
        return dict(output.get("conversation_summary") or {})
    return {}


def _row_id(trace: RunTrace, case_context: Dict[str, Any]) -> str:
    trace_input = get_trace_input(trace) if trace else {}
    return str(case_context.get("case_id") or case_context.get("id") or trace.case_id or trace_input.get("case_id") or trace.trace_id or "")


def _status(trace: RunTrace, judge: Optional[JudgeResult], judge_summary: Dict[str, Any], case_context: Dict[str, Any]) -> str:
    if case_context.get("status"):
        return str(case_context.get("status"))
    if judge_summary.get("status"):
        return str(judge_summary.get("status"))
    if judge and judge.overall_fulfillment.get("status"):
        return str(judge.overall_fulfillment.get("status"))
    if judge and judge.verdict:
        return str(judge.verdict)
    return str(trace.status or ("error" if trace.error or case_context.get("error") else ""))


def _judge_summary(trace: RunTrace, judge: Optional[JudgeResult], case_context: Dict[str, Any]) -> Dict[str, Any]:
    if not judge:
        return {}
    if trace.error or case_context.get("error"):
        return {
            "status": trace.error or str(case_context.get("error") or ""),
            "fulfillment_status": "",
            "verdict": judge.verdict or "",
            "score": judge.score,
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
            "status": (judge.overall_fulfillment or {}).get("status") or judge.verdict or trace.status or "",
            "fulfillment_status": judge.summary.get("fulfillment_status") or "",
            "verdict": judge.verdict or "",
            "score": judge.score,
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
        "status": (judge.overall_fulfillment or {}).get("status") or judge.verdict or trace.status or "",
        "fulfillment_status": summary.get("fulfillment_status") or "",
        "verdict": judge.verdict or "",
        "score": judge.score,
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
        "issue_count": len(check.issues or []),
        "protocol_gap_count": len(check.protocol_gaps or []),
        "consistency_gap_count": len(check.consistency_gaps or []),
        "recommended_fix_count": len(check.recommended_fixes or []),
        "issues": list(check.issues or []),
    }


def _root_cause(attribute: Optional[AttributeResult]) -> str:
    if not attribute:
        return ""
    if attribute.summary:
        return str(attribute.summary.get("summary_text") or attribute.root_cause_hypothesis or attribute.incomplete_reason or "")
    return str(attribute.root_cause_hypothesis or attribute.incomplete_reason or "")


def build_trace_table_row(
    trace: RunTrace,
    judge: Optional[JudgeResult] = None,
    attribute: Optional[AttributeResult] = None,
    view: Optional[FrontendViewModel] = None,
    check: Optional[CheckReport] = None,
    *,
    case_context: Optional[Dict[str, Any]] = None,
    judge_summary: Optional[Dict[str, Any]] = None,
    attribution_summary: Optional[Dict[str, Any]] = None,
) -> TraceTableRow:
    """Materialize the Summary table schema from existing schema-layer objects."""
    case_context = dict(case_context or {})
    if not judge_summary:
        judge_summary = _judge_summary(trace, judge, case_context)
    else:
        judge_summary = dict(judge_summary)
    if not attribution_summary:
        attribution_summary = _attribution_summary(attribute)
    else:
        attribution_summary = dict(attribution_summary)
    input_payload = get_trace_input(trace) if get_trace_input(trace) not in (None, {}, "") else case_context.get("input") or case_context.get("case_input") or ""
    status = _status(trace, judge, judge_summary, case_context)
    fulfillment_status = _fulfillment_status(judge, judge_summary, status)
    verdict = str(judge_summary.get("verdict") or (judge.verdict if judge else "") or "")
    fallbacks = _fallbacks(trace, trace.live_result, judge, attribute, check)
    fallback_summary = _fallback_summary(fallbacks)
    check_summary = _check_summary(check)
    quality_flags = list(judge.quality_flags if judge else []) + list(attribute.quality_flags if attribute else []) + list(fallback_summary.get("quality_flags") or [])
    conversation_detail = _conversation_detail(trace)
    causal_category = str(attribution_summary.get("causal_category") or attribute_causal_category(attribute))
    divergence_stage = attribute_failure_stage(attribute)
    issue_count = len(check.issues or []) + len(check.protocol_gaps or []) + len(check.consistency_gaps or []) if check else 0

    return TraceTableRow(
        id=_row_id(trace, case_context),
        input=_first_scalar(input_payload),
        scenario=_scenario(trace, case_context, input_payload),
        output_summary=_short_value(_output(trace, view, judge, case_context)),
        reference_summary=_short_value(_reference(trace, view, judge, case_context, input_payload)),
        status=status,
        execution_mode=str(case_context.get("execution_mode") or trace.execution_mode or ""),
        output_source=str(case_context.get("output_source") or trace_output_source(trace) or ""),
        verdict=verdict,
        score=judge_summary.get("score") if judge_summary.get("score") is not None else (judge.score if judge else None),
        fulfillment_status=fulfillment_status,
        judge_summary=judge_summary,
        attribution_summary=attribution_summary,
        check_summary=check_summary,
        fallback_summary=fallback_summary,
        needs_human_review=bool((judge.needs_human_review if judge else False) or (attribute.needs_human_review if attribute else False) or fallback_summary.get("needs_human_review")),
        quality_flags=quality_flags,
        check_passed=check.passed if check else None,
        issue_count=issue_count,
        fallback_count=len(fallbacks),
        causal_category=causal_category,
        divergence_stage=divergence_stage,
        root_cause_summary=_short_value(_root_cause(attribute), 900),
        created_at=str(trace.created_at or ""),
        stop_reason=str(trace.stop_reason or ""),
        interaction_mode=str(trace.interaction_mode or ("interactive_intent" if conversation_detail else "single_turn")),
        conversation_summary=_conversation_summary(trace),
        conversation_detail=conversation_detail,
        trace_id=str(trace.trace_id or case_context.get("trace_id") or ""),
    )


def _trace_from_run(run: Dict[str, Any]) -> RunTrace:
    trace = normalize_run_trace(run.get("trace"))
    if trace is not None:
        return trace
    return RunTrace(trace_id=str(run.get("trace_id") or ""), project_id=str(run.get("project_id") or ""), input={}, normalized_request={})


def build_trace_table_row_from_run(run: Dict[str, Any]) -> TraceTableRow:
    """Compatibility wrapper: normalize a serialized run into schema objects, then build the table row."""
    existing_row = run.get("table_row")
    if isinstance(existing_row, TraceTableRow):
        return existing_row
    trace = _trace_from_run(run)
    judge = normalize_judge_result(run.get("judge"))
    attribute = normalize_attribute_result(run.get("attribute"))
    check = normalize_check_report(run.get("check"))
    view = normalize_frontend_view(run.get("frontend_view"))
    case_context = {
        "case_id": run.get("case_id") or trace.case_id,
        "id": run.get("id"),
        "status": run.get("status"),
        "execution_mode": trace.execution_mode or run.get("execution_mode"),
        "output_source": trace_output_source(trace) or run.get("output_source"),
        "scenario": trace.scenario or run.get("scenario"),
        "reference": trace.reference_contract or run.get("reference"),
        "output": run.get("output"),
        "error": run.get("error"),
    }
    return build_trace_table_row(
        trace,
        judge,
        attribute,
        view,
        check,
        case_context=case_context,
    )


def build_case_pool_table(project_id: str, rows: Iterable[TraceTableRow]) -> CasePoolTable:
    materialized_rows = list(rows)
    fulfillment_counts = Counter(row.fulfillment_status or row.status or "pending" for row in materialized_rows)
    verdict_counts = Counter(row.verdict or "uncertain" for row in materialized_rows)
    scenario_counts = Counter(row.scenario or "未分类" for row in materialized_rows)
    summary = {
        "fulfilled_count": fulfillment_counts.get("fulfilled", 0),
        "not_fulfilled_count": sum(fulfillment_counts.get(item, 0) for item in ("not_fulfilled", "not_evaluable")),
        "pending_count": fulfillment_counts.get("pending", 0) + fulfillment_counts.get("", 0),
        "correct_count": verdict_counts.get("correct", 0),
        "incorrect_count": verdict_counts.get("incorrect", 0),
        "uncertain_count": verdict_counts.get("uncertain", 0) + verdict_counts.get("", 0),
        "human_review_count": len([row for row in materialized_rows if row.needs_human_review]),
        "check_failed_count": len([row for row in materialized_rows if row.check_passed is False]),
        "issue_count": sum(row.issue_count for row in materialized_rows),
        "fallback_count": sum(row.fallback_count for row in materialized_rows),
        "rows_with_fallback_count": len([row for row in materialized_rows if row.fallback_count]),
        "by_scenario": dict(scenario_counts),
    }
    return CasePoolTable(project_id=project_id, rows=materialized_rows, total=len(materialized_rows), summary=summary)


def build_case_pool_table_from_runs(project_id: str, runs: Iterable[Dict[str, Any]]) -> CasePoolTable:
    """Compatibility wrapper for serialized run payloads at HTTP boundaries."""
    return build_case_pool_table(project_id, [build_trace_table_row_from_run(run) for run in runs])
