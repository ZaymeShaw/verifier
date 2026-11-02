import copy
import sqlite3
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from impl.core import axes_clustering as ac, run_store
from impl.core.run_store import LatestRunStore, WorkspaceBusy, WorkspaceConflict
from impl.server import service
from impl.server.routes import router

TYPES = [
    {'type_id': 'a', 'title': 'Axis A', 'verdict_scope': 'axis',
     'verdict_enum': [{'value': 'v1', 'description': 'first meaning'}, {'value': 'v2', 'description': 'second meaning'}]},
    {'type_id': 'b', 'title': 'Axis B', 'verdict_scope': 'item',
     'verdict_enum': [{'value': 'x', 'description': 'claim meaning'}]},
]
AXES = [
    {'type_id': 'a', 'status': 'succeeded', 'verdict': 'v1', 'text': 'same symptom', 'items': []},
    {'type_id': 'b', 'status': 'succeeded', 'items': [
        {'key': 'claim 1', 'value': 'x', 'reason': 'reason one'},
        {'key': 'claim 2', 'value': 'x', 'reason': 'reason two'}]},
]


def material():
    return ac.build_material([{'pool_index': 7, 'request_key': 'j:0', 'axes': AXES},
                              {'pool_index': 9, 'request_key': 'j:1', 'axes': [
                                  {'type_id': 'a', 'status': 'succeeded', 'verdict': 'v2', 'text': 'other symptom'}]}], TYPES)


def valid_output(data):
    # 故意反转输入轴/标签顺序，验证程序不重新按名称、数量或枚举词排序。
    return {'axes': [{'axis_id': axis['axis_id'], 'priority_reason': 'axis priority from criteria', 'labels': [
        {'value': label['value'], 'priority_reason': 'label priority from criteria', 'clusters': [
            {'name': 'shared situation', 'description': 'grouped by reason', 'priority_reason': 'cluster priority from criteria',
             'member_refs': [r['ref'] for r in label['records']]}]}
        for label in reversed(axis['labels'])]} for axis in reversed(data['axes'])]}


def test_material_uses_reason_and_declared_meaning_not_private_trace():
    data = material()
    assert len(data['refs']) == 4
    assert data['axes'][0]['labels'][0]['description'] == 'first meaning'
    assert data['axes'][0]['labels'][0]['records'][0]['reason'] == 'same symptom'
    assert [v['item_index'] for v in data['refs'].values()] == [None, 0, 1, None]
    assert data['axes'][1]['labels'][0]['records'][0]['case_ref'] == data['axes'][1]['labels'][0]['records'][1]['case_ref'] == 'C8'
    assert 'problematic' not in ac.SYSTEM_PROMPT + ac.DEFAULT_CRITERIA
    assert 'sound' not in ac.SYSTEM_PROMPT + ac.DEFAULT_CRITERIA


def test_validated_order_is_model_order_and_extra_usage_is_not_semantics():
    data = material()
    output = valid_output(data)
    output['metrics'] = {'input_tokens': 10}
    result = ac.validate_result(output, data)
    assert [axis['axis_id'] for axis in result['axes']] == ['b', 'a']
    assert [label['value'] for label in result['axes'][1]['labels']] == ['v2', 'v1']
    assert result['refs'] == data['refs']


@pytest.mark.parametrize('damage', ['unknown_axis', 'unknown_label', 'foreign_ref', 'missing_ref', 'duplicate_ref', 'empty_reason'])
def test_invalid_model_membership_is_rejected(damage):
    data = material()
    output = valid_output(data)
    first = output['axes'][0]['labels'][0]['clusters'][0]
    if damage == 'unknown_axis': output['axes'][0]['axis_id'] = 'other'
    if damage == 'unknown_label': output['axes'][0]['labels'][0]['value'] = 'other'
    if damage == 'foreign_ref': first['member_refs'] = ['R1']
    if damage == 'missing_ref': first['member_refs'] = first['member_refs'][:1]
    if damage == 'duplicate_ref': first['member_refs'] *= 2
    if damage == 'empty_reason': first['description'] = '   '
    with pytest.raises(ValueError): ac.validate_result(output, data)


