from __future__ import annotations

from typing import Any

import pytest

from impl.core.live_protocol import MultiTurnInteractiveLive, RealServiceLive, SingleTurnLive
from impl.core.live_transport import LiveTransport
from impl.core.mock_agent import MockAgent
from impl.core.schema import MockBuildSpec, MockContinueDecision, MockIntentOutput, ProjectSpec, SingleTurnCase
from impl.core.trace import TraceContext, trace_from_live


class _Checker:
    def __init__(self, request_ok: bool = True, output_ok: bool = True):
        self.request_ok = request_ok
        self.output_ok = output_ok

    def request(self, payload: Any) -> bool:
        return self.request_ok

    def output(self, payload: Any) -> bool:
        return self.output_ok


class _LiveSchema:
    def __init__(self, checker: _Checker):
        self.check = checker


class _SingleMock:
    def __init__(self):
        self.generated_intents = 0

    def build_user_intent(self, scenario: str) -> MockIntentOutput:
        self.generated_intents += 1
        return MockIntentOutput(user_intent="generated", query="wrong-query", scenario=scenario)

    def build_initial_request(self, intent: MockIntentOutput) -> dict[str, Any]:
        return {"query": intent.query}


class _MultiMock:
    def __init__(self):
        self.index = 0
        self.inferred = 0

    def build_next_request(self, intent: MockIntentOutput, accumulated: dict | None) -> dict[str, Any]:
        self.index += 1
        return {"query": f"turn-{int((accumulated or {}).get('current_turn') or 0) + 1}"}

    def infer_user_intent(self, initial_request: dict[str, Any]) -> MockIntentOutput:
        self.inferred += 1
        return MockIntentOutput(user_intent="inferred", query=str(initial_request.get("query") or ""))

    def decide_next_action(self, intent: MockIntentOutput, accumulated: dict) -> MockContinueDecision:
        return MockContinueDecision(action="stop", stop_reason="goal_satisfied") if accumulated["current_turn"] >= 2 else MockContinueDecision(action="continue")

    def safety_max_turns(self) -> int:
        return 3


class _Adapter:
    def __init__(self, mock: Any):
        self._mock = mock

    def mock(self) -> Any:
        return self._mock


class _SingleLive(RealServiceLive, SingleTurnLive):
    def deliver_real(self, request: dict[str, Any], transport: LiveTransport) -> LiveTransport:
        transport.post("http://live.test", json_body=request, carries_live_request=True, contributes_raw_response=True)
        return transport

    def extract_output(self, raw_response: list[Any]) -> dict[str, Any]:
        return dict(raw_response[0])


class _MultiLive(RealServiceLive, MultiTurnInteractiveLive):
    def deliver_real(self, request: dict[str, Any], transport: LiveTransport) -> LiveTransport:
        transport.post("http://live.test", json_body=request, carries_live_request=True, contributes_raw_response=True)
        return transport

    def extract_output(self, raw_response: list[Any]) -> dict[str, Any]:
        return dict(raw_response[0])


@pytest.fixture(autouse=True)
def _fake_live_http(monkeypatch):
    class Response:
        status = 200
        headers = {}

        def __init__(self, request):
            self._request = request

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            import json
            payload = json.loads((self._request.data or b"{}").decode("utf-8"))
            return json.dumps({"answer": payload.get("query")}).encode("utf-8")

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", lambda request, timeout=0: Response(request))


def _spec() -> ProjectSpec:
    return ProjectSpec(project_id="demo", name="demo", runtime={"ready": []})


def _live(instance_type: type, mock: Any, *, request_ok: bool = True, output_ok: bool = True):
    # 绕过 ProjectLive.__init__ 的项目 live_schema/LLM 加载，只测试协议主流程。
    instance = instance_type.__new__(instance_type)
    instance.spec = _spec()
    instance.live_schema = _LiveSchema(_Checker(request_ok=request_ok, output_ok=output_ok))
    instance._adapter = _Adapter(mock)
    return instance


