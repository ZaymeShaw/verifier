"""llm_probe Mock：fixture 为主，动态生成只产信封形状。

SessionTranslator（spec/mock/protocol.md 6.1）：原话 ↔ 信封的确定性互转。
原话写进 capability mock_body 模板的 `{query}` 槽位，会话身份写进 `{session_id}` 槽位。
`{query}` 位于消息数组（OpenAI 式 [{role, content}]）时，按接口约定由调用方带历史：
本会话此前各轮的原话与被测服务的实际答复依次写在本轮原话之前；
不在消息数组里的模板没有历史字段，历史由被测服务按 session_id 自己记。
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from impl.core.mock_protocol import ProjectMock
from impl.core.session import SessionState, SessionTranslator, UserMessage
from impl.projects.llm_probe_loop.capability import (
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
            messages = _message_list(path)
            if messages is None:
                slot_set(body, path, message.text)
            else:
                slot_set(body, messages, _history(state.transcript) + [{"role": "user", "content": message.text}])
        for path in slots["session_id"]:
            slot_set(body, path, state.session_id)
        # 沿用的首轮信封里请求标识已落成具体值；每轮放回占位符，发送时由 fresh_delivery_placeholders 换新，
        # 否则多轮共用一个请求标识，按它关联 trace 的 provider 会撞号。
        for path in slots["request_id"]:
            slot_set(body, path, "{request_id}")
        return envelope

    def user_message_from_request(self, request: Dict[str, Any]) -> UserMessage:
        ref = str(request.get("capability_ref") or "").strip() or default_capability_ref()
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        path = template_slots(ref)["query"][0]
        messages = _message_list(path)
        if messages is None:
            text = slot_get(body, path)
        else:
            items = slot_get(body, messages)
            text = items[-1].get("content") if isinstance(items, list) and items and isinstance(items[-1], dict) else None
        return UserMessage(type="text", text=str(text or ""))

    def extract_mock_message(self, request: Dict[str, Any]) -> str:
        return self.user_message_from_request(request).text


def _message_list(path: tuple) -> Optional[tuple]:
    """`{query}` 在 [..., <数组>, i, "content"] 位置时返回该消息数组的路径。"""
    return path[:-2] if len(path) >= 2 and path[-1] == "content" and isinstance(path[-2], int) else None


def _answer_text(entry: Dict[str, Any]) -> str:
    """被测服务实际返回给用户的答复正文；transcript 前缀条目直接带 content。"""
    output = entry.get("extracted_output")
    if not isinstance(output, dict):
        return str(entry.get("content") or "")
    text = str(output.get("output_text") or "")
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    # 业务报错、繁忙、答非所问等都原样进历史；没有 answer 字段时带整个返回体，不丢这一轮。
    return str(payload["answer"] or "") if isinstance(payload, dict) and "answer" in payload else text


def _history(transcript: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    history = []
    for entry in transcript:
        role = entry.get("role")
        text = str(entry.get("content") or "") if role == "user" else _answer_text(entry) if role == "assistant" else ""
        if text.strip():
            history.append({"role": role, "content": text})
    return history
