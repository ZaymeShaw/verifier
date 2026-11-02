"""Six judges: obligation × link pairing, grouped output, structural checks, and no post-hoc semantic override."""
import json
from types import SimpleNamespace

from tests.support.expectations import E, PROJECTION

import pytest

from impl.core.capability_store import validate_entry
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

SIX = ('intent_understanding', 'planning_routing', 'tool_execution', 'context_memory', 'knowledge_data', 'model_capability')
RUNTIME = SimpleNamespace(spec=SimpleNamespace(project_id='llm_probe'), scenario_id='no-such-scenario',
                          trace_id='x', ensure_time_left=lambda _: None, expectation_projection=PROJECTION)
ABSENT = [(common.ABSENT_OBLIGATION, 'knowledge_data:none')]


def link(link_id, link_type, facts=None):
    return {'link_id': link_id, 'link_type': link_type, 'turn': 'turn1', 'input': [{'ref': 'a', 'field': 'x'}],
            'output': [{'ref': 'b', 'field': 'y'}], 'facts': facts or {}}


def llm_result(ob, link_id, outcome='pass', refs=('a',), **extra):
    return {'obligation_id': ob, 'link_id': link_id, 'outcome': outcome, 'expected': 'e', 'observed': 'o',
            'source_refs': [], 'evidence': {'input': list(refs), 'output': list(refs)}, 'missing': [],
            'judged_by': 'llm', **extra}


@pytest.mark.parametrize('outcomes,expected', [
    (['pass', 'insufficient_evidence'], ('not_evaluable', 'any_insufficient_evidence')),
    (['fail', 'insufficient_evidence'], ('problematic', 'any_fail')),
    (['not_applicable'], ('not_applicable', 'none_applicable')),
    (['pass', 'not_applicable'], ('sound', 'any_pass')),
    (['pass', 'contract_missing'], ('sound', 'any_pass')),          # 契约缺失单列，不拉低也不支撑 sound
    (['contract_missing'], ('not_evaluable', 'only_contract_missing')),
    ([], ('not_evaluable', 'no_results'))])
def test_aggregation_does_not_count_missing_or_na_as_pass(outcomes, expected):
    assert common.aggregate_verdict([{'outcome': o} for o in outcomes]) == expected


def test_scoped_obligations_claim_their_links_and_generic_covers_the_rest():
    obligations = common.PROCESS_SPECS['context_memory'].obligations
    links = [link('context_memory:input:c1', 'context_memory'), link('context_memory:deliver:turn1', 'context_memory'), link('context_memory:step:a→b', 'context_memory', {'contains': True}),
             link('context_memory:offmap:x', 'context_memory')]
    decided, pending = common.pair_up(obligations, links)
    assert decided[('arrives_intact', 'context_memory:step:a→b')]['judged_by'] == 'program'
    assert decided[('arrives_intact', 'context_memory:step:a→b')]['outcome'] == 'pass'
    assert pending == [('input_assembled', 'context_memory:input:c1'), ('history_and_state', 'context_memory:input:c1'),
                       ('delivered_intact', 'context_memory:deliver:turn1'), ('arrives_intact', 'context_memory:offmap:x')]


def test_project_declaration_adds_pairs_without_removing_the_generic_fallback():
    entry = {'process_obligations': [{'id': 'retry_rule', 'link_type': 'planning_routing', 'applies_to': ['planning_routing:repeat'],
                                      'situation': 's', 'duty': 'd', 'confirmed': '2026-09-29'}]}
    extra = common.project_obligations(entry, 'planning_routing')
    assert [ob.obligation_id for ob in extra] == ['project:retry_rule']
    assert common.project_obligations(entry, 'tool_execution') == ()
    obligations = common.PROCESS_SPECS['planning_routing'].obligations + extra
    _, pending = common.pair_up(obligations, [link('planning_routing:repeat:t1', 'planning_routing'), link('planning_routing:offmap:q', 'planning_routing')])
    assert pending == [('repeat_justified', 'planning_routing:repeat:t1'), ('project:retry_rule', 'planning_routing:repeat:t1'),
                       ('decision_matches_rule', 'planning_routing:offmap:q')]
    with pytest.raises(ValueError, match='不是环节类型'):
        common.project_obligations({'process_obligations': [{**entry['process_obligations'][0], 'link_type': 'Z'}]},
                                   'planning_routing')


