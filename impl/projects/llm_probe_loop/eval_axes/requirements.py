"""需求侧材料按轮切分、用户各轮原话（从 llm_probe 的需求轴与说法抽取搬来，口径不变）。"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def turn_materials(material: dict) -> list[tuple[str, dict]]:
    """每轮一份需求材料（spec/alg/expectations.md §2.1）：本轮用户原话 + 本轮请求里的历史，看不到后面的轮次。
    场景对需求轴的描述不在这里：框架按本轴描述槽位放进每一份（spec/alg/axis_loop.md §2.5）。"""
    turns = sorted({s['turn'] for s in material['sources']}, key=lambda t: int(t[1:])) or ['t1']
    out = []
    for turn in turns:
        body = {'sources': [s for s in material['sources'] if s['turn'] == turn],
                'missing': [m for m in material['missing'] if m['turn'] == turn]}
        body['sha256'] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        out.append((turn, body))
    return out


def user_turns(trace: Any) -> list[str]:
    """用户各轮原话，按先后排列。多轮时 normalized_request 只是第一轮，后面的更正、追问在对话记录里；
    没有对话记录时取请求体里的用户消息（DashScope 形状在 input.messages，其余在 messages）。"""
    turns = [str(m.get('query') or m.get('content') or '') for m in getattr(trace, 'conversation_transcript', None) or []
             if isinstance(m, Mapping) and m.get('role') == 'user']
    if turns:
        return turns
    body = (getattr(trace, 'normalized_request', None) or {}).get('body') or {}
    messages = (body.get('input') or {}).get('messages') if isinstance(body.get('input'), Mapping) else body.get('messages')
    return [str(m.get('content') or '') for m in messages or [] if isinstance(m, Mapping) and m.get('role') == 'user']
