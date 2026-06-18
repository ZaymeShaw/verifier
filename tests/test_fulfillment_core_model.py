import unittest

from impl.core.adapter import ProjectAdapter
from impl.core.attribute import attribute_failure
from impl.core.cluster import cluster_attributes
from impl.core.schema import AttributeResult, BusinessExpectation, ExpectationAttribution, FulfillmentAssessment, JudgeResult, ProjectSpec, RunTrace
from impl.core.state_machine import DEFAULT_TRACE_GRAPH, TraceStateMachineRunner, evaluate_gate


class DemoAdapter(ProjectAdapter):
    def build_request(self, input_data):
        return input_data

    def extract_output(self, raw_response):
        return raw_response if isinstance(raw_response, dict) else {"output": raw_response}


class FulfillmentCoreModelTest(unittest.TestCase):
    def test_attribute_targets_failed_intent_derived_expectations(self):
        from impl.core.attribute import _attribution_targets

        judge = JudgeResult(
            trace_id="trace-attribute-target",
            project_id="client_search",
            verdict="incorrect",
            intent_model={"raw_user_request": "查找有生存金未领取的客户"},
            business_expectations=[{
                "expectation_id": "exp-survival-benefit",
                "source_intent_id": "intent-survival-benefit",
                "user_goal": "找到有生存金未领取的客户",
                "required_outcome": "输出未领取生存金搜索条件",
                "failure_impact": "下游无法筛选目标客户",
            }],
            fulfillment_assessments=[{"expectation_id": "exp-survival-benefit", "status": "not_fulfilled", "downstream_impact": "blocked"}],
            overall_fulfillment={"status": "not_fulfilled"},
        )

        targets = _attribution_targets(judge)

        self.assertEqual(targets[0]["expectation_id"], "exp-survival-benefit")
        self.assertEqual(targets[0]["source_intent_id"], "intent-survival-benefit")
        self.assertEqual(targets[0]["user_goal"], "找到有生存金未领取的客户")

    def test_client_search_intent_frame_exposes_generic_search_dimensions(self):
        from impl.core.project_loader import load_adapter, load_project

        spec = load_project("client_search")
        adapter = load_adapter(spec)
        trace = RunTrace(
            trace_id="trace-client-intent-frame",
            project_id="client_search",
            input={"query": "有生存金未领取的客户"},
            normalized_request={"user_text": "有生存金未领取的客户"},
            extracted_output={"structured_output": []},
            project_fields={"application_boundary": {"judge_scope": "parser_condition_semantics_only"}},
        )

        frame = adapter.build_intent_frame(trace)

        self.assertEqual(frame["business_task_type"], "natural_language_to_downstream_client_search_conditions")
        self.assertIn("target_population", frame["critical_intent_dimensions"])
        self.assertIn("operator", frame["critical_intent_dimensions"])
        self.assertIn("downstream-executable search conditions", frame["output_semantics"])

    def test_adapter_default_expectation_uses_intent_model_not_verdict_reasoning(self):
        adapter = DemoAdapter(ProjectSpec(project_id="demo", name="Demo"))
        trace = RunTrace(
            trace_id="trace-intent-fallback",
            project_id="demo",
            input={"query": "查找高价值客户"},
            normalized_request={"query": "查找高价值客户"},
            extracted_output={"conditions": []},
        )
        judge = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="incorrect",
            reasoning_summary="stale verdict-derived reason must not become expected outcome",
            verdict_derivation={"why_verdict": "verdict-only explanation"},
            intent_model={
                "raw_user_request": "查找高价值客户",
                "explicit_intents": [{"intent_id": "intent-high-value", "goal": "筛选高价值客户"}],
                "success_definition": "输出可执行的高价值客户搜索条件",
                "blocking_requirements": [{"intent_id": "intent-high-value", "requirement": "保留高价值客户筛选语义"}],
                "intent_evidence": [{"intent_id": "intent-high-value", "source": "input", "text": "高价值客户"}],
            },
        )

        result = adapter.ensure_fulfillment_judge_result(trace, judge)
        expectation = result.business_expectations[0]

        self.assertEqual(expectation["source_intent_id"], "intent-high-value")
        self.assertEqual(expectation["user_intent"], "筛选高价值客户")
        self.assertEqual(expectation["expected_outcome"], "输出可执行的高价值客户搜索条件")
        self.assertNotIn("stale verdict-derived", expectation["expected_outcome"])

    def test_judge_result_carries_intent_model_as_primary_object(self):
        judge = JudgeResult(
            trace_id="trace-intent-model",
            project_id="client_search",
            verdict="correct",
            intent_model={
                "raw_user_request": "查找有生存金未领取的客户",
                "explicit_intents": [{"intent_id": "intent-search-target", "goal": "找到目标客户"}],
                "implicit_business_intents": [{"intent_id": "intent-executable-search", "goal": "生成可执行搜索条件"}],
                "constraints": {"target_population": "客户", "condition": "有生存金未领取"},
                "success_definition": "下游搜索能按未领取生存金条件筛选客户",
                "blocking_requirements": [{"intent_id": "intent-search-target", "requirement": "保留生存金未领取条件"}],
                "nice_to_have_requirements": [],
                "intent_evidence": [{"intent_id": "intent-search-target", "source": "input", "text": "有生存金未领取"}],
            },
            business_expectations=[{"expectation_id": "exp-search-target", "source_intent_id": "intent-search-target"}],
            fulfillment_assessments=[{"expectation_id": "exp-search-target", "status": "fulfilled", "blocking": True}],
            overall_fulfillment={"status": "fulfilled"},
        )

        judge.derive_verdict_from_fulfillment()

        self.assertEqual(judge.intent_model["raw_user_request"], "查找有生存金未领取的客户")
        self.assertEqual(judge.business_expectations[0]["source_intent_id"], "intent-search-target")
        self.assertEqual(judge.verdict, "correct")

    def test_judge_result_carries_fulfillment_primary_objects_and_derived_verdict(self):
        expectation = BusinessExpectation(
            expectation_id="exp-answer-grounded",
            downstream_consumer="QA user",
            user_intent="understand policy purpose",
            expected_outcome="answer is grounded in provided context",
            acceptance_criteria=["relevant", "grounded"],
            boundary={"scope": "current answer"},
            priority="blocking",
        )
        assessment = FulfillmentAssessment(
            expectation_id="exp-answer-grounded",
            status="not_fulfilled",
            score=0.2,
            expected_evidence=["context mentions risk assessment"],
            actual_evidence=["answer is empty"],
            boundary_decision={"within_evaluable_scope": True},
            downstream_impact="user cannot verify answer",
            blocking=True,
        )

        judge = JudgeResult(
            trace_id="trace-fulfillment",
            project_id="QA",
            verdict="correct",
            consumer_contract={"consumer": "QA user", "contract": "answer relevance and groundedness"},
            business_expectations=[expectation],
            fulfillment_assessments=[assessment],
            overall_fulfillment={"status": "not_fulfilled", "blocking_expectations": ["exp-answer-grounded"]},
        )
        judge.derive_verdict_from_fulfillment()

        self.assertEqual(judge.verdict, "incorrect")
        self.assertEqual(judge.business_expectations[0].expectation_id, "exp-answer-grounded")
        self.assertEqual(judge.fulfillment_assessments[0].status, "not_fulfilled")
        self.assertEqual(judge.verdict_derivation["primary_source"], "fulfillment_assessments")

    def test_blocking_not_evaluable_fulfillment_derives_uncertain_verdict(self):
        judge = JudgeResult(
            trace_id="trace-not-evaluable",
            project_id="QA",
            verdict="incorrect",
            fulfillment_assessments=[{"expectation_id": "QA:answer_quality", "status": "not_evaluable", "blocking": True}],
            overall_fulfillment={"status": "not_evaluable", "blocking_expectations": ["QA:answer_quality"]},
        )

        judge.derive_verdict_from_fulfillment()

        self.assertEqual(judge.verdict, "uncertain")
        self.assertEqual(judge.verdict_derivation["blocking_expectations"], ["QA:answer_quality"])

    def test_fulfilled_overall_reconciles_stale_wrong_and_missing_compatibility_fields(self):
        judge = JudgeResult(
            trace_id="trace-stale-compat",
            project_id="QA",
            verdict="incorrect",
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "fulfilled", "blocking": True}],
            overall_fulfillment={"status": "fulfilled", "blocking_expectations": ["exp-answer"]},
            wrong=[{"requirement": "stale wrong"}],
            missing=["stale missing"],
            extra=[{"requirement": "stale extra"}],
        )

        judge.derive_verdict_from_fulfillment()

        self.assertEqual("correct", judge.verdict)
        self.assertEqual([], judge.wrong)
        self.assertEqual([], judge.missing)
        self.assertEqual([], judge.extra)
        self.assertEqual([], judge.verdict_derivation["blocking_expectations"])
        self.assertEqual("fulfilled", judge.overall_fulfillment["status"])

    def test_not_fulfilled_assessment_reconciles_stale_fulfilled_overall_status(self):
        judge = JudgeResult(
            trace_id="trace-stale-overall",
            project_id="QA",
            verdict="correct",
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "not_fulfilled", "blocking": False}],
            overall_fulfillment={"status": "fulfilled", "blocking_expectations": []},
        )

        judge.derive_verdict_from_fulfillment()

        self.assertEqual("incorrect", judge.verdict)
        self.assertEqual("not_fulfilled", judge.overall_fulfillment["status"])
        self.assertEqual(["exp-answer"], judge.overall_fulfillment["blocking_expectations"])
        self.assertEqual(["exp-answer"], judge.verdict_derivation["blocking_expectations"])

    def test_derived_verdict_consistency_gate_rejects_stale_verdict_and_overall_state(self):
        judge = JudgeResult(
            trace_id="trace-gate-stale",
            project_id="QA",
            verdict="correct",
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "not_fulfilled", "blocking": False}],
            overall_fulfillment={"status": "fulfilled", "blocking_expectations": []},
        )

        decision = evaluate_gate("derived_verdict_consistency", {"judge_result": judge}, {})

        self.assertFalse(decision.passed)
        self.assertTrue(decision.contradictions)

    def test_attribute_result_carries_expectation_level_attribution(self):
        attribution = ExpectationAttribution(
            expectation_id="exp-search-condition",
            fulfillment_status="partially_fulfilled",
            causal_category="implementation_bug",
            earliest_divergence={"node": "adapter.normalize", "evidence": ["operator dropped"]},
            causal_chain=[{"node": "adapter.normalize", "status": "failed"}],
            local_verifications=[{"method": "schema_validate", "result": "operator missing"}],
            suspected_locations=[{"path": "adapter.py", "evidence": ["operator mapping"]}],
            improvement_direction=["preserve operator during normalization"],
        )

        attribute = AttributeResult(
            trace_id="trace-fulfillment",
            project_id="client_search",
            expectation_attributions=[attribution],
            causal_category="implementation_bug",
            probe_results=[{"probe": "schema_validate", "status": "failed"}],
        )

        self.assertEqual(attribute.expectation_attributions[0].expectation_id, "exp-search-condition")
        self.assertEqual(attribute.causal_category, "implementation_bug")
        self.assertTrue(attribute.probe_results)

    def test_default_graph_uses_fulfillment_state_names(self):
        states = set(DEFAULT_TRACE_GRAPH["states"])

        for state in {
            "build_business_expectations",
            "evaluate_fulfillment",
            "fulfillment_critic",
            "attribute_expectations",
            "run_attribution_probes",
            "attribution_critic",
        }:
            self.assertIn(state, states)

        for legacy_state in {"judge_plan", "judge_compare", "judge_critic", "attribute_plan", "attribute_probe"}:
            self.assertNotIn(legacy_state, states)

    def test_attribute_transition_is_based_on_fulfillment_gap_not_verdict(self):
        judge = JudgeResult(
            trace_id="trace-fulfillment",
            project_id="QA",
            verdict="correct",
            consumer_contract={"consumer": "QA user"},
            business_expectations=[{"expectation_id": "exp-answer"}],
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "partially_fulfilled", "blocking": True}],
            overall_fulfillment={"status": "partially_fulfilled"},
        )
        context = {"judge_result": judge}
        runner = TraceStateMachineRunner(graph=DEFAULT_TRACE_GRAPH, executors={})

        self.assertTrue(runner._condition_matches("fulfillment_requires_attribute", context, []))

    def test_fulfillment_gates_require_contract_expectations_and_assessments(self):
        incomplete = JudgeResult(trace_id="trace-fulfillment", project_id="QA", verdict="uncertain")
        context = {"judge_result": incomplete}

        self.assertFalse(evaluate_gate("consumer_contract_present", context, {}).passed)
        self.assertFalse(evaluate_gate("business_expectation_coverage", context, {}).passed)
        self.assertFalse(evaluate_gate("fulfillment_assessment_coverage", context, {}).passed)

        complete = JudgeResult(
            trace_id="trace-fulfillment",
            project_id="QA",
            verdict="correct",
            consumer_contract={"consumer": "QA user"},
            business_expectations=[{"expectation_id": "exp-answer"}],
            fulfillment_assessments=[{"expectation_id": "exp-answer", "status": "fulfilled"}],
            overall_fulfillment={"status": "fulfilled"},
        )
        context = {"judge_result": complete}

        self.assertTrue(evaluate_gate("consumer_contract_present", context, {}).passed)
        self.assertTrue(evaluate_gate("business_expectation_coverage", context, {}).passed)
        self.assertTrue(evaluate_gate("fulfillment_assessment_coverage", context, {}).passed)
        self.assertTrue(evaluate_gate("derived_verdict_consistency", context, {}).passed)

    def test_fulfilled_attribute_uses_expectation_attribution_not_no_failure_record(self):
        trace = RunTrace(
            trace_id="trace-fulfilled",
            project_id="demo",
            input={"case_id": "case-fulfilled"},
            normalized_request={},
            extracted_output={"answer": "ok"},
        )
        judge = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="correct",
            consumer_contract={"consumer": "demo user"},
            business_expectations=[{"expectation_id": "exp-demo", "expected_outcome": "answer is useful"}],
            fulfillment_assessments=[{"expectation_id": "exp-demo", "status": "fulfilled", "blocking": False}],
            overall_fulfillment={"status": "fulfilled"},
            evidence=["answer satisfies expectation"],
        )

        attribute = attribute_failure(ProjectSpec(project_id="demo", name="Demo"), trace, judge, llm=None, project_attribute_context={})

        self.assertEqual(attribute.causal_category, "no_issue")
        self.assertEqual(attribute.expectation_attributions[0]["expectation_id"], "exp-demo")
        self.assertEqual(attribute.expectation_attributions[0]["fulfillment_status"], "fulfilled")
        self.assertNotEqual(attribute.failure_category, "none")
        self.assertTrue(attribute.verification_steps)
        self.assertTrue(attribute.patch_direction)

    def test_cluster_includes_fulfilled_expectation_attributions(self):
        attribute = AttributeResult(
            trace_id="trace-fulfilled",
            project_id="demo",
            case_id="case-fulfilled",
            expectation_attributions=[{"expectation_id": "exp-demo", "fulfillment_status": "fulfilled", "causal_category": "no_issue"}],
            causal_category="no_issue",
            probe_results=[{"probe": "judge_evidence", "status": "passed"}],
            analysis_method="fulfilled_expectation_attribution",
            evidence_chain=["answer satisfies expectation"],
            analysis_quality={"passed": True, "missing": []},
        )

        summary = cluster_attributes("demo", [attribute])

        self.assertEqual(summary.clusters[0]["causal_category"], "no_issue")
        self.assertEqual(summary.clusters[0]["fulfillment_statuses"], ["fulfilled"])
        self.assertEqual(summary.clusters[0]["expectation_ids"], ["exp-demo"])

    def test_compact_summary_keeps_attribute_root_cause_out_of_judge_reason(self):
        from impl.server import _compact_summaries

        attribute_reason = "业务预期已达成，当前归因为 no_issue，不进入失败根因链路。"
        judge_summary, attribution_summary = _compact_summaries(
            {},
            {"verdict": "correct", "score": 1.0, "reasoning_summary": "judge says fulfilled", "overall_fulfillment": {"status": "fulfilled"}},
            {
                "causal_category": "no_issue",
                "root_cause_hypothesis": attribute_reason,
                "analysis_quality": {"passed": True},
                "expectation_attributions": [{"expectation_id": "exp-demo", "fulfillment_status": "fulfilled"}],
            },
            {},
            [{"expectation_id": "exp-demo", "status": "fulfilled", "blocking": False}],
            [{"expectation_id": "exp-demo", "fulfillment_status": "fulfilled"}],
        )

        self.assertEqual(judge_summary["reason"], "judge says fulfilled")
        self.assertEqual(judge_summary["reason_stage"], "judge")
        self.assertNotIn("no_issue", judge_summary["reason"])
        self.assertEqual(attribution_summary["summary_text"], attribute_reason)

    def test_batch_case_retry_exhaustion_preserves_original_exception(self):
        from impl.core import pipeline

        original_run_chain = pipeline.run_chain
        try:
            def fail_run_chain(*args, **kwargs):
                raise RuntimeError("synthetic client_search failure")

            pipeline.run_chain = fail_run_chain
            result = pipeline._batch_case(0, {"id": "client_search_value_service_100-005", "input": {"query": "65岁以上寿险VIP客户"}}, "client_search", None)
        finally:
            pipeline.run_chain = original_run_chain

        self.assertEqual(result["case_id"], "client_search_value_service_100-005")
        self.assertEqual(result["execution_mode"], "error")
        self.assertIn("synthetic client_search failure", result["error"])
        self.assertEqual(result["judge"]["judge_method"], "batch_case_exception")
        self.assertIn("synthetic client_search failure", result["judge"]["reasoning_summary"])

    def test_downstream_boundary_gaps_handles_missing_application_boundary(self):
        from impl.core.check import _downstream_boundary_gaps

        trace = RunTrace(
            trace_id="trace-downstream-boundary",
            project_id="client_search",
            input={"query": "客户姓名是张伟的人"},
            normalized_request={"user_text": "客户姓名是张伟的人"},
            extracted_output={"structured_output": [{"field": "searchClientName", "operator": "MATCH", "value": "张伟"}]},
            project_fields={"downstream_search": {"status": "unavailable", "payload": {"conditions": []}}},
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, verdict="uncertain", boundary_decision={"application_boundary": None})

        gaps = _downstream_boundary_gaps(trace, judge)

        self.assertIn("Downstream search is unavailable/skipped but JudgeResult does not constrain application_boundary.judge_scope to parser_condition_semantics_only.", gaps)

    def test_client_search_name_query_batch_case_does_not_raise_none_get(self):
        from impl.core import pipeline

        case = next(
            item
            for item in pipeline.mock_cases("client_search")
            if item["id"] == "identity_demographics_income-001"
        )

        result = pipeline._batch_case(0, case, "client_search", None)

        self.assertNotEqual(result["execution_mode"], "error")
        self.assertIsNone(result.get("error"))
        self.assertNotIn("NoneType", (result.get("judge") or {}).get("reasoning_summary") or "")

    def test_checklist_does_not_mutate_reference_to_force_failure(self):
        from pathlib import Path

        source = Path("impl/checklist/check1.py").read_text(encoding="utf-8")

        self.assertNotIn("INJECTED_WRONG_VALUE", source)
        self.assertNotIn("force not_fulfilled", source)

    def test_marketing_planning_event_summary_uses_configured_sse_aliases(self):
        from impl.core.project_loader import load_adapter, load_project

        adapter = load_adapter(load_project("marketting-planning"))
        events = [
            {"event": "reasoning_start"},
            {"event": "card_start"},
            {"event": "card_message_content"},
            {"event": "card_end"},
        ]

        summary = adapter._event_summary(events)

        self.assertIn("planning_started", summary["names"])
        self.assertIn("card_delta", summary["names"])
        self.assertIn("done", summary["names"])
        self.assertEqual(summary["raw_names"], ["reasoning_start", "card_start", "card_message_content", "card_end"])
        self.assertTrue(summary["completed"])

    def test_marketing_intent_adapter_does_not_invent_missing_slots_from_query(self):
        from impl.core.project_loader import load_adapter, load_project

        adapter = load_adapter(load_project("marketting-planning-intent"))

        output = adapter.extract_output({
            "raw": {"nlu_info": {"intent": "marketing_plan", "confidence": 0.95, "path_types": []}},
            "request": {"query": "我要做明年的目标达成规划"},
        })

        self.assertNotIn("year", output["slots"])

    def test_qa_mock_expected_quality_is_promoted_to_metadata(self):
        from impl.core.project_loader import load_adapter, load_project

        adapter = load_adapter(load_project("QA"))

        case = adapter._normalize_mock_case({
            "id": "qa-labeled-incorrect",
            "input": {"question": "等待期是否赔付？", "expected_quality": "incorrect", "expected_error_type": "answer_incomplete"},
            "output": {"actual_answer": "不赔。"},
            "reference": {"golden_answer": "等待期内一般不赔，但意外情形需按条款判断。"},
        })

        self.assertEqual(case["metadata"]["expected_quality"], "incorrect")
        self.assertEqual(case["metadata"]["expected_error_type"], "answer_incomplete")


if __name__ == "__main__":
    unittest.main()