def test_capability_entry_validates_process_obligations():
    ok = {'id': 'retry_rule', 'link_type': 'planning_routing', 'situation': 's', 'duty': 'd', 'confirmed': '2026-09-29',
          'applies_to': ['planning_routing:repeat'], 'label': '标签'}
    entry = validate_entry('insurance', {'capability': '回答保险问题', 'process_obligations': [ok]})
    assert entry['process_obligations'] == [ok]
    for broken, pattern in [({**ok, 'id': 'Bad-Id'}, 'id'), ({**ok, 'duty': ''}, 'duty'),
                            ({**ok, 'confirmed': '29/09/2026'}, 'confirmed'), ({**ok, 'applies_to': 'planning_routing:repeat'}, 'applies_to')]:
        with pytest.raises(ValueError, match=pattern):
            validate_entry('insurance', {'capability': '回答保险问题', 'process_obligations': [broken]})
    with pytest.raises(ValueError, match='重复|unique|唯一'):
        validate_entry('insurance', {'capability': '回答保险问题', 'process_obligations': [ok, ok]})


def test_coverage_is_exactly_once():
    pending = [('a', 'l1'), ('a', 'l2')]
    common.check_coverage([llm_result('a', 'l1'), llm_result('a', 'l2')], pending)
    for results, word in [([llm_result('a', 'l1')], '遗漏'), ([llm_result('a', 'l1')] * 2 + [llm_result('a', 'l2')], '重复'),
                          ([llm_result('a', 'l1'), llm_result('a', 'l2'), llm_result('b', 'l1')], '未知')]:
        with pytest.raises(ValueError, match=word):
            common.check_coverage(results, pending)
    with pytest.raises(ValueError, match='missing'):
        common.check_coverage([llm_result('a', 'l1', 'insufficient_evidence'), llm_result('a', 'l2')], pending)


def test_incomplete_model_output_is_not_salvaged_into_business_gaps():
    assert not hasattr(common, 'salvage')


def test_annotate_never_downgrades_fail_and_only_demotes_unsupported_pass():
    obligations = {'a': common.Obligation('a', 'model_capability', 's', 'd', source='trace')}
    links = {'model_capability:c1': link('model_capability:c1', 'model_capability')}
    fail = llm_result('a', 'model_capability:c1', 'fail', refs=(), source_refs=['elsewhere'])
    bare_pass = llm_result('a', 'model_capability:c1', 'pass', refs=())
    common.annotate([fail, bare_pass], obligations, links, {'a', 'b', 'elsewhere'}, 'scope')
    assert fail['outcome'] == 'fail'
    assert any('两端' in f for f in fail['flags'])
    assert any('不在该次调用的输入' in f for f in fail['flags'])
    assert bare_pass['outcome'] == 'insufficient_evidence'
    special = llm_result('a', 'model_capability:c1', 'pass', source_refs=['a'])
    special['evidence']['input'] = ['case']
    common.annotate([special], obligations, links, {'a'}, 'scope')
    assert not any('读取回执' in f for f in special['flags'])


@pytest.mark.parametrize('axis_id', SIX)
def test_axis_gets_analysis_materials_without_retrieval_tools(monkeypatch, axis_id):
    dossier = {
        'records': [{'id': 'record1', 'kind': 'runs', 'turn': 'turn1', 'scope': 'current',
                     'fields': {'output': {'status': 'available', 'value': 'SELECTED BODY END'}}},
                    {'id': 'record2', 'kind': 'runs', 'turn': 'turn1', 'scope': 'current',
                     'fields': {'output': {'status': 'available', 'value': 'UNSELECTED BODY'}}}],
        'contents': {}, 'gaps': [], 'coverage': [], 'sources': [], 'model_calls': [],
        'current': [], 'history': [], 'observed_at_collection': [],
        'structure': {'route': [], 'coverage_note': '', 'suspects': []},
    }
    observed = []
    class Client:
        def complete_json(self, system, user, **kwargs):
            p = json.loads(user); observed.append(p)
            return {'reason': '缺少实际请求', 'scope_note': '当前轮', 'results': [
                {'obligation_id': ob, 'link_ids': ids, 'outcome': 'insufficient_evidence', 'expectation_ids': [], 'matched_link_id': '', 'expectation_checks': [],
                 'observed': '未保存当前步骤实际请求', 'source_refs': [], 'input_refs': ['record1'], 'output_refs': [],
                 'missing': ['当前步骤的完整请求']} for ob, ids in p['pending'].items()]}
        def usage(self): return {'llm_calls': 1}
    def factory(*args, **kwargs):
        assert not kwargs.get('tools')
        return Client()
    monkeypatch.setattr(common, 'axis_llm', factory)
    outcome = AXIS_TYPES[axis_id].run(
        {'expectations': E, 'trace_analysis': {'dossier': dossier, 'coverage': [],
                            'selections': prepare_selections(dossier, {}, {axis_id: {'refs': ['record1'], 'why': ['本轴需要的记录']}}), 'structure': {'route': []}}},
        ScenarioAxis(axis_id, True, '评判'), RUNTIME)
    assert outcome.output['assessment']['verdict'] == 'not_evaluable'
    view = observed[0]['dossier_view']
    assert [row['id'] for row in view['records']] == ['record1']
    assert 'UNSELECTED BODY' not in json.dumps(view, ensure_ascii=False)
    assert 'catalog' not in observed[0]
    assert outcome.usage['tool_calls'] == 0
    assert {l['link_type'] for l in observed[0]['links']['links']} <= set(AXIS_LINK_TYPES[axis_id])
    assert observed[0]['suspects_for_this_axis'] == ['本轴需要的记录']
    assert outcome.output['view']['excluded'] == []
    assert outcome.output['results'] and all(r['judged_by'] == 'llm' for r in outcome.output['results'])


