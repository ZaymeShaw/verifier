from __future__ import annotations

import pytest

from impl.core.judge import _reprompt_judge, finalize_judge_result
from impl.core.judge_protocol import ProjectJudge
from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult, ProjectSpec, RunTrace
from impl.core.schema.normalize import normalize_fulfillment_assessment


def _result(*, blocking: bool, status: str) -> JudgeResult:
    return JudgeResult(
        trace_id="trace-1",
        project_id="fixture-project",
        business_expectations=[
            BusinessExpectation(
                expectation_id="core-goal",
                blocking=blocking,
                expected_outcome="complete the core goal",
            )
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="core-goal", status=status)
        ],
        overall_fulfillment={"status": "fulfilled" if status != "fulfilled" else "not_fulfilled"},
    )


def test_nonblocking_gap_does_not_fail_overall() -> None:
    result = finalize_judge_result(_result(blocking=False, status="not_fulfilled"))

    assert result.overall_fulfillment["status"] == "fulfilled"
    assert "1 non-blocking gaps" in result.summary["reason"]


def test_blocking_failure_deterministically_fails_overall() -> None:
    result = finalize_judge_result(_result(blocking=True, status="not_fulfilled"))

    assert result.overall_fulfillment["status"] == "not_fulfilled"
    assert result.overall_fulfillment["blocking_expectations"] == ["core-goal"]


def test_missing_blocking_assessment_is_not_evaluable() -> None:
    result = JudgeResult(
        trace_id="trace-1",
        project_id="fixture-project",
        business_expectations=[
            BusinessExpectation(
                expectation_id="core-goal",
                blocking=True,
                expected_outcome="complete the core goal",
            )
        ],
    )

    assert finalize_judge_result(result).overall_fulfillment["status"] == "not_evaluable"


def test_assessment_blocking_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="FulfillmentAssessment.blocking 已删除"):
        normalize_fulfillment_assessment({
            "expectation_id": "core-goal",
            "status": "fulfilled",
            "blocking": True,
        })


def test_reprompt_contains_previous_complete_output() -> None:
    captured = {}

    class Client:
        def complete_json(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"ok": True}

    previous = {"business_expectations": [{"expectation_id": "core-goal", "blocking": True}]}
    result = _reprompt_judge(
        Client(),
        "system",
        "original-user",
        previous,
        [{"kind": "missing_fulfillment_assessment", "expectation_id": "core-goal"}],
        "trace-1",
    )

    assert result == {"ok": True}
    assert "上次完整输出" in captured["user"]
    assert '"expectation_id": "core-goal"' in captured["user"]
    assert "保留未报错字段" in captured["user"]


@pytest.mark.parametrize("failure_marker", ["llm_call_failed", "llm_output_validation_failed"])
def test_llm_failure_is_terminal_and_cannot_be_upgraded_by_project_reconcile(monkeypatch, failure_marker) -> None:
    class RecordingJudge(ProjectJudge):
        def __init__(self, spec):
            super().__init__(spec)
            self.reconcile_called = False

        def build_context(self, trace):
            return {}

        def reconcile_result(self, trace, result):
            self.reconcile_called = True
            result.business_expectations = [
                BusinessExpectation(expectation_id="fabricated", blocking=True)
            ]
            result.fulfillment_assessments = [
                FulfillmentAssessment(expectation_id="fabricated", status="fulfilled")
            ]
            return result

    failure = JudgeResult(
        trace_id="trace-failed",
        project_id="fixture-project",
        overall_fulfillment={"status": "not_evaluable"},
        reasoning_summary="provider failed",
        evidence=[failure_marker],
    )
    monkeypatch.setattr("impl.core.judge.judge_trace", lambda **_kwargs: failure)
    judge = RecordingJudge(ProjectSpec(project_id="fixture-project", name="Fixture Project"))

    result = judge.judge_trace(RunTrace(trace_id="trace-failed", project_id="fixture-project"))

    assert judge.reconcile_called is False
    assert result.business_expectations == []
    assert result.fulfillment_assessments == []
    assert result.overall_fulfillment["status"] == "not_evaluable"
    assert result.summary["fulfillment_status"] == "not_evaluable"
