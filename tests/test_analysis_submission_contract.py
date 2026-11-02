"""Analysis submission has two explicit discovery lists, never empty-string tags."""
import copy
import json

import pytest

from impl.projects.llm_probe.eval_axes.adapters import trace_analysis
from impl.projects.llm_probe.process_loop.analysis import SUBMIT_PARAMETERS
from tests.test_trace_analysis_submission import _run_script
from tests.test_trace_analysis import snapshot
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from types import SimpleNamespace


def payload(existing=(), new=()):
    return dict(route=[], coverage_note='只描述已读证据',
                existing_link_suspects=list(existing), new_link_suspects=list(new))


def existing(ref, link_id='intent_understanding:turn1'):
    return dict(link_id=link_id, why='表达值得核查', source_refs=[ref])


def discovered(ref, link_type='tool_execution'):
    return dict(link_type=link_type, why='运行记录有表外调用',
                input_refs=[ref], output_refs=[], source_refs=[ref])


def test_schema_expresses_two_lists_without_inactive_fields_or_empty_enum():
    properties = SUBMIT_PARAMETERS['properties']
    assert set(properties) == set(SUBMIT_PARAMETERS['required']) == {
        'route', 'coverage_note', 'existing_link_suspects', 'new_link_suspects'}
    assert SUBMIT_PARAMETERS['additionalProperties'] is False
    old = properties['existing_link_suspects']['items']
    new = properties['new_link_suspects']['items']
    assert set(old['properties']) == {'link_id', 'why', 'source_refs'}
    assert set(new['properties']) == {'link_type', 'why', 'source_refs', 'input_refs', 'output_refs'}
    assert set(new['properties']['link_type']['enum']) == set(trace_analysis.LINK_TYPES) | {'unclassified'}
    assert 'new_link_type' not in json.dumps(SUBMIT_PARAMETERS)
    for item in (old, new):
        assert item['additionalProperties'] is False
        assert set(item['required']) == set(item['properties'])
        assert item['properties']['source_refs']['minItems'] == 1
    def check(node):
        if isinstance(node, dict):
            assert '' not in node.get('enum', [])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(SUBMIT_PARAMETERS)


@pytest.mark.parametrize('has_existing,has_new', [(False, False), (True, False), (False, True), (True, True)])
def test_both_lists_flow_through_read_receipts_and_downstream(monkeypatch, has_existing, has_new):
    dossier = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ref = next(r['id'] for r in dossier['records'] if r['kind'] == 'runs')
    submitted = payload([existing(ref)] if has_existing else [], [discovered(ref)] if has_new else [])
    script = [[('dossier_collect', {'ids': [ref]})], [('submit_structure', submitted)]]
    client, outcome = _run_script(monkeypatch, script)
    assert not outcome.failed, outcome.failure_reason
    assert len(client.requests) == 2
    suspects = [s for s in outcome.output['suspects'] if 'analysis' in s['origin']]
    assert len(suspects) == int(has_existing) + int(has_new)
    assert sum(bool(s.get('off_map')) for s in suspects) == int(has_new)
    if has_existing:
        old = next(s for s in suspects if not s['off_map'])
        assert old['link_id'] == 'intent_understanding:turn1'
        assert old['link_type'] == 'intent_understanding'
    if has_new:
        added = next(s for s in suspects if s['off_map'])
        assert added['link_id'] and added['link_type'] == 'tool_execution'
        assert added['input_refs'] == [ref] and added['output_refs'] == []
        from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links
        links = _axis_links('tool_execution', dossier, outcome.output['structure'])
        assert any(link['link_id'] == added['link_id'] and link['input'] == [{'ref': ref, 'field': ''}]
                   for link in links)
    # Raw model lists are a submission protocol; downstream keeps one canonical list.
    assert 'existing_link_suspects' not in outcome.output['structure']
    assert 'new_link_suspects' not in outcome.output['structure']


