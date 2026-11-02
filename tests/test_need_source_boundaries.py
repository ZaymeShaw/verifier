"""Offline R4/R5/R7 counterexamples; synthetic sources, never live model calls."""
import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from impl.core import capability_store
from impl.core.tool_loop import History
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.business_trace.providers import agno
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('No network allowed in source boundary tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)


def msg(role, content):
    return dict(role=role, content=content)


def call(messages):
    return dict(pre=dict(messages=messages), outcome=dict(event='success', response=dict(
        choices=[dict(message=msg('assistant', 'answer'))])))


def trace(request=None, *, messages=None, provider='llmtracing', records=None):
    records = copy.deepcopy(records or {})
    if messages is not None:
        records['calls'] = [call(messages)]
    return SimpleNamespace(normalized_request=request, project_fields=dict(business_trace=dict(
        provider=provider, status='succeeded', records=records)))


def wants(material):
    return [s for s in material['sources'] if s['side'] == 'want']


@pytest.mark.parametrize('outer', ['Tell me current status.', {'query': 'Tell me current status.'},
    {'body': {'message': 'Tell me current status.'}}, {'body': {'input': 'Tell me current status.'}}])
def test_outer_request_wins_over_first_model_user_and_fake_history(outer):
    t = trace(outer, messages=[msg('user', 'PREPROCESSOR_QUERY'),
        msg('assistant', 'DIRECT_RESULT'), msg('user', 'PREPROCESSOR_RESULT=ACTIVE')])
    y = project_requirements(t)
    assert [s['value'] for s in wants(y)] == ['Tell me current status.']
    assert not y['missing']
    assert all(s['side'] != 'history' for s in y['sources'])
    assert not any('c1.m' in r for s in y['sources'] for r in s['trace_refs'])
    assert 'PREPROCESSOR' not in json.dumps(y) and 'DIRECT_RESULT' not in json.dumps(y)


@pytest.mark.parametrize('provider', ['llmtracing', 'agno', None])
def test_model_role_cannot_supply_unrecorded_original_or_history(provider):
    t = trace({'capability_ref': 'registered'}, provider=provider,
              messages=[msg('user', 'internal query'), msg('assistant', 'internal result'),
                        msg('user', 'generated instruction')])
    y = project_requirements(t)
    assert y['sources'] == []
    assert y['missing'] == [dict(turn='t1', component='user', reason='用户原文未独立记录')]


def test_outer_message_history_is_preserved_but_current_outputs_are_not():
    request = {'body': {'messages': [msg('system', 'DESIGN'), msg('user', 'Policy P1'),
        msg('assistant', 'Prior answer'), msg('user', 'Its status?'),
        msg('assistant', 'CURRENT_OUTPUT')]}}
    t = trace(request, messages=[msg('user', 'FAKE_HISTORY'), msg('assistant', 'DIRECT_RESULT'),
                                msg('user', 'Its status?')])
    y = project_requirements(t)
    assert [s['value'] for s in wants(y)] == ['Its status?']
    assert [s['value'] for s in y['sources'] if s['side'] == 'history'] == [
        msg('user', 'Policy P1'), msg('assistant', 'Prior answer')]
    assert not any(x in json.dumps(y) for x in ['DESIGN', 'CURRENT_OUTPUT', 'FAKE_HISTORY', 'DIRECT_RESULT'])


def test_turn_records_use_each_outer_original_and_mock_source_not_model_content():
    t = SimpleNamespace(turn_records=[
        dict(request={'body': {'query': 'First query'}}, project_fields={'business_trace': {
            'records': {'calls': [call([msg('user', 'internal first')])]}}}),
        dict(mock_message='Its status?', request={'body': {'custom_slot': 'Its status?'}},
             project_fields={'business_trace': {'records': {'calls': [call([msg('user', 'internal next')])]}}})])
    y = project_requirements(t)
    assert [(s['turn'], s['value']) for s in wants(y)] == [('t1', 'First query'), ('t2', 'Its status?')]
    assert not y['missing']


@pytest.mark.parametrize('value', ['  Original run input.\n', {'input_content': 'Original run input.'}])
def test_registered_agno_run_input_is_a_legitimate_original(value):
    t = trace({}, provider='agno', records={'run': {'run_id': 'current', 'run_input': value,
        'content': 'CURRENT_RESULT'}}, messages=[msg('user', 'internal rewritten request')])
    y = project_requirements(t)
    expected = value['input_content'] if isinstance(value, dict) else value
    assert [s['value'] for s in wants(y)] == [expected]
    assert not y['missing'] and 'CURRENT_RESULT' not in json.dumps(y)


@pytest.mark.parametrize('provider', ['llmtracing', 'unregistered', None])
def test_other_providers_cannot_invent_raw_original_from_run_shape(provider):
    t = trace({}, provider=provider, records={'run': {'run_input': 'not registered original'}})
    assert not wants(project_requirements(t))
    assert project_requirements(t)['missing']


def test_outer_original_precedes_agno_run_input():
    t = trace({'query': 'Outer original'}, provider='agno', records={'run': {'run_input': 'rewritten'}})
    assert [s['value'] for s in wants(project_requirements(t))] == ['Outer original']


@pytest.mark.parametrize('change', [{'status': 'failed'}, {'association': {'run_id': 'another-run'}}])
def test_failed_or_mismatched_agno_association_does_not_supply_original(change):
    t = trace({}, provider='agno', records={'run': {'run_id': 'current', 'run_input': 'not established'}})
    t.project_fields['business_trace'].update(change)
    y = project_requirements(t)
    assert y['sources'] == [] and y['missing']


def test_matching_original_before_generated_last_user_is_not_replaced_or_history():
    t = trace({'query': 'Outer original'}, messages=[msg('user', 'Outer original'),
        msg('assistant', 'DIRECT_OUTPUT'), msg('user', 'GENERATED_INSTRUCTION')])
    y = project_requirements(t)
    source, = y['sources']
    assert source['value'] == 'Outer original' and source['side'] == 'want'
    assert source['trace_refs'] == ['t1.request', 't1.c1.m1']
    assert 'DIRECT_OUTPUT' not in json.dumps(y) and 'GENERATED_INSTRUCTION' not in json.dumps(y)


def test_agno_history_requires_adapter_ordering_not_just_a_different_run_id():
    current = dict(run_id='current', created_at=100, run_input='Its status?', content='CURRENT')
    past = dict(run_id='past', created_at=50, status='COMPLETED', metrics={'duration': 1},
                run_input='Policy P1', content='Prior answer')
    ordered, _ = agno._history([past], current, None)
    assert ordered[0]['ordering'] == 'created_at_plus_duration'
    t = trace({}, provider='agno', records={'run': current, 'history_runs': [
        *ordered, dict(past, run_id='unconfirmed', content='UNCONFIRMED'),
        dict(current, ordering='created_at_plus_duration')]}, messages=[msg('user', 'INTERNAL')])
    y = project_requirements(t)
    assert [s['value'] for s in y['sources'] if s['side'] == 'history'] == [
        msg('user', 'Policy P1'), msg('assistant', 'Prior answer')]
    assert not any(x in json.dumps(y) for x in ['CURRENT', 'UNCONFIRMED', 'INTERNAL'])


def interleaved_trace():
    q = 'Tell me current status.'
    return trace({'body': {'message': q}}, records={'calls': [
        call([msg('user', 'Earlier request.'), msg('system', 'Rule 1.'),
              msg('user', q), msg('system', 'Rule 2.')]),
        call([msg('system', 'Rule 1.'), msg('system', 'Rule 2.'), msg('user', 'Earlier request.')]),
        call([msg('system', 'Rule 1.'), msg('user', q)])]})


def frozen(t):
    y = project_requirements(t)
    es = [dict(expectation_id='E1', source_refs=['t1.user'], about='status',
        statement=wants(y)[0]['value'], condition='always', ambiguity_group='')]
    e = dict(sources=y['sources'], expectations=es,
        sha256=hashlib.sha256(json.dumps(es, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
    p = dict(expectations_sha256=e['sha256'], data_needs=[dict(expectation_id='E1',
        need='none', reason='synthetic test', methods=[], missing=[])])
    return e, p


def test_transcript_message_ids_use_original_indices_and_replay_only_actual_content():
    t = interleaved_trace()
    tr = build_transcript(t, t.project_fields['business_trace'])
    rows = {r['id']: r for r in tr['records']}
    source, = wants(project_requirements(t))
    assert rows['t1.c1.m1']['text'] == 'Earlier request.'
    assert rows['t1.c1.m3']['text'] == source['value']
    assert 't1.c1.m3' in source['trace_refs']
    assert 't1.c1.m1' in rows['t1.c2']['input_refs']
    assert 't1.c1.m3' not in rows['t1.c2']['input_refs']


def test_nonmessage_slots_do_not_renumber_original_input_positions():
    t = trace({'query': 'Outer original'}, messages=[None, msg('user', 'Outer original'),
        msg('system', 'Rule'), msg('user', 'Other internal query')])
    tr = build_transcript(t, t.project_fields['business_trace'])
    rows = {r['id']: r for r in tr['records']}
    assert rows['t1.c1.m2']['message']['content'] == 'Outer original'
    assert 't1.c1.m2' in wants(project_requirements(t))[0]['trace_refs']


def test_save_preserves_need_fields_through_active_artifact_and_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(capability_store, 'ROOT', tmp_path / 'impl')
    original = dict(capability='Unsplit mixed background', criterion='  Deliver A.\n',
                    description='User-facing service.\n', downstream=['Return label.'])
    saved = capability_store.save_capability('llm_probe', 'source_test', original)['entry']
    assert saved == original
    assert capability_store.load_capability_map('llm_probe')['source_test'] == original
    # A second normal save must not erase already configured fields either.
    capability_store.save_capability('llm_probe', 'source_test', saved)
    y = project_requirements(trace({'query': 'User original'}), saved)
    assert [s['value'] for s in wants(y)] == ['User original', original['criterion']]
    assert next(s for s in y['sources'] if s['id'] == 'scenario.description')['value'] == original['description']
    assert y['missing'] == [dict(turn='case', component='capability', reason='capability 未拆分')]
    assert 'Return label.' not in json.dumps(y)


@pytest.mark.parametrize('key', ['criterion', 'description'])
@pytest.mark.parametrize('value', [None, 1, True, [], {},
    pytest.param('x' * (capability_store.MAX_CAPABILITY_CHARS + 1), id='oversize')])
def test_need_config_fields_reject_wrong_shape_or_oversize(key, value):
    with pytest.raises(ValueError, match=key):
        capability_store.validate_entry('source_test', dict(capability='legacy', **{key: value}))


@pytest.mark.parametrize('value', [None, 'not a list', {}, [1], ['valid', None]])
def test_downstream_placeholder_is_only_a_string_list(value):
    with pytest.raises(ValueError, match='downstream'):
        capability_store.validate_entry('source_test', dict(capability='legacy', downstream=value))


def test_absent_and_empty_need_fields_are_not_synthesized():
    assert capability_store.validate_entry('source_test', {'capability': 'legacy'}) == {'capability': 'legacy'}
    entry = dict(capability='legacy', criterion='', description='', downstream=[])
    assert capability_store.validate_entry('source_test', entry) == entry
