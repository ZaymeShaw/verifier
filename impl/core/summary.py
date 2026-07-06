from __future__ import annotations

from typing import Any, Dict, List


_FAILURE_DIMENSION_STATUSES = {"not_fulfilled"}


def aggregate_failure_dimensions(judge: dict) -> list[dict]:
    assessments = judge.get("fulfillment_assessments") or []
    boundary_decision = judge.get("boundary_decision") or {}
    within_scope = boundary_decision.get("within_evaluable_scope")
    # evidence 优先从 fulfillment_assessments[*].actual_evidence/expected_evidence 取，
    # 回退到 reasoning_summary / why_verdict，确保业务证据不丢失。
    reasoning = judge.get("reasoning_summary") or ""
    derivation = judge.get("verdict_derivation") or {}
    why_verdict = derivation.get("why_verdict") or ""
    dimensions: list[dict] = []
    for item in assessments:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _FAILURE_DIMENSION_STATUSES:
            continue
        evidence_parts: list[str] = []
        for key in ("actual_evidence", "expected_evidence", "evidence_refs"):
            ev = item.get(key)
            if isinstance(ev, list):
                for entry in ev:
                    if isinstance(entry, str) and entry:
                        evidence_parts.append(entry)
                    elif isinstance(entry, dict):
                        text = entry.get("summary") or entry.get("value") or entry.get("ref") or entry.get("reason")
                        if text:
                            evidence_parts.append(str(text))
            elif isinstance(ev, str) and ev:
                evidence_parts.append(ev)
        if not evidence_parts and (item.get("downstream_impact")):
            evidence_parts.append(str(item.get("downstream_impact")))
        if not evidence_parts and why_verdict:
            evidence_parts.append(why_verdict)
        elif not evidence_parts and reasoning:
            evidence_parts.append(reasoning)
        dimensions.append({
            "expectation_id": item.get("expectation_id") or "",
            "status": status,
            "blocking": bool(item.get("blocking")),
            "downstream_impact": item.get("downstream_impact") or "",
            "within_evaluable_scope": within_scope,
            "evidence": " | ".join(evidence_parts) if evidence_parts else "",
        })
    dimensions.sort(key=lambda dim: (not dim["blocking"], dim["expectation_id"]))
    return dimensions


def summary_from_fulfillment(judge: dict) -> dict:
    quality_flags = judge.get("quality_flags") or []
    degradation = ""
    if "llm_call_failed" in quality_flags:
        degradation = "[llm_call_failed] "
    elif "self_check_failed" in quality_flags:
        degradation = "[self_check_failed] "

    dimensions = aggregate_failure_dimensions(judge)
    verdict = judge.get("verdict") or ""
    reasoning_summary = judge.get("reasoning_summary") or ""
    derivation = judge.get("verdict_derivation") or {}
    why_verdict = derivation.get("why_verdict") or ""
    judge_method = judge.get("judge_method") or ""
    overall = judge.get("overall_fulfillment") or {}
    fulfillment_status = overall.get("status") or ""
    assessments = judge.get("fulfillment_assessments") or []
    assessment_count = len(assessments)
    blocking_count = len([item for item in assessments if isinstance(item, dict) and item.get("blocking")])

    if judge_method == "llm_call_failed":
        reason = f"{degradation}uncertain · LLM 调用失败，未做出算法判断"
        reason_source = "degradation_marker"
    elif verdict == "correct":
        tail = f" · {reasoning_summary}" if reasoning_summary else ""
        reason = f"{degradation}fulfilled · {blocking_count} blocking expectations all met{tail}"
        reason_source = "aggregated_fulfillment"
    elif verdict == "incorrect":
        blocking_ids = [dim["expectation_id"] for dim in dimensions if dim["blocking"] and dim["expectation_id"]]
        ids_text = ",".join(blocking_ids) if blocking_ids else "(none)"
        primary_impact = next((dim["downstream_impact"] for dim in dimensions if dim["downstream_impact"]), "")
        tail = f" · {reasoning_summary}" if reasoning_summary else (" · " + primary_impact if primary_impact else "")
        reason = f"{degradation}not_fulfilled · blocking=[{ids_text}]{tail}"
        reason_source = "aggregated_fulfillment"
    else:
        tail = why_verdict or judge_method or reasoning_summary or "unclear"
        reason = f"{degradation}uncertain · {tail}"
        reason_source = "degradation_marker" if degradation else "reasoning_summary"

    return {
        "reason": reason,
        "primary_failure_dimensions": dimensions,
        "reason_source": reason_source,
        "fulfillment_status": fulfillment_status,
        "assessment_count": assessment_count,
        "blocking_count": blocking_count,
        "is_formal_attribution": reason_source == "aggregated_fulfillment",
    }


def summary_from_attribution(attribute: dict) -> dict:
    if not attribute:
        return {}
    attributions = attribute.get("expectation_attributions") or []
    has_attribution = bool(attributions)
    has_incomplete = bool(attribute.get("incomplete_reason"))
    analysis_quality = attribute.get("analysis_quality") or {}
    is_formal = bool(analysis_quality.get("passed") is True or has_attribution) and not has_incomplete
    summary_text = attribute.get("incomplete_reason") or attribute.get("root_cause_hypothesis") or ""
    return {
        "causal_category": attribute.get("causal_category") or "",
        "attribution_count": len(attributions),
        "probe_count": len(attribute.get("probe_results") or []),
        "summary_text": summary_text,
        "is_complete": is_formal,
        "is_formal_attribution": is_formal,
    }
