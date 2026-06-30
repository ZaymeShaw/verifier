from __future__ import annotations

from typing import Any, Dict, List


_FAILURE_DIMENSION_STATUSES = {"not_fulfilled", "partially_fulfilled", "contested"}


def aggregate_failure_dimensions(judge: dict) -> list[dict]:
    assessments = judge.get("fulfillment_assessments") or []
    boundary_decision = judge.get("boundary_decision") or {}
    within_scope = boundary_decision.get("within_evaluable_scope")
    dimensions: list[dict] = []
    for item in assessments:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _FAILURE_DIMENSION_STATUSES:
            continue
        dimensions.append({
            "expectation_id": item.get("expectation_id") or "",
            "status": status,
            "blocking": bool(item.get("blocking")),
            "downstream_impact": item.get("downstream_impact") or "",
            "within_evaluable_scope": within_scope,
            "evidence": item.get("evidence") or "",
        })
    dimensions.sort(key=lambda dim: (not dim["blocking"], dim["expectation_id"]))
    return dimensions


def summary_from_fulfillment(judge: dict) -> dict:
    quality_flags = judge.get("quality_flags") or []
    degradation = ""
    # Only surface LLM degradation when the judge actually fell back to an
    # uncertain LLM-failure result. Deterministic project gates may start from a
    # failed LLM result and then replace it with current-case contract evidence;
    # in that case the summary must not keep stale fallback wording.
    if (judge.get("verdict") or "") == "uncertain" and "llm_call_failed" in quality_flags:
        degradation = "[llm_call_failed] "
    elif (judge.get("verdict") or "") == "uncertain" and "self_check_failed" in quality_flags:
        degradation = "[self_check_failed] "

    dimensions = aggregate_failure_dimensions(judge)
    verdict = judge.get("verdict") or ""
    reasoning_summary = judge.get("reasoning_summary") or ""
    derivation = judge.get("verdict_derivation") or {}
    why_verdict = derivation.get("why_verdict") or ""
    judge_method = judge.get("judge_method") or ""

    if judge_method == "llm_call_failed":
        reason = f"{degradation}uncertain · LLM 调用失败，未做出算法判断"
        reason_source = "degradation_marker"
    elif verdict == "correct":
        assessments = judge.get("fulfillment_assessments") or []
        count = len([item for item in assessments if isinstance(item, dict) and item.get("blocking")])
        tail = f" · {reasoning_summary}" if reasoning_summary else ""
        reason = f"{degradation}fulfilled · {count} blocking expectations all met{tail}"
        reason_source = "aggregated_fulfillment"
    elif verdict == "incorrect":
        blocking_ids = [dim["expectation_id"] for dim in dimensions if dim["blocking"] and dim["expectation_id"]]
        ids_text = ",".join(blocking_ids) if blocking_ids else "(none)"
        primary_impact = next((dim["downstream_impact"] for dim in dimensions if dim["downstream_impact"]), "")
        head = f"{degradation}not_fulfilled · blocking=[{ids_text}]"
        reason = f"{head} · {primary_impact}" if primary_impact else head
        reason_source = "aggregated_fulfillment"
    elif verdict == "partially_correct":
        partial_ids = [dim["expectation_id"] for dim in dimensions if dim["expectation_id"]]
        ids_text = ",".join(partial_ids) if partial_ids else "(none)"
        head = f"{degradation}partially_fulfilled · partial=[{ids_text}]"
        reason = head
        reason_source = "aggregated_fulfillment"
    else:
        tail = why_verdict or judge_method or reasoning_summary or "unclear"
        reason = f"{degradation}uncertain · {tail}"
        reason_source = "degradation_marker" if degradation else "reasoning_summary"

    return {
        "reason": reason,
        "primary_failure_dimensions": dimensions,
        "reason_source": reason_source,
    }
