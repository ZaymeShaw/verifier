"""Analysis handoff must carry recorded endpoint bodies, not just readable IDs."""
from tests.support.expectations import E, PROJECTION
import json
from types import SimpleNamespace

import pytest

from impl.projects.llm_probe.business_trace.materials import material_view, prepare_axis_materials
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis


def row(ident, kind, **fields):
    return {"id": ident, "kind": kind, "scope": "current", "turn": "turn1",
            "fields": {k: {"status": "available", "value": v} for k, v in fields.items()}}


def data():
    return {"records": [], "contents": {}, "sources": [], "gaps": [], "coverage": [], "model_calls": []}


def unshare(value, view):
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return unshare(view["shared_contents"][value["shared_ref"]], view)
        return {k: unshare(v, view) for k, v in value.items()}
    if isinstance(value, list):
        return [unshare(v, view) for v in value]
    return value


def model(d, ident, messages, output, **request):
    req = {"messages": messages, **request}
    d["records"] += [row(ident, "model_calls", exact_request=json.dumps(req, ensure_ascii=False)),
                     row(ident + "-out", "messages", content=output)]
    d["model_calls"].append({"id": ident, "scope": "current", "turn": "turn1",
                           "exact_request": {"status": "available"}, "output_message_ref": ident + "-out"})
    return req


def test_large_actual_request_and_output_reach_axis_without_analyst_read_receipts():
    d = data()
    body = "padding " * 4000 + '字段说明：A 是周年日，不是生效日。'
    original = model(d, 'c', [{"role": "tool", "content": body}], '把 A 错写为生效日', temperature=0)
    s = prepare_selections(d, {"suspects": [], "evidence_audit": {"reads": []}}, {"model_capability": {"refs": []}})
    view = s['model_capability']['materials'][0]['view']
    request = next(r for r in view['records'] if r['id'] == 'c')['fields']['exact_request']['value']
    assert unshare(request, view) == original
    assert '不是生效日' in json.dumps(view, ensure_ascii=False)
    assert not view['excluded']
    assert any(r['path'] == '/fields/exact_request/value' and r['full'] for r in view['reads'])


def test_actual_input_does_not_inherit_backend_only_rules_or_another_calls_input():
    d = data()
    req = model(d, 'c', [{"role": "user", "content": "仅此输入"}], '结果')
    d['records'].append(row('backend', 'tool_calls', result='后台独有规则，不曾送给模型'))
    suspects = [{'link_id': 'model_capability:c', 'source_refs': ['backend']}]
    view = material_view(d, common._axis_links('model_capability', d, {}), suspects)
    assert '后台独有规则' not in json.dumps(view, ensure_ascii=False)
    assert unshare(view['records'][0]['fields']['exact_request']['value'], view) == req


def test_request_interning_preserves_message_strings_order_and_tool_definitions():
    d = data()
    text = '{ "value" : "' + 'x' * 16000 + '" }\n'
    req1 = model(d, 'c1', [{"role": "tool", "content": text}], 'first')
    req2 = model(d, 'c2', [{"role": "tool", "content": text}, {"role": "assistant", "content": "first"}], 'second')
    d['records'][0]['fields']['raw_attributes'] = {'status': 'available', 'value': {'llm.tools.0.tool.json_schema': '{"name":"lookup"}', 'internal': 'NOT A MODEL INPUT'}}
    links = common._axis_links('model_capability', d, {})
    view = material_view(d, links, [])
    got = {r['id']: r for r in view['records']}
    assert unshare(got['c1']['fields']['exact_request']['value'], view) == req1
    assert unshare(got['c2']['fields']['exact_request']['value'], view) == req2
    assert unshare(got['c1']['captured_tool_definitions'], view) == {'llm.tools.0.tool.json_schema': '{"name":"lookup"}'}
    assert list(view['shared_contents'].values()).count(text) == 1
    assert 'NOT A MODEL INPUT' not in json.dumps(view)


