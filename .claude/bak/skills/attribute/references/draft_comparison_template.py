from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace

AttributeFn = Callable[[ProjectSpec, Any, RunTrace, JudgeResult], AttributeResult]


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return value


def _result_summary(result: AttributeResult) -> dict[str, Any]:
    data = _plain(result)
    if not isinstance(data, dict):
        return {"raw": data}
    return {
        "expectation_attributions": data.get("expectation_attributions") or [],
        "suspected_locations": data.get("suspected_locations") or [],
        "root_cause_hypothesis": data.get("root_cause_hypothesis") or "",
        "evidence": data.get("evidence") or [],
        "evidence_strength": data.get("evidence_strength"),
    }


def _quality_notes(current: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    notes = []
    if draft.get("evidence_strength") and draft.get("evidence_strength") != current.get("evidence_strength"):
        notes.append("draft changes evidence_strength; verify calibration against current trace evidence")
    if draft.get("suspected_locations") and not current.get("suspected_locations"):
        notes.append("draft adds suspected_locations")
    if draft.get("evidence") and not current.get("evidence"):
        notes.append("draft adds evidence")
    if not draft.get("root_cause_hypothesis"):
        notes.append("draft lacks root_cause_hypothesis")
    return notes


def compare_attribute_outputs(
    spec: ProjectSpec,
    adapter: Any,
    cases: Iterable[dict[str, Any]],
    current_attribute: AttributeFn,
    draft_attribute: AttributeFn,
) -> dict[str, Any]:
    """Template comparator: copy into a project draft and adapt case loading only."""
    rows = []
    for index, case in enumerate(cases):
        trace = case["trace"]
        judge_result = case["judge_result"]
        current = _result_summary(current_attribute(spec, adapter, trace, judge_result))
        draft = _result_summary(draft_attribute(spec, adapter, trace, judge_result))
        rows.append(
            {
                "case_key": case.get("case_key") or index,
                "judge_status": (judge_result.overall_fulfillment or {}).get("status"),
                "current": current,
                "draft": draft,
                "quality_notes": _quality_notes(current, draft),
            }
        )
    return {
        "case_count": len(rows),
        "rows": rows,
        "decision_rule": "Promote only when draft improves current evidence quality/link localization without adding overfit markers or inflated evidence_strength.",
    }
