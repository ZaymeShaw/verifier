from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import AttributeResult, ClusterSummary


def cluster_attributes(project_id: str, attributes: Iterable[AttributeResult]) -> ClusterSummary:
    grouped = defaultdict(list)
    for item in attributes:
        if item.primary_error_type == "none" or item.failure_category == "none":
            continue
        if not item.root_cause_hypothesis and not item.failure_category and not item.primary_error_type:
            continue
        if item.primary_error_type:
            key = "::".join(part for part in [item.scenario, item.primary_error_type] if part) or "未分类"
        else:
            key = item.failure_category or "未分类"
        grouped[key].append(item)
    clusters = []
    for category, items in grouped.items():
        first = items[0] if items else None
        clusters.append(
            {
                "cluster_id": category,
                "failure_category": first.failure_category if first else category,
                "scenario": first.scenario if first else "",
                "primary_error_type": first.primary_error_type if first else "",
                "error_types": first.error_types if first else [],
                "severity": first.severity if first else "",
                "needs_human_review": any(bool(item.needs_human_review) for item in items),
                "count": len(items),
                "representative_cases": [item.case_id or item.trace_id for item in items[:5]],
                "representative_traces": [item.trace_id for item in items[:5]],
                "common_root_cause": first.root_cause_hypothesis if first else "",
                "next_actions": first.verification_steps if first else [],
            }
        )
    return ClusterSummary(project_id=project_id, clusters=clusters)
