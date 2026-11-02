"""需求侧白名单投影：本轮产出与系统设计声明不能进入 y_need。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .reader import redact


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
        if not calls:
            current_id = (records.get('run') or {}).get('run_id')
            for i, history in enumerate(records.get('history_runs') or []):
                # Unidentified records cannot prove that content predates this run.
                if not current_id or not history.get('run_id') or history['run_id'] == current_id:
                    continue
                for field, role in [('run_input', 'user'), ('content', 'assistant')]:
                    value = history.get(field)
                    if isinstance(value, str) and value.strip():
                        add(f'{tid}.history.{i}.{role}', 'history', tid, 'history',
                            {'role': role, 'content': value}, trace_refs=[f'turn{n}/records/history_runs/{i}'])
        first = (calls[0].get('pre') or {}) if calls else {}
        messages = first.get('messages') or []
        # Only the first model request is eligible, before this turn's outputs.
        users = [i for i, m in enumerate(messages) if m.get('role') == 'user']
        if users:
            current = users[-1]
            for i, m in enumerate(messages[:current]):
                if m.get('role') in {'user', 'assistant'} and m.get('content') and not m.get('tool_calls'):
                    add(f'{tid}.history.{i}', 'history', tid, 'history',
                        {'role': m['role'], 'content': m['content']})
            value = messages[current].get('content')
            if value:
                add(f'{tid}.user', 'want', tid, 'user', value,
                    trace_refs=[f'{tid}.c1.m{current + 1}'])
            else:
                missing.append(dict(turn=tid, component='user', reason='用户原文未独立记录'))
        else:
            request = turn.get('mock_message') or turn.get('request') or {}
            if isinstance(request, Mapping):
                body = request.get('body') if isinstance(request.get('body'), Mapping) else request
                request = body.get('message') or body.get('query') or body.get('input')
            if not request:
                request = (records.get('run') or {}).get('run_input')
            if isinstance(request, str) and request.strip():
                add(f'{tid}.user', 'want', tid, 'user', request, trace_refs=[f'turn{n}'])
            else:
                missing.append(dict(turn=tid, component='user', reason='用户原文未独立记录'))
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
