from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[5]
_CASES = (
    ("stale-clarification-tool-primary", "20260718-183430", "separate"),
    ("fulfilled-business-control", "20260718-190439", "embedded"),
    ("stale-present-files-and-script-neighbor", "20260718-183128", "separate"),
)


def _migrate_judge_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Migrate historical reports to the current protocol without changing verdict facts."""
    result = copy.deepcopy(value)
    assessment_blocking = {
        str(item.get("expectation_id") or ""): bool(item.get("blocking"))
        for item in result.get("fulfillment_assessments") or []
        if isinstance(item, dict)
    }
    for expectation in result.get("business_expectations") or []:
        if not isinstance(expectation, dict):
            continue
        expectation_id = str(expectation.get("expectation_id") or "")
        expectation.setdefault("blocking", assessment_blocking.get(expectation_id, False))
        expectation.setdefault("evidence_refs", [])
    for assessment in result.get("fulfillment_assessments") or []:
        if not isinstance(assessment, dict):
            continue
        assessment.pop("blocking", None)
        assessment.setdefault("evidence_refs", [])
    return result


def load_cases() -> list[dict[str, Any]]:
    cases = []
    for case_key, stamp, judge_source in _CASES:
        rows = _ROOT / "report" / "api-check" / stamp / "rows"
        run_chain = json.loads((rows / "023-deerflow-run_chain.response.json").read_text(encoding="utf-8"))
        judge = (
            run_chain["judge"]
            if judge_source == "embedded"
            else json.loads((rows / "028-deerflow-judge.response.json").read_text(encoding="utf-8"))
        )
        cases.append({
            "case_key": case_key,
            "trace": copy.deepcopy(run_chain["trace"]),
            "judge_result": _migrate_judge_schema(judge),
        })
    return cases
