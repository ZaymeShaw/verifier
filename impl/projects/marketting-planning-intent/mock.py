"""Marketing Planning Intent 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from impl.core.mock_protocol import ProjectMock, SingleTurnMock
from impl.core.schema import ProjectSpec, SingleTurnCase, MultiTurnCase


class MarketingIntentMock(SingleTurnMock, ProjectMock):
    """Marketing Planning Intent 项目 Mock 实现。

    继承 SingleTurnMock（交互模式=单轮）+ ProjectMock。
    退出多轮签名，实现 build_user_intent + build_live_request。
    """

    def build_user_intent(self, scenario: str):
        """扮演用户产意图：委托 MockAgent.build_intent 并转 MockIntentOutput。"""
        from impl.core.mock_agent import MockAgent, build_spec_from_project
        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_live_request(self, intent) -> Dict[str, Any]:
        """把用户表达确定性映射为 MPIIntentNormalizedRequest；API body 由 Live 扩展层转换。"""
        if intent.live_request is not None:
            return dict(intent.live_request)
        session_id = f"eval-intent-{int(time.time() * 1000)}"
        return {
            "case_id": "",
            "session_id": session_id,
            "query": str(getattr(intent, "query", "") or getattr(intent, "user_intent", "") or ""),
            "scenario": str(getattr(intent, "scenario", "") or "intent_recognition"),
            "reference": {},
            "metadata": {},
            "user_intent": str(getattr(intent, "user_intent", "") or "") or None,
        }

    def normalize_case(
        self,
        case: SingleTurnCase | MultiTurnCase
    ) -> SingleTurnCase | MultiTurnCase:
        """归一化 Case：补充 marketting-planning-intent 项目特有字段"""
        if isinstance(case, SingleTurnCase):
            input_data = dict(case.input or {})
            # 确保有 query 字段
            if not input_data.get("query"):
                input_data["query"] = str(input_data.get("user_text") or input_data.get("user_intent") or "")
                case.input = input_data
        return case
