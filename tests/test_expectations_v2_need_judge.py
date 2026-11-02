"""Offline v2 need boundary and project-local frozen-E main judge contracts."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from impl.core.judge import finalize_judge_result
from impl.core.schema import RunTrace
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.eval_axes.adapters import expectations
from impl.projects.llm_probe import need_judge


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('No network allowed in need judge tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)


def trace():
    return RunTrace(trace_id='need-test', project_id='llm_probe', case_id='need-test',
        normalized_request={'body': {'messages': [
            {'role': 'system', 'content': 'DESIGN_SENTINEL'},
            {'role': 'user', 'content': '保单P1'},
            {'role': 'assistant', 'content': '上次的回答'},
            {'role': 'user', 'content': '当前状态呢？'},
        ]}},
        extracted_output={'output_text': '交费有效'},
        project_fields={'business_trace': {'records': {'calls': [
            {'pre': {'messages': [
                {'role': 'system', 'content': 'DESIGN_SENTINEL'},
                {'role': 'user', 'content': '保单P1'},
                {'role': 'assistant', 'content': '上次的回答'},
                {'role': 'user', 'content': '当前状态呢？'},
                {'role': 'tool', 'content': 'TOOL_SENTINEL'},
            ], 'tools': [{'description': 'TOOL_DESIGN_SENTINEL'}],
                'optional_params': {'response_format': {'type': 'json_object'}}},
             'post': {'content': 'ACTUAL_SENTINEL'}},
            {'pre': {'messages': [{'role': 'user', 'content': 'LATER_SENTINEL'}]}}
        ], 'definitions': [{'system_message': 'TEMPLATE_SENTINEL'}]}}})


def entry(refs=None):
    return {'expectation_id': 'E1', 'source_refs': refs or ['t1.user'], 'about': '保单状态',
            'statement': '告知当前状态', 'condition': '总是', 'ambiguity_group': ''}


def frozen():
    material = project_requirements(trace())
    es = [{**entry(), 'expectation_id': 't1.E1', 'turn': 't1'}]
    return dict(expectations=es, sources=material['sources'], missing=material['missing'],
                material_sha256=material['sha256'], verdict='complete',
                sha256=hashlib.sha256(json.dumps(es, ensure_ascii=False, sort_keys=True).encode()).hexdigest())


def test_need_material_excludes_design_and_actual_and_later_calls():
    material = project_requirements(trace(), {'description': '保险业务背景', 'criterion': '回应所问',
        'capability': 'CAPABILITY_SENTINEL', 'downstream': ['DOWNSTREAM_SENTINEL']})
    text = json.dumps(material, ensure_ascii=False)
    assert 'SENTINEL' not in text
    assert [(s['id'], s['side'], s['component']) for s in material['sources']][-2:] == [
        ('scenario.description', 'background', 'description'), ('scenario.criterion', 'want', 'criterion')]
    assert material['missing'] == [{'turn': 'case', 'component': 'capability', 'reason': 'capability 未拆分'}]
    assert 't1.c1.m4' in text


def test_design_and_downstream_changes_do_not_change_material_hash():
    t = trace()
    original = project_requirements(t)
    records = t.project_fields['business_trace']['records']
    records['definitions'] = [{'system_message': 'CHANGED'}]
    records['calls'][0]['post'] = {'content': 'CHANGED ANSWER'}
    assert original == project_requirements(t, {'downstream': ['ignored']})
    assert not original['missing']


@pytest.mark.parametrize('refs', [['scenario.description'], ['t1.history.1'], ['scenario.description', 't1.history.1']])
def test_background_and_history_cannot_independently_generate_need(refs):
    material = project_requirements(trace(), {'description': '背景'})
    with pytest.raises(ValueError, match='不能独立'):
        expectations.validate({'expectations': [entry(refs)]}, material)
    expectations.validate({'expectations': [entry(['t1.user', *refs])]}, material)


def test_reject_design_source_even_if_payload_tries_to_use_it():
    material = project_requirements(trace())
    material['sources'].append(dict(id='design', side='commitment', component='system'))
    with pytest.raises(ValueError, match='需求材料只能'):
        expectations.validate({'expectations': [entry(['design'])]}, material)


@pytest.mark.parametrize('capability', ['legacy mixed', ' '])
def test_capability_always_partial_with_user(monkeypatch, capability):
    material = project_requirements(trace(), {'capability': capability})
    class Client:
        def complete_json(self, system, prompt, **kw):
            assert capability != 'legacy mixed' or capability not in prompt
            return {'expectations': [entry()]}
        def usage(self): return {}
    monkeypatch.setattr(expectations, 'axis_llm', lambda *a, **k: Client())
    runtime = SimpleNamespace(spec=None, trace_id='test', ensure_time_left=lambda _: None)
    output = expectations.run({'requirements': material}, None, runtime).output
    assert output['verdict'] == 'partial'
    assert output['missing'][0]['reason'] == 'capability 未拆分'


def test_frozen_main_projection_keeps_id_hash_and_condition(monkeypatch):
    e = frozen()
    original = copy.deepcopy(e)
    calls = []
    class Client:
        def complete_json(self, system, prompt, **kw):
            material = json.loads(prompt)
            calls.append((kw['stage'], material))
            assert material['E'] == e
            if kw['stage'] == 'llm_probe_need_blocking':
                assert set(material) == {'E'}  # no actual, capability or design inputs
                return {'expectations_sha256': e['sha256'], 'items': [{'expectation_id': 't1.E1', 'blocking': True}]}
            return {'expectations_sha256': e['sha256'], 'items': [{'expectation_id': 't1.E1',
                'status': 'fulfilled', 'observed': '答复为交费有效', 'downstream_impact': '用户获得状态'}],
                'reasoning_summary': '状态已交付'}
    monkeypatch.setattr(need_judge, 'axis_llm', lambda *a, **kw: Client())
    result = finalize_judge_result(need_judge.run_need_judge(None, trace(), e, {'user_prompt_extras': {'output': '交费有效'}}))
    assert result.overall_fulfillment['status'] == 'fulfilled'
    assert e == original
    assert result.expected == {}  # live-schema reference shape; E identity lives on the evidence refs
    assert result.business_expectations[0].evidence_refs[0]['expectations_sha256'] == e['sha256']
    assert result.fulfillment_assessments[0].evidence_refs[0]['expectations_sha256'] == e['sha256']
    assert result.business_expectations[0].expected_outcome == e['expectations'][0]['statement']
    assert result.business_expectations[0].acceptance_criteria == [{'condition': '总是', 'ambiguity_group': ''}]
    assert result.fulfillment_assessments[0].expectation_id == 't1.E1'
    assert len(calls) == 2


@pytest.mark.parametrize('bad', ['hash', 'missing', 'duplicate', 'invented', 'self_derived'])
def test_main_strict_response_contract_rejects_invalid_e_references(bad):
    e = frozen()
    payload = {'expectations_sha256': e['sha256'], 'items': [{'expectation_id': 'E1', 'blocking': True}]}
    if bad == 'hash': payload['expectations_sha256'] = 'other'
    if bad == 'missing': payload['items'] = []
    if bad == 'duplicate': payload['items'] *= 2
    if bad == 'invented': payload['items'][0]['expectation_id'] = 'E2'
    if bad == 'self_derived': payload['business_expectations'] = [entry()]
    with pytest.raises(ValueError):
        need_judge._validate(payload, need_judge.StructuredOutputSpec.from_dataclass(need_judge.BlockingProjection), e)


def test_missing_frozen_e_blocks_main_instead_of_self_deriving(monkeypatch):
    from impl.projects.llm_probe import eval_axes
    from impl.projects.llm_probe.judge import ProcessJudgeExecution
    from tests.test_process_main_judge import report
    r = report()
    r['results'] = [item for item in r['results'] if item['type_id'] != 'expectations']
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider': 'agno'})
    monkeypatch.setattr(eval_axes, 'build_report', lambda *a: r)
    monkeypatch.setattr(need_judge, 'run_need_judge', lambda *a: pytest.fail('no E, no judgment'))
    result = ProcessJudgeExecution().run(SimpleNamespace(spec=None), trace(), None)
    assert result.overall_fulfillment['status'] == 'not_evaluable'
    assert 'expectations_failed' in result.evidence


def test_description_only_does_not_require_nonempty_e():
    material = project_requirements(SimpleNamespace(), {'description': '只是业务背景'})
    expectations.validate({'expectations': []}, material)
    assert material['missing'] == [{'turn': 't1', 'component': 'user', 'reason': '用户原文未独立记录'}]


def test_changed_frozen_content_rejected_before_client(monkeypatch):
    e = frozen()
    e['expectations'][0]['statement'] = '改成答案'
    monkeypatch.setattr(need_judge, 'axis_llm', lambda *a, **kw: pytest.fail('must not call client'))
    with pytest.raises(ValueError, match='内容指纹不匹配'):
        need_judge.run_need_judge(None, trace(), e, {})


def test_needs_are_written_per_turn_without_later_turns(monkeypatch):
    """每轮一份（spec/alg/expectations.md §2.1）：写第 1 轮时看不到第 2 轮；判准只在最后一轮，背景每轮都带。"""
    src = lambda ref, side, turn, component, value: dict(id=ref, side=side, turn=turn, component=component, value=value,
                                                        scope='request', trace_refs=[])
    material = {'sources': [src('t1.user', 'want', 't1', 'user', '查伏云平'),
                            src('t2.history.0', 'history', 't2', 'history', {'role': 'user', 'content': '查伏云平'}),
                            src('t2.user', 'want', 't2', 'user', '说错了，是余昕雅'),
                            src('scenario.description', 'background', 'case', 'description', '保险业务'),
                            src('scenario.criterion', 'want', 'case', 'criterion', '承接更正')],
                'missing': [], 'sha256': 'x'}
    prompts = []

    class Client:
        def complete_json(self, system, prompt, **kw):
            body = json.loads(prompt)
            prompts.append([s['id'] for s in body['sources']])
            want = next(s['id'] for s in body['sources'] if s['side'] == 'want')
            return {'expectations': [{**entry([want]), 'expectation_id': 'E1'}]}
        def usage(self): return {}
    monkeypatch.setattr(expectations, 'axis_llm', lambda *a, **k: Client())
    runtime = SimpleNamespace(spec=None, trace_id='test', ensure_time_left=lambda _: None)
    out = expectations.run({'requirements': material}, None, runtime).output
    assert prompts == [['t1.user', 'scenario.description'],
                       ['t2.history.0', 't2.user', 'scenario.description', 'scenario.criterion']]
    assert [(e['expectation_id'], e['turn']) for e in out['expectations']] == [('t1.E1', 't1'), ('t2.E1', 't2')]
    expectations.validate_frozen(out)
    out['expectations'][0]['source_refs'] = ['t2.user']
    with pytest.raises(ValueError, match='本轮或整案'):
        expectations.validate_frozen(out)
