"""QA 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

from typing import Any, Dict

from impl.core.mock_protocol import ProjectMock, SingleTurnMock
from impl.core.schema import ProjectSpec, RunTrace, SingleTurnCase, MultiTurnCase


class QAMock(SingleTurnMock, ProjectMock):
    """QA 项目 Mock 实现。

    继承 SingleTurnMock（交互模式=单轮）+ ProjectMock。
    实现 build_user_intent（场景级意图）+ build_live_request（单轮 request）。
    """

    def build_user_intent(self, scenario: str):
        """扮演用户产意图：委托 MockAgent.build_intent 并转 MockIntentOutput。"""
        from impl.core.mock_agent import MockAgent, build_spec_from_project
        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_live_request(self, intent) -> Dict[str, Any]:
        """产单轮 request：委托 MockAgent 把意图翻译成 REQUEST_SCHEMA 形状。"""
        if intent.live_request is not None:
            return intent.live_request
        from impl.core.mock_agent import MockAgent, build_spec_from_project, build_live_request_from_intent
        agent = MockAgent(self.spec)
        scenario = str(getattr(intent, "scenario", "") or "")
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return build_live_request_from_intent(agent, build_spec, intent).input

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
