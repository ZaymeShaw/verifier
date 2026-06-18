import unittest
from unittest.mock import patch

from impl.core.pipeline import run_chain
from impl.core.schema import AttributeResult, JudgeResult, RunTrace, SubagentResult
from impl.core.state_machine import DEFAULT_TRACE_GRAPH, TraceStateMachineRunner


def trace_executor(context):
    context["trace"] = RunTrace(
        trace_id="trace-regression",
        project_id="regression",
        input={"query": "current case"},
        normalized_request={"query": "current case"},
        extracted_output={"answer": "actual"},
        execution_trace=[{"stage": "adapter.extract", "status": "ok"}],
        evidence_refs=[{"type": "trace", "source": "current_case"}],
    )
    return {"status": "succeeded", "evidence_refs": context["trace"].evidence_refs}


def judge_executor(judge):
    def executor(context):
        context["judge_result"] = judge
        return {"status": "succeeded"}

    return executor


def attribute_executor(attribute, evidence_refs=None):
    def executor(context):
        context["attribute_result"] = attribute
        return {"status": "succeeded", "evidence_refs": evidence_refs or []}

    return executor


class TraceStateMachineRegressionTest(unittest.TestCase):
    def test_recoverable_missing_fulfillment_evidence_retries_then_stops_incomplete(self):
        judge = JudgeResult(
            trace_id="trace-regression",
            project_id="regression",
            verdict="incorrect",
            consumer_contract={"consumer": "regression user"},
            business_expectations=[{"expectation_id": "exp-answer"}],
            evaluation_boundary={"scope": "current_case"},
        )
        context = {}

        TraceStateMachineRunner(
            graph=DEFAULT_TRACE_GRAPH,
            executors={"execute_or_capture": trace_executor, "build_business_expectations": judge_executor(judge)},
        ).run(context)

        failed_recoverable = [gate for record in context["state_history"] for gate in record.gate_decisions if not gate.passed and gate.recoverable]
        self.assertEqual(context["stop_reason"], "incomplete_retry_limit")
        self.assertTrue(any(gate.gate_id == "fulfillment_assessment_coverage" for gate in failed_recoverable))
        self.assertGreaterEqual([record.state_id for record in context["state_history"]].count("collect_evidence"), 2)

    def test_subagent_conflict_is_recorded_and_blocks_finalization_until_incomplete(self):
        graph = {
            **DEFAULT_TRACE_GRAPH,
            "states": {
                **DEFAULT_TRACE_GRAPH["states"],
                "collect_evidence": {
                    "role": "collect_evidence",
                    "executor_refs": [
                        {"executor_id": "claim_a", "executor_type": "deterministic", "role": "claim_a"},
                        {"executor_id": "claim_b", "executor_type": "deterministic", "role": "claim_b"},
                    ],
                    "merge_policy": "parallel_agreement",
                },
            },
            "limits": {"max_steps": 12, "max_retries_per_state": 1},
        }
        judge = JudgeResult(
            trace_id="trace-regression",
            project_id="regression",
            verdict="correct",
            expected={"answer": "expected"},
            actual={"answer": "actual"},
            consumer_contract={"consumer": "regression user"},
            business_expectations=[{"expectation_id": "exp-answer"}],
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "fulfilled", "boundary_decision": {"within_evaluable_scope": True}}],
            overall_fulfillment={"status": "fulfilled"},
            reconstructed_intent="answer quality",
            verdict_derivation={"basis": "fulfillment_assessments"},
            evaluation_boundary={"scope": "current_case"},
        )
        context = {}

        TraceStateMachineRunner(
            graph=graph,
            executors={
                "execute_or_capture": trace_executor,
                "claim_a": lambda context: SubagentResult(
                    executor_id="claim_a",
                    executor_type="deterministic",
                    role="claim_a",
                    output={"claim": "A"},
                    claims=[{"field": "answer", "value": "A"}],
                    contradictions=[{"field": "answer", "a": "A", "b": "B"}],
                ),
                "claim_b": lambda context: SubagentResult(
                    executor_id="claim_b",
                    executor_type="deterministic",
                    role="claim_b",
                    output={"claim": "B"},
                    claims=[{"field": "answer", "value": "B"}],
                ),
                "build_business_expectations": judge_executor(judge),
            },
        ).run(context)

        contradiction_gates = [gate for record in context["state_history"] for gate in record.gate_decisions if gate.gate_id == "contradiction_free"]
        self.assertEqual(context["stop_reason"], "incomplete_retry_limit")
        self.assertTrue(any(not gate.passed and gate.contradictions for gate in contradiction_gates))
        collect_record = next(record for record in context["state_history"] if record.state_id == "collect_evidence")
        self.assertEqual(len(collect_record.subagent_results), 2)

    def test_unrecoverable_missing_trace_stops_at_human_review(self):
        context = {}

        TraceStateMachineRunner(graph=DEFAULT_TRACE_GRAPH, executors={"execute_or_capture": lambda context: {"status": "failed"}}).run(context)

        self.assertEqual(context["stop_reason"], "human_review_required")
        self.assertIn("incomplete_or_human_review", [record.state_id for record in context["state_history"]])
        trace_gate = next(gate for record in context["state_history"] for gate in record.gate_decisions if gate.gate_id == "trace_available")
        self.assertFalse(trace_gate.passed)
        self.assertFalse(trace_gate.recoverable)

    def test_unrecoverable_error_trace_stops_at_human_review(self):
        def error_trace_executor(context):
            context["trace"] = RunTrace(
                trace_id="trace-error",
                project_id="regression",
                input={"query": "current case"},
                normalized_request={"query": "current case"},
                status="error",
                error="service unavailable",
            )
            return {"status": "failed", "errors": ["service unavailable"]}

        context = {}

        TraceStateMachineRunner(graph=DEFAULT_TRACE_GRAPH, executors={"execute_or_capture": error_trace_executor}).run(context)

        self.assertEqual(context["stop_reason"], "human_review_required")
        trace_gate = next(gate for record in context["state_history"] for gate in record.gate_decisions if gate.gate_id == "trace_available")
        self.assertFalse(trace_gate.passed)
        self.assertIn("trace.status", trace_gate.missing_evidence)

    def test_run_chain_returns_human_review_payload_when_live_trace_errors_before_judge(self):
        with patch("urllib.request.urlopen", side_effect=OSError("service unavailable")):
            result = run_chain(
                "marketting-planning",
                {
                    "case_id": "mp-live-smoke-unavailable-regression",
                    "query": "帮我规划下个月保费增长活动",
                    "scenario": "execution_planning",
                    "expected_stage": "planning",
                },
            )

        self.assertEqual(result["trace"]["status"], "error")
        self.assertEqual(result["trace"]["stop_reason"], "human_review_required")
        self.assertEqual(result["judge"]["verdict"], "uncertain")
        self.assertIn("service unavailable", result["judge"]["reasoning_summary"])
        self.assertFalse(result["check"]["passed"])

    def test_successful_deep_attribution_reaches_finalize_with_grounded_evidence(self):
        judge = JudgeResult(
            trace_id="trace-regression",
            project_id="regression",
            verdict="incorrect",
            expected={"answer": "expected"},
            actual={"answer": "actual"},
            consumer_contract={"consumer": "regression user"},
            business_expectations=[{"expectation_id": "exp-answer"}],
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "not_fulfilled", "blocking": True, "boundary_decision": {"within_evaluable_scope": True}}],
            overall_fulfillment={"status": "not_fulfilled", "blocking_expectations": ["exp-answer"]},
            reconstructed_intent="answer quality",
            verdict_derivation={"basis": "fulfillment_assessments"},
            evaluation_boundary={"scope": "current_case"},
            wrong=[{"requirement": "answer", "expected_fragment": "expected", "actual_fragment": "actual"}],
        )
        attribute = AttributeResult(
            trace_id="trace-regression",
            project_id="regression",
            failure_category="mapping_error",
            failure_stage="adapter.extract",
            evidence_chain=[{"query": "current case"}, {"expected": "expected"}, {"actual": "actual"}],
            trace_analysis=[{"stage": "adapter.extract", "status": "ok"}],
            chain_nodes=[{"stage": "adapter.extract", "status": "failed", "evidence": ["actual != expected"]}],
            local_verifications=[{"method": "trace_probe", "result": "mismatch reproduced"}],
            earliest_divergence={"node": "adapter.extract", "evidence": ["actual != expected"], "confidence": "high"},
            evidence_coverage={"query": True, "actual": True, "expected": True, "execution_trace": True, "unsupported_claims": []},
            analysis_quality={"passed": True, "status": "supported_root_cause", "missing": []},
            expectation_attributions=[{
                "expectation_id": "exp-answer",
                "fulfillment_status": "not_fulfilled",
                "causal_category": "implementation_bug",
                "earliest_divergence": {"node": "adapter.extract", "evidence": ["actual != expected"]},
                "causal_chain": [{"stage": "adapter.extract", "status": "failed"}],
                "local_verifications": [{"method": "trace_probe", "result": "mismatch reproduced"}],
                "suspected_locations": [{"kind": "adapter", "path": "adapter.extract_output", "evidence": ["actual != expected"]}],
                "improvement_direction": ["fix adapter.extract_output mapping"],
            }],
            causal_category="implementation_bug",
            probe_results=[{"probe": "trace_probe", "status": "failed", "evidence": ["actual != expected"]}],
            suspected_locations=[{"kind": "adapter", "path": "adapter.extract_output", "evidence": ["actual != expected"]}],
            patch_direction=["fix adapter.extract_output mapping"],
        )
        context = {}

        TraceStateMachineRunner(
            graph=DEFAULT_TRACE_GRAPH,
            executors={
                "execute_or_capture": trace_executor,
                "build_business_expectations": judge_executor(judge),
                "run_attribution_probes": attribute_executor(attribute, evidence_refs=[{"type": "local_probe", "source": "current_trace"}]),
                "finalize": lambda context: {"status": "succeeded"},
            },
        ).run(context)

        self.assertEqual(context["stop_reason"], "completed")
        state_ids = [record.state_id for record in context["state_history"]]
        self.assertIn("attribution_critic", state_ids)
        self.assertIn("finalize", state_ids)
        attribute_gates = [gate for record in context["state_history"] for gate in record.gate_decisions if gate.gate_id in {"expectation_attribution_evidence", "causal_category_support", "improvement_direction_support"}]
        self.assertTrue(attribute_gates)
        self.assertTrue(all(gate.passed for gate in attribute_gates))
    def test_adapter_registered_attribution_probe_runs_before_attribute_normalization(self):
        from impl.core.adapter import ProjectAdapter
        from impl.core.project_loader import load_project
        from impl.core.pipeline import attribute

        class ProbeAdapter(ProjectAdapter):
            def build_request(self, input_data):
                return input_data

            def extract_output(self, raw_response):
                return raw_response if isinstance(raw_response, dict) else {}

            def attribution_probes(self, trace, judge_result):
                return [
                    {
                        "method": "current_trace_probe",
                        "probe": "current_trace_probe",
                        "status": "failed",
                        "target": "extracted_output.answer",
                        "result": "mismatch reproduced",
                        "evidence": [trace.extracted_output.get("answer"), judge_result.expected.get("answer")],
                    }
                ]

            def normalize_attribute_result(self, trace, judge_result, attribute_result):
                return attribute_result

        trace = RunTrace(
            trace_id="trace-probe-contract",
            project_id="regression",
            input={"query": "current case"},
            normalized_request={"query": "current case"},
            extracted_output={"answer": "actual"},
            execution_trace=[{"stage": "adapter.extract", "status": "ok"}],
        )
        judge = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="incorrect",
            expected={"answer": "expected"},
            actual=trace.extracted_output,
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "not_fulfilled", "blocking": True}],
            overall_fulfillment={"status": "not_fulfilled"},
            wrong=[{"requirement": "answer", "expected_fragment": "expected", "actual_fragment": "actual"}],
        )

        with patch("impl.core.pipeline.load_project", return_value=load_project("QA")), patch("impl.core.pipeline.load_adapter", return_value=ProbeAdapter(load_project("QA"))), patch("impl.core.pipeline.attribute_failure", return_value=AttributeResult(trace_id=trace.trace_id, project_id=trace.project_id, analysis_method="llm_attribute")):
            result = attribute("regression", trace, judge)

        self.assertEqual("current_trace_probe", result.local_verifications[0]["method"])
        self.assertEqual("current_trace_probe", result.probe_results[0]["probe"])
        self.assertTrue(result.evidence_coverage["local_probe"])
        self.assertEqual("supported_root_cause", result.analysis_quality["status"])

    def test_client_search_fulfilled_run_without_state_attribute_uses_no_issue_attribution(self):
        case = next(case for case in run_chain.__globals__["mock_cases"]("client_search") if case["id"] == "cs-survival-benefit-correct-1")
        result = run_chain("client_search", case)

        self.assertEqual("correct", result["judge"]["verdict"])
        self.assertEqual("fulfilled", result["judge"]["overall_fulfillment"]["status"])
        self.assertTrue(result["attribute"].get("expectation_attributions"))
        self.assertEqual("no_issue", result["attribute"].get("causal_category"))
        self.assertNotEqual("state_machine_incomplete", result["attribute"].get("failure_stage"))
        self.assertNotIn("attribute_incomplete", result["attribute"].get("quality_flags") or [])
        self.assertTrue(result["check"].get("passed"), result["check"].get("issues"))

        from impl.core.pipeline import incomplete_state_attribute_result

        trace = RunTrace(
            trace_id="trace-missing-attribute",
            project_id="QA",
            input={"case_id": "qa-missing-output-1"},
            normalized_request={"input": {"question": "健康告知有什么用？"}},
            extracted_output={"actual_answer": ""},
            execution_trace=[{"stage": "qa.output.read", "status": "suspicious", "evidence": "empty output"}],
            stop_reason="incomplete_retry_limit",
        )
        judge = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="incorrect",
            expected={"actual_answer": "健康告知用于评估健康风险。"},
            actual={"actual_answer": ""},
            missing=["actual_answer"],
            evidence=["actual_answer_present=False"],
        )

        attribute = incomplete_state_attribute_result(trace, judge)

        self.assertEqual(attribute.trace_id, trace.trace_id)
        self.assertEqual(attribute.project_id, trace.project_id)
        self.assertFalse(attribute.analysis_quality["passed"])
        self.assertTrue(attribute.incomplete_reason)
        self.assertTrue(attribute.trace_analysis)
        self.assertTrue(attribute.chain_nodes)
        self.assertTrue(attribute.patch_direction)


if __name__ == "__main__":
    unittest.main()
