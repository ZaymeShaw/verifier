"""Policy Search 用户模拟。主体单轮；interactive scenario 才补下一轮。"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from impl.core.mock_protocol import MultiTurnInteractiveMock, ProjectMock
from impl.core.schema import MockContinueDecision, MockIntentOutput
from impl.core.session import SessionState, SessionTranslator, UserMessage
from impl.projects.policy_search.rich_mock import MockDemand


SCENARIO_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "atomic_condition": {
        "intent": "筛选保额不少于五十万元的保单",
        "query": "保额不低于50万的保单",
    },
    "compound_logic": {
        "intent": "筛选张三或李四作为投保人、今年生效且保额不少于五十万元的保单",
        "query": "张三或李四作为投保人，今年生效且保额不低于50万的保单",
    },
    "time_boundary": {
        "intent": "筛选八月份生效的保单",
        "query": "8月生效的保单",
    },
    "enum_alias": {
        "intent": "筛选万能险类别的保单",
        "query": "万能帐户保单",
    },
    "agent_identity": {
        "intent": "筛选由当前登录代理人销售的保单",
        "query": "我销售的保单",
    },
    "context_disambiguation": {
        "intent": "上一轮保额条件缺失，本轮补金额",
        "query": "50万以上",
        "contexts": [
            {"role": "user", "content": "帮我查一下保额比较高的保单", "sub_agent": ""},
            {"role": "assistant", "content": "“保额”缺少必要的条件，请补充后重试", "sub_agent": "POLICY_SEARCH"},
        ],
    },
    "clarification": {
        "intent": "表达了年缴保费筛选方向但没有提供必要金额条件",
        "query": "年缴保费的保单",
    },
    "clarification_reply": {
        "intent": "上一轮只点名保额，本轮用金额短答补槽",
        "query": "保额的保单",
        "next_query": "50万以上",
    },
    "clarification_then_new_query": {
        "intent": "上一轮在问生效时间，本轮改口提完整新问题",
        "query": "先问生效时间",
        "next_query": "张三且保费超过30万的保单",
    },
    "unsupported": {
        "intent": "筛选投诉次数超过三次但首期不支持的保单",
        "query": "投诉超过3次的保单",
    },
    "surface_generalization": {
        "intent": "用口语表达筛选处于失效状态的保单",
        "query": "帮我找下已经失效了的那些保单",
    },
}


def _user_context_from(payload: Dict[str, Any]) -> Dict[str, Any]:
    context: Dict[str, Any] = {"contexts": list(payload.get("contexts") or [])}
    next_query = str(payload.get("next_query") or "").strip()
    if next_query:
        context["next_query"] = next_query
    return context


def demand_template(demand: MockDemand) -> Dict[str, Any]:
    template: Dict[str, Any] = {
        "contexts": list(demand.contexts),
        "diversity_seed": demand.demand_id,
    }
    if demand.query:
        template["mock_query"] = demand.query
    if demand.next_query:
        template["next_query"] = demand.next_query
    return template


def _contexts_from_transcript(transcript: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """state.transcript → extra_input_params.args.contexts。只搬运，不发明历史。"""
    contexts: List[Dict[str, Any]] = []
    for item in transcript:
        role = str(item.get("role") or "")
        if role == "user":
            contexts.append({"role": "user", "content": str(item.get("content") or ""), "sub_agent": ""})
        elif role == "assistant":
            output = item.get("extracted_output") if isinstance(item.get("extracted_output"), dict) else {}
            content = str(output.get("message") or item.get("content") or "")
            contexts.append({"role": "assistant", "content": content, "sub_agent": "POLICY_SEARCH"})
    return contexts


class PolicySearchMock(MultiTurnInteractiveMock, SessionTranslator, ProjectMock):
    # spec/mock/protocol.md 6.4：原话槽位 policySearchParseArgs.query；历史字段 args.contexts。
    supports_history_injection = True

    def request_from_user_message(self, message: UserMessage, state: SessionState) -> Dict[str, Any]:
        if message.type != "text":
            raise ValueError(f"policy_search has no structured user actions; got {message.type!r}")
        base = dict(state.last_request or {})
        if not base:
            base = {
                "session_id": state.session_id,
                "trace_id": state.session_id,
                "user_id": "verifier-user",
                "org_id": "verifier-org",
                "org_name": "verifier",
                "ts": 1785983400000,
                "token": "",
                "app_scenario": "policy_search_parse",
                "source": "verifier",
                "user_text": "",
                "history": [],
                "user_action": "write",
                "action_scenario": "policySearch",
                "extra_input_params": {
                    "policySearchParseArgs": {
                        "currentTime": "2026-08-06 10:30:00",
                        "agentCode": "A12345678",
                    },
                    "agent_args": None,
                    "args": {"contexts": []},
                },
                "application_setting": None,
                "scenario": None,
            }
        extra = dict(base.get("extra_input_params") or {})
        parse_args = dict(extra.get("policySearchParseArgs") or {})
        parse_args["query"] = message.text
        extra["policySearchParseArgs"] = parse_args
        extra["args"] = {"contexts": _contexts_from_transcript(state.transcript)}
        request = dict(base)
        request["session_id"] = state.session_id
        request["trace_id"] = f"{state.session_id}-turn{state.turn_index}"
        request["extra_input_params"] = extra
        return request

    def user_message_from_request(self, request: Dict[str, Any]) -> UserMessage:
        return UserMessage(type="text", text=self.extract_mock_message(request))

    def build_user_intent_for_case(
        self,
        scenario: str,
        *,
        requested_intent: str = "",
        template: Dict[str, Any] | None = None,
    ) -> MockIntentOutput:
        """消费覆盖规划器给出的事实任务，不让 LLM 补造测试答案。"""
        task = dict(template or {})
        if "mock_query" not in task:
            return super().build_user_intent_for_case(
                scenario,
                requested_intent=requested_intent,
                template=template,
            )
        return MockIntentOutput(
            user_intent=str(requested_intent or task.get("user_intent") or ""),
            query=str(task.get("mock_query") or ""),
            user_context=_user_context_from(task),
            system_understanding="用户通过自然语言筛选保单，系统返回查询语法树而非保单列表。",
            scenario=scenario,
        )

    def generate_demand_case(self, demand: MockDemand):
        """通过公共 Mock 模板方法生成一条覆盖任务对应的标准 Case。"""
        return self.generate_mock_case(
            scenario=demand.scenario,
            intent=demand.user_intent,
            template=demand_template(demand),
        )

    def build_user_intent(self, scenario: str) -> MockIntentOutput:
        example = SCENARIO_EXAMPLES.get(scenario) or SCENARIO_EXAMPLES["atomic_condition"]
        return MockIntentOutput(
            user_intent=str(example["intent"]),
            query=str(example["query"]),
            user_context=_user_context_from(example),
            system_understanding="用户通过自然语言筛选保单，系统返回查询语法树而非保单列表。",
            scenario=scenario or "atomic_condition",
        )

    def build_initial_request(self, intent: MockIntentOutput) -> Dict[str, Any]:
        contexts = list((intent.user_context or {}).get("contexts") or [])
        request_id = uuid.uuid4().hex
        return {
            "session_id": f"verifier-policy-{request_id[:12]}",
            "trace_id": f"verifier-policy-{request_id}",
            "user_id": "verifier-user",
            "org_id": "verifier-org",
            "org_name": "verifier",
            "ts": 1785983400000,
            "token": "",
            "app_scenario": "policy_search_parse",
            "source": "verifier",
            "user_text": "",
            "history": [],
            "user_action": "write",
            "action_scenario": "policySearch",
            "extra_input_params": {
                "policySearchParseArgs": {
                    "query": intent.query,
                    "currentTime": "2026-08-06 10:30:00",
                    "agentCode": "A12345678",
                },
                "agent_args": None,
                "args": {"contexts": contexts},
            },
            "application_setting": None,
            "scenario": None,
        }

    def extract_mock_message(self, request: Dict[str, Any]) -> str:
        extra = request.get("extra_input_params") or {}
        args = extra.get("policySearchParseArgs") or {}
        return str(args.get("query") or "")

    def infer_user_intent(self, initial_request: Dict[str, Any]) -> MockIntentOutput:
        extra = initial_request.get("extra_input_params") or {}
        contexts = list(((extra.get("args") or {}).get("contexts") or []))
        query = self.extract_mock_message(initial_request)
        return MockIntentOutput(
            user_intent=query,
            query=query,
            user_context={"contexts": contexts},
            system_understanding="用户通过自然语言筛选保单，系统返回查询语法树而非保单列表。",
            scenario="",
        )

    def decide_next_action(
        self,
        intent: MockIntentOutput,
        accumulated_output: Dict[str, Any],
    ) -> MockContinueDecision:
        """只按 scenario 和本轮 status 决定是否追问，不调用模型。"""
        scenario = str(getattr(intent, "scenario", "") or "")
        if scenario not in set(self.spec.interactive_scenarios):
            return MockContinueDecision(action="stop", stop_reason="goal_satisfied")
        turns = [
            turn
            for turn in ((accumulated_output or {}).get("turns") or [])
            if isinstance(turn, dict)
        ]
        if len(turns) != 1:
            return MockContinueDecision(action="stop", stop_reason="goal_satisfied")
        last_output = turns[0].get("extract_output") or turns[0].get("extracted_output") or {}
        if str(last_output.get("status") or "") != "UNSUPPORTED":
            return MockContinueDecision(action="stop", stop_reason="goal_satisfied")
        next_query = str((intent.user_context or {}).get("next_query") or "").strip()
        if not next_query:
            return MockContinueDecision(action="stop", stop_reason="goal_satisfied")
        return MockContinueDecision(action="continue")

    def build_next_request(
        self,
        intent: MockIntentOutput,
        accumulated_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        turns = [
            turn
            for turn in ((accumulated_output or {}).get("turns") or [])
            if isinstance(turn, dict)
        ]
        last_turn = turns[-1] if turns else {}
        last_request = dict(last_turn.get("live_request") or {})
        last_output = last_turn.get("extract_output") or last_turn.get("extracted_output") or {}
        previous_query = self.extract_mock_message(last_request)
        assistant = str(last_output.get("message") or "").strip() or "请补充查询条件"
        next_query = str((intent.user_context or {}).get("next_query") or "").strip()
        if not next_query:
            raise ValueError("interactive case is missing next_query")
        extra = dict(last_request.get("extra_input_params") or {})
        parse_args = dict(extra.get("policySearchParseArgs") or {})
        parse_args["query"] = next_query
        extra["policySearchParseArgs"] = parse_args
        extra["args"] = {
            "contexts": [
                {"role": "user", "content": previous_query, "sub_agent": ""},
                {"role": "assistant", "content": assistant, "sub_agent": "POLICY_SEARCH"},
            ]
        }
        request = dict(last_request)
        session_id = str(last_request.get("session_id") or f"verifier-policy-{uuid.uuid4().hex[:12]}")
        request["session_id"] = session_id
        request["trace_id"] = f"{session_id}-turn{len(turns) + 1}"
        request["extra_input_params"] = extra
        return request

