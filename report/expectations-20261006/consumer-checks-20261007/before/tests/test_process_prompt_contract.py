"""Prompt/schema/evidence agreement, including adversarial inputs and final coverage repair."""
import copy
import json
from types import SimpleNamespace

import pytest

from impl.core.structured_output import StructuredOutputSpec, enforce_output, render_output_constraint
from impl.projects.llm_probe.process_contract import AXIS_DESCRIPTIONS, source_in_inputs
from impl.projects.llm_probe.eval_axes.adapters import process_common as common, expectations
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import PROTOCOL_PROMPT
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.process_loop import analysis, evaluation, llmtracing
from impl.projects.llm_probe.process_loop import expectation_projection as projection
from tests.test_expectations import fixture, result
from tests.test_process_axis_investigation import dossier, result as group_result
from tests.test_llmtracing_tool_loop import ScriptClient, material as transcript_material


def test_prompts_schema_and_runtime_share_named_axes():
    schemas = [StructuredOutputSpec.from_dataclass(common.ProcessAssessment).json_schema(), llmtracing.OUTPUT.json_schema()]
    for schema in schemas:
        assert set(schema['$defs']['Problem']['properties']['attribution_axes']['items']['enum']) == set(AXIS_DESCRIPTIONS)
        assert 'expected' not in schema['$defs']['ResultGroup']['properties']
        assert schema['$defs']['ResultGroup']['properties']['matched_link_id']['minLength'] == 0
    assert set(projection.JOIN_SPEC.json_schema()['$defs']['ContractBinding']['properties']['axes']['items']['enum']) == set(AXIS_DESCRIPTIONS)
    for prompt in [common._MATERIAL_SYSTEM, analysis.SYSTEM, evaluation.SYSTEM, llmtracing.SYSTEM, projection.JOIN_SYSTEM, expectations.SYSTEM]:
        assert not any(c in prompt for c in 'ικρσμχΛ')
    assert 'dossier_collect' not in common._MATERIAL_SYSTEM
    assert '有 problems 或 upstream_issue_ids' in PROTOCOL_PROMPT
    assert '只输出符合 schema 的 JSON' not in evaluation.SYSTEM
    assert '共享会话的 briefing.links' in evaluation.SYSTEM
    assert '没有 dimension 单轴字段' in evaluation.SYSTEM
    assert '若提供 recorded_issues' in evaluation.SYSTEM
    assert 'source_refs 是判准出处' in common._MATERIAL_SYSTEM


def test_project_obligation_config_uses_the_same_axis_ids_as_link_schema():
    from impl.core.capability_store import load_capability_map
    from impl.projects.llm_probe.business_trace.links import LINK_TYPES

    capability_map = load_capability_map('llm_probe')
    for capability in ('insurance-agno-e2e', 'insurance-llmtracing'):
        obligations = capability_map[capability]['process_obligations']
        assert len(obligations) == 1
        assert obligations[0]['link_type'] in LINK_TYPES
        assert obligations[0]['applies_to'] == ['planning_routing:repeat']
        assert common.project_obligations(capability_map[capability], 'planning_routing')[0].obligation_id == 'project:retry_after_non_retryable'


def test_transcript_prompt_maps_source_id_to_readable_evidence_id():
    from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation
    from tests.support.expectations import E, PROJECTION

    frozen = copy.deepcopy(E)
    frozen['sources'] = [dict(id='t1.user', side='want', component='user', value='Check device A.',
                              scope='request', trace_refs=['t1.c1.m2', 'unavailable'])]
    client = ScriptClient(['done'])
    evaluator = TranscriptEvaluation(transcript_material(), {'context_memory': common.PROCESS_SPECS['context_memory']},
                                     {'context_memory': 'Check device A.'}, None, client, trace_id='contract-map',
                                     expectations=frozen, projection=PROJECTION)
    evaluator.run()
    prompt = json.loads(client.requests[0][-1]['content'])
    assert prompt['source_to_evidence']['t1.user'] == ['t1.c1.m2']
    assert 't1.user' not in {row['id'] for row in prompt['evidence']}