def test_deliver_turn_returns_one_valid_project_output():
    live = _live(_SingleLive, _SingleMock())

    output = live.deliver_turn({"query": "hello"})

    assert output == {"answer": "hello"}


def test_multi_turn_returns_last_output_and_keeps_all_turn_facts_in_context():
    live = _live(_MultiLive, _MultiMock())
    ctx = TraceContext(project_id="demo", case_id="case-1", multi_turn=True)
    intent = MockIntentOutput(user_intent="finish task", query="start", scenario="multi")

    output = live.execute_live({"query": "turn-1"}, ctx, intent)

    assert output == {"answer": "turn-2"}
    assert [turn["extracted_output"] for turn in ctx.turns] == [
        {"answer": "turn-1"},
        {"answer": "turn-2"},
    ]
    assert ctx.final_output_turn == 2
    assert ctx.stop_reason == "goal_satisfied"
    assert ctx.completion_status == "completed"


def test_mock_continue_decision_prompt_defines_all_states_and_long_term_no_progress():
    class Llm:
        def __init__(self):
            self.system = ""

        def complete_json(self, system, *_args, **_kwargs):
            self.system = system
            return {"action": "continue", "stop_reason": ""}

    llm = Llm()
    decision = MockAgent(_spec(), llm=llm).decide_next_action(
        MockIntentOutput(user_intent="完成规划", query="开始规划"),
        {"turns": [], "current_turn": 1},
    )

    assert decision == MockContinueDecision(action="continue", stop_reason="")
    assert "continue：目标尚未满足，但交互仍有实质进展" in llm.system
    assert "goal_satisfied：用户从可见结果主观认为目标已经满足" in llm.system
    assert "user_abandons：用户明确不愿继续交互" in llm.system
    assert "perceived_no_progress：经过持续交互后长期没有实质进展" in llm.system
    assert "合理且有推进作用的澄清" in llm.system
    assert "证据不足以停止时也选择 continue" in llm.system


def test_mock_continue_decision_normalizes_provider_free_text_reason():
    class Llm:
        def complete_json(self, *_args, **_kwargs):
            return {"action": "stop", "stop_reason": "已经达到用户目标，无需继续"}

    decision = MockAgent(_spec(), llm=Llm()).decide_next_action(
        MockIntentOutput(user_intent="验证结果", query="执行一次"),
        {"turns": [], "current_turn": 1},
    )

    assert decision == MockContinueDecision(action="stop", stop_reason="goal_satisfied")


def test_mock_continue_decision_unwraps_provider_discriminated_action():
    class Llm:
        def complete_json(self, *_args, **_kwargs):
            return {
                "action": {"type": "stop", "stop_reason": "goal_satisfied"},
                "stop_reason": "",
            }

    decision = MockAgent(_spec(), llm=Llm()).decide_next_action(
        MockIntentOutput(user_intent="验证结果", query="执行一次"),
        {"turns": [], "current_turn": 1},
    )

    assert decision == MockContinueDecision(action="stop", stop_reason="goal_satisfied")


def test_multi_turn_retries_malformed_continue_decision_once():
    class RetryMock(_MultiMock):
        def __init__(self):
            super().__init__()
            self.decisions = 0

        def decide_next_action(self, intent, accumulated):
            self.decisions += 1
            if self.decisions == 1:
                raise ValueError("malformed provider output")
            return MockContinueDecision(action="stop", stop_reason="user_abandons")

    mock = RetryMock()
    live = _live(_MultiLive, mock)
    ctx = TraceContext(project_id="demo", case_id="case-retry", multi_turn=True)

    output = live.execute_live(
        {"query": "turn-1"},
        ctx,
        MockIntentOutput(user_intent="try once", query="turn-1"),
    )

    assert output == {"answer": "turn-1"}
    assert mock.decisions == 2
    assert ctx.stop_reason == "user_abandons"


