"""需求侧投影：只复制白名单声明/用户原文，不把运行记录交给 e。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .reader import redact


def project_requirements(trace: Any, scenario: Mapping[str, Any] | None = None) -> dict:
    sources, missing = [], []

    def add(ref, side, turn, component, value, *, scope='request', trace_refs=()):
        if value is None or value == '':
            return
        sources.append(dict(id=ref, side=side, turn=turn, component=component,
                            value=redact(value), scope=scope, trace_refs=list(trace_refs)))

    def definitions(node, path, turn):
        if isinstance(node, list):
            for i, item in enumerate(node):
                definitions(item, f'{path}/{i}', turn)
        elif isinstance(node, Mapping):
            # Copy individual declaration fields, never an arbitrary definition subtree.
            scope = 'observed_at_collection_not_verified_run_version'
            if 'name' in node and 'parameters' in node:
                add(path, 'commitment', turn, 'tools',
                    {k: node[k] for k in ('name', 'description', 'parameters', 'returns') if k in node},
                    scope=scope, trace_refs=[path])
            for key, component in [('system_message', 'system'), ('output_schema', 'format'),
                                   ('response_format', 'format')]:
                if key in node:
                    add(f'{path}/{key}', 'commitment', turn, component, node[key], scope=scope,
                        trace_refs=[path])
            # Templates are registered by the adapter; filled instances are never read.
            for i, template in enumerate(node.get('instruction_templates') or []):
                if isinstance(template, Mapping) and isinstance(template.get('template'), str):
                    add(f'{path}/instruction_templates/{i}', 'commitment', turn, 'system',
                        template['template'], scope=scope, trace_refs=[path])
            for key, value in node.items():
                if key not in {'system_message', 'instruction_templates', 'parameters', 'output_schema',
                               'response_format', 'description', 'returns'} and isinstance(value, (dict, list)):
                    definitions(value, f'{path}/{key}', turn)

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
                if current_id and history.get('run_id') == current_id:
                    continue
                for field, role in [('run_input', 'user'), ('content', 'assistant')]:
                    value = history.get(field)
                    if isinstance(value, str) and value.strip():
                        add(f'{tid}.history.{i}.{role}', 'history', tid, 'history',
                            {'role': role, 'content': value}, trace_refs=[f'turn{n}/records/history_runs/{i}'])
        first = (calls[0].get('pre') or {}) if calls else {}
        messages = first.get('messages') or []
        # The first request is the boundary before this turn's model/tool outputs.
        # Only user/assistant dialogue before the last user is history; never tool messages.
        users = [i for i, m in enumerate(messages) if m.get('role') == 'user']
        if users:
            current = users[-1]
            for i, m in enumerate(messages[:current]):
                if m.get('role') in {'user', 'assistant'} and m.get('content') and not m.get('tool_calls'):
                    add(f'{tid}.history.{i}', 'history', tid, 'history',
                        {'role': m['role'], 'content': m['content']})
            add(f'{tid}.user', 'want', tid, 'user', messages[current].get('content'),
                trace_refs=[f'{tid}.c1.m{current + 1}'])
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
        definitions(records.get('definitions') or [], f'turn{n}/records/definitions', tid)
        if calls:
            # Typed API declarations are separate from interpolated system messages.
            tools = first.get('tools')
            if tools is None:
                tools = (first.get('optional_params') or {}).get('tools')
            if tools == []:
                add(f'{tid}.tools', 'commitment', tid, 'tools', [], trace_refs=[f'{tid}.c1.tools'])
            if tools is not None:
                for i, tool in enumerate(tools if isinstance(tools, list) else [tools]):
                    add(f'{tid}.tools.{i}', 'commitment', tid, 'tools', tool,
                        trace_refs=[f'{tid}.c1.tools'])
            params = first.get('optional_params') or {}
            if 'response_format' in params:
                add(f'{tid}.format', 'commitment', tid, 'format', params['response_format'],
                    trace_refs=[f'{tid}.c1.params'])
            # No declared template provenance: fail closed. A system role does not
            # prove that its content is free of Direct/tool outcomes interpolated upstream.
            if any(m.get('role') == 'system' for m in messages) and not any(
                    s['turn'] == tid and s['component'] == 'system' for s in sources):
                missing.append(dict(turn=tid, component='system', reason='只有运行时 system 消息，未独立登记规则模板'))
        for component in ('system', 'tools', 'format'):
            if not any(s['turn'] == tid and s['component'] == component for s in sources) and not any(
                    m['turn'] == tid and m['component'] == component for m in missing):
                missing.append(dict(turn=tid, component=component, reason='声明未采集；不能由运行结果反推'))
    # Scenario declarations do not depend on which consumers are enabled.
    # Never include capability/caller-stated abilities or expected/actual answers here.
    for key in ('description', 'criterion'):
        value = (scenario or {}).get(key)
        if isinstance(value, str) and value.strip():
            add(f'scenario.{key}', 'want', 'case', 'criterion', value)
    body = {'sources': sources, 'missing': missing}
    body['sha256'] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return body