def test_multiple_situations_in_one_reason_can_have_multiple_memberships():
    data = material(); output = valid_output(data)
    output['axes'][0]['labels'][0]['clusters'].append(copy.deepcopy(output['axes'][0]['labels'][0]['clusters'][0]))
    output['axes'][0]['labels'][0]['clusters'][1]['name'] = 'another aspect'
    assert len(ac.validate_result(output, data)['axes'][0]['labels'][0]['clusters']) == 2


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    monkeypatch.setattr(run_store, 'STORE', store)
    cases = [{'id': 'same', 'project_id': 'llm_probe', 'scenario': 's', 'live_request': {}, 'output': None, 'reference': None}]
    ids = store.start('llm_probe', 'case-job', cases)
    store.save_run('llm_probe', 'case-job', ids[0], {'status': 'done', 'table_row': {'eval_axes_summary': AXES}})
    store.finish('llm_probe', 'case-job', {})
    return store


def selections():
    return [{'pool_index': 0, 'request_key': 'case-job:0'}]


def start_store(store, job='cluster-job'):
    snap = store.clustering_inputs('llm_probe', selections(), ac.DEFAULT_CRITERIA)
    state = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    return store.begin_clustering('llm_probe', state['criteria'], state['criteria_version'], snap['data_revision'], selections(), job, ac.DEFAULT_CRITERIA)


def test_backend_owns_default_and_latest_criteria_with_conflict_detection(store):
    first = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    assert first['criteria'] == ac.DEFAULT_CRITERIA and first['criteria_version'] == 1
    store.save_clustering_criteria('llm_probe', 'new standard', 1, ac.DEFAULT_CRITERIA)
    restored = LatestRunStore(store.path).clustering_state('llm_probe', 'do not overwrite saved standard')
    assert restored['criteria'] == 'new standard' and restored['criteria_version'] == 2
    with pytest.raises(WorkspaceConflict): store.save_clustering_criteria('llm_probe', 'stale editor', 1, ac.DEFAULT_CRITERIA)
    assert store.clustering_state('other', ac.DEFAULT_CRITERIA)['criteria_version'] == 1


@pytest.mark.parametrize('change', ['criteria', 'cases'])
def test_inflight_old_result_cannot_overwrite_new_settings_or_cases(store, change):
    start_store(store)
    if change == 'criteria': store.save_clustering_criteria('llm_probe', 'newer', 1, ac.DEFAULT_CRITERIA)
    else: store.clear('llm_probe', keep_cases=True)
    state = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    with pytest.raises(WorkspaceBusy):
        store.begin_clustering('llm_probe', state['criteria'], state['criteria_version'], state['data_revision'], selections(), 'another', ac.DEFAULT_CRITERIA)
    assert not store.finish_clustering('llm_probe', 'cluster-job', result={'old': 'result'})
    state = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    assert state['status'] == 'stale' and state['result'] is None


def test_only_latest_clustering_is_stored_and_case_mutation_invalidates_it(store):
    start_store(store)
    assert store.finish_clustering('llm_probe', 'cluster-job', result={'generation': 1})
    start_store(store, 'next')
    assert store.finish_clustering('llm_probe', 'next', result={'generation': 2})
    assert LatestRunStore(store.path).clustering_state('llm_probe', ac.DEFAULT_CRITERIA)['result'] == {'generation': 2}
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM axis_clustering').fetchone()[0] == 1
    store.update_run('llm_probe', 'case-job:0', {'status': 'done', 'table_row': {'eval_axes_summary': AXES}})
    assert store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)['result'] is None
    with pytest.raises(WorkspaceConflict): store.clustering_inputs('llm_probe', [{'pool_index': 0, 'request_key': 'wrong'}], ac.DEFAULT_CRITERIA)


