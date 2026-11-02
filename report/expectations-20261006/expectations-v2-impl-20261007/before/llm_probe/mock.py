"""llm_probe Mock：fixture 为主，动态生成只产信封形状。

SessionTranslator（spec/mock/protocol.md 6.1）：原话 ↔ 信封的确定性互转。
原话写进 capability mock_body 模板的 `{query}` 槽位，会话身份写进 `{session_id}` 槽位；
历史由被测服务按 session_id 自己记，不注入请求体。
"""
from __future__ import annotations

import copy
from typing import Any, Dict

from impl.core.mock_protocol import ProjectMock
from impl.core.session import SessionState, SessionTranslator, UserMessage
from impl.projects.llm_probe.capability import (
    default_capability_ref,
    load_capability_map,
    mock_body,
    slot_get,
    slot_set,
    template_slots,
)


class LlmProbeMock(SessionTranslator, ProjectMock):
    supports_history_injection = False

    def build_user_intent(self, scenario: str):
        from impl.core.mock_agent import MockAgent, build_spec_from_project

        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_initial_request(self, intent) -> Dict[str, Any]:
        query = str(getattr(intent, "query", "") or "").strip()
        if not query:
            raise ValueError("llm_probe mock case 缺少可见 query；不得用私有 user_intent 补业务请求")
        mapping = load_capability_map()
        ref = str(getattr(intent, "scenario", "") or "").strip()
        if ref not in mapping:
            ref = default_capability_ref()
        return {
            "body": mock_body(ref, query),
            "method": "POST",
            "capability_ref": ref,
        }

    # --- SessionTranslator ---

    def request_from_user_message(self, message: UserMessage, state: SessionState) -> Dict[str, Any]:
        if message.type != "text":
            raise ValueError("llm_probe 只接受 text 消息；结构化动作请用 protocol-fuzz 发原始请求体")
        if state.last_request:
            # 同一会话沿用首轮信封（身份、capability、固定字段），只换原话与会话身份。
            envelope = copy.deepcopy(state.last_request)
            ref = str(envelope.get("capability_ref") or "").strip() or default_capability_ref()
        else:
            ref = default_capability_ref()
            envelope = {"body": mock_body(ref, message.text), "method": "POST", "capability_ref": ref}
        slots = template_slots(ref)
        body = envelope.setdefault("body", {})
        for path in slots["query"]:
            slot_set(body, path, message.text)
        for path in slots["session_id"]:
            slot_set(body, path, state.session_id)
        return envelope

    def user_message_from_request(self, request: Dict[str, Any]) -> UserMessage:
        ref = str(request.get("capability_ref") or "").strip() or default_capability_ref()
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        text = slot_get(body, template_slots(ref)["query"][0])
        return UserMessage(type="text", text=str(text or ""))

    def extract_mock_message(self, request: Dict[str, Any]) -> str:
        return self.user_message_from_request(request).text
