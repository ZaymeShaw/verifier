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


def _canonical(item: AttributeResult) -> bool:
    return not (item.incomplete_reason or item.needs_human_review or item.analysis_quality.get("passed") is False or "llm_call_failed" in (item.quality_flags or []))


def _mechanism_key(item: AttributeResult) -> str:
    if not _canonical(item):
        return "needs_human_review::insufficient_evidence"
    locations = item.suspected_locations or []
    if locations:
        first = locations[0]
        if isinstance(first, dict):
            location = first.get("location") or first.get("file") or first.get("module") or first.get("field")
            if location:
                return "mechanism::" + str(location)
        return "mechanism::" + str(first)
    divergence = item.earliest_divergence or {}
    node = divergence.get("node") if isinstance(divergence, dict) else None
    if node:
        return "mechanism::" + str(node)
    if item.primary_error_type:
        return "::".join(part for part in ["mechanism", item.scenario, item.primary_error_type] if part)
    return "mechanism::" + (item.failure_category or "未分类")


def _representative_diffs(items: list[AttributeResult]) -> list[dict[str, Any]]:
    diffs = []
    for item in items[:5]:
        divergence = item.earliest_divergence or {}
        diffs.append({
            "case_id": item.case_id or item.trace_id,
            "node": divergence.get("node") if isinstance(divergence, dict) else "",
            "expected": divergence.get("expected") if isinstance(divergence, dict) else None,
            "actual": divergence.get("actual") if isinstance(divergence, dict) else None,
            "evidence": divergence.get("evidence") if isinstance(divergence, dict) else [],
        })
    return diffs


def cluster_attributes(project_id: str, attributes: Iterable[AttributeResult]) -> ClusterSummary:
    grouped = defaultdict(list)
    for item in attributes:
        if item.primary_error_type == "none" or item.failure_category == "none":
            continue
        if not item.root_cause_hypothesis and not item.failure_category and not item.primary_error_type:
            continue
        grouped[_mechanism_key(item)].append(item)
    clusters = []
    for category, items in grouped.items():
        first = items[0] if items else None
        canonical = bool(first and _canonical(first))
        affected_fields = _unique(field for item in items for field in _field_values([item.earliest_divergence, item.suspected_locations, item.chain_nodes]))
        patch_directions = _unique(step for item in items for step in (item.patch_direction or []))
        verification_steps = _unique(step for item in items for step in (item.verification_steps or []))
        clusters.append(
            {
                "cluster_id": category,
                "mechanism": category.replace("mechanism::", "") if canonical else "insufficient_evidence_or_human_review",
                "failure_category": first.failure_category if first else category,
                "scenario": first.scenario if first else "",
                "primary_error_type": first.primary_error_type if first else "",
                "error_types": _unique(error for item in items for error in (item.error_types or [])),
                "severity": first.severity if first else "",
                "needs_human_review": any(bool(item.needs_human_review) for item in items) or not canonical,
                "canonical_attribution": canonical,
                "count": len(items),
                "representative_cases": [item.case_id or item.trace_id for item in items[:5]],
                "representative_traces": [item.trace_id for item in items[:5]],
                "common_root_cause": first.root_cause_hypothesis if first else "",
                "shared_failure_pattern": first.root_cause_hypothesis if first else "",
                "affected_fields": affected_fields,
                "representative_diffs": _representative_diffs(items),
                "minimal_fix_direction": patch_directions[:5],
                "verification_cases": [item.case_id or item.trace_id for item in items[:10]],
                "next_actions": verification_steps[:5],
            }
        )
    return ClusterSummary(project_id=project_id, clusters=clusters)