def test_confirmed_project_obligation_is_its_own_criterion_not_an_invented_expectation():
    _, frozen, _ = fixture()
    ob = common.Obligation('project:retry_after_non_retryable', 'planning_routing', '重复调用',
                           '不可重试后拦住同参重发', source='project')
    group = result('project:retry_after_non_retryable', 'planning_routing:repeat', 'pass', ids=())
    group['source_refs'] = ['project:retry_after_non_retryable']
    projection.bind_results([group], {ob.obligation_id: ob}, frozen)
    assert group['expected'] == ob.duty
    assert group['expectation_ids'] == []
    group['source_refs'] = []
    with pytest.raises(ValueError, match='项目义务必须引用'):
        projection.bind_results([group], {ob.obligation_id: ob}, frozen)


def test_confirmed_project_breach_can_generate_a_problem_without_inventing_e():
    _, frozen, _ = fixture()
    ob = common.Obligation('project:retry_after_non_retryable', 'planning_routing', '重复调用',
                           '不可重试后拦住同参重发', source='project')
    row = result(ob.obligation_id, 'planning_routing:repeat', 'fail', ids=())
    row['source_refs'] = [ob.obligation_id]
    row['problems'] = [dict(problem_id='non-retryable-repeat', phenomenon='不可重试后仍同参重发',
        expectation_ids=[], observed='工具明确不可重试后仍同参重发', source_refs=[ob.obligation_id],
        input_refs=['rule'], output_refs=['repeat'], attribution_axes=['planning_routing'], impact='unknown')]
    bad = copy.deepcopy(row)
    bad['problems'][0]['source_refs'] = ['obligation:' + ob.obligation_id]
    with pytest.raises(ValueError, match='项目义务问题必须引用'):
        projection.bind_results([bad], {ob.obligation_id: ob}, frozen)
    projection.bind_results([row], {ob.obligation_id: ob}, frozen)
    assert row['problems'][0]['expected'] == ob.duty
    assert row['problems'][0]['expectation_ids'] == []
    assert row['problems'][0]['source_refs'] == [ob.obligation_id]


def test_transcript_briefing_states_contract_coverage_separately_from_pending():
    from tests.support.expectations import E, PROJECTION
    frozen = copy.deepcopy(E)
    frozen['sources'] = [dict(id='system-rule', side='commitment', component='system', turn='t1', value='不得丢失状态')]
    frozen['expectations'] = [dict(expectation_id='explicit-commitment', source_refs=['system-rule'],
        about='状态传递', statement='不得丢失状态', condition='存在状态时', ambiguity_group='')]
    projected = copy.deepcopy(PROJECTION)
    projected['contracts'] = [dict(expectation_id='explicit-commitment', axes=['context_memory'])]
    client = ScriptClient(['done'])
    evaluator = llmtracing.TranscriptEvaluation(transcript_material(), {'context_memory': common.PROCESS_SPECS['context_memory']},
        {'context_memory': 'criterion'}, None, client, trace_id='coverage-briefing',
        expectations=frozen, projection=projected)
    evaluator.run()
    briefing = json.loads(client.requests[0][-1]['content'])['axes'][0]
    assert briefing['coverage_required'] == ['explicit-commitment']
    assert briefing['pending']
    assert '两项独立要求' in llmtracing.SYSTEM
    assert 'source=trace 或 case' in llmtracing.SYSTEM


def test_greek_axis_is_rejected_by_the_declared_schema_not_only_late_validator():
    payload = group_result(['visible'])
    payload['results'][0]['problems'][0]['attribution_axes'] = ['χ']
    with pytest.raises(ValueError):
        enforce_output(payload, StructuredOutputSpec.from_dataclass(common.ProcessAssessment), caller='test')
    payload['results'][0]['problems'][0]['attribution_axes'] = ['knowledge_data']
    enforce_output(payload, StructuredOutputSpec.from_dataclass(common.ProcessAssessment), caller='test')


def test_instruction_container_requires_all_original_rules_in_this_call():
    source = {'component': 'system', 'value': {'instructions': ['禁止编造', '完整输出 JSON']}}
    actual = {'messages': [{'role': 'system', 'content': '规则：禁止编造。完整输出 JSON。'}]}
    assert source_in_inputs(source, [actual])
    assert not source_in_inputs(source, [{'messages': [{'role': 'system', 'content': '禁止编造'}]}])
    assert not source_in_inputs(source, [{'messages': [{'role': 'user', 'content': '禁止编造。完整输出 JSON。'}]}])
    assert not source_in_inputs(source, [{'kind': 'message', 'role': 'user', 'origin': 'model_request',
                                          'text': '禁止编造。完整输出 JSON。'}])
    assert source_in_inputs(source, [{'kind': 'system', 'origin': 'model_request',
                                      'text': '禁止编造。完整输出 JSON。'}])
    assert not source_in_inputs(source, [])
    assert not source_in_inputs({**source, 'value': {'instructions': []}}, [actual])
    assert not source_in_inputs({**source, 'value': {'instructions': ['禁止编造'], 'unknown_wrapper': 'x'}}, [actual])