def _run_single(monkeypatch, answers):
    class Client:
        calls = 0
        def complete_json(self, system, user, **kw):
            self.calls += 1
            answer = answers[self.calls - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer
        def usage(self): return {}
    client = Client()
    monkeypatch.setattr(common, 'axis_llm', lambda *a, **kw: client)
    dossier = {'records': [{'id': 'known', 'kind': 'runs', 'turn': 'turn1', 'scope': 'current', 'fields': {'output': {'status': 'available', 'value': 'evidence'}}}],
               'contents': {}, 'gaps': [], 'coverage': [], 'sources': [], 'model_calls': [],
               'current': [], 'history': [], 'observed_at_collection': []}
    outcome = common.run_process_axis('knowledge_data', {'expectations': E, 'trace_analysis': {'dossier': dossier, 'coverage': [],
        'selections': prepare_selections(dossier, {}, {'knowledge_data': {'refs': ['known'], 'why': []}})}},
        ScenarioAxis('knowledge_data', True, 'test'), RUNTIME, common.PROCESS_SPECS['knowledge_data'])
    return client, outcome


def _group(outcome='pass', refs=('known',), **extra):
    return {'obligation_id': ABSENT[0][0], 'link_ids': [ABSENT[0][1]], 'outcome': outcome, 'expectation_ids': [], 'matched_link_id': '', 'expectation_checks': [],
            'observed': '明确原文', 'source_refs': [], 'input_refs': list(refs), 'output_refs': [], 'missing': [], **extra}


@pytest.mark.parametrize('second', [
    {'reason': '理由', 'scope_note': '本轮', 'results': [_group(refs=())]},
    [{'reason': '理由', 'scope_note': '本轮', 'results': [_group()]}],
    '', ['not', 'an', 'object'],
    ValueError('[judge] LLM 产出不符合结构化输出约束，已阻断'),
])
def test_p6_invalid_second_attempt_is_a_run_error(monkeypatch, second):
    with pytest.raises(ValueError):
        _run_single(monkeypatch, [{'reason': '理由', 'scope_note': '本轮', 'results': []}, second])


def test_all_program_decided_axis_skips_the_model(monkeypatch):
    monkeypatch.setattr(common, 'build_links', lambda *a, **k: {'links': [link('context_memory:step:a→b', 'context_memory', {'contains': True})]})
    class Client:
        def complete_json(self, *a, **k): raise AssertionError('不应调用模型')
        def usage(self): return {}
    monkeypatch.setattr(common, 'axis_llm', lambda *a, **kw: Client())
    outcome = common.run_process_axis('context_memory', {'expectations': E, 'trace_analysis': {'dossier': {'records': [], 'contents': {}},
        'selections': prepare_selections({'records': [], 'contents': {}}, {}, {'context_memory': {}})}}, ScenarioAxis('context_memory', True, ''), RUNTIME, common.PROCESS_SPECS['context_memory'])
    assert outcome.output['assessment']['verdict'] == 'sound'
    assert outcome.output['results'][0]['judged_by'] == 'program'
