import unittest

from impl.core.project_loader import load_adapter, load_project
from impl.core.schema import JudgeResult, RunTrace


def adapter(project_id):
    return load_adapter(load_project(project_id))


class ProjectFulfillmentAdaptersTest(unittest.TestCase):
    def test_qa_reconcile_builds_answer_quality_fulfillment_contract(self):
        subject = adapter("QA")
        trace = RunTrace(
            trace_id="trace-qa-fulfillment",
            project_id="QA",
            input={"question": "等待期是否赔付？"},
            normalized_request={"input": {"question": "等待期是否赔付？"}, "reference": {"golden_answer": "等待期疾病通常不赔，意外除外。"}, "scenario": "qa_gold_answer"},
            extracted_output={"actual_answer": "等待期不赔。"},
            project_fields={"reference": {"golden_answer": "等待期疾病通常不赔，意外除外。"}, "scenario": "qa_gold_answer"},
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, verdict="incorrect", wrong=[{"requirement": "groundedness", "status": "wrong"}], score=0.4)

        result = subject.reconcile_judge_result(trace, judge)

        expectation = result.business_expectations[0]
        assessment = result.fulfillment_assessments[0]
        self.assertEqual(result.consumer_contract["consumer"], "QA user")
        self.assertEqual(expectation["expectation_id"], "QA:answer_quality")
        self.assertIn("answer_relevance", expectation["required_capabilities"])
        self.assertIn("groundedness", expectation["required_capabilities"])
        self.assertIn("reference_alignment", expectation["required_capabilities"])
        self.assertEqual(assessment["status"], "not_fulfilled")
        self.assertTrue(assessment["blocking"])
        self.assertEqual(result.verdict, "incorrect")

    def test_client_search_reconcile_builds_downstream_condition_fulfillment_contract(self):
        subject = adapter("client_search")
        trace = RunTrace(
            trace_id="trace-client-search-fulfillment",
            project_id="client_search",
            input={"query": "45岁女性保费10万以上"},
            normalized_request={"user_text": "45岁女性保费10万以上"},
            extracted_output={"structured_output": [{"field": "clientSex", "operator": "MATCH", "value": "女"}], "logic": "AND"},
            project_fields={"application_boundary": {"scope": "structured_client_search"}, "conditions": [{"field": "clientSex"}]},
            execution_trace=[{"stage": "adapter.extract_output", "status": "ok"}],
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, verdict="incorrect", missing=[{"requirement": "clientAge", "status": "missing"}], wrong=[], score=0.5)

        result = subject.reconcile_judge_result(trace, judge)

        expectation = result.business_expectations[0]
        assessment = result.fulfillment_assessments[0]
        self.assertEqual(result.consumer_contract["consumer"], "downstream client search")
        self.assertEqual(expectation["expectation_id"], "client_search:search_condition_contract")
        self.assertIn("field_operator_value_logic", expectation["required_capabilities"])
        self.assertIn("downstream_search_executability", expectation["required_capabilities"])
        self.assertEqual(assessment["status"], "not_evaluable")
        self.assertTrue(assessment["blocking"])

    def test_marketing_planning_reconcile_builds_stage_path_sse_fulfillment_contract(self):
        subject = adapter("marketting-planning")
        trace = RunTrace(
            trace_id="trace-mp-fulfillment",
            project_id="marketting-planning",
            input={"query": "规划NBEV增长"},
            normalized_request={},
            extracted_output={"stage": "planning", "card_summary": [], "event_summary": {"names": ["intent_detected"], "completed": False}, "fallback": {"used": False}},
            project_fields={"reference": {"expected_stage": "planning", "required_path_types": ["premium_growth"], "required_events": ["done"]}, "expected_stage": "planning", "expected_path_types": ["premium_growth"], "application_boundary": {"allow_fallback": False}},
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, verdict="correct", score=1)

        result = subject.reconcile_judge_result(trace, judge)

        expectation = result.business_expectations[0]
        assessment = result.fulfillment_assessments[0]
        self.assertEqual(result.consumer_contract["consumer"], "marketing planning user")
        self.assertEqual(expectation["expectation_id"], "marketting-planning:planning_output_contract")
        self.assertIn("stage_routing", expectation["required_capabilities"])
        self.assertIn("path_card_generation", expectation["required_capabilities"])
        self.assertIn("sse_completion", expectation["required_capabilities"])
        self.assertEqual(assessment["status"], "not_fulfilled")
        self.assertEqual(result.verdict, "incorrect")

    def test_marketing_intent_reconcile_builds_single_turn_intent_fulfillment_contract(self):
        subject = adapter("marketting-planning-intent")
        trace = RunTrace(
            trace_id="trace-mpi-fulfillment",
            project_id="marketting-planning-intent",
            input={"query": "我想看NBEV增长"},
            normalized_request={},
            extracted_output={"intent": "unknown", "confidence": 0.2, "slots": {}, "fallback": True},
            project_fields={"reference": {"intent": "premium_growth", "required_slots": ["year"], "allow_fallback": False, "min_confidence": 0.8}, "application_boundary": {"scope": "single_turn_intent_recognition"}},
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, verdict="correct", score=1)

        result = subject.reconcile_judge_result(trace, judge)

        expectation = result.business_expectations[0]
        assessment = result.fulfillment_assessments[0]
        self.assertEqual(result.consumer_contract["consumer"], "marketing intent router")
        self.assertEqual(expectation["expectation_id"], "marketting-planning-intent:intent_contract")
        self.assertIn("intent_label", expectation["required_capabilities"])
        self.assertIn("slot_extraction", expectation["required_capabilities"])
        self.assertIn("fallback_control", expectation["required_capabilities"])
        self.assertEqual(assessment["status"], "not_fulfilled")
        self.assertTrue(assessment["blocking"])


if __name__ == "__main__":
    unittest.main()