def test_goal_satisfied_is_rejected_when_latest_output_has_no_business_evidence():
    class EmptyLive(_MultiLive):
        def extract_output(self, raw_response):
            return {
                "robot_text": "",
                "stage": "unknown",
                "event_summary": {"protocol_completed": False, "business_completed": False},
                "card_summary": [],
            }

    class PrematureStopMock(_MultiMock):
        def decide_next_action(self, intent, accumulated):
            return MockContinueDecision(action="stop", stop_reason="goal_satisfied")

    live = _live(EmptyLive, PrematureStopMock())
    ctx = TraceContext(project_id="demo", case_id="case-empty", multi_turn=True)

    output = live.execute_live(
        {"query": "turn-1"},
        ctx,
        MockIntentOutput(user_intent="get a plan", query="turn-1"),
    )

    assert output["stage"] == "unknown"
    assert ctx.stop_reason == "perceived_no_progress"
    assert ctx.completion_status == "completed"


def test_request_validation_failure_produces_error_trace_not_success():
    live = _live(_SingleLive, _SingleMock(), request_ok=False)
    case = SingleTurnCase(
        id="case-1",
        input={"query": "hello"},
        user_intent="answer the question",
        scenario="single",
    )

    trace = trace_from_live(live, case)

    assert trace.status == "error"
    assert trace.extracted_output == {}
    assert trace.completion_status == "failed"
    assert trace.turn_records
    assert trace.turn_records[0]["call_status"] == "failed"
    assert "request check failed" in (trace.error or "")


def test_multi_turn_infers_optional_intent_from_request_schema_input():
    mock = _MultiMock()
    live = _live(_MultiLive, mock)
    ctx = TraceContext(project_id="demo", case_id="case-inferred", multi_turn=True)

    output = live.execute_live({"query": "turn-1"}, ctx)

    assert output == {"answer": "turn-2"}
    assert mock.inferred == 1
    assert ctx.intent == MockIntentOutput(user_intent="inferred", query="turn-1")


def test_request_shaped_case_does_not_generate_or_replace_its_intent():
    mock = _SingleMock()
    live = _live(_SingleLive, mock)
    case = SingleTurnCase(
        id="case-1",
        input={"query": "authoritative-query"},
        output={"answer": "evaluation-only"},
        reference={"answer": "reference-only"},
        scenario="single",
    )

    trace = trace_from_live(live, case)

    assert mock.generated_intents == 0
    assert trace.input == {"query": "authoritative-query"}
    assert trace.normalized_request == {"query": "authoritative-query"}
    assert trace.extracted_output == {"answer": "authoritative-query"}


def test_output_validation_failure_is_not_hidden_by_fallback_output():
    live = _live(_SingleLive, _SingleMock(), output_ok=False)
    ctx = TraceContext(project_id="demo", case_id="case-1")
    intent = MockIntentOutput(user_intent="answer", query="hello")

    with pytest.raises(ValueError, match="output check failed"):
        live.execute_live({"query": "hello"}, ctx, intent)

    assert ctx.completion_status == "failed"
    assert ctx.turns[-1]["call_status"] == "failed"


def test_multi_turn_controller_decision_error_preserves_last_business_output():
    class BrokenDecisionMock(_MultiMock):
        def decide_next_action(self, intent, accumulated):
            raise ValueError("mock clock context missing")

    live = _live(_MultiLive, BrokenDecisionMock())
    ctx = TraceContext(project_id="demo", case_id="case-controller-error", multi_turn=True)

    output = live.execute_live(
        {"query": "turn-1"},
        ctx,
        MockIntentOutput(user_intent="get a plan", query="turn-1"),
    )

    assert output == {"answer": "turn-1"}
    assert ctx.stop_reason == "decision_error"
    assert ctx.completion_status == "incomplete"
    assert ctx.final_output_turn == 1
    assert ctx.interaction_controller_status == "error"
    assert ctx.interaction_controller_error == "mock clock context missing"
    assert ctx.turns[-1]["call_status"] == "succeeded"


