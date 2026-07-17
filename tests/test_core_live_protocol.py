from __future__ import annotations

from typing import Any

import pytest

from impl.core.live_protocol import MultiTurnInteractiveLive, RealServiceLive, SingleTurnLive
from impl.core.schema import MockIntentOutput, ProjectSpec, SingleTurnCase
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

    def build_live_request(self, intent: MockIntentOutput) -> dict[str, Any]:
        if intent.live_request is not None:
            return dict(intent.live_request)
        return {"query": intent.query}


class _MultiMock:
    def __init__(self):
        self.index = 0

    def build_next_request(self, intent: MockIntentOutput, accumulated: dict | None) -> dict[str, Any]:
        self.index += 1
        return {"query": f"turn-{self.index}"}

    def max_turns(self) -> int:
        return 3

    def should_stop(self, transcript: list[dict], last_result: Any) -> bool:
        return self.index >= 2


class _Adapter:
    def __init__(self, mock: Any):
        self._mock = mock

    def mock(self) -> Any:
        return self._mock


class _SingleLive(RealServiceLive, SingleTurnLive):
    def deliver_real(self, request: dict[str, Any]) -> Any:
        return {"answer": request.get("query")}


class _MultiLive(RealServiceLive, MultiTurnInteractiveLive):
    def deliver_real(self, request: dict[str, Any]) -> Any:
        return {"answer": request.get("query")}


def _spec() -> ProjectSpec:
    return ProjectSpec(project_id="demo", name="demo", common={"ready": []}, root="/missing")


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

    output = live.execute_live(intent, ctx)

    assert output == {"answer": "turn-2"}
    assert [turn["extracted_output"] for turn in ctx.turns] == [
        {"answer": "turn-1"},
        {"answer": "turn-2"},
    ]
    assert ctx.final_output_turn == 2
    assert ctx.stop_reason == "mock_should_stop"
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
        live.execute_live(intent, ctx)

    assert ctx.completion_status == "failed"
    assert ctx.turns[-1]["call_status"] == "failed"
