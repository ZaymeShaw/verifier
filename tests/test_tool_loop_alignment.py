import copy
import json
import time
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from impl.core.axes_clustering import build_material, validate_result
from impl.core.tool_loop import LoopContext, Step
from impl.tool_loop_lab import alignment, service, store
from impl.tool_loop_lab.connection import Connection
from impl.tool_loop_lab.store import LabStore
from impl.tool_loop_lab.__main__ import create_app

TYPES = [{'type_id': 'a', 'title': 'Axis A', 'verdict_scope': 'axis', 'verdict_enum': [{'value': 'v'}]}]


def workspace():
    return {'cases': [{'case': {'id': 'duplicate', 'scenario': 's', 'live_request': {'q': str(i)}, 'output': None},
                       'status': 'done', 'request_key': f'j:{i}'} for i in range(2)],
            'runs': [{'request_key': f'j:{i}', 'trace': {'input': {'q': f'actual-{i}'}, 'extracted_output': i,
                     'raw_response': {'secret_trace': 'MUST_NOT_COPY'}},
                      'table_row': {'id': 'duplicate', 'input': f'actual-{i}', 'eval_axes_summary': [
                          {'type_id': 'a', 'status': 'succeeded', 'verdict': 'v', 'text': f'reason-{i}', 'items': []}]}}
                     for i in range(2)], 'batch': {'status': 'completed'}}


def source_reader(w=None):
    w = w or workspace()
    requests = []
    def read(path, payload):
        requests.append((path, copy.deepcopy(payload)))
        if path == '/api/run_workspace': return copy.deepcopy(w)
        if path == '/api/eval_axes/types': return {'types': TYPES}
        if path == '/api/axes_clustering/state':
            scope = [{'pool_index': 1, 'request_key': 'j:1'}]
            matches = payload['selections'] == scope
            return {'status': 'completed', 'data_revision': 'rev', 'criteria_version': 1, 'job_version': 1,
                    'job_id': 'source-cluster', 'criteria': 'source criteria', 'scope_matches': matches, 'selections': scope,
                    'result': {'axes': [{'axis_id': 'a', 'priority_reason': 'p', 'labels': [{'value': 'v', 'priority_reason': 'p',
                               'clusters': [{'name': 'DO_NOT_FEED_BASELINE', 'description': 'old grouping', 'priority_reason': 'p', 'member_refs': ['old-ref']}]}]}],
                               'refs': {'old-ref': {'pool_index': 1, 'request_key': 'j:1', 'axis_id': 'a', 'value': 'v', 'item_index': None}}} if matches else None}
        pytest.fail('unexpected source API ' + path)
    return read, requests


def test_one_way_projection_preserves_identity_values_and_baseline_scope():
    read, calls = source_reader()
    snapshot = alignment.collect('http://127.0.0.1:8021', 'llm_probe', reader=read)
    assert snapshot['counts'] == {'cases': 2, 'with_run': 2, 'with_reasons': 2, 'reasons': 2}
    assert [c['id'] for c in snapshot['cases']] == ['duplicate', 'duplicate']
    assert [c['pool_index'] for c in snapshot['cases']] == [0, 1]
    assert [c['request_key'] for c in snapshot['cases']] == ['j:0', 'j:1']
    assert snapshot['cases'][0]['output'] == 0 and snapshot['cases'][1]['output'] == 1
    assert snapshot['cases'][0]['input'] == {'q': 'actual-0'}
    assert snapshot['cases'][1]['axes'][0]['text'] == 'reason-1'
    assert snapshot['baseline']['clustering']['refs']['old-ref']['pool_index'] == 1
    assert 'MUST_NOT_COPY' not in json.dumps(snapshot)
    assert {path for path, _ in calls} == alignment.Source.PATHS
    assert calls[-1][0] == '/api/run_workspace'


def test_sync_detects_changed_content_even_if_request_identity_did_not_change():
    read, _ = source_reader(); count = 0
    def changing(path, payload):
        nonlocal count
        result = read(path, payload)
        if path == '/api/run_workspace':
            count += 1
            if count == 2: result['runs'][0]['trace']['extracted_output'] = 'changed'
        return result
    with pytest.raises(ValueError, match='发生变化'):
        alignment.collect('http://127.0.0.1:8021', 'llm_probe', reader=changing)


