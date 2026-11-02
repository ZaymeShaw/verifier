"""Offline provenance and lossless-block contracts (no model/network calls)."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.projects.llm_probe.business_trace.design_rules import (
    COLLECTION, dossier_blocks, project_design, transcript_blocks, quote_text,
)
from impl.projects.llm_probe.business_trace.dossier import _Contents, expand_content, resolve_node_path
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript


def row(ref, kind, **fields):
    return dict(id=ref, kind=kind, turn='turn1', scope='current',
                fields={k: dict(status='available', value=v) for k, v in fields.items()})


def link(ref='c1', axis='model_capability'):
    return dict(link_id=f'{axis}:{ref}', link_type=axis, turn='turn1',
                input=[dict(ref=ref, field='exact_request')],
                output=[dict(ref=ref, field='output')])


def trace(records):
    return SimpleNamespace(project_fields={'business_trace': {'records': records, 'status': 'complete'}})


def text(blocks):
    return '\n'.join(b['text'] for b in blocks)


def test_project_never_reads_outputs_results_or_interpolated_system_messages():
    records = dict(definitions=[dict(name='agent', system_message='原始规则',
                                    instruction_templates=[dict(template='若失败，\n不要继续。', instance='实例秘密')])],
                   calls=[dict(pre=dict(messages=[dict(role='system', content='运行结果插入')],
                                        tools=[dict(name='lookup', parameters={}, description='按编号查')]),
                               outcome={'response': '响应秘密'})],
                   run={'content': '运行秘密'}, tool_calls=[{'result': '工具秘密'}])
    first = project_design(trace(records))
    assert '原始规则' in text(first['blocks'])
    assert all(b['scope'] == COLLECTION for b in first['blocks'])
    assert all(word not in text(first['blocks']) for word in ['秘密', '运行结果插入'])
    changed = copy.deepcopy(records)
    changed['calls'][0]['outcome'] = {'response': '任意输出改变'}
    changed['calls'][0]['pre']['messages'] = [{'role': 'system', 'content': '另一运行结果'}]
    assert project_design(trace(changed)) == first
    assert len(first['sha256']) == 64


def test_project_uses_first_call_typed_declarations_not_later_runtime_material():
    result = project_design(trace({'calls': [
        {'pre': {'optional_params': {'tools': [{'name': 'first', 'parameters': {}}],
                                     'response_format': {'type': 'json_object'}}}},
        {'pre': {'tools': [{'name': 'later', 'parameters': {}}]}}]}))
    assert 'first' in text(result['blocks']) and 'later' not in text(result['blocks'])
    assert any(b['component'] == 'format' for b in result['blocks'])


def test_model_exact_input_only_and_tool_names():
    request = dict(messages=[dict(role='system', content='整段必须 JSON'),
                             dict(role='user', content='条件独立一条'),
                             dict(role='tool', content='上次工具回填')],
                   tools=[dict(type='function', function=dict(name='lookup', description='查询', parameters={}))])
    d = dict(records=[row('c1', 'model_calls', exact_request=json.dumps(request), output='输出中的伪规则'),
                      row('c2', 'model_calls', exact_request={'messages': [{'content': '别的调用'}]}),
                      row('backend', 'tool_calls', result='未送达结果')])
    blocks = dossier_blocks(d, [link()], 'model_capability')
    assert '整段必须 JSON' in text(blocks) and '上次工具回填' in text(blocks)
    assert not any(x in text(blocks) for x in ['伪规则', '别的调用', '未送达结果'])
    assert all(b['scope'] == 'actual_input' and b['link_ids'] == ['model_capability:c1'] for b in blocks)
    assert len(blocks) == 4
    assert [b for b in blocks if b.get('role') == 'tool'][0]['component'] == 'system'
    assert {b['tool'] for b in blocks if b['component'] == 'tools'} == {'lookup'}
    assert {f'/fields/exact_request/value/messages/{i}' for i in range(3)} <= {b['path'] for b in blocks}


def test_same_text_different_source_ownership_not_deduplicated():
    d = dict(records=[row(c, 'model_calls', exact_request={'messages': [{'content': '相同规则'}]})
                      for c in ['c1', 'c2']])
    blocks = dossier_blocks(d, [link('c1'), link('c2')], 'model_capability')
    leaves = [b for b in blocks if quote_text(b, '/content') == '相同规则']
    assert len(leaves) == 2 and leaves[0]['id'] != leaves[1]['id']
    assert leaves[0]['link_ids'] != leaves[1]['link_ids']
    assert dossier_blocks(d, [link('c1')], 'model_capability') == [b for b in blocks if b['ref'] == 'c1']


def test_schema_nodes_and_string_leaves_keep_conditions_and_verbatim_quotes():
    condition = '仅最终响应。\n例外：用户说 "取消" 时不适用。'
    schema = {'properties': {'a/b~c': {'description': condition, 'type': 'string'}},
              'required': ['a/b~c'], 'additionalProperties': False}
    d = dict(records=[row('c1', 'model_calls', exact_request={'messages': [], 'response_format': schema})])
    blocks = dossier_blocks(d, [link()], 'model_capability')
    assert len(blocks) == 2
    field = next(b for b in blocks if b['path'].endswith('/properties/a~1b~0c'))
    assert quote_text(field, '/description') == condition
    assert quote_text(field) == field['text']
    assert json.loads(next(b['text'] for b in blocks if b['path'].endswith('/response_format'))) == schema


def test_unverified_collected_rules_never_upgrade_to_actual_input():
    definition = row('def', 'definitions', system_message='仅采集时规则')
    definition.update(name='agent', scope=COLLECTION, definition_type='component')
    run = row('run', 'runs', input='任务'); run.update(name='agent', run_id='r1')
    d = dict(records=[definition, run, row('c1', 'model_calls', exact_request={'messages': []})])
    assert not dossier_blocks(d, [link()], 'model_capability')
    blocks = dossier_blocks(d, [link(axis='planning_routing')], 'planning_routing')
    assert any(b['text'] == '仅采集时规则' and b['scope'] == COLLECTION for b in blocks)


def test_tool_execution_description_is_execution_specific_but_definition_is_not():
    tool = row('tool', 'tool_calls', arguments={}, result='不是规则', tool_description='本次执行说明')
    tool['name'] = 'lookup'
    definition = row('def', 'definitions', description='采集版', parameters={})
    definition.update(name='lookup', definition_type='tool', scope=COLLECTION)
    l = link('tool', 'tool_execution'); l['input'][0]['field'] = 'arguments'
    blocks = dossier_blocks({'records': [tool, definition]}, [l], 'tool_execution')
    assert any(b['text'] == '本次执行说明' and b['scope'] == 'execution' and b['tool'] == 'lookup' for b in blocks)
    assert any('采集版' in b['text'] and b['scope'] == COLLECTION for b in blocks)
    assert len(blocks) == 2
    assert '不是规则' not in text(blocks)


def test_context_compares_proven_owner_and_actual_request_not_arbitrary_first_run():
    wrong = row('wrong', 'runs', input='猜测的应送达'); wrong['run_id'] = 'wrong'
    own = row('own', 'runs', input={'system_message': '应该送达'}); own['run_id'] = 'r1'
    call = row('c1', 'model_calls', exact_request={'messages': [{'content': '实际送达'}]})
    call['reconstructed_input'] = {'run_id': 'r1'}
    l = link(axis='context_memory')
    l['input'] = [{'ref': 'own', 'field': 'input'}]
    l['output'] = [{'ref': 'c1', 'field': 'exact_request'}]
    d = {'records': [wrong, own, call]}
    blocks = dossier_blocks(d, [l], 'context_memory')
    assert any('应该送达' in b['text'] and b['scope'] == 'execution' for b in blocks)
    assert any('实际送达' in b['text'] and b['scope'] == 'actual_input' for b in blocks)
    l['input'][0]['ref'] = 'wrong'
    blocks = dossier_blocks(d, [l], 'context_memory')
    assert any(b['text'] == '猜测的应送达' and b['scope'] == COLLECTION for b in blocks)


def test_reconstructed_messages_are_not_proof_of_exact_model_input():
    message = row('m', 'messages', content='重建候选'); message['role'] = 'system'
    d = {'records': [message], 'model_calls': [dict(id='c1', reconstructed_input={'message_refs': ['m']})]}
    l = link(); l['input'] = [{'ref': 'm', 'field': 'content'}]
    assert dossier_blocks(d, [l], 'model_capability') == []
    blocks = dossier_blocks(d, [l], 'context_memory')
    assert blocks[0]['scope'] == COLLECTION


def test_content_interning_expands_losslessly_and_keeps_source_record():
    original = '带换行的规则\n' * 100
    pool = _Contents()
    d = {'records': [row('c1', 'model_calls', exact_request=pool.add({'messages': [{'content': original}]}))],
         'contents': pool.values}
    blocks = dossier_blocks(d, [link()], 'model_capability')
    assert len(blocks) == 1
    assert quote_text(blocks[0], '/content') == original and blocks[0]['ref'] == 'c1'


def test_span_tools_and_format_are_owned_by_that_call_only():
    c1 = row('c1', 'model_calls', exact_request=[],
             raw_attributes={'llm.tools.0.tool.json_schema': json.dumps({'name': 'lookup', 'parameters': {}}),
                             'private': '后台规则'},
             invocation_parameters=json.dumps({'response_format': {'type': 'json_object'}}))
    blocks = dossier_blocks({'records': [c1]}, [link()], 'model_capability')
    assert any(b.get('tool') == 'lookup' for b in blocks)
    assert any(b['component'] == 'format' for b in blocks)
    assert '后台规则' not in text(blocks)


def transcript():
    calls = []
    for i in range(2):
        calls.append({'call_id': str(i), 'pre': {
            'messages': [{'role': 'system', 'content': '相同系统\n条件另起一行'},
                         {'role': 'user', 'content': f'调用{i + 1}独有'}],
            'tools': [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {}}}],
            'optional_params': {'response_format': {'type': 'json_object'}}},
            'outcome': {'event': 'success', 'response': {'choices': [{'message': {'content': '输出不是规则'}}]}}})
    return build_transcript(SimpleNamespace(), {'records': {'calls': calls}, 'status': 'complete'})


def test_transcript_uses_own_call_and_canonical_sources_with_receiving_link_ids():
    t = transcript()
    l = link('t1.c2')
    blocks = transcript_blocks(t, [l], 'model_capability')
    assert '调用2独有' in text(blocks) and '调用1独有' not in text(blocks)
    assert '输出不是规则' not in text(blocks)
    assert any(b['ref'] == 't1.c1.system' and b['link_ids'] == ['model_capability:t1.c2'] for b in blocks)
    assert any(b.get('tool') == 'lookup' for b in blocks)
    assert any(b['component'] == 'format' for b in blocks)


def test_transcript_model_requires_call_ownership_not_arbitrary_input_ref():
    l = link('t1.c2.m2')
    assert transcript_blocks(transcript(), [l], 'model_capability') == []


def test_separate_conditions_are_not_keyword_filtered_or_rewritten():
    d = {'records': [row('c1', 'model_calls', exact_request={'messages': [
        {'role': 'system', 'content': '只在用户确认后适用。'},
        {'role': 'system', 'content': '整段输出必须为 JSON。'},
        {'role': 'system', 'content': '附录：取消时例外。'}]})]}
    blocks = dossier_blocks(d, [link()], 'model_capability')
    assert len(blocks) == 3
    assert {'只在用户确认后适用。', '整段输出必须为 JSON。', '附录：取消时例外。'} == {quote_text(b, '/content') for b in blocks}


def test_missing_or_redacted_request_never_claimed_as_actual():
    r = row('c1', 'model_calls', exact_request='隐藏的规则')
    r['fields']['exact_request']['status'] = 'redacted'
    assert dossier_blocks({'records': [r]}, [link()], 'model_capability') == []


def test_digest_and_block_ids_ignore_mapping_insertion_order():
    one = {'definitions': [{'system_message': '规则', 'output_schema': {'required': ['x'], 'type': 'object'}}]}
    two = {'definitions': [{'output_schema': {'type': 'object', 'required': ['x']}, 'system_message': '规则'}]}
    assert project_design(trace(one)) == project_design(trace(two))


def test_message_output_endpoint_locates_its_own_recorded_call_input():
    d = {'records': [row('c1', 'model_calls', exact_request={'messages': [{'content': '正确调用规则'}]}),
                     row('out', 'messages', content='输出')],
         'model_calls': [{'id': 'c1', 'output_message_ref': 'out'}]}
    l = link(); l['input'] = []; l['output'] = [{'ref': 'out', 'field': 'content'}]
    assert '正确调用规则' in text(dossier_blocks(d, [l], 'model_capability'))


def test_collection_tool_description_is_not_execution_proof():
    tool = row('tool', 'tool_calls', tool_description='未核实执行版本')
    tool.update(scope=COLLECTION, name='lookup')
    blocks = dossier_blocks({'records': [tool]}, [link('tool', 'tool_execution')], 'tool_execution')
    assert blocks and all(b['scope'] == COLLECTION for b in blocks)


def test_transcript_preserves_system_boundaries_and_tool_data_role():
    messages = [{'role': 'system', 'content': 'one\n\nparagraph'},
                {'role': 'system', 'content': 'two'},
                {'role': 'tool', 'tool_call_id': 'x', 'content': {'data': 'not a rule'}}]
    t = build_transcript(SimpleNamespace(), {'status': 'complete', 'records': {'calls': [
        {'pre': {'messages': messages}}, {'pre': {'messages': messages}}]}})
    from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import render
    assert 'one\n\nparagraph\n\ntwo' in render(t)
    blocks = transcript_blocks(t, [link('t1.c2')], 'model_capability')
    assert len(blocks) == 3
    assert sorted(b['role'] for b in blocks) == ['system', 'system', 'tool']
    assert {quote_text(b, '/content') for b in blocks if b['role'] == 'system'} == {'one\n\nparagraph', 'two'}
    assert all(b['link_ids'] == ['model_capability:t1.c2'] for b in blocks)


def test_material_shared_namespace_cannot_shadow_original_content_id():
    from impl.projects.llm_probe.business_trace.materials import material_view, model_material
    long = 'shared body ' * 100
    d = {'records': [row('c1', 'model_calls', exact_request=long, output=long)],
         'contents': {'content#1': 'independent original'}}
    view = model_material(material_view(d, [link()], [], extra_refs=['content#1']))
    assert view['contents']['content#1'] == 'independent original'
    assert view['shared_contents']['shared#1'] == long
    assert not set(view['contents']) & set(view['shared_contents'])
    for info in view['records'][0]['fields'].values():
        assert info['value'] == {'shared_ref': 'shared#1'}


def test_nested_format_fields_not_schema_scalar_leaves():
    schema = {'type': 'json_schema', 'json_schema': {'schema': {
        'required': ['a'], 'if': {'required': ['b']},
        'properties': {'a': {'type': 'object', 'properties': {'b': {'enum': ['x', 'y']}}}}}}}
    blocks = dossier_blocks({'records': [row('c1', 'model_calls', exact_request={
        'response_format': schema})]}, [link()], 'model_capability')
    assert len(blocks) == 3
    root = next(b for b in blocks if b['path'].endswith('/response_format'))
    assert quote_text(root, '/json_schema/schema/if') == '{"required":["b"]}'


@pytest.mark.parametrize('wrapped', [False, True])
def test_declaration_preserves_whole_tool_and_reverse_source_paths(wrapped):
    condition = '仅在确认后。\n用户说 "取消" 时禁止调用。'
    tool = dict(name='lookup', description='按 "编号" 查', parameters={
        'if': {'required': ['confirmed']}, 'then': {'required': ['id']},
        'properties': {'id': {'description': condition}}}, strict=True,
        **{'x-condition': condition, 'x-extra': {'deny': ['unconfirmed']}})
    original = {'type': 'function', 'function': tool, 'x-condition': condition} if wrapped else tool
    records = {'definitions': [original], 'tool_calls': [{'result': '运行结果不可进入'}]}
    b, = project_design(trace(records))['blocks']
    assert json.loads(b['text']) == original
    assert b['tool'] == 'lookup' and b['scope'] == COLLECTION
    base = '/function' if wrapped else ''
    for path in [base + '/description', base + '/x-condition',
                 base + '/parameters/properties/id/description', base + '/strict']:
        source = resolve_node_path(original, b['path'] + path)
        assert quote_text(b, path) == (source if isinstance(source, str) else json.dumps(source))
    changed = copy.deepcopy(records)
    changed['tool_calls'][0]['result'] = '任意不同输出'
    assert project_design(trace(changed)) == project_design(trace(records))


def test_tool_fields_wrapper_quotes_reverse_resolve_to_source_record():
    condition = '必须先确认。\n例外：用户说 "取消"。'
    source = row('def', 'definitions', description='按 "编号" 查询', strict=True,
                 parameters={'properties': {'id': {'description': condition}},
                             'if': {'required': ['confirmed']}, 'then': {'required': ['id']}},
                 **{'x-condition': condition, 'x-extra': {'deny': True}})
    source.update(name='lookup', definition_type='tool', scope=COLLECTION)
    b, = dossier_blocks({'records': [source]}, [link('def', 'tool_execution')], 'tool_execution')
    assert json.loads(b['text']) == source['fields']
    for path in ['/description/value', '/parameters/value/properties/id/description',
                 '/x-condition/value', '/strict/value']:
        original = resolve_node_path(source, b['path'] + path)
        assert quote_text(b, path) == (original if isinstance(original, str) else json.dumps(original))
    with pytest.raises(ValueError):
        quote_text(b, '/parameters/properties/id/description')


@pytest.mark.parametrize('scope', ['current', COLLECTION])
def test_paired_span_description_keeps_source_scope_and_only_owning_links(scope):
    tool = row('tool', 'tool_calls', arguments={}, result='不是规则')
    tool.update(name='lookup', span_ref='span')
    span = row('span', 'tool_calls', tool_description='当次规则：仅在 "确认" 后。\n取消时禁止。')
    span.update(name='lookup', persisted_ref='tool', scope=scope)
    adjacent = row('adjacent', 'tool_calls', tool_description='相邻但无关')
    adjacent.update(name='lookup')
    d = {'records': [tool, span, adjacent, row('other', 'tool_calls', arguments={})]}
    own = link('tool', 'tool_execution')
    blocks = dossier_blocks(d, [own, link('other', 'tool_execution')], 'tool_execution')
    b, = blocks
    assert b['ref'] == 'span' and b['path'] == '/fields/tool_description/value'
    assert b['scope'] == ('execution' if scope == 'current' else COLLECTION)
    assert b['tool'] == 'lookup' and b['link_ids'] == [own['link_id']]
    assert quote_text(b) == resolve_node_path(span, b['path'])
    assert dossier_blocks(d, [own], 'model_capability') == []
    del tool['span_ref']
    assert dossier_blocks(d, [own], 'tool_execution') == []


def test_frozen_persisted_tool_gets_actual_paired_description_block():
    from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links
    root = Path(__file__).resolve().parents[1]
    frozen = root / 'report/expectations-20261006/unit-format-full-live-20261007/result.json'
    result = json.loads(frozen.read_text())
    d = next(r for r in result['axes']['results'] if r['type_id'] == 'trace_analysis')['output']['dossier']
    tool = next(r for r in d['records'] if r['id'] == 'turn1/records/run/step_executor_runs/0/tools/0')
    span = next(r for r in d['records'] if r['id'] == tool['span_ref'])
    assert span['persisted_ref'] == tool['id'] and span['scope'] == 'current'
    links = _axis_links('tool_execution', d, {})
    blocks = dossier_blocks(d, links, 'tool_execution')
    b, = [b for b in blocks if b['ref'] == span['id']]
    original = expand_content(span['fields']['tool_description']['value'], d.get('contents', {}))
    assert len(original) == 389
    assert b['text'] == original and b['scope'] == 'execution' and b['tool'] == 'policy_detail'
    assert b['path'] == '/fields/tool_description/value'
    assert b['link_ids'] == sorted(l['link_id'] for l in links if any(
        e['ref'] == tool['id'] for side in ('input', 'output') for e in l[side]))


