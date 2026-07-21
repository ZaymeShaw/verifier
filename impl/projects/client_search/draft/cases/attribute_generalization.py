from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[5]


def _read_json(relative_path: str) -> Any:
    return json.loads((_REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _from_chain_report(case_key: str, relative_path: str) -> dict[str, Any]:
    payload = _read_json(relative_path)
    judge_result = payload["judge"]
    blocking_by_expectation = {
        item.get("expectation_id"): item.get("blocking")
        for item in judge_result.get("fulfillment_assessments", [])
        if item.get("expectation_id") and isinstance(item.get("blocking"), bool)
    }
    for expectation in judge_result.get("business_expectations", []):
        expectation_id = expectation.get("expectation_id")
        if "blocking" not in expectation and expectation_id in blocking_by_expectation:
            expectation["blocking"] = blocking_by_expectation[expectation_id]
    for assessment in judge_result.get("fulfillment_assessments", []):
        assessment.pop("blocking", None)
    return {
        "case_key": case_key,
        "trace": payload["trace"],
        "judge_result": judge_result,
    }


def load_cases() -> list[dict[str, Any]]:
    """Freeze different gap shapes; these cases never configure the candidate."""
    prior_cases = _read_json(
        "report/draft-mechanism/20260720-client-search-attribute/iteration-cases.json"
    )
    name_value_gap = next(
        case for case in prior_cases if case["case_key"] == "cs13_suffix_failure"
    )
    return [
        {
            **name_value_gap,
            "case_key": "wrong_condition_value",
        },
        _from_chain_report(
            "missing_expected_and_extra_unrelated_condition",
            "report/api-check/20260717-004620/rows/018-client_search-run_chain.response.json",
        ),
        _from_chain_report(
            "fulfilled_control",
            "report/api-check/20260719-025942/rows/022-client_search-run_chain.response.json",
        ),
    ]
