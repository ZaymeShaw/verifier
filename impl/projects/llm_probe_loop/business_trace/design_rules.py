"""Deterministic original-block inventory, not rule extraction or applicability judgment.

Pointers address expanded record values (JSON transport envelopes are decoded).
Structured units retain deterministic JSON; string units retain verbatim text.
The system component denotes candidate message sources, including tool DATA,
not a normative-rule classification. Message roles remain available for judgment.
An inventory receipt is not proof that every semantic rule was checked.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .dossier import expand_content, resolve_node_path
from .materials import _supporting_definitions

COLLECTION = 'observed_at_collection_not_verified_run_version'
_FORMAT = {'response_format', 'output_schema', 'response_settings', 'input_schema'}
_SYSTEM = {'system_message', 'instructions', 'instruction_templates'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


def _decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def quote_text(block, path=''):
    """Resolve a quote using the dossier path convention; root is original text."""
    if not path:
        return block['text']
    value = resolve_node_path(json.loads(block['text']), path)
    return value if isinstance(value, str) else _json(value)


class _Blocks:
    def __init__(self):
        self.rows = {}

    def add(self, ref, path, value, component, scope, link_id=None, tool=None, role=None):
        if value is None:
            return
        text = value if isinstance(value, str) else _json(value)
        identity = [ref, path, component, scope, tool, role, text]
        ident = 'design:' + hashlib.sha256(_json(identity).encode()).hexdigest()
        row = self.rows.setdefault(ident, dict(id=ident, ref=ref, path=path, text=text,
                                               component=component, scope=scope))
        if role:
            row['role'] = role
        if tool:
            row['tool'] = tool
        if link_id is not None:
            ids = row.setdefault('link_ids', [])
            if link_id not in ids:
                ids.append(link_id)
        # Only actual format fields are additional units. The whole parent keeps
        # required/conditional/combinator constraints; messages and tools stay whole.
        if component == 'format':
            self.format_fields(ref, path, value, scope, link_id)

    def format_fields(self, ref, path, value, scope, link_id):
        if not isinstance(value, Mapping):
            return
        for key, child in sorted(value.items()):
            sub = _pointer(path, key)
            if key in {'properties', 'patternProperties', '$defs', 'definitions'} and isinstance(child, Mapping):
                for name, schema in sorted(child.items()):
                    self.add(ref, _pointer(sub, name), schema, 'format', scope, link_id)
            elif key in {'schema', 'json_schema', 'items', 'additionalProperties', 'if', 'then', 'else', 'not', 'contains'}:
                self.format_fields(ref, sub, child, scope, link_id)
            elif key in {'allOf', 'anyOf', 'oneOf', 'prefixItems'} and isinstance(child, list):
                for i, schema in enumerate(child):
                    self.format_fields(ref, _pointer(sub, i), schema, scope, link_id)

    def tools(self, ref, path, value, scope, link_id=None):
        value = _decode(value)
        tools = list(enumerate(value)) if isinstance(value, list) else [(None, value)]
        for index, tool in tools:
            tool = _decode(tool)
            function = tool.get('function', tool) if isinstance(tool, Mapping) else {}
            name = function.get('name') if isinstance(function, Mapping) else None
            self.add(ref, _pointer(path, index) if index is not None else path,
                     tool, 'tools', scope, link_id, name)

    def declarations(self, ref, path, node, scope, link_id=None):
        """Walk declaration trees only; never call this on arbitrary runtime records."""
        if isinstance(node, list):
            for i, child in enumerate(node):
                self.declarations(ref, _pointer(path, i), child, scope, link_id)
        elif isinstance(node, Mapping):
            function = node.get('function', node)
            if isinstance(function, Mapping) and 'name' in function and 'parameters' in function:
                self.tools(ref, path, node, scope, link_id)
                return
            for key, child in node.items():
                sub = _pointer(path, key)
                if key == 'instruction_templates':
                    self.templates(ref, sub, child, scope, link_id)
                elif key in _SYSTEM:
                    self.add(ref, sub, child, 'system', scope, link_id)
                elif key in _FORMAT:
                    self.add(ref, sub, child, 'format', scope, link_id)
                elif key == 'tools':
                    self.tools(ref, sub, child, scope, link_id)
                elif key not in {'output', 'result', 'outcome', 'messages', 'instance'} and isinstance(child, (Mapping, list)):
                    self.declarations(ref, sub, child, scope, link_id)

    def templates(self, ref, path, templates, scope, link_id=None):
        for i, template in enumerate(templates or []):
            if isinstance(template, Mapping) and isinstance(template.get('template'), str):
                self.add(ref, _pointer(_pointer(path, i), 'template'), template['template'],
                         'system', scope, link_id)

    def request(self, ref, path, request, scope, link_id):
        request = _decode(request)
        if isinstance(request, list):
            messages, base = request, path
        elif isinstance(request, Mapping):
            messages, base = request.get('messages', []), _pointer(path, 'messages')
            for key in sorted(_FORMAT):
                if key in request:
                    self.add(ref, _pointer(path, key), request[key], 'format', scope, link_id)
            if 'tools' in request:
                self.tools(ref, _pointer(path, 'tools'), request['tools'], scope, link_id)
        else:
            self.add(ref, path, request, 'system', scope, link_id)
            return
        for i, message in enumerate(messages):
            self.add(ref, _pointer(base, i), message, 'system', scope, link_id,
                     role=message.get('role') if isinstance(message, Mapping) else None)

    def result(self):
        for row in self.rows.values():
            if 'link_ids' in row:
                row['link_ids'].sort()
        return sorted(self.rows.values(), key=lambda b: (b['ref'], b['path'], b['id']))


def project_design(trace: Any) -> dict:
    """Pre-run candidate methods: declarations, never interpolated runtime messages.

    Only the first gateway call's typed tools/format declarations are read. Even
    its system messages may contain upstream tool results, so templates must be
    independently registered under definitions. All blocks are reference-only.
    """
    blocks = _Blocks()
    turns = getattr(trace, 'turn_records', None) or [dict(
        project_fields=getattr(trace, 'project_fields', None) or {})]
    for n, turn in enumerate(turns, 1):
        records = ((turn.get('project_fields') or {}).get('business_trace') or {}).get('records') or {}
        definitions = records.get('definitions') or []
        entries = enumerate(definitions) if isinstance(definitions, list) else [(None, definitions)]
        for i, node in entries:
            ref = f'turn{n}/records/definitions' + (f'/{i}' if i is not None else '')
            blocks.declarations(ref, '', node, COLLECTION)
        calls = records.get('calls') or []
        if calls:
            pre = calls[0].get('pre') or {}
            ref = f'turn{n}/records/calls/0'
            for params, path in [(pre, '/pre'), (pre.get('optional_params') or {}, '/pre/optional_params')]:
                if 'tools' in params:
                    blocks.tools(ref, path + '/tools', params['tools'], COLLECTION)
                for key in sorted(_FORMAT):
                    if key in params:
                        blocks.add(ref, _pointer(path, key), params[key], 'format', COLLECTION)
    result = {'blocks': blocks.result()}
    result['sha256'] = hashlib.sha256(_json(result).encode()).hexdigest()
    return result


def dossier_blocks(dossier: Mapping, links: list, axis_id: str) -> list:
    """Enumerate exact inputs plus applicable reference definitions per supplied link."""
    blocks = _Blocks()
    rows = {r['id']: r for r in dossier.get('records', [])}
    calls = {c['id']: c for c in dossier.get('model_calls', [])}

    def value(row, field):
        info = row.get('fields', {}).get(field) or {}
        if info.get('status') in {'available', 'empty'}:
            return expand_content(info.get('value'), dossier.get('contents', {}))
        return None

    def request(row, link_id):
        ref = row['id']
        exact = value(row, 'exact_request')
        if exact is None:
            return
        blocks.request(ref, '/fields/exact_request/value', exact, 'actual_input', link_id)
        params = _decode(value(row, 'invocation_parameters'))
        if isinstance(params, Mapping):
            for key in sorted(_FORMAT):
                if key in params:
                    blocks.add(ref, '/fields/invocation_parameters/value/' + key,
                               params[key], 'format', 'actual_input', link_id)
        tools = value(row, 'tool_definitions')
        if tools is not None:
            blocks.tools(ref, '/fields/tool_definitions/value', tools, 'actual_input', link_id)
        attrs = value(row, 'raw_attributes')
        for key, child in (attrs.items() if isinstance(attrs, Mapping) else []):
            if key == 'llm.tools' or key.startswith('llm.tools.'):
                blocks.tools(ref, _pointer('/fields/raw_attributes/value', key), child, 'actual_input', link_id)

    for link in links:
        lid = link['link_id']
        endpoints = [(side, end) for side in ('input', 'output') for end in link.get(side, [])]
        endpoint_refs = {end['ref'] for _, end in endpoints}
        for call in calls.values():
            if call.get('output_message_ref') in endpoint_refs and call['id'] in rows:
                request(rows[call['id']], lid)
        if axis_id in {'planning_routing', 'knowledge_data'}:
            # What the model actually received this turn is the only confirmable version of its rules.
            turn = (link.get('turn') or '').replace('turn', 't', 1)
            for call in calls.values():
                row = rows.get(call['id'])
                if row and turn and (row.get('turn') or '').replace('turn', 't', 1) == turn:
                    request(row, lid)
        for side, end in endpoints:
            row = rows.get(end['ref'])
            if not row:
                continue
            field, kind = end.get('field', ''), row.get('kind')
            if kind == 'model_calls' and (side == 'input' or axis_id != 'model_capability'):
                request(row, lid)
            elif kind == 'messages' and field == 'content':
                # Reconstructed membership does not prove an exact request. For non-model
                # axes retain it as a reference rather than silently upgrading provenance.
                owners = [c for c in calls.values() if row['id'] in
                          (c.get('reconstructed_input') or {}).get('message_refs', [])]
                if axis_id != 'model_capability' and owners:
                    blocks.add(row['id'], '/fields/content/value', value(row, 'content'),
                               'system', COLLECTION, lid, role=row.get('role'))
            if axis_id != 'model_capability' and kind == 'tool_calls':
                # span_ref is the provider's verified same-call pairing, not
                # temporal proximity. Keep the description's original source.
                sources = [row]
                span = rows.get(row.get('span_ref'))
                if span and span.get('kind') == 'tool_calls':
                    sources.append(span)
                for source in sources:
                    description = value(source, 'tool_description')
                    if description is not None:
                        blocks.add(source['id'], '/fields/tool_description/value', description,
                                   'tools', 'execution' if source.get('scope') == 'current' else COLLECTION,
                                   lid, source.get('name'))
            if axis_id == 'context_memory' and side == 'input' and kind in {'runs', 'steps'} and field == 'input':
                # Existing link builder can guess a first run. Accept only the run_id
                # recorded on the destination call, never that positional guess.
                targets = [rows.get(e['ref'], {}) for e in link.get('output', [])]
                owned = any(row.get('run_id') and row.get('run_id') ==
                            ((t.get('reconstructed_input') or {}).get('run_id') or t.get('run_id'))
                            for t in targets if t.get('kind') == 'model_calls')
                blocks.add(row['id'], '/fields/input/value', value(row, 'input'), 'system',
                           'execution' if owned else COLLECTION, lid)
        if axis_id == 'model_capability':
            continue
        refs = set(_supporting_definitions(rows, [link]))
        refs.update(end['ref'] for _, end in endpoints if rows.get(end['ref'], {}).get('kind') == 'definitions')
        # Tool definitions nested under an applicable component retain its ownership.
        refs.update(ref for ref, row in rows.items() if row.get('kind') == 'definitions'
                    and any(ref.startswith(parent + '/') for parent in list(refs)))
        for ref in sorted(refs):
            row = rows[ref]
            if row.get('definition_type') == 'tool':
                # Preserve actual field wrappers: /fields/description/value must
                # resolve in the source record, not a synthetic flattened object.
                body = expand_content(row.get('fields', {}), dossier.get('contents', {}))
                blocks.add(ref, '/fields', body, 'tools', COLLECTION, lid, row.get('name'))
                continue
            for field in row.get('fields', {}):
                body = value(row, field)
                path = '/fields/' + field + '/value'
                if field == 'instruction_templates':
                    blocks.templates(ref, path, body, COLLECTION, lid)
                elif field in _SYSTEM:
                    blocks.add(ref, path, body, 'system', COLLECTION, lid)
                elif field in _FORMAT:
                    blocks.add(ref, path, body, 'format', COLLECTION, lid)
                elif field == 'tools':
                    blocks.tools(ref, path, body, COLLECTION, lid)
                elif field == 'definition':
                    blocks.declarations(ref, path, body, COLLECTION, lid)
    return blocks.result()


def transcript_blocks(transcript: Mapping, links: list, axis_id: str) -> list:
    """Use gateway call.input_refs, not temporal proximity or an arbitrary first call.

    Original message metadata preserves boundaries; renderer text is not parsed
    into invented messages. Component system is a candidate source, not a rule verdict.
    """
    rows = {r['id']: r for r in transcript.get('records', [])}
    blocks = _Blocks()
    for link in links:
        lid = link['link_id']
        refs = {e['ref'] for side in ('input', 'output') for e in link.get(side, [])}
        owners = [r for r in rows.values() if r.get('kind') == 'call' and
                  (r['id'] in refs or r['id'] + '.response' in refs)]
        allowed = {ref for call in owners for ref in call.get('input_refs', [])}
        # Without a call endpoint, explicit request entries are still exact input
        # evidence for non-model axes. Model ownership must identify the call.
        if axis_id != 'model_capability':
            allowed.update(refs)
        for ref in sorted(allowed):
            row = rows.get(ref, {})
            if row.get('origin') not in {'model_request', 'model_received_tool_result'}:
                continue
            source = row
            seen = set()
            while source.get('canonical_ref') and source['canonical_ref'] not in seen:
                seen.add(source['canonical_ref'])
                source = rows.get(source['canonical_ref'], {})
            text = source.get('text')
            if text is None:
                continue
            # Keep the canonical source ref; link_ids provide receiving-call ownership.
            source_ref = source['id']
            kind = row.get('kind')
            if kind == 'tools':
                blocks.tools(source_ref, '/text', text, 'actual_input', lid)
            elif kind == 'params':
                params = _decode(text)
                if isinstance(params, Mapping):
                    for key in sorted(_FORMAT):
                        if key in params:
                            blocks.add(source_ref, _pointer('/text', key), params[key], 'format', 'actual_input', lid)
            elif kind == 'system':
                for i, message in enumerate(source['messages']):
                    blocks.add(source_ref, f'/messages/{i}', message, 'system', 'actual_input', lid,
                               role=message.get('role'))
            elif kind == 'message':
                blocks.add(source_ref, '/message', source['message'], 'system', 'actual_input', lid,
                           role=source['message'].get('role'))
    return blocks.result()