def test_tool_only_assistant_output_is_preserved_and_not_reported_as_missing():
    d = data(); model(d, 'c', [], '')
    out = d['records'][1]
    out['fields']['content'] = {'status': 'missing', 'note': '没有文本'}
    calls = [{'id': 'tc1', 'function': {'name': 'lookup', 'arguments': '{"q": "X"}'}}]
    out['fields']['tool_calls'] = {'status': 'available', 'value': calls}
    view = material_view(d, common._axis_links('model_capability', d, {}), [])
    rendered = next(r for r in view['records'] if r['id'] == 'c-out')
    assert unshare(rendered['fields']['tool_calls']['value'], view) == calls
    assert not view['missing_endpoints']


def test_missing_body_is_explicit_not_an_empty_success():
    d = data(); model(d, 'c', [], 'answer')
    d['records'][0]['fields']['exact_request'] = {'status': 'redacted', 'note': '未记录实际请求'}
    view = material_view(d, common._axis_links('model_capability', d, {}), [])
    assert view['missing_endpoints'][0]['ref'] == 'c'
    assert view['missing_endpoints'][0]['reason'] == '未记录实际请求'
    assert not any(r['id'] == 'c' for r in view['reads'])


def test_batches_do_not_split_or_omit_calls_and_single_oversize_unit_stays_whole():
    d = data()
    for n in range(3): model(d, f'c{n}', [{"role": "user", "content": str(n) * 1800}], 'reply')
    links = common._axis_links('model_capability', d, {})
    batches = prepare_axis_materials(d, links, [], target_chars=100)
    assert [l for b in batches for l in b['links']] == links
    assert len(batches) == 3 and all(b['oversize'] for b in batches)
    for n, batch in enumerate(batches):
        ids = {r['id'] for r in batch['view']['records']}
        assert ids == {f'c{n}', f'c{n}-out'}
        assert batch['view']['excluded'] == []


def test_axis_consumes_each_prepared_batch_once_and_retries_only_the_bad_batch(monkeypatch):
    d = data()
    for n in range(2): model(d, f'c{n}', [{"role": "user", "content": str(n) * 2000}], 'reply')
    links = common._axis_links('model_capability', d, {})
    batches = prepare_axis_materials(d, links, [], target_chars=100)
    seen = []
    class Client:
        def complete_json(self, system, prompt, **kw):
            p, _ = json.JSONDecoder().raw_decode(prompt)
            seen.append(p)
            assert 'tool_budget' not in p and 'catalog' not in p
            if len(seen) == 2: return {'reason': 'r', 'scope_note': 's', 'results': []}
            ident = p['links']['links'][0]['input'][0]['ref']
            return {'reason': 'r', 'scope_note': 's', 'results': [
                {'obligation_id': ob, 'link_ids': ids, 'outcome': 'fail', 'expectation_ids': [], 'expectation_checks': [], 'matched_link_id': '', 'observed': 'o',
                 'source_refs': [ident], 'input_refs': [ident], 'output_refs': [ident + '-out'], 'missing': [],
                 'problems': [dict(problem_id=ident, phenomenon='wrong answer', expectation_ids=[], observed='o',
                     source_refs=[ident], input_refs=[ident], output_refs=[ident + '-out'],
                     attribution_axes=['model_capability'], impact='unknown')] }
                for ob, ids in p['pending'].items()]}
        def usage(self): return {'llm_calls': len(seen)}
    def client(*a, **kw):
        assert not kw.get('tools')
        return Client()
    monkeypatch.setattr(common, 'axis_llm', client)
    monkeypatch.setattr(common, '_scenario_entry', lambda _: None)
    runtime = SimpleNamespace(spec=None, trace_id='test', ensure_time_left=lambda *_: None, expectation_projection=PROJECTION)
    spec = common.AxisSpec('q', '', (common.Obligation('faithful', 'model_capability', 's', 'd'),))
    outcome = common.run_process_axis('model_capability', {'expectations': E, 'trace_analysis': {'dossier': d,
        'selections': {'model_capability': {'materials': batches}}}}, ScenarioAxis('model_capability', True, ''), runtime, spec)
    assert len(seen) == 3 and seen[1] == seen[2] and seen[0] != seen[1]
    assert len(outcome.output['results']) == 2
    assert outcome.usage['tool_calls'] == 0
    assert len(outcome.output['view']['batches']) == 2
    assert outcome.output['view']['unverified_refs'] == []


