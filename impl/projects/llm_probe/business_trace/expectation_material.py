"""需求侧白名单投影：本轮产出与系统设计声明不能进入 y_need。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .reader import redact


def _content(value: Any) -> Any:
    """Keep the recorded content verbatim, not its transport envelope."""
    if (isinstance(value, str) and value.strip()) or (isinstance(value, list) and value):
        return value
    return None


def _request_material(request: Any) -> tuple[Any, list[tuple[int, Mapping]]]:
    """Only the outer business request establishes user/history provenance."""
    if not isinstance(request, Mapping):
        return _content(request), []
    body = request.get('body') if isinstance(request.get('body'), Mapping) else request
    # DashScope 形状在 input.messages，其余在 messages（与 knowledge_loop.extract.user_turns 同一口径）。
    nested = body.get('input') if isinstance(body.get('input'), Mapping) else {}
    messages = body.get('messages') or nested.get('messages') or []
    users = [i for i, m in enumerate(messages) if isinstance(m, Mapping) and m.get('role') == 'user']
    if users:
        current = users[-1]
        history = [(i, m) for i, m in enumerate(messages[:current])
                   if isinstance(m, Mapping) and m.get('role') in {'user', 'assistant'}
                   and _content(m.get('content')) is not None and not m.get('tool_calls')]
        return _content(messages[current].get('content')), history
    # 不是对话消息形状：整份请求体就是用户这一轮发来的东西，原样作为用户原话，不猜字段名
    # （spec/alg/expectations.md §2.1）。空字段去掉，免得噪声。
    payload = {k: v for k, v in body.items() if v not in (None, '', [], {})}
    return (payload or None), []


def project_requirements(trace: Any, scenario: Mapping[str, Any] | None = None) -> dict:
    sources, missing = [], []

    def add(ref, side, turn, component, value, *, trace_refs=()):
        if value is None or value == '':
            return
        sources.append(dict(id=ref, side=side, turn=turn, component=component,
                            value=redact(value), scope='request', trace_refs=list(trace_refs)))

    turns = getattr(trace, 'turn_records', None) or [dict(
        request=getattr(trace, 'normalized_request', None),
        project_fields=getattr(trace, 'project_fields', None) or {})]
    for n, turn in enumerate(turns, 1):
        tid = f't{n}'
        snapshot = (turn.get('project_fields') or {}).get('business_trace') or {}
        records = snapshot.get('records') or {}
        calls = records.get('calls') or []
        value, history_messages = _request_material(turn.get('mock_message') or turn.get('request'))
        source_ref = f'{tid}.request'
        for i, message in history_messages:
            add(f'{tid}.history.{i}', 'history', tid, 'history',
                {'role': message['role'], 'content': message['content']}, trace_refs=[source_ref])
        # Agno's registered adapter records the associated outer run input and
        # explicitly orders history. A gateway model call has neither guarantee.
        run = records.get('run') or {}
        current_id = run.get('run_id')
        associated_id = (snapshot.get('association') or {}).get('run_id')
        if (snapshot.get('provider') == 'agno' and snapshot.get('status') != 'failed'
                and (not associated_id or associated_id == current_id)):
            if value is None:
                raw = run.get('run_input')
                value = _content(raw.get('input_content') if isinstance(raw, Mapping) else raw)
                source_ref = f'turn{n}/records/run'
            for i, history in enumerate(records.get('history_runs') or []):
                if (not current_id or not history.get('run_id') or history['run_id'] == current_id
                        or history.get('ordering') not in {'trace_timestamps', 'created_at_plus_duration'}):
                    continue
                for field, role in [('run_input', 'user'), ('content', 'assistant')]:
                    raw = history.get(field)
                    if field == 'run_input' and isinstance(raw, Mapping):
                        raw = raw.get('input_content')
                    if _content(raw) is not None:
                        add(f'{tid}.history.{i}.{role}', 'history', tid, 'history',
                            {'role': role, 'content': raw}, trace_refs=[f'turn{n}/records/history_runs/{i}'])
        if value is None:
            missing.append(dict(turn=tid, component='user', reason='用户原文未独立记录'))
            continue
        # Model role/position never supplies an original or proves prior history.
        # It only links an independently recorded original to identical input.
        first = (calls[0].get('pre') or {}) if calls else {}
        matching = [f'{tid}.c1.m{i + 1}' for i, message in enumerate(first.get('messages') or [])
                    if isinstance(message, Mapping) and message.get('role') == 'user'
                    and message.get('content') == value and not message.get('tool_calls')]
        add(f'{tid}.user', 'want', tid, 'user', value, trace_refs=[source_ref, *matching])
    # Description is context, never an independent requirement source.
    for key, side in [('description', 'background'), ('criterion', 'want')]:
        value = (scenario or {}).get(key)
        if isinstance(value, str) and value.strip():
            add(f'scenario.{key}', side, 'case', key, value)
    # The mixed legacy field must be split by its maintainer, not by the model.
    if (scenario or {}).get('capability'):
        missing.append(dict(turn='case', component='capability', reason='capability 未拆分'))
    # downstream is deliberately not read while its implementation is deferred.
    body = {'sources': sources, 'missing': missing}
    body['sha256'] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return body
