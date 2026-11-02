"""Demand P1–P7 exercised through the same output/aggregation/clustering boundaries as production."""
import copy
import pytest

from impl.core.axes_clustering import build_material
from impl.core.table_view import eval_axes_summary
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import validate_issue_references
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES


def problem(pid, axes, observed='目标记录没有返回'):
    return dict(problem_id=pid, phenomenon=observed, expected='应返回目标记录', observed=observed,
                source_refs=['case'], input_refs=['request'], output_refs=['response'],
                attribution_axes=axes, impact='yes')


def unit(outcome, *, link='q1', problems=(), upstream=()):
    return dict(obligation_id='check', link_id=link, outcome=outcome, expected='应返回目标记录',
                observed='实际结果', source_refs=['case'], evidence={'input': ['request'], 'output': ['response']},
                missing=['输入或输出不可见'] if outcome == 'insufficient_evidence' else [],
                judged_by='llm', flags=[], problems=list(problems), upstream_issue_ids=list(upstream),
                origin='runtime_recall')


def outcome(axis, *units):
    ob = common.Obligation('check', 'knowledge_data', '需要数据', '应返回目标记录', source='case')
    return common._outcome(list(units), {'check': ob}, '核对后的理由', '请求与返回', [], {}, axis_id=axis)


def as_report(axis, result):
    return dict(type_id=axis, axis_id=axis, status='succeeded', verdict=result.output['assessment']['verdict'],
                output=result.output, summary=result.summary.as_dict())


def test_p1_missing_query_is_untested_but_missing_data_is_problematic():
    planning = outcome('planning_routing', unit('fail', problems=[problem('plan-q1', ['planning_routing'])]))
    data = outcome('knowledge_data', unit('input_invalid', upstream=['plan-q1']))
    validate_issue_references({'planning_routing': planning.output, 'knowledge_data': data.output})
    assert data.output['assessment']['verdict'] == 'untested'
    assert data.output['issues'] == []
    assert data.output['assessment']['composition']['input_invalid'][0]['upstream_issue_ids'] == ['plan-q1']
    queried = outcome('knowledge_data', unit('fail', problems=[problem('data-q1', ['knowledge_data'])]))
    assert queried.output['assessment']['verdict'] == 'problematic'


def test_p2_unresolved_problem_does_not_inflate_two_defect_rates():
    issue = problem('empty-return', ['tool_execution', 'knowledge_data'])
    tool = outcome('tool_execution', unit('insufficient_evidence', problems=[issue]))
    data = outcome('knowledge_data', unit('insufficient_evidence', problems=[issue]))
    validate_issue_references({'tool_execution': tool.output, 'knowledge_data': data.output})
    assert {o.output['assessment']['verdict'] for o in (tool, data)} == {'not_evaluable'}
    assert {p['problem_id'] for o in (tool, data) for p in o.output['issues']} == {'empty-return'}
    assert tool.output['issues'][0]['attribution'] == 'unresolved'


def test_p3_invalid_input_does_not_exempt_independent_fabrication():
    context = outcome('context_memory', unit('fail', problems=[problem('lost-prompt', ['context_memory'])]))
    model = outcome('model_capability', unit('input_invalid', upstream=['lost-prompt']), unit('pass', link='no-fabrication'))
    validate_issue_references({'context_memory': context.output, 'model_capability': model.output})
    assert model.output['assessment']['verdict'] == 'sound'
    assert model.output['assessment']['composition']['counts']['input_invalid'] == 1
    bad = outcome('model_capability', unit('input_invalid', upstream=['lost-prompt']),
                  unit('fail', link='no-fabrication', problems=[problem('made-up-date', ['model_capability'])]))
    assert bad.output['assessment']['verdict'] == 'problematic'


def test_p4_p5_composition_survives_table_projection():
    for first, rest, verdict in [('fail', 'insufficient_evidence', 'problematic'), ('pass', 'contract_missing', 'sound')]:
        p = [problem('bad-data', ['knowledge_data'])] if first == 'fail' else []
        result = outcome('knowledge_data', unit(first, problems=p), unit(rest, link='q2'))
        rows = eval_axes_summary({'results': [as_report('knowledge_data', result)]})
        assert rows[0]['verdict'] == verdict
        assert rows[0]['composition']['counts'][rest] == 1
        assert len(result.output['assessment']['contract_missing']) == (rest == 'contract_missing')