@pytest.mark.parametrize('url', ['https://external.example', 'http://127.0.0.1:8021/delete', 'http://user:secret@localhost:8021', 'file:///tmp/data', 'http://127.0.0.1:8021?q=key'])
def test_source_is_local_only_with_no_credential_forwarding(url):
    with pytest.raises(ValueError): alignment.source_url(url)


def test_source_running_or_empty_does_not_produce_snapshot():
    for w in [{'cases': [], 'batch': {}}, {'cases': [], 'batch': {'status': 'running'}}]:
        read, _ = source_reader(w)
        with pytest.raises(ValueError): alignment.collect('http://localhost:8021', 'llm_probe', reader=read)


def test_unavailable_source_clustering_is_explicit_not_invented():
    read, _ = source_reader()
    def stale(path, payload):
        if path == '/api/axes_clustering/state':
            return {'status': 'stale', 'criteria': 'latest standard', 'scope_matches': False, 'selections': []}
        return read(path, payload)
    snapshot = alignment.collect('http://localhost:8021', 'llm_probe', reader=stale)
    assert snapshot['baseline']['clustering'] is None
    assert '没有' in snapshot['baseline']['note']
    assert len(snapshot['cases']) == 2 and snapshot['criteria'] == 'latest standard'


def test_failed_sync_preserves_last_alignment(tmp_path, monkeypatch):
    read, _ = source_reader()
    snapshot = alignment.collect('http://localhost:8021', 'llm_probe', reader=read)
    lab = LabStore(tmp_path / 'lab.sqlite3');monkeypatch.setattr(store, 'STORE', lab);lab.save_alignment(snapshot)
    def fail(*args): raise ValueError('source changed')
    monkeypatch.setattr(alignment, 'collect', fail)
    with pytest.raises(ValueError, match='source changed'):
        service.sync_alignment('http://localhost:8021', 'llm_probe')
    assert lab.alignment()['id'] == snapshot['id']


def test_aligned_baseline_is_not_in_model_material_or_tools(tmp_path, monkeypatch):
    read, _ = source_reader()
    snapshot = alignment.collect('http://localhost:8021', 'llm_probe', reader=read)
    lab = LabStore(tmp_path / 'lab.sqlite3');monkeypatch.setattr(store, 'STORE', lab);lab.save_alignment(snapshot)
    example = service.load_examples()['EXAMPLES']['clustering']
    loop = example['build'](None, dataset=snapshot)
    assert 'DO_NOT_FEED_BASELINE' not in loop.system_prompt
    for tool in loop.tools:
        if tool.tool_id == 'read_case': assert 'DO_NOT_FEED_BASELINE' not in json.dumps(tool.execute_fn(case_ref='C2'))
        if tool.tool_id == 'read_reasons': assert 'DO_NOT_FEED_BASELINE' not in json.dumps(tool.execute_fn(refs=['R1', 'R2']))
    with pytest.raises(ValueError, match='真实案例必须'):
        service.start('clustering', 'x', 'scripted', 'aligned', snapshot['id'])
    newer = copy.deepcopy(snapshot);newer['id'] = 'newer';lab.save_alignment(newer)
    with pytest.raises(ValueError, match='已变化'):
        service.start('clustering', 'x', 'model', 'aligned', snapshot['id'])
    assert lab.state()['run'] is None


def test_case_comparison_matches_request_identity_not_case_name():
    tree = {'axes': [{'axis_id': 'a', 'labels': [{'value': 'v', 'clusters': [
        {'name': 'one group', 'description': 'x', 'member_refs': ['x', 'y', 'z']}]}]}],
        'refs': {'x': {'pool_index': 1, 'request_key': 'run:1', 'axis_id': 'a', 'value': 'v', 'item_index': 0},
                 'y': {'pool_index': 1, 'request_key': 'run:1', 'axis_id': 'a', 'value': 'v', 'item_index': 1},
                 'z': {'pool_index': 2, 'request_key': 'run:2', 'axis_id': 'a', 'value': 'v', 'item_index': 0}}}
    path = Path(__file__).resolve().parents[1] / 'impl/frontend/tool_loop_lab_compare.js'
    code = f"require({json.dumps(str(path))});const input=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify([...LabCaseComparison.memberships(input)]));"
    response = subprocess.run(['node', '-e', code], input=json.dumps(tree), capture_output=True, text=True)
    assert response.returncode == 0, response.stderr
    rows = json.loads(response.stdout)
    assert [json.loads(key) for key, _ in rows] == [[1, 'run:1'], [2, 'run:2']]
    assert all(len(groups) == 1 for _, groups in rows)


