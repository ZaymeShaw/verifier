from impl.core.attribute import _fulfilled_attribute_result
from impl.core.check import check_chain
from impl.core.pipeline import incomplete_state_attribute_result
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _trace() -> RunTrace:
    return RunTrace(
        trace_id="trace-1",
        project_id="demo",
        case_id="case-authoritative",
        input={"case_id": "stale-input-case"},
        normalized_request={"query": "hello"},
        raw_response={"answer": "ok"},
        extracted_output={"answer": "ok"},
        execution_trace=[{"stage": "live", "status": "ok"}],
        status="ok",
    )


def _judge() -> JudgeResult:
    return JudgeResult(
        trace_id="trace-1",
        project_id="demo",
        overall_fulfillment={"status": "fulfilled"},
        fulfillment_assessments=[{"expectation_id": "exp", "status": "fulfilled"}],
        evidence=["current trace output matches"],
        reasoning_summary="fulfilled",
        expected={"answer": "ok"},
        actual={"answer": "ok"},
    )


def test_attribute_results_use_run_trace_case_id_as_single_source():
    trace = _trace()
    judge = _judge()

    assert _fulfilled_attribute_result(ProjectSpec(project_id="demo", name="demo"), trace, judge).case_id == "case-authoritative"
    trace.stop_reason = "incomplete"
    assert incomplete_state_attribute_result(trace, judge).case_id == "case-authoritative"


def test_check_reports_attribute_case_id_mismatch():
    trace = _trace()
    judge = _judge()
    attribute = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id="",
        root_cause_hypothesis="no issue",
        evidence=["judge fulfilled"],
        evidence_strength="strong",
    )

    report = check_chain(ProjectSpec(project_id="demo", name="demo", adapter="adapter.py"), trace, judge, attribute)

    assert "AttributeResult case_id does not match RunTrace." in report.consistency_gaps