def test_p7_clustering_members_are_atomic_problems_and_keep_attribution():
    result = outcome('knowledge_data', unit('fail', problems=[problem('missing', ['knowledge_data']),
                          problem('version', ['knowledge_data'], '返回版本错误')]))
    rows = eval_axes_summary({'results': [as_report('knowledge_data', result)]})
    material = build_material([{'pool_index': 0, 'request_key': 'run:0', 'axes': rows}], [AXIS_TYPES['knowledge_data'].describe()])
    records = material['axes'][0]['labels'][0]['records']
    assert len(records) == 2
    assert {r['issue_id'] for r in material['refs'].values()} == {'missing', 'version'}
    assert all(r['reason'] != result.summary.text for r in records)
    assert all(r['issue']['attribution_axes'] == ['knowledge_data'] for r in records)


def test_unknown_or_local_upstream_references_are_rejected():
    bad = outcome('knowledge_data', unit('input_invalid', upstream=['missing']))
    with pytest.raises(ValueError, match='上游问题'):
        validate_issue_references({'knowledge_data': bad.output})
    local = outcome('knowledge_data', unit('fail', problems=[problem('local', ['knowledge_data'])]),
                    unit('input_invalid', link='q1', upstream=['local']))
    with pytest.raises(ValueError, match='上游问题'):
        validate_issue_references({'knowledge_data': local.output})


def test_fail_without_problem_and_unresolved_fail_are_rejected():
    with pytest.raises(ValueError, match='问题记录'):
        outcome('knowledge_data', unit('fail'))
    with pytest.raises(ValueError, match='未定位'):
        outcome('knowledge_data', unit('fail', problems=[problem('u', ['tool_execution', 'knowledge_data'])]))


def test_missing_required_exercise_is_enumerated_with_evidence_and_cannot_be_na():
    from impl.projects.llm_probe.process_loop.expectation_projection import required_units
    e = {'sources': [{'id': 'u', 'side': 'want', 'turn': 't1'}],
         'expectations': [{'expectation_id': 'q1', 'source_refs': ['u'], 'about': '查询保单'}]}
    links = required_units('knowledge_data', e, {'data_needs': [
        {'expectation_id': 'q1', 'need': 'tool', 'tool_expectation_ids': []}]})
    assert len(links) == 1 and links[0]['link_id'] == 'knowledge_data:expected:q1' and not links[0]['output']
    r = unit('not_applicable', link=links[0]['link_id'])
    with pytest.raises(ValueError, match='应发生'):
        common.validate_result_evidence([r], {'check': common.Obligation('check', 'knowledge_data', 's', 'd')},
                                       {links[0]['link_id']: links[0]}, {'request', 'response'})


def test_registered_verdicts_and_obligations_match_protocol():
    for axis in common.PROCESS_SPECS:
        assert 'untested' in AXIS_TYPES[axis].verdict_values
        assert 'issues' in AXIS_TYPES[axis].output_fields
    assert 'no_fabrication' in {ob.obligation_id for ob in common.PROCESS_SPECS['model_capability'].obligations}
    assert 'empty_or_rejection_expected' not in {ob.obligation_id for ob in common.PROCESS_SPECS['tool_execution'].obligations}


def test_issue_sources_project_original_trace_and_evaluation_time_criterion():
    ob = common.Obligation('check', 'knowledge_data', '需要数据', '应返回目标记录', source='case')
    row = unit('fail', problems=[problem('missing', ['knowledge_data'])])
    result = common._outcome([row], {'check': ob}, 'reason', 'scope', [], {},
                             axis_id='knowledge_data', criterion='ORIGINAL CASE REQUIREMENT')
    report = {'results': [
        {'type_id': 'trace_analysis', 'output': {'dossier': {
            'records': [{'id': 'request', 'body': {'content_ref': 'body1'}},
                        {'id': 'response', 'body': 'EMPTY QUERY RESULT'}],
            'contents': {'body1': 'ORIGINAL QUERY'}}}},
        as_report('knowledge_data', result)]}
    projected = eval_axes_summary(report)[1]['evidence_records']
    assert projected['case'] == 'ORIGINAL CASE REQUIREMENT'
    assert projected['request']['body'] == 'ORIGINAL QUERY'
    assert projected['response']['body'] == 'EMPTY QUERY RESULT'
