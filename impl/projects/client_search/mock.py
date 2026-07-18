"""Client Search 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

from typing import Any, Dict

from impl.core.mock_protocol import ProjectMock, SingleTurnMock
from impl.core.schema import ProjectSpec, SingleTurnCase, MultiTurnCase


class ClientSearchMock(SingleTurnMock, ProjectMock):
    """Client Search 项目 Mock 实现。

    继承 SingleTurnMock（交互模式=单轮）+ ProjectMock。
    实现 build_user_intent（场景级意图）+ build_live_request（单轮 request）。
    """

    def build_user_intent(self, scenario: str):
        """扮演用户产意图：委托 MockAgent.build_intent 并转 MockIntentOutput。"""
        from impl.core.mock_agent import MockAgent, build_spec_from_project
        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_initial_request(self, intent) -> Dict[str, Any]:
        """把用户表达确定性映射为 ClientSearchRequest；不让 LLM 编造协议字段。"""
        return {
            "user_text": str(getattr(intent, "query", "") or getattr(intent, "user_intent", "") or ""),
            "user_id": "eval-user",
            "trace_id": "",
            "session_id": "general-eval-session",
            "source": "askbob",
            "extra_input_params": {},
        }

    def normalize_case(
        self,
        case: SingleTurnCase | MultiTurnCase
    ) -> SingleTurnCase | MultiTurnCase:
        """归一化 Case：补充 client_search 项目特有字段"""
        if isinstance(case, SingleTurnCase):
            input_data = dict(case.input or {})
            # 确保有 user_text 字段
            if not input_data.get("user_text"):
                input_data["user_text"] = str(input_data.get("query") or "")
                case.input = input_data
        return case