def test_trace_keeps_controller_error_separate_from_business_execution_status():
    class BrokenDecisionMock(_MultiMock):
        def decide_next_action(self, intent, accumulated):
            raise RuntimeError("controller provider unavailable")

    live = _live(_MultiLive, BrokenDecisionMock())
    case = SingleTurnCase(
        id="case-controller-trace",
        input={"query": "turn-1"},
        user_intent="get a plan",
        scenario="multi",
    )

    trace = trace_from_live(live, case)

    assert trace.status == "ok"
    assert trace.error in (None, "")
    assert trace.extracted_output == {"answer": "turn-1"}
    assert trace.completion_status == "incomplete"
    assert trace.stop_reason == "decision_error"
    assert trace.interaction_controller_status == "error"
    assert trace.interaction_controller_error == "controller provider unavailable"


def test_invalid_next_request_is_recorded_as_controller_error():
    class InvalidRequestMock(_MultiMock):
        def decide_next_action(self, intent, accumulated):
            return MockContinueDecision(action="continue")

        def build_next_request(self, intent, accumulated):
            return {}

    live = _live(_MultiLive, InvalidRequestMock())
    ctx = TraceContext(project_id="demo", case_id="case-invalid-next-request", multi_turn=True)

    output = live.execute_live(
        {"query": "turn-1"},
        ctx,
        MockIntentOutput(user_intent="get a plan", query="turn-1"),
    )

    assert output == {"answer": "turn-1"}
    assert ctx.stop_reason == "request_build_error"
    assert ctx.completion_status == "incomplete"
    assert ctx.interaction_controller_status == "error"
    assert "empty or invalid request" in ctx.interaction_controller_error


def test_chat_request_shape_mapping_preserves_the_generated_user_query():
    mapped = MockAgent._preserve_chat_user_query(
        {
            "input": {
                "messages": [
                    {"role": "system", "content": "runtime context"},
                    {"role": "user", "content": "invented rewrite"},
                ]
            },
            "config": {"configurable": {}},
        },
        "the user-authored request",
    )

    assert mapped["input"]["messages"][-1]["content"] == "the user-authored request"


def test_business_context_is_used_only_for_open_ended_intent_generation(monkeypatch):
    spec = ProjectSpec(project_id="demo", name="demo", description="demo product")
    agent = MockAgent(spec, llm=object())
    monkeypatch.setattr(agent, "_mandatory_context", lambda: {"content": "DOMAIN CONTRACT"})

    open_prompt = agent._intent_system_prompt(MockBuildSpec(project_id="demo", scenario="planning"))
    fixed_prompt = agent._intent_system_prompt(
        MockBuildSpec(
            project_id="demo",
            scenario="planning",
            requested_intent="the caller's fixed goal",
        )
    )

    assert "DOMAIN CONTRACT" in open_prompt
    assert "DOMAIN CONTRACT" not in fixed_prompt
    assert "requested_intent 是调用方已经确定的具体用户目标" in fixed_prompt


def test_fixed_intent_fidelity_failure_does_not_release_unreviewed_query():
    class FidelityFailureLlm:
        calls = 0

        def complete_json(self, system, _user, **_kwargs):
            self.calls += 1
            if "语义保真编辑器" in system:
                return {"error": "review unavailable"}
            return {"query": "an unsupported specific query", "user_intent": "changed intent"}

    llm = FidelityFailureLlm()
    agent = MockAgent(
        ProjectSpec(project_id="demo", name="demo", description="demo product"),
        llm=llm,
    )
    result = agent.build(
        MockBuildSpec(
            project_id="demo",
            scenario="planning",
            requested_intent="the caller's fixed goal",
        )
    )

    assert result.query == ""
    assert result.metadata["error"] == "fidelity_error:review unavailable"
    assert llm.calls == 2
