"""Marketing Planning 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.mock_protocol import ProjectMock
from impl.core.schema import ProjectSpec, SingleTurnCase, MultiTurnCase


class MarketingPlanningMock(ProjectMock):
    """Marketing Planning 项目 Mock 实现"""

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

    def next_turn(
        self,
        case: SingleTurnCase | MultiTurnCase,
        previous_turns: List[Dict[str, Any]],
        live_feedback: Dict[str, Any]
    ) -> Dict[str, Any]:
        """扮演用户追问（多轮项目）：委托 MockAgent 通用逻辑"""
        from impl.core.mock_agent import MockAgent
        agent = MockAgent(self.spec)
        case_dict = {"input": dict(getattr(case, "input", {}) or {}), "scenario": str(getattr(case, "scenario", "") or "")}
        return agent.next_turn(case_dict, previous_turns, live_feedback)

    def normalize_case(
        self,
        case: SingleTurnCase | MultiTurnCase
    ) -> SingleTurnCase | MultiTurnCase:
        """归一化 Case：补充 marketting-planning 项目特有字段"""
        if isinstance(case, SingleTurnCase):
            input_data = dict(case.input or {})
            # 确保有 query 字段
            if not input_data.get("query"):
                input_data["query"] = str(input_data.get("user_intent") or input_data.get("user_text") or "")
                case.input = input_data
        return case
