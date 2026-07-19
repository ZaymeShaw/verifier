from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult, RunTrace
from impl.core.table_view import build_trace_table_row


def test_existing_judge_analysis_is_not_replaced_by_execution_error():
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        input={"query": "plan"},
        normalized_request={"query": "plan"},
        status="error",
        error="decision_error",
        interaction_controller_status="error",
        interaction_controller_error="mock provider malformed output",
    )
    judge = JudgeResult(
        trace_id="trace-1",
        project_id="deerflow",
        business_expectations=[
            BusinessExpectation(
                expectation_id="deliver-plan",
                blocking=True,
                expected_outcome="deliver a usable plan",
            )
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="deliver-plan",
                status="not_fulfilled",
                downstream_impact="plan cannot be executed",
            )
        ],
        overall_fulfillment={"status": "not_fulfilled"},
        reasoning_summary="The output omitted execution details.",
        summary={
            "fulfillment_status": "not_fulfilled",
            "reason": "The output omitted execution details.",
            "reason_source": "aggregated_fulfillment",
            "assessment_count": 1,
            "blocking_count": 1,
        },
    )

    row = build_trace_table_row(trace, judge, None, None, None)

    assert row.status == "not_fulfilled"
    assert row.fulfillment_status == "not_fulfilled"
    assert row.judge_summary["reason"] == "The output omitted execution details."
    assert row.judge_summary["reason_source"] == "aggregated_fulfillment"
    assert row.judge_summary["assessment_count"] == 1
    assert row.execution_status == "error"
    assert row.execution_error == "decision_error"
    assert row.interaction_controller_status == "error"
    assert row.interaction_controller_error == "mock provider malformed output"


def test_execution_error_is_used_as_fallback_only_when_judge_is_absent():
    trace = RunTrace(
        trace_id="trace-2",
        project_id="deerflow",
        input={"query": "plan"},
        normalized_request={"query": "plan"},
        status="error",
        error="live request failed",
    )

    row = build_trace_table_row(trace, None, None, None, None)

    assert row.judge_summary["reason"] == "live request failed"
    assert row.judge_summary["reason_source"] == "execution_error"
    assert row.execution_status == "error"
