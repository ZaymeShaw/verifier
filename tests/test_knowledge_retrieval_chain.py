"""Chain test: verify knowledge retrieval sufficiency for complex queries."""
import unittest
from unittest.mock import Mock, patch

from impl.core.judge import judge_trace
from impl.core.knowledge_base import ProjectKnowledgeBase
from impl.core.schema import ProjectSpec, RunTrace


class KnowledgeRetrievalChainTest(unittest.TestCase):
    def test_complex_query_recalls_all_relevant_fields(self):
        """验证复杂查询（多字段组合）能召回所有相关字段定义"""
        spec = ProjectSpec(
            project_id="client_search",
            name="Client Search",
            root="/tmp/test-project",
            documents={
                "source_field_definitions": "fields.yaml",
            },
        )

        # 模拟包含多个字段的复杂查询
        trace = RunTrace(
            trace_id="chain_test_complex",
            project_id="client_search",
            input={"query": "45岁女性，年缴保费10万以上，且有未领取生存金"},
            normalized_request={"query": "45岁女性，年缴保费10万以上，且有未领取生存金"},
            extracted_output={"filters": []},
        )

        # Mock knowledge base with field entries
        kb = Mock()
        kb.to_context.return_value = """// Relevant field definitions for query '45岁女性，年缴保费10万以上，且有未领取生存金':
field: clientAge (GT, integer)
  desc: 客户年龄
field: clientSex (EQ, string)
  desc: 客户性别
  enum: 男, 女
field: annPremSegNum (GT, integer)
  desc: 年缴保费档位
field: payAmountDue (EXISTS, nested)
  desc: 未领取生存金
"""

        llm = Mock()
        llm.complete_json.return_value = {
            "verdict": "incorrect",
            "intent_model": {"raw_user_request": trace.input["query"]},
            "consumer_contract": {"consumer": "client_search", "contract": "test"},
            "business_expectations": [],
            "fulfillment_assessments": [],
            "overall_fulfillment": {"status": "not_fulfilled"},
            "condition_assessments": [
                {"requirement": "clientAge", "status": "missing"},
                {"requirement": "clientSex", "status": "missing"},
                {"requirement": "annPremSegNum", "status": "missing"},
                {"requirement": "payAmountDue", "status": "missing"},
            ],
            "expected": {"filters": ["clientAge", "clientSex", "annPremSegNum", "payAmountDue"]},
            "actual": {"filters": []},
        }

        with patch("impl.core.judge.load_knowledge_base", return_value=kb):
            result = judge_trace(spec, trace, llm=llm)

        # 验证知识库被调用检索
        kb.to_context.assert_called_once()
        query_arg = kb.to_context.call_args.args[0]
        self.assertIn("45岁", query_arg)
        self.assertIn("女性", query_arg)
        self.assertIn("保费", query_arg)
        self.assertIn("生存金", query_arg)

        # 验证 judge 结果包含所有字段
        condition_reqs = [c["requirement"] for c in result.condition_assessments]
        self.assertIn("clientAge", condition_reqs)
        self.assertIn("clientSex", condition_reqs)
        self.assertIn("annPremSegNum", condition_reqs)
        self.assertIn("payAmountDue", condition_reqs)

    def test_empty_query_logs_warning_but_continues(self):
        """验证空查询时记录警告但不中断流程"""
        spec = ProjectSpec(
            project_id="test_empty",
            name="Test Empty",
            documents={},
        )

        trace = RunTrace(
            trace_id="empty_query_test",
            project_id="test_empty",
            input={},
            normalized_request={},
            extracted_output={},
        )

        llm = Mock()
        llm.complete_json.return_value = {
            "verdict": "uncertain",
            "intent_model": {"raw_user_request": ""},
            "consumer_contract": {"consumer": "test_empty", "contract": "test"},
            "business_expectations": [],
            "fulfillment_assessments": [],
            "overall_fulfillment": {"status": "not_evaluable"},
        }

        with patch("impl.core.judge.load_knowledge_base") as kb_loader, \
             patch("impl.core.judge.logger") as logger_mock:
            kb_loader.return_value.to_context.return_value = ""
            result = judge_trace(spec, trace, llm=llm)

            # 验证记录了警告
            logger_mock.warning.assert_called_once()
            warning_msg = logger_mock.warning.call_args.args[0]
            self.assertIn("Empty query", warning_msg)
            self.assertIn("empty_query_test", warning_msg)

            # 验证流程继续执行
            self.assertEqual(result.verdict, "uncertain")


if __name__ == "__main__":
    unittest.main()
