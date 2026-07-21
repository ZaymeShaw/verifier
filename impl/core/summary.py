from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


_FAILURE_DIMENSION_STATUSES = {"not_fulfilled"}


def aggregate_failure_dimensions(judge: dict) -> list[dict]:
    assessments = judge.get("fulfillment_assessments") or []
    blocking_by_id = {
        str(item.get("expectation_id") or ""): bool(item.get("blocking"))
        for item in (judge.get("business_expectations") or [])
        if isinstance(item, dict)
    }
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
            "blocking": blocking_by_id.get(str(item.get("expectation_id") or ""), False),
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
    expectations = judge.get("business_expectations") or []
    blocking_count = len([item for item in expectations if isinstance(item, dict) and item.get("blocking")])
    nonblocking_failures = len([dim for dim in dimensions if not dim["blocking"]])

    if fulfillment_status == "fulfilled":
        tail = f" · {reasoning_summary}" if reasoning_summary else ""
        incomplete = f" · {nonblocking_failures} non-blocking gaps" if nonblocking_failures else ""
        reason = f"fulfilled · {blocking_count} blocking expectations all met{incomplete}{tail}"
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


def summary_from_attribution(
    attribute: dict,
    failed_expectation_ids: Optional[Iterable[str]] = None,
    *,
    judge_status: str = "",
) -> dict:
    """Deterministically derive the display summary from reviewed findings."""
    if not attribute:
        return {}
    findings = list(attribute.get("findings") or [])
    unresolved_reason = str(attribute.get("unresolved_reason") or "").strip()
    failed_ids = list(dict.fromkeys(str(item) for item in (failed_expectation_ids or []) if str(item)))
    covered_ids = list(dict.fromkeys(
        str(expectation_id)
        for finding in findings
        for expectation_id in (finding.get("affected_expectation_ids") or [])
        if str(expectation_id)
    ))
    unresolved_ids = [item for item in failed_ids if item not in set(covered_ids)]
    if judge_status == "fulfilled" and not failed_ids:
        status = "not_applicable"
        summary_text = "Judge 未发现需要归因的 not_fulfilled business gap。"
    elif findings and not unresolved_ids and not unresolved_reason:
        status = "complete"
        lines = [str(item.get("conclusion") or "").strip() for item in findings]
        summary_text = "\n".join(item for item in lines if item)
    elif findings:
        status = "partial"
        lines = [str(item.get("conclusion") or "").strip() for item in findings]
        summary_text = "\n".join(item for item in [*lines, unresolved_reason] if item)
    else:
        status = "unresolved"
        summary_text = unresolved_reason
    is_formal = bool(findings)
    return {
        "summary_text": summary_text,
        "finding_count": len(findings),
        "covered_expectation_ids": covered_ids,
        "unresolved_expectation_ids": unresolved_ids,
        "attribution_status": status,
        "is_complete": status == "complete",
        "is_formal_attribution": is_formal,
    }
