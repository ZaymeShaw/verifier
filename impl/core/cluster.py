from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import AttributeResult, ClusterSummary, to_dict


def cluster_attributes(project_id: str, attributes: Iterable[AttributeResult]) -> ClusterSummary:
    """Cluster only reviewed findings; unresolved guesses never become mechanisms."""
    grouped = defaultdict(list)
    for attribute in attributes:
        for finding in attribute.findings or []:
            grouped[finding.conclusion.strip()].append((attribute, finding))

    clusters = []
    for index, (conclusion, items) in enumerate(grouped.items(), start=1):
        expectation_ids = list(dict.fromkeys(
            expectation_id
            for _, finding in items
            for expectation_id in finding.affected_expectation_ids
        ))
        clusters.append({
            "cluster_id": f"finding-cluster-{index}",
            "mechanism": conclusion,
            "fulfillment_statuses": ["not_fulfilled"],
            "expectation_ids": expectation_ids,
            "needs_human_review": False,
            "canonical_attribution": True,
            "count": len(items),
            "representative_cases": [attribute.case_id or attribute.trace_id for attribute, _ in items[:5]],
            "representative_traces": [attribute.trace_id for attribute, _ in items[:5]],
            "common_root_cause": conclusion,
            "shared_failure_pattern": conclusion,
            "affected_fields": [],
            "representative_diffs": [
                {
                    "case_id": attribute.case_id or attribute.trace_id,
                    "conclusion": finding.conclusion,
                    "evidence": to_dict(finding.evidence),
                }
                for attribute, finding in items[:5]
            ],
            "minimal_fix_direction": [],
            "verification_cases": [attribute.case_id or attribute.trace_id for attribute, _ in items[:10]],
            "next_actions": [],
        })

    roots = [item["common_root_cause"] for item in clusters[:3]]
    common = roots[0] if len(roots) == 1 else "多个已验证缺陷" if roots else ""
    priority = "high" if any(item["count"] >= 3 for item in clusters) else "medium" if clusters else "low"
    return ClusterSummary(project_id=project_id, clusters=clusters, common_root_cause=common, priority=priority)
