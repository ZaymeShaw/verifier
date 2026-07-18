"""Marketing Planning 项目的 Mock 实现

实现 ProjectMock 协议。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from impl.core.mock_protocol import MultiTurnInteractiveMock, ProjectMock
from impl.core.schema import MockContinueDecision, MockIntentOutput, ProjectSpec, SingleTurnCase, MultiTurnCase


class MarketingPlanningMock(MultiTurnInteractiveMock, ProjectMock):
    """Marketing Planning 项目 Mock 实现。

    继承 MultiTurnInteractiveMock（交互模式=多轮）+ ProjectMock。
    实现 build_user_intent（场景级意图）+ build_next_request（每轮 request）。

    spec/adapter/trace.md 行 92：build_next_request 签名
    (intent, accumulated) → REQUEST_SCHEMA。产出必须符合 live_schema.REQUEST_SCHEMA（MPApiRequest）。
    """

    def build_user_intent(self, scenario: str):
        """扮演用户产意图：委托 MockAgent.build_intent 并转 MockIntentOutput。"""
        from impl.core.mock_agent import MockAgent, build_spec_from_project
        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_next_request(
        self,
        intent,
        accumulated_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """产每一轮的 request。spec/adapter/trace.md 行 92。

        协议层已经把 intent 算好传入，项目层直接使用，不自己调 build_user_intent。
        - accumulated_output=None（首轮）：基于 intent 产首轮 request
        - accumulated_output=<上一轮累积>（后续轮）：基于 intent + 历史累积产下一轮 request

        产出必须符合 MPApiRequest 形状（live_schema.REQUEST_SCHEMA）。
        """
        from impl.core.mock_agent import MockAgent
        agent = MockAgent(self.spec)
        acc = accumulated_output if isinstance(accumulated_output, dict) else {}
        turns = [t for t in (acc.get("turns") or []) if isinstance(t, dict)]
        last_turn = turns[-1] if turns else {}
        prior_request = last_turn.get("live_request") if isinstance(last_turn.get("live_request"), dict) else {}
        session_id = str(prior_request.get("session_id") or f"mock-{self.spec.project_id}-{int(time.time() * 1000)}")
        last_output = last_turn.get("extract_output") if isinstance(last_turn.get("extract_output"), dict) else {}
        live_feedback = {
            "stage": last_output.get("stage"),
            "missing_fields": last_output.get("missing_fields") or [],
            "extracted_output": last_output,
        }
        case_dict = {
            "scenario": str(getattr(intent, "scenario", "") or "intent_recognition"),
            "metadata": {"user_context": dict(getattr(intent, "user_context", {}) or {})},
            "user_intent": str(getattr(intent, "user_intent", "") or ""),
        }
        query = str(agent.next_turn(case_dict, turns, live_feedback).get("query") or "")
        if not query:
            raise ValueError("MockAgent.next_turn 未生成下一轮 query")

        # 产出符合 MPApiRequest 形状（live_schema.REQUEST_SCHEMA）
        return {
            "session_id": session_id,
            "trace_id": session_id,
            "org_id": "eval-org",
            "user_text": query,
            "history": [],
            "user_action": "send_message",
            "action_scenario": "marketing_planning",
            "user_id": "eval-user",
            "ts": int(time.time()),
            "token": "mock_token",
            "app_scenario": "customer_service",
            "docs_num": 5,
            "source": "offline_task",
            "extra_input_params": {
                "agent_args": {"conversation_id": session_id, "message": {"content": query, "content_type": "text"}},
                "args": {"extensions": {}, "contexts": []},
            },
        }

    def infer_user_intent(self, initial_request: Dict[str, Any]) -> MockIntentOutput:
        from impl.core.mock_agent import MockAgent
        return MockAgent(self.spec).infer_user_intent(initial_request, scenario=str(initial_request.get("scenario") or "multi_turn_field_accumulation"))

    def decide_next_action(self, intent: MockIntentOutput, accumulated_output: Dict[str, Any]) -> MockContinueDecision:
        from impl.core.mock_agent import MockAgent
        return MockAgent(self.spec).decide_next_action(intent, accumulated_output)

    def safety_max_turns(self) -> int:
        return 12

    def extract_mock_message(self, request: Dict[str, Any]) -> str:
        return str(request.get("user_text") or "") if isinstance(request, dict) else ""

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
