from __future__ import annotations

from typing import Any, Dict, List


_FAILURE_DIMENSION_STATUSES = {"not_fulfilled"}


def aggregate_failure_dimensions(judge: dict) -> list[dict]:
    assessments = judge.get("fulfillment_assessments") or []
    reasoning = judge.get("reasoning_summary") or ""
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
        if not evidence_parts and reasoning:
            evidence_parts.append(reasoning)
        dimensions.append({
            "expectation_id": item.get("expectation_id") or "",
            "status": status,
            "blocking": bool(item.get("blocking")),
            "downstream_impact": item.get("downstream_impact") or "",
            "evidence": " | ".join(evidence_parts) if evidence_parts else "",
        })
    dimensions.sort(key=lambda dim: (not dim["blocking"], dim["expectation_id"]))
    return dimensions


def summary_from_fulfillment(judge: dict) -> dict:
    """从 judge 结果中提取前端展示用的摘要。

    spec/info-volume.md：verdict 已删除，改用 overall_fulfillment.status 驱动。
    输出字段不变，前端兼容。
    """
    dimensions = aggregate_failure_dimensions(judge)
    reasoning_summary = judge.get("reasoning_summary") or ""
    overall = judge.get("overall_fulfillment") or {}
    fulfillment_status = overall.get("status") or ""
    assessments = judge.get("fulfillment_assessments") or []
    assessment_count = len(assessments)
    blocking_count = len([item for item in assessments if isinstance(item, dict) and item.get("blocking")])

    if fulfillment_status == "fulfilled":
        tail = f" · {reasoning_summary}" if reasoning_summary else ""
        reason = f"fulfilled · {blocking_count} blocking expectations all met{tail}"
        reason_source = "aggregated_fulfillment"
    elif fulfillment_status == "not_fulfilled":
        blocking_ids = [dim["expectation_id"] for dim in dimensions if dim["blocking"] and dim["expectation_id"]]
        ids_text = ",".join(blocking_ids) if blocking_ids else "(none)"
        primary_impact = next((dim["downstream_impact"] for dim in dimensions if dim["downstream_impact"]), "")
        tail = f" · {reasoning_summary}" if reasoning_summary else (" · " + primary_impact if primary_impact else "")
        reason = f"not_fulfilled · blocking=[{ids_text}]{tail}"
        reason_source = "aggregated_fulfillment"
    else:
        tail = reasoning_summary or "unclear"
        reason = f"not_evaluable · {tail}"
        reason_source = "reasoning_summary"

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
    """从 attribute 结果中提取前端展示用的摘要。

    spec/info-volume.md：用 evidence_strength 和 root_cause_hypothesis 驱动。
    """
    if not attribute:
        return {}
    attributions = attribute.get("expectation_attributions") or []
    has_attribution = bool(attributions)
    summary_text = attribute.get("root_cause_hypothesis") or ""
    evidence_strength = attribute.get("evidence_strength") or ""
    is_formal = has_attribution and evidence_strength in ("strong", "medium")
    return {
        "attribution_count": len(attributions),
        "probe_count": 0,
        "summary_text": summary_text,
        "is_complete": is_formal,
        "is_formal_attribution": is_formal,
    }