def test_manual_alignment_and_run_remain_separate_and_old_run_is_frozen(tmp_path, monkeypatch):
    read, _ = source_reader()
    snapshot = alignment.collect('http://localhost:8021', 'llm_probe', reader=read)
    lab = LabStore(tmp_path / 'lab.sqlite3');monkeypatch.setattr(store, 'STORE', lab)
    monkeypatch.setattr(alignment, 'collect', lambda *args: copy.deepcopy(snapshot))
    material = build_material([{'pool_index': c['pool_index'], 'request_key': c['request_key'], 'axes': c['axes']} for c in snapshot['cases']], snapshot['types'])
    output = {'axes': [{'axis_id': 'a', 'priority_reason': 'p', 'labels': [{'value': 'v', 'priority_reason': 'p', 'clusters': [
        {'name': 'new grouping', 'description': 'common situation', 'priority_reason': 'p', 'members': [{'ref': r['ref'], 'evidence': r['reason']} for a in material['axes'] for label in a['labels'] for r in label['records']]}]}]}]}
    class Model:
        def __init__(self): self.index = 0
        def complete_step(self, messages, functions, **kwargs):
            assert 'DO_NOT_FEED_BASELINE' not in json.dumps(messages)
            self.index += 1
            if self.index == 3: return Step({'role': 'assistant', 'content': 'done'})
            return Step({'role': 'assistant', 'tool_calls': [{'id': str(self.index), 'type': 'function', 'function': {
                'name': 'read_reasons' if self.index == 1 else 'submit_clustering',
                'arguments': json.dumps({'refs': list(material['refs'])} if self.index == 1 else output)}}]})
    calls = []
    class Config(Connection):
        def client(self): calls.append(1);return Model()
    monkeypatch.setattr(service, 'load_connection', lambda: Config(base_url='http://localhost:1/v1', model='test', api_key='test-key'))
    with TestClient(create_app()) as api:
        synced = api.post('/api/tool_loop_lab/alignment/sync', json={'source_url': 'http://localhost:8021', 'project': 'llm_probe'})
        assert synced.status_code == 200 and calls == []
        assert api.get('/api/tool_loop_lab/alignment').json()['snapshot']['id'] == snapshot['id']
        preview = api.get('/api/tool_loop_lab/alignment/preview', params={'snapshot_id': snapshot['id']}).json()
        assert preview['cases'][1]['input'] == {'q': 'actual-1'}
        started = api.post('/api/tool_loop_lab/start', json={'example_id': 'clustering', 'mode': 'model', 'input': snapshot['criteria'],
                          'data_source': 'aligned', 'alignment_id': snapshot['id']})
        assert started.status_code == 200, started.text
        for _ in range(100):
            state = api.get('/api/tool_loop_lab/state').json()
            if state['run']['status'] != 'running': break
            time.sleep(.02)
        assert state['run']['status'] == 'complete', state['run']
        artifact = state['run']['result']['value']
        assert artifact['cases'] == snapshot['cases'] and artifact['baseline'] == snapshot['baseline']
        assert artifact['alignment']['id'] == snapshot['id'] and calls == [1]
        running_metadata = {'title': 'inflight'}
        lab.start('held-run', running_metadata)
        refused = api.post('/api/tool_loop_lab/alignment/sync', json={'source_url': 'http://localhost:8021', 'project': 'llm_probe'})
        assert refused.status_code == 409
        lab.finish('held-run', 'complete', result={'value': artifact})
        snapshot['id'] = 'updated';snapshot['cases'][0]['output'] = 'new source output'
        api.post('/api/tool_loop_lab/alignment/sync', json={'source_url': 'http://localhost:8021', 'project': 'llm_probe'})
        assert api.get('/api/tool_loop_lab/state').json()['run']['result']['value'] == artifact
        assert api.get('/api/tool_loop_lab/alignment/preview', params={'snapshot_id': artifact['alignment']['id']}).status_code == 409
        assert calls == [1]
