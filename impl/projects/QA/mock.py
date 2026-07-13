"""QA 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.mock_protocol import ProjectMock
from impl.core.schema import ProjectSpec, RunTrace, SingleTurnCase, MultiTurnCase


class QAMock(ProjectMock):
    """QA 项目 Mock 实现"""

    def build_user_intent(self, scenario: str) -> Dict[str, Any]:
        """扮演用户产意图：委托 MockAgent.build_intent"""
        from impl.core.mock_agent import MockAgent, build_spec_from_project
        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        result = agent.build_intent(build_spec)
        return {
            "query": result.input.get("query", ""),
            "expected_intent": result.expected_intent,
            "user_intent": result.input.get("user_intent", ""),
            "input": result.input,
        }

    def normalize_case(
        self,
        case: SingleTurnCase | MultiTurnCase
    ) -> SingleTurnCase | MultiTurnCase:
        """归一化 Case：补充 QA 项目特有字段"""
        if isinstance(case, SingleTurnCase):
            input_data = dict(case.input or {})
            # 确保有 question 字段
            if not input_data.get("question"):
                input_data["question"] = str(input_data.get("query") or "")
                case.input = input_data
        return case