def test_clustering_failure_and_service_restart_remain_explicit(store, monkeypatch):
    start_store(store)
    store.finish_clustering('llm_probe', 'cluster-job', error='synthetic provider error')
    state = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    assert state['status'] == 'failed' and state['result'] is None
    assert state['criteria'] == ac.DEFAULT_CRITERIA
    start_store(store, 'restarted')
    monkeypatch.setattr(run_store, '_alive', lambda pid: False)
    restored = LatestRunStore(store.path).clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    assert restored['status'] == 'failed' and '中断' in restored['error']


def test_selection_scope_and_current_snapshot_are_checked_before_model(store, monkeypatch):
    from impl.server import axes_clustering_jobs
    called = []
    monkeypatch.setattr(ac, 'cluster_with_llm', lambda *a: called.append(a))
    with pytest.raises(WorkspaceConflict):
        axes_clustering_jobs.start({'project': 'llm_probe', 'criteria': 'x', 'expected_version': 1,
                                    'selections': [{'pool_index': 0, 'request_key': 'stale'}]})
    assert called == []
    snap = store.clustering_inputs('llm_probe', selections(), ac.DEFAULT_CRITERIA)
    store.update_run('llm_probe', 'case-job:0', {'table_row': {'eval_axes_summary': AXES}})
    with pytest.raises(WorkspaceConflict):
        store.begin_clustering('llm_probe', 'x', 1, snap['data_revision'], selections(), 'late', ac.DEFAULT_CRITERIA)


def test_actual_llm_adapter_uses_current_criteria_and_structured_output(monkeypatch):
    from impl.core import llm_client
    data = material()
    captured = {}
    class FakeClient:
        request_timeout_seconds = 600
        def __init__(self, **kwargs): captured['client'] = kwargs
        def complete_json(self, system, user, **kwargs):
            import json
            captured.update(system=system, user=json.loads(user), options=kwargs)
            return {**valid_output(data), 'metrics': {'input_tokens': 12}, 'raw_model_response': {'model': 'served-model'}}
    monkeypatch.setattr(llm_client, 'LlmClient', FakeClient)
    events = []
    result = ac.cluster_with_llm('llm_probe', 'prefer examples of stable handling', data,
                                 on_progress=lambda stage, detail, **kwargs: events.append((stage, kwargs)))
    assert events == [('model_request', {'request_timeout_seconds': 600}), ('validating', {})]
    assert captured['user']['criteria'] == 'prefer examples of stable handling'
    assert captured['client'] == {'role': 'axes_clustering', 'tools': [], 'tool_call_limit': 0}
    assert captured['options']['output_spec'] is ac.OUTPUT_SPEC
    assert result['usage']['input_tokens'] == 12 and result['model'] == 'served-model'


def test_api_saving_is_free_and_regenerate_uses_saved_criteria(store, monkeypatch):
    called = []
    monkeypatch.setattr(service, 'eval_axes_types', lambda _: {'types': TYPES})
    def fake_llm(project, criteria, data, *, on_progress=None):
        called.append(criteria)
        if on_progress:
            on_progress('model_request', 'synthetic model request', request_timeout_seconds=600)
        return ac.validate_result(valid_output(data), data)
    monkeypatch.setattr(ac, 'cluster_with_llm', fake_llm)
    app = FastAPI();app.include_router(router)
    with TestClient(app) as api:
        def post(path, **kw):
            return api.post('/api/axes_clustering/' + path, json={'project': 'llm_probe', **kw})
        initial = post('state', selections=selections()).json()
        assert not called and initial['criteria_version'] == 1
        saved = post('criteria', criteria='my criteria', expected_version=1).json()
        assert not called and saved['criteria_version'] == 2
        started = post('start', criteria='different priority', expected_version=2, selections=selections())
        assert started.status_code == 200
        for _ in range(100):
            result = post('state', selections=selections()).json()
            if result['status'] != 'running': break
            time.sleep(.01)
        assert result['status'] == 'completed' and result['job_version'] == 3
        assert called == ['different priority'] and result['criteria'] == 'different priority'
        assert result['result']['axes'][0]['axis_id'] == 'b'
        assert post('criteria', criteria='stale', expected_version=2).status_code == 409
        for _ in range(3): post('state', selections=selections())
        assert len(called) == 1
