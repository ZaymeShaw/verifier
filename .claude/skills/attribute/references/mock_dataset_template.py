from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from impl.core.schema import JudgeResult, RunTrace


MOCK_DATASET_POLICY: dict[str, Any] = {
    "frozen": True,
    "update_policy": "Do not change mock cases during draft optimization unless the user explicitly updates the draft config.",
    "purpose": "Hold the evaluation target stable while draft/tool implementations iterate.",
}


def build_mock_attribution_cases(raw_cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Template: adapt raw project examples into trace/judge pairs inside project draft/."""
    cases = []
    for index, raw in enumerate(raw_cases):
        trace = raw.get("trace")
        judge_result = raw.get("judge_result")
        if not isinstance(trace, RunTrace) or not isinstance(judge_result, JudgeResult):
            raise TypeError("Each mock case must provide RunTrace trace and JudgeResult judge_result")
        cases.append(
            {
                "case_key": raw.get("case_key") or index,
                "trace": trace,
                "judge_result": judge_result,
                "expected_check": raw.get("expected_check") or {},
            }
        )
    return cases


MOCK_CASE_CONTRACT: dict[str, Any] = {
    "case_key": "Stable non-secret identifier for the mock row; do not use production-only case ids as logic.",
    "trace": "RunTrace built from current or synthetic project-shaped request/output/reference evidence.",
    "judge_result": "JudgeResult with fulfilled/not_fulfilled/not_evaluable status and current evidence.",
    "expected_check": "Optional assertions for evidence strength, missing evidence behavior, and anti-overfit markers.",
    "frozen_policy": "Mock rows are fixed by config and must not be changed by the optimization loop unless the user explicitly requests it.",
}
