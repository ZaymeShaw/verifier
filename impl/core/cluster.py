from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .schema import AttributeResult, ClusterSummary


def _field_values(value: Any) -> list[str]:
    fields = []
    if isinstance(value, dict):
        field = value.get("field")
        if field:
            fields.append(str(field))
        for item in value.values():
            fields.extend(_field_values(item))
    elif isinstance(value, list):
        for item in value:
            fields.extend(_field_values(item))
    return fields


def _unique(items: Iterable[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        key = str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _expectation_items(item: AttributeResult) -> list[dict[str, Any]]:
    result = []
    for attribution in item.expectation_attributions or []:
        if isinstance(attribution, dict):
            result.append(attribution)
        else:
            result.append({
                "expectation_id": getattr(attribution, "expectation_id", ""),
                "fulfillment_status": getattr(attribution, "fulfillment_status", ""),
                "root_cause_hypothesis": getattr(attribution, "root_cause_hypothesis", ""),
            })
    return result


def _primary_expectation_item(item: AttributeResult) -> dict[str, Any]:
    items = _expectation_items(item)
    return items[0] if items else {}


def _canonical(item: AttributeResult) -> bool:
    return item.evidence_strength in ("strong", "medium")


def _mechanism_key(item: AttributeResult) -> str:
    expectation = _primary_expectation_item(item)
    root_cause = item.root_cause_hypothesis or expectation.get("root_cause_hypothesis")
    fulfillment_status = expectation.get("fulfillment_status")
    if root_cause:
        return "root_cause::" + "::".join(part for part in [str(root_cause)[:80], str(fulfillment_status or "")] if part)
    if not _canonical(item):
        return "needs_human_review::insufficient_evidence"
    locations = item.suspected_locations or []
    if locations:
        first = locations[0]
        if isinstance(first, dict):
            location = first.get("location") or first.get("file") or first.get("module") or first.get("field")
            if location:
                return "location::" + str(location)
        return "location::" + str(first)
    return "mechanism::unclassified"


def _representative_diffs(items: list[AttributeResult]) -> list[dict[str, Any]]:
    diffs = []
    for item in items[:5]:
        diffs.append({
            "case_id": item.case_id or item.trace_id,
            "root_cause": item.root_cause_hypothesis,
            "evidence": item.evidence or [],
        })
    return diffs


def cluster_attributes(project_id: str, attributes: Iterable[AttributeResult]) -> ClusterSummary:
    grouped = defaultdict(list)
    for item in attributes:
        has_expectation_attribution = bool(_expectation_items(item))
        if not has_expectation_attribution and not item.root_cause_hypothesis:
            continue
        grouped[_mechanism_key(item)].append(item)
    clusters = []
    for category, items in grouped.items():
        first = items[0] if items else None
        canonical = bool(first and _canonical(first))
        expectation_items = [expectation for item in items for expectation in _expectation_items(item)]
        fulfillment_statuses = _unique(expectation.get("fulfillment_status") for expectation in expectation_items)
        expectation_ids = _unique(expectation.get("expectation_id") for expectation in expectation_items)
        affected_fields = _unique(field for item in items for field in _field_values([item.suspected_locations]))
        representative_evidence = _unique(step for item in items for step in (item.evidence or []))
        clusters.append(
            {
                "cluster_id": category,
                "mechanism": category.replace("root_cause::", "").replace("location::", "") if canonical else "insufficient_evidence_or_human_review",
                "fulfillment_statuses": fulfillment_statuses,
                "expectation_ids": expectation_ids,
                "needs_human_review": not canonical,
                "canonical_attribution": canonical,
                "count": len(items),
                "representative_cases": [item.case_id or item.trace_id for item in items[:5]],
                "representative_traces": [item.trace_id for item in items[:5]],
                "common_root_cause": first.root_cause_hypothesis if first else "",
                "shared_failure_pattern": first.root_cause_hypothesis if first else "",
                "affected_fields": affected_fields,
                "representative_diffs": _representative_diffs(items),
                "minimal_fix_direction": [],
                "verification_cases": [item.case_id or item.trace_id for item in items[:10]],
                "next_actions": representative_evidence[:5],
            }
        )
    return ClusterSummary(
        project_id=project_id,
        clusters=clusters,
        common_root_cause=_derive_common_root_cause(clusters),
        priority=_derive_priority(clusters),
    )


def _derive_common_root_cause(clusters: list[dict]) -> str:
    if not clusters:
        return ""
    root_causes: list[str] = []
    for c in clusters[:3]:
        rc = c.get("common_root_cause") or c.get("shared_failure_pattern") or ""
        if rc and rc not in root_causes:
            root_causes.append(rc)
    if len(root_causes) == 0:
        return ""
    if len(root_causes) == 1:
        return root_causes[0]
    return "多个根因混合"


def _derive_priority(clusters: list[dict]) -> str:
    if not clusters:
        return "normal"
    total = sum(c.get("count", 0) for c in clusters)
    needs_review = sum(c.get("count", 0) for c in clusters if c.get("needs_human_review"))
    if needs_review > 0 and needs_review == total:
        return "high"
    if needs_review > total // 2:
        return "medium"
    return "normal"