def test_execution_gets_actual_paired_span_description_metrics_and_declared_schema():
    d = data()
    d['records'] += [row('t', 'tool_calls', arguments={'q': 'x'}, result='reply', metrics={'start_time': 1, 'end_time': 2}),
                     row('span', 'tool_calls', tool_description='该次调用实际工具说明', duration_ms=1000),
                     row('def', 'definitions', description='采集时的工具说明', parameters={'q': 'string'})]
    d['records'][0].update(name='lookup', span_ref='span')
    d['records'][1].update(name='lookup', persisted_ref='t')
    d['records'][2].update(name='lookup', definition_type='tool', scope='observed_at_collection_not_verified_run_version')
    links = common._axis_links('tool_execution', d, {})
    view = material_view(d, links, [])
    records = {r['id']: r for r in view['records']}
    assert unshare(records['span']['fields']['tool_description']['value'], view) == '该次调用实际工具说明'
    assert unshare(records['t']['fields']['metrics']['value'], view) == {'start_time': 1, 'end_time': 2}
    assert records['def']['scope'] == 'observed_at_collection_not_verified_run_version'
    assert 'parameters' in records['def']['fields']
    assert '不能据此证明当次' in view['reading_guide']
    assert any(r['id'] == 'span' for r in view['reads'])


def test_planning_gets_related_workflow_definition_even_without_a_suspect():
    d = data();d['sources']=[{'id':'turn1'}]
    d['records'] += [row('run', 'runs', input='question'), row('step', 'steps', output='reply'),
                     row('def', 'definitions', steps=[{'type':'Condition', 'rule':'走符合条件的分支'}])]
    d['records'][0]['name']='workflow'
    d['records'][1]['parent_ref']='run'
    d['records'][2].update(name='workflow', definition_type='component', scope='observed_at_collection_not_verified_run_version')
    view = material_view(d, common._axis_links('planning_routing', d, {}), [])
    assert '走符合条件的分支' in json.dumps(view,ensure_ascii=False)
    assert any(r['id']=='def' for r in view['reads'])


def test_reconstructed_request_does_not_certify_collection_time_definition_as_received():
    d = data()
    d['records'] += [row('run', 'runs', input='user'), row('message', 'messages', content='question'),
                     row('def/agent', 'definitions', system_message='background'),
                     row('def/agent/tool', 'definitions', description='采集时规则', parameters={}),
                     row('out', 'messages', content='answer')]
    d['records'][0].update(name='agent', run_id='agent-run')
    d['records'][2].update(name='agent', definition_type='component', scope='observed_at_collection_not_verified_run_version')
    d['records'][3].update(name='lookup', definition_type='tool', scope='observed_at_collection_not_verified_run_version')
    d['model_calls']=[{'id':'call', 'turn':'turn1','scope':'current','output_message_ref':'out',
                       'reconstructed_input':{'run_id':'agent-run','message_refs':['message'],'status':'verified'}}]
    view = material_view(d, common._axis_links('model_capability', d, {}), [])
    assert not view['missing_endpoints']
    assert view['input_limitations'][0]['ref']=='def/agent/tool'
    assert '不能证明本次模型收到' in view['input_limitations'][0]['reason']
    assert not any(r['id']=='def/agent' for r in view['records'])