@pytest.mark.parametrize('mutation', [
    lambda p: p.pop('new_link_suspects'),
    lambda p: p.update(suspects=[]),
    lambda p: p['existing_link_suspects'][0].update(link_id=''),
    lambda p: p['existing_link_suspects'][0].update(link_id='invented'),
    lambda p: p['existing_link_suspects'][0].update(link_type='tool_execution'),
    lambda p: p['existing_link_suspects'][0].update(source_refs=[]),
    lambda p: p['new_link_suspects'][0].update(link_type=''),
    lambda p: p['new_link_suspects'][0].update(link_type='invented'),
    lambda p: p['new_link_suspects'][0].update(link_id='invented'),
    lambda p: p['new_link_suspects'][0].update(input_refs=[]),
    lambda p: p['new_link_suspects'][0].update(input_refs=['']),
    lambda p: p['new_link_suspects'][0].update(source_refs=[]),
    lambda p: p['new_link_suspects'][0].update(why=' '),
])
def test_invalid_or_mixed_submissions_are_rejected_not_normalized(mutation):
    submitted = payload([existing('ref')], [discovered('ref')])
    mutation(submitted)
    before = copy.deepcopy(submitted)
    with pytest.raises(ValueError):
        trace_analysis._validate(submitted, {'intent_understanding:turn1'})
    assert submitted == before


def test_new_discovery_unread_endpoint_requires_read_before_acceptance(monkeypatch):
    dossier = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ref = next(r['id'] for r in dossier['records'] if r['kind'] == 'runs')
    submitted = payload(new=[discovered(ref)])
    _, outcome = _run_script(monkeypatch, [
        [('submit_structure', submitted)],
        [('dossier_collect', {'ids': [ref]}), ('submit_structure', submitted)],
        [('submit_structure', submitted)],
    ])
    assert not outcome.failed
    assert [s['accepted'] for s in outcome.output['structure']['evidence_audit']['submissions']] == [False, False, True]
    assert next(s for s in outcome.output['suspects'] if s.get('off_map'))['source_refs'] == [ref]


def test_old_empty_string_discriminator_contract_is_rejected():
    old = dict(route=[], coverage_note='', suspects=[dict(
        link_id='intent_understanding:turn1', new_link_type='', input_refs=[], output_refs=[],
        why='旧格式', source_refs=['ref'])])
    with pytest.raises(ValueError):
        trace_analysis._validate(old, {'intent_understanding:turn1'})


@pytest.mark.parametrize('with_program', [False, True])
def test_existing_findings_take_type_and_endpoints_from_table_without_mutating_input(with_program):
    table = {'existing-step': {'link_type': 'tool_execution',
                              'input': [{'ref': 'request', 'field': 'arguments'}],
                              'output': [{'ref': 'response', 'field': 'result'}]}}
    findings = [dict(link_id='existing-step', why='核对对象', source_refs=['response']),
                dict(link_id='existing-step', why='核对条件', source_refs=['request'])]
    program = [dict(link_id='existing-step', why='程序线索')] if with_program else []
    before = copy.deepcopy((program, findings, table))
    merged = trace_analysis.merge_suspects(program, findings, [], table, trace_analysis.PROCESS_AXES)
    assert len(merged) == 1
    row = merged[0]
    assert row['link_id'] == 'existing-step' and row['link_type'] == 'tool_execution'
    assert row['input_refs'] == ['request'] and row['output_refs'] == ['response']
    assert row['source_refs'] == ['response', 'request']
    assert row['origin'] == (['program', 'analysis'] if with_program else ['analysis'])
    assert row['why'] == (['程序线索'] if with_program else []) + ['核对对象', '核对条件']
    assert row['off_map'] is False
    assert before == (program, findings, table)


def test_unclassified_discovery_is_preserved_without_inventing_an_axis():
    finding = discovered('evidence', link_type='unclassified')
    submitted = payload(new=[finding])
    trace_analysis._validate(submitted, set())
    merged = trace_analysis.merge_suspects([], [], [finding], {}, trace_analysis.PROCESS_AXES)
    assert merged[0]['link_type'] == 'unclassified'
    assert merged[0]['axes'] == list(trace_analysis.PROCESS_AXES)
    assert merged[0]['source_refs'] == ['evidence']
    assert merged[0]['off_map'] is True