def test_model_source_match_never_borrows_other_call_or_rewrites_source():
    _, e, _ = fixture()
    e['sources'][0].update(component='system', value={'instructions': ['禁止编造', '完整输出 JSON']})
    row = result('output_faithful', 'model_capability:call', 'pass')
    row['evidence']['input'] = ['call']
    ob = {'output_faithful': common.PROCESS_SPECS['model_capability'].obligations[0]}
    links = {'model_capability:call': {'input': [{'ref': 'call', 'field': 'exact_request'}]}}
    data = {'records': [{'id': ident, 'fields': {'exact_request': {'value': {'messages': [{'role': 'system', 'content': text}]}}}}
                        for ident, text in [('call', '禁止编造'), ('other', '禁止编造。完整输出 JSON')]]}
    frozen = copy.deepcopy(e)
    with pytest.raises(ValueError, match='expectation_id=Q'):
        projection.validate_dossier_expectations([row], ob, e, links, data)
    data['records'][0]['fields']['exact_request']['value'] = data['records'][1]['fields']['exact_request']['value']
    projection.validate_dossier_expectations([row], ob, e, links, data)
    assert frozen == e


def test_last_batch_coverage_is_explicit_and_repairable_before_axis_commit(monkeypatch):
    data = dossier()
    e = {'expectations': [dict(expectation_id='K', source_refs=['rules'], about='数据适用范围',
                             statement='不得把历史数据当实时值', condition='使用历史数据时', ambiguity_group='')],
         'sources': [dict(id='rules', side='commitment', component='system', turn='t1', value='不得把历史数据当实时值')],
         'missing': [], 'sha256': 'frozen'}
    projected = {'contracts': [{'expectation_id': 'K', 'axes': ['knowledge_data']}], 'data_needs': []}
    prompts = []
    class Client:
        def complete_json(self, system, user, **kwargs):
            p, _ = json.JSONDecoder().raw_decode(user)
            prompts.append((p, user, system + render_output_constraint(kwargs['output_spec'])))
            assert p['coverage_required'] == ['K']
            assert 'visible' in p['reference_catalog']['readable_ids']
            assert 'visible/result' not in p['reference_catalog']['readable_ids']
            pairs = [(ob, link) for ob, links in p['pending'].items() for link in links]
            reply = group_result(['visible'], outcome='not_applicable', pairs=pairs)
            if len(prompts) == 2:
                for group in reply['results']:
                    group.update(expectation_ids=['K'], expectation_checks=[{'expectation_id': 'K', 'outcome': 'not_applicable',
                        'observed': '本次只有静态材料，没有历史数据用于实时结论，条件不成立。'}])
            return reply
        def usage(self): return {'llm_calls': len(prompts)}
    monkeypatch.setattr(common, 'axis_llm', lambda *a, **kw: Client())
    runtime = SimpleNamespace(spec=SimpleNamespace(project_id='llm_probe'), scenario_id='none',
        trace_id='contract-test', ensure_time_left=lambda *_: None, expectation_projection=projected)
    out = common.run_process_axis('knowledge_data', {'expectations': e, 'trace_analysis': {'dossier': data,
        'structure': {}, 'coverage': [], 'selections': {'knowledge_data': {'refs': ['visible']}}}},
        ScenarioAxis('knowledge_data', True, ''), runtime, common.PROCESS_SPECS['knowledge_data'])
    assert len(prompts) == 2
    assert '承诺侧期望未核对' in prompts[1][1]
    assert prompts[0][0] == prompts[1][0]
    assert out.output['results'][0]['expectation_ids'] == ['K']


def test_cross_field_outcome_rule_is_stated_and_still_enforced():
    _, e, _ = fixture()
    row = result(outcome='pass')
    row['expectation_checks'][0]['outcome'] = 'insufficient_evidence'
    ob = {'work_coverage': common.PROCESS_SPECS['planning_routing'].obligations[2]}
    assert '不是投票' in PROTOCOL_PROMPT
    with pytest.raises(ValueError, match='单位结论必须保留'):
        projection.bind_results([row], ob, e)
