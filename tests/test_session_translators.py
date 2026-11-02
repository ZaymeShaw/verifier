"""spec/mock/protocol.md 6.1/6.2：多轮项目的 SessionTranslator 契约与三道自动约束。"""
from __future__ import annotations

import pytest

from impl.core.project_loader import load_adapter, load_project
from impl.core.session import SessionState, SessionTranslator, UserMessage
from scripts.check_adapter_compliance import check_session_translator

MULTI_TURN_PROJECTS = ["policy_search", "marketting-planning", "deerflow"]


@pytest.mark.parametrize("project_id", MULTI_TURN_PROJECTS)
def test_multi_turn_projects_implement_translator(project_id: str) -> None:
    mock = load_adapter(load_project(project_id)).mock()
    assert isinstance(mock, SessionTranslator)
    assert isinstance(mock.supports_history_injection, bool)


@pytest.mark.parametrize("project_id", MULTI_TURN_PROJECTS + ["llm_probe"])
def test_translator_satisfies_protocol_constraints(project_id: str) -> None:
    assert check_session_translator(project_id) == []


def test_llm_probe_translator_fills_template_slots_and_keeps_identity() -> None:
    """单轮项目也可带翻译函数：原话进 {query} 槽，会话身份进 {session_id} 槽，其余沿用首轮信封。"""
    mock = load_adapter(load_project("llm_probe")).mock()
    first_request = {
        "capability_ref": "insurance-agno-e2e",
        "method": "POST",
        "body": {
            "session_id": "{session_id}",
            "user_id": "EMP000006",
            "empno": "EMP000006",
            "agentno": "EMP000006",
            "stream": False,
            "messages": [{"role": "user", "content": "皮奕辰名下有哪些保单？"}],
        },
    }
    state = SessionState(session_id="replay-ctx-ref-abc", turn_index=1, transcript=[], last_request=first_request)
    turn1 = mock.request_from_user_message(UserMessage(type="text", text="皮奕辰名下有哪些保单？"), state)
    assert turn1["body"]["session_id"] == "replay-ctx-ref-abc"
    assert turn1["body"]["user_id"] == "EMP000006"
    assert turn1["body"]["messages"] == [{"role": "user", "content": "皮奕辰名下有哪些保单？"}]
    assert mock.user_message_from_request(turn1).text == "皮奕辰名下有哪些保单？"

    state2 = SessionState(session_id="replay-ctx-ref-abc", turn_index=2, transcript=[], last_request=turn1)
    turn2 = mock.request_from_user_message(UserMessage(type="text", text="这张保单的被保人是谁？"), state2)
    assert turn2["body"]["session_id"] == "replay-ctx-ref-abc"
    assert turn2["body"]["empno"] == "EMP000006"
    assert turn2["body"]["messages"][-1]["content"] == "这张保单的被保人是谁？"


def test_llm_probe_translator_resets_request_id_each_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """多轮沿用首轮信封时，请求标识槽每轮放回占位符；发送前各自换成新值，会话身份不变。"""
    from impl.projects.llm_probe import capability

    template = {"session_id": "{session_id}", "trace_id": "{request_id}", "messages": [{"role": "user", "content": "{query}"}]}
    monkeypatch.setattr(capability, "load_capability_map", lambda: {"lf": {"mock_body": template}})
    mock = load_adapter(load_project("llm_probe")).mock()
    sent_first = capability.fresh_delivery_placeholders(
        {"session_id": "s-1", "trace_id": "{request_id}", "messages": [{"role": "user", "content": "q1"}]})
    first_request = {"capability_ref": "lf", "method": "POST", "body": sent_first}
    state = SessionState(session_id="s-1", turn_index=2, transcript=[], last_request=first_request)
    turn2 = mock.request_from_user_message(UserMessage(type="text", text="q2"), state)
    assert turn2["body"]["trace_id"] == "{request_id}"
    assert turn2["body"]["session_id"] == "s-1"
    sent_second = capability.fresh_delivery_placeholders(turn2["body"])
    assert sent_second["trace_id"].startswith("llm-probe-req-") and sent_second["trace_id"] != sent_first["trace_id"]

def test_compliance_check_flags_broken_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    from impl.projects.policy_search.mock import PolicySearchMock

    monkeypatch.setattr(
        PolicySearchMock,
        "user_message_from_request",
        lambda self, request: UserMessage(type="text", text="改写过的原话"),
    )
    violations = check_session_translator("policy_search")
    assert any("往返不变式" in reason for _, _, reason in violations)


def test_compliance_check_flags_llm_use(monkeypatch: pytest.MonkeyPatch) -> None:
    from impl.projects.deerflow.mock_base import DeerflowMockBase

    original = DeerflowMockBase.request_from_user_message

    def with_llm(self, message, state):
        from impl.core.llm_client import LlmClient

        LlmClient()
        return original(self, message, state)

    monkeypatch.setattr(DeerflowMockBase, "request_from_user_message", with_llm)
    violations = check_session_translator("deerflow")
    assert any("禁 LLM" in reason for _, _, reason in violations)


def test_policy_search_translator_injects_history_from_transcript() -> None:
    mock = load_adapter(load_project("policy_search")).mock()
    first = mock.request_from_user_message(
        UserMessage(type="text", text="保额的保单"),
        SessionState(session_id="s1", turn_index=1, transcript=[], last_request=None),
    )
    assert first["session_id"] == "s1"
    assert first["trace_id"] == "s1-turn1"
    assert first["extra_input_params"]["args"]["contexts"] == []
    second = mock.request_from_user_message(
        UserMessage(type="text", text="50万以上"),
        SessionState(
            session_id="s1",
            turn_index=2,
            transcript=[
                {"role": "user", "content": "保额的保单", "request": first},
                {"role": "assistant", "content": "status=UNSUPPORTED", "extracted_output": {"message": "请补充金额"}},
            ],
            last_request=first,
        ),
    )
    assert second["trace_id"] == "s1-turn2"
    assert second["extra_input_params"]["policySearchParseArgs"]["query"] == "50万以上"
    assert second["extra_input_params"]["args"]["contexts"] == [
        {"role": "user", "content": "保额的保单", "sub_agent": ""},
        {"role": "assistant", "content": "请补充金额", "sub_agent": "POLICY_SEARCH"},
    ]


def test_deerflow_translator_inherits_thread_id() -> None:
    mock = load_adapter(load_project("deerflow")).mock()
    request = mock.request_from_user_message(
        UserMessage(type="text", text="继续"),
        SessionState(
            session_id="s1",
            turn_index=2,
            transcript=[
                {"role": "user", "content": "开始"},
                {"role": "assistant", "content": "ok", "extracted_output": {"session_summary": {"thread_id": "t-42"}}},
            ],
            last_request={"input": {"messages": []}, "config": {"configurable": {"thread_id": ""}}},
        ),
    )
    assert request == {
        "input": {"messages": [{"role": "user", "content": "继续"}]},
        "config": {"configurable": {"thread_id": "t-42"}},
    }
