from impl.core.judge import build_judge_evidence_view
from impl.core.schema import RunTrace


def test_judge_evidence_uses_complete_trace_not_only_final_output():
    trace = RunTrace(
        trace_id="trace-1",
        project_id="demo",
        case_id="case-1",
        input={"query": "finish the task"},
        normalized_request={"query": "turn-2"},
        raw_response=[{"answer": "partial"}, {"answer": "done"}],
        extracted_output={"answer": "done"},
        reference_contract={"answer": "done"},
        turn_records=[
            {"turn_index": 1, "request": {"query": "turn-1"}, "raw_response": {"private": "raw-1"}, "extracted_output": {"answer": "partial"}},
            {"turn_index": 2, "request": {"query": "turn-2"}, "raw_response": {"private": "raw-2"}, "extracted_output": {"answer": "done"}},
        ],
        final_output_turn=2,
        conversation_transcript=[{"role": "user", "content": "turn-1"}],
        stop_reason="mock_should_stop",
        completion_status="completed",
        status="ok",
    )

    evidence = build_judge_evidence_view(trace)

    assert evidence["final_output"] == {"answer": "done"}
    assert evidence["final_output_turn"] == 2
    assert len(evidence["turns"]) == 2
    assert evidence["stop_reason"] == "mock_should_stop"
    assert evidence["raw_response_evidence"] is None
    assert all("raw_response" not in turn for turn in evidence["turns"])
    assert evidence["evidence_completeness"] == {"complete": True, "missing_evidence": []}


def test_judge_evidence_exposes_raw_response_only_for_incomplete_execution():
    trace = RunTrace(
        trace_id="trace-2",
        project_id="demo",
        raw_response={"error": "bad payload"},
        extracted_output={},
        status="error",
        error="schema failed",
        completion_status="failed",
    )

    evidence = build_judge_evidence_view(trace)

    assert evidence["raw_response_evidence"] == {"error": "bad payload"}
    assert evidence["evidence_completeness"]["complete"] is False
    assert set(evidence["evidence_completeness"]["missing_evidence"]) == {
        "final_output",
        "successful_execution",
    }
