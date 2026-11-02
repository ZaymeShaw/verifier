"""V2 requirement isolation and six-axis counterexamples; no model-quality claim."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.core.structured_output import enforce_output, render_output_constraint
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.business_trace.design_rules import project_design, dossier_blocks
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript
from impl.projects.llm_probe.eval_axes.adapters import expectations as axis
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from tests.support.expectations import E, content_sha256
from tests.support.llmtracing import make_trace


def fixture(*, condition='总是'):
    material = {'sources': [dict(id='user', side='want', turn='t1', component='user',
        value='查询保单现金价值', scope='request', trace_refs=['t1.c1.m2'])], 'missing': []}
    material['sha256'] = content_sha256(material)
    entries = [dict(expectation_id='Q', source_refs=['user'], about='保单现金价值',
                    statement='告知金额', condition=condition, ambiguity_group='')]
    e = dict(expectations=entries, sources=material['sources'], missing=[], verdict='complete',
             material_sha256=material['sha256'], sha256=content_sha256(entries))
    projected = dict(expectations_sha256=e['sha256'], data_needs=[dict(expectation_id='Q', need='external', methods=[],
        reason='现金价值是外部保单事实，不是因为存在工具才需要数据', missing=['工具说明未提供'])])
    return material, e, projected


def result(ob='work_coverage', link='planning_routing:expected:Q', outcome='insufficient_evidence', ids=('Q',), matched=''):
    """Internal expanded row, not the model submission schema."""
    refs = ['expectation:' + ident for ident in ids] or [ob if ob.startswith('project:') else 'obligation:' + ob]
    missing = ['原始产出'] if outcome in {'insufficient_evidence', 'contract_missing'} else []
    return dict(obligation_id=ob, link_id=link, outcome=outcome, expectation_ids=list(ids), matched_link_id=matched,
        expectation_checks=[dict(expectation_id=x, outcome=outcome, observed='核对原文') for x in ids],
        criterion_refs=refs, criterion_checks=[dict(criterion_ref=ref, outcome=outcome,
            observed='核对原文', missing=missing[:]) for ref in refs],
        observed='没有可见的查询', source_refs=refs[:], evidence={'input': ['t1.c1.m2'], 'output': []},
        missing=missing, problems=[], upstream_issue_ids=[], judged_by='llm', flags=[])


def test_projection_excludes_outputs_runtime_system_tools_and_caller_ability():
    trace = make_trace()
    records = trace.project_fields['business_trace']['records']
    first = records['calls'][0]['pre']
    first['messages'][0]['content'] = '[本轮 Direct 已执行] 状态=EMPTY; PRIVATE_RUNTIME'
    first['tools'] = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}]
    first['optional_params'] = {'response_format': {'type': 'json_object'}, 'runtime_value': 'PRIVATE_PARAM'}
    records['definitions'] = [{'data': {'system_message': '声明的静态规则',
        'instruction_templates': [{'template': '状态={status}; 不重复查询', 'instance': 'PRIVATE_INSTANCE'}]}}]
    y = project_requirements(trace, {'criterion': '按原文作答', 'capability': 'PRIVATE_CAPABILITY'})
    text = json.dumps(y, ensure_ascii=False)
    assert not any(v in text for v in ('PRIVATE_RUNTIME', 'PRIVATE_PARAM', 'PRIVATE_INSTANCE', 'PRIVATE_CAPABILITY',
                                       'state unknown', '状态={status}', '声明的静态规则', 'lookup', 'json_object'))
    assert {s['side'] for s in y['sources']} == {'want'}
    assert y['missing'] == [dict(turn='case', component='capability', reason='capability 未拆分')]
    changed = copy.deepcopy(trace)
    changed.raw_response = {'answer': 'changed'}
    changed.project_fields['business_trace']['records']['calls'][1]['outcome'] = {'event': 'failure', 'error': 'changed'}
    assert y == project_requirements(changed, {'criterion': '按原文作答', 'capability': 'different'})


def test_history_resolves_reference_but_current_assistant_is_not_input_to_e():
    trace = make_trace()
    first = trace.project_fields['business_trace']['records']['calls'][0]['pre']
    original_messages = [{'role': 'user', 'content': 'P001状态'},
        {'role': 'assistant', 'content': '有效'}, {'role': 'user', 'content': '它的缴费方式呢'}]
    trace.normalized_request['body'] = {'messages': copy.deepcopy(original_messages)}
    first['messages'] = [first['messages'][0], *original_messages]
    y = project_requirements(trace)
    assert [s['value'] for s in y['sources'] if s['side'] == 'want'] == ['它的缴费方式呢']
    assert len([s for s in y['sources'] if s['side'] == 'history']) == 2
    assert y['missing'] == [] and 'state unknown' not in json.dumps(y)


def test_agno_original_run_input_and_definition_provenance():
    trace = SimpleNamespace(turn_records=[], normalized_request={}, project_fields={'business_trace': {
        'provider': 'agno', 'status': 'succeeded', 'association': {'run_id': 'current'}, 'records': {
        'run': {'run_id': 'current', 'run_input': '查P002现金价值', 'content': 'SECRET_RESULT'},
        'definitions': [{'data': {'system_message': '只按工具结果回答'}}]}}})
    y = project_requirements(trace)
    assert [s['value'] for s in y['sources']] == ['查P002现金价值'] and y['missing'] == []
    assert 'SECRET_RESULT' not in json.dumps(y)
    blocks = project_design(trace)['blocks']
    assert any('只按工具结果回答' in b['text'] and b['scope'] == 'observed_at_collection_not_verified_run_version' for b in blocks)


@pytest.mark.parametrize('component,original', [
    ('system_message', '历史仅用于理解指代和未完成意图；历史答案不是本轮事实依据，时效性/个人数据须重新调用工具核实'),
    ('instruction_templates', '[Direct 已执行] 状态={status}；不要重复请求相同保单相同字段；可使用其他能力补充，否则把未完成项写入 gaps'),
])
def test_retired_design_gold_cases_are_original_sources_not_demands(component, original):
    trace = make_trace()
    value = original if component == 'system_message' else [{'template': original, 'instance': 'PRIVATE_INSTANTIATED_RESULT'}]
    trace.project_fields['business_trace']['records']['definitions'] = [{'data': {component: value}}]
    y = project_requirements(trace)
    assert original not in json.dumps(y, ensure_ascii=False)
    assert not y['missing']
    blocks = project_design(trace)['blocks']
    block, = [b for b in blocks if b['text'] == original]
    assert block['scope'] == 'observed_at_collection_not_verified_run_version'
    assert block['component'] == 'system' and block['path']
    assert 'PRIVATE_INSTANTIATED_RESULT' not in json.dumps(blocks, ensure_ascii=False)


@pytest.mark.parametrize('change', ['duplicate', 'runtime_ref', 'history_only', 'background_only', 'design_material',
                                   'single_ambiguity', 'empty', 'consumer_field'])
def test_invalid_expectation_sets_rejected(change):
    material, e, _ = fixture()
    p = {'expectations': copy.deepcopy(e['expectations'])}
    if change == 'duplicate': p['expectations'].append(copy.deepcopy(p['expectations'][0]))
    if change == 'runtime_ref': p['expectations'][0]['source_refs'] = ['t1.c2.response']
    if change == 'history_only': material['sources'][0].update(side='history', component='history')
    if change == 'background_only': material['sources'][0].update(side='background', component='description')
    if change == 'design_material': material['sources'][0]['component'] = 'system'
    if change == 'single_ambiguity': p['expectations'][0]['ambiguity_group'] = 'g'
    if change == 'empty': p['expectations'][0]['about'] = ' '
    if change == 'consumer_field': p['expectations'][0]['blocking'] = True
    with pytest.raises(ValueError): axis.validate(p, material)


def test_material_verdict_and_bounded_reprompt_do_not_depend_on_consumers(monkeypatch):
    material, e, _ = fixture()
    material['missing'] = [dict(component='capability', reason='capability 未拆分', turn='case')]
    sent = []
    class Client:
        def complete_json(self, system, prompt, **kwargs):
            sent.append(prompt)
            return {'expectations': e['expectations']} if len(sent) % 2 == 0 else {'expectations': []}
        def usage(self): return {'llm_calls': len(sent)}
    monkeypatch.setattr(axis, 'axis_llm', lambda *a, **kw: Client())
    runtime = SimpleNamespace(spec=None, trace_id='test', ensure_time_left=lambda *_: None, enabled_axes=['model_capability'])
    one = axis.run({'requirements': material}, ScenarioAxis('expectations', True, ''), runtime)
    runtime.enabled_axes = ['model_capability', 'fulfilled']
    two = axis.run({'requirements': material}, ScenarioAxis('expectations', True, ''), runtime)
    assert one.output == two.output and one.output['verdict'] == 'partial'
    assert len(sent) == 4 and sent[0] == sent[2]


def test_frozen_b_projection_separates_design_format_from_user_demands():
    from impl.core.schema import normalize_run_trace
    root = Path(__file__).resolve().parents[1]
    trace = normalize_run_trace(json.loads((root / 'report/llmtracing-calibration-draft/frozen-inputs/B.trace.json').read_text()))
    y = project_requirements(trace)
    # This historical frozen trace has no independently recorded outer request.
    # Do not promote its gateway user message to an original merely to populate E.
    assert y['sources'] == []
    assert y['missing'] == [dict(turn='t1', component='user', reason='用户原文未独立记录')]
    assert not any(s['component'] in {'system', 'tools', 'format'} for s in y['sources'])
    assert all(not ref.endswith('.response') for s in y['sources'] for ref in s['trace_refs'])
    assert not any(m['component'] in {'system', 'tools', 'format'} for m in y['missing'])
    assert any(b['component'] == 'format' and 'json_schema' in b['text'] for b in project_design(trace)['blocks'])


def test_expectations_are_analysis_and_not_clustering_dimensions():
    from impl.core.table_view import eval_axes_summary
    from impl.core.axes_clustering import build_material
    from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
    _, e, _ = fixture()
    rows = eval_axes_summary({'results': [{'type_id': 'expectations', 'status': 'succeeded', 'verdict': 'complete', 'output': e}]}, 'llm_probe')
    assert rows[0]['role'] == 'analysis'
    data = build_material([{'pool_index': 0, 'request_key': 'case', 'axes': rows}], [AXIS_TYPES['expectations'].describe()])
    assert not data['axes'] and not data['refs']


def test_agno_history_is_context_only_and_current_output_excluded():
    trace = SimpleNamespace(turn_records=[], normalized_request={}, project_fields={'business_trace': {
        'provider': 'agno', 'status': 'succeeded', 'association': {'run_id': 'current'}, 'records': {
        'run': {'run_id': 'current', 'run_input': '它的缴费方式呢', 'content': 'CURRENT_SECRET'},
        'history_runs': [{'run_id': 'past', 'run_input': 'P001状态', 'content': '已生效', 'ordering': 'trace_timestamps'},
                        {'run_id': 'current', 'run_input': '它的缴费方式呢', 'content': 'CURRENT_SECRET',
                         'ordering': 'trace_timestamps'}]}}})
    y = project_requirements(trace)
    assert len([s for s in y['sources'] if s['side'] == 'history']) == 2
    assert 'CURRENT_SECRET' not in json.dumps(y)


@pytest.mark.parametrize('tools', [None, []])
def test_tool_absence_does_not_make_demand_material_partial(tools):
    trace = make_trace()
    trace.project_fields['business_trace']['records']['calls'][0]['pre']['tools'] = tools
    assert project_requirements(trace)['missing'] == []


@pytest.mark.parametrize('item', json.loads((Path(__file__).parent / 'fixtures/expectations_gold.json').read_text())['cases'], ids=lambda item: item['id'])
def test_spec_gold_fixtures_obey_provider_contract(item):
    axis.validate(item['expected'], item['material'])
    assert all(s['side'] in {'want', 'history', 'background'} for s in item['material']['sources'])
    users = {s['id'] for s in item['material']['sources'] if s['component'] == 'user'}
    assert all(users.intersection(e['source_refs']) for e in item['expected']['expectations'])


def test_dossier_order_provides_planning_issues_before_dependent_data(monkeypatch):
    from impl.projects.llm_probe import capability
    from impl.projects.llm_probe.eval_axes import build_report, runner
    seen = []
    monkeypatch.setattr(capability, 'capability_business_trace', lambda _: {'provider': 'agno'})
    monkeypatch.setattr(runner, 'run_axes', lambda spec, trace, axes, **kw: seen.extend(a.type_id for a in axes) or [])
    trace = make_trace('agno')
    trace.normalized_request = {'capability_ref': 'insurance-agno-e2e'}
    build_report(SimpleNamespace(project_id='llm_probe'), trace)
    assert seen.index('expectations') < seen.index('planning_routing') < seen.index('tool_execution') < seen.index('knowledge_data')
    assert seen.index('context_memory') < seen.index('model_capability')




def test_request_body_without_messages_is_the_user_source_as_is():
    """请求体不是对话消息形状时，整份请求体就是用户这一轮发来的东西，不靠猜字段名（spec/alg/expectations.md §2.1）。"""
    trace = SimpleNamespace(turn_records=None, project_fields={},
                            normalized_request={'body': {'user_text': '五十岁以上的客户', 'session_id': 's1', 'extra': {}}})
    material = project_requirements(trace)
    user = [s for s in material['sources'] if s['component'] == 'user']
    assert len(user) == 1 and user[0]['value'] == {'user_text': '五十岁以上的客户', 'session_id': 's1'}
    assert material['missing'] == []


def test_criterion_alone_cannot_produce_an_expectation():
    material = {'sources': [{'id': 'c', 'side': 'want', 'turn': 'case', 'component': 'criterion', 'value': '交付查询条件',
                             'scope': 'request', 'trace_refs': []},
                            {'id': 'u', 'side': 'want', 'turn': 't1', 'component': 'user', 'value': '红色的鞋',
                             'scope': 'request', 'trace_refs': []}], 'missing': [], 'sha256': 'x'}
    only_criterion = {'expectations': [{'expectation_id': 'E1', 'source_refs': ['c'], 'about': '查询', 'statement': '交付查询条件',
                                        'condition': '总是', 'ambiguity_group': ''}]}
    with pytest.raises(ValueError, match='必须引用本轮用户原话'):
        axis.validate(only_criterion, material)
