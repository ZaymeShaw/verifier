from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .schema import AttributeResult, ClusterSummary, attribute_causal_category, attribute_failure_stage


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
                "causal_category": getattr(attribution, "causal_category", ""),
            })
    return result


def _primary_expectation_item(item: AttributeResult) -> dict[str, Any]:
    items = _expectation_items(item)
    return items[0] if items else {}


def _canonical(item: AttributeResult) -> bool:
    return not (item.incomplete_reason or item.needs_human_review or item.analysis_quality.get("passed") is False or "llm_call_failed" in (item.quality_flags or []))


def _mechanism_key(item: AttributeResult) -> str:
    expectation = _primary_expectation_item(item)
    causal_category = item.causal_category or expectation.get("causal_category")
    fulfillment_status = expectation.get("fulfillment_status")
    if causal_category:
        return "expectation::" + "::".join(part for part in [str(causal_category), str(fulfillment_status or "")] if part)
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
    causal_category = attribute_causal_category(item)
    divergence_stage = attribute_failure_stage(item)
    if causal_category:
        return "::".join(part for part in ["mechanism", item.scenario, causal_category] if part)
    return "mechanism::" + (divergence_stage or "未分类")


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
        has_expectation_attribution = bool(_expectation_items(item))
        causal_category = attribute_causal_category(item)
        if not has_expectation_attribution and causal_category in {"", "none", "no_issue"}:
            continue
        if not has_expectation_attribution and not item.root_cause_hypothesis and not causal_category:
            continue
        grouped[_mechanism_key(item)].append(item)
    clusters = []
    for category, items in grouped.items():
        first = items[0] if items else None
        canonical = bool(first and _canonical(first))
        expectation_items = [expectation for item in items for expectation in _expectation_items(item)]
        causal_categories = _unique([attribute_causal_category(item) for item in items if attribute_causal_category(item)] + [expectation.get("causal_category") for expectation in expectation_items if expectation.get("causal_category")])
        fulfillment_statuses = _unique(expectation.get("fulfillment_status") for expectation in expectation_items)
        expectation_ids = _unique(expectation.get("expectation_id") for expectation in expectation_items)
        affected_fields = _unique(field for item in items for field in _field_values([item.earliest_divergence, item.suspected_locations, item.chain_nodes]))
        patch_directions = _unique(step for item in items for step in (item.patch_direction or []))
        verification_steps = _unique(step for item in items for step in (item.verification_steps or []))
        clusters.append(
            {
                "cluster_id": category,
                "mechanism": category.replace("mechanism::", "").replace("expectation::", "") if canonical else "insufficient_evidence_or_human_review",
                "causal_category": causal_categories[0] if causal_categories else "",
                "fulfillment_statuses": fulfillment_statuses,
                "expectation_ids": expectation_ids,
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
    return ClusterSummary(
        project_id=project_id,
        clusters=clusters,
        common_root_cause=_derive_common_root_cause(clusters),
        priority=_derive_priority(clusters),
    )


def _derive_common_root_cause(clusters: list[dict]) -> str:
    """从聚类结果中提取共性根因摘要。"""
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
    # 多聚类时取最高频的 causal_category 作为主导根因
    from collections import Counter
    cat = Counter(c.get("causal_category") or "" for c in clusters)
    top_cat = cat.most_common(1)[0][0] if cat else ""
    return top_cat or "多个根因混合"


def _derive_priority(clusters: list[dict]) -> str:
    """从聚类结果中推导优先级。"""
    if not clusters:
        return "normal"
    total = sum(c.get("count", 0) for c in clusters)
    needs_review = sum(c.get("count", 0) for c in clusters if c.get("needs_human_review"))
    if needs_review > 0 and needs_review == total:
        return "high"
    if needs_review > total // 2:
        return "medium"
    top_cat = clusters[0].get("causal_category") or ""
    if top_cat in {"implementation_bug", "needs_human_review"}:
        return "high"
    return "normal"
