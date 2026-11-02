import pytest

from impl.core import axes_clustering as ac, run_store
from impl.core.run_store import LatestRunStore, WorkspaceBusy
from impl.server import axes_clustering_jobs


@pytest.fixture
def clock(monkeypatch):
    value = [1000.0]
    monkeypatch.setattr(run_store.time, 'time', lambda: value[0])
    return value


def test_batch_progress_events_are_real_and_eta_uses_observed_throughput(tmp_path, clock):
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    cases = [{'id': str(i)} for i in range(4)]
    ids = store.start('p', 'batch', cases)
    initial = store.batch_progress('p')
    assert initial['done'] == 0 and initial['progress']['started_at'] == 1000
    assert initial['progress']['eta_seconds'] is None
    clock[0] = 1010
    store.save_run('p', 'batch', ids[0], {'status': 'done'})
    first = store.batch_progress('p')
    assert first['done'] == 1 and first['progress']['eta_seconds'] == 30
    clock[0] = 1020
    polled = store.batch_progress('p')
    assert polled['progress']['last_event_at'] == 1010  # 读取状态不是任务进展。
    assert polled['progress']['no_event_seconds'] == 10
    store.save_run('p', 'batch', ids[0], {'status': 'done'})
    assert store.batch_progress('p')['done'] == 1
    clock[0] = 1040
    for identity in ids[1:]: store.save_run('p', 'batch', identity, {'status': 'done'})
    finalizing = store.batch_progress('p')
    assert finalizing['done'] == 4 and finalizing['status'] == 'running'
    assert finalizing['progress']['stage'] == 'finalizing' and finalizing['progress']['eta_seconds'] is None
    clock[0] = 1060
    store.finish('p', 'batch', {})
    clock[0] = 2000
    restored = LatestRunStore(store.path).batch_progress('p')
    assert restored['status'] == 'completed' and restored['progress']['elapsed_seconds'] == 60
    assert restored['progress']['finished_at'] == 1060


def test_no_invented_start_time_for_unrecorded_task(tmp_path):
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    store.start('p', 'old', [{'id': 'case'}])
    with store._db() as db: db.execute('DELETE FROM task_progress')
    state = store.batch_progress('p')
    assert state['total'] == 1 and state['progress'] is None


def test_state_reading_is_allowed_during_batch_but_model_start_is_not(tmp_path, monkeypatch, clock):
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    monkeypatch.setattr(run_store, 'STORE', store)
    ids = store.start('llm_probe', 'batch', [{'id': 'case'}])
    selections = [{'pool_index': 0, 'request_key': ids[0]['request_key']}]
    state = axes_clustering_jobs.state({'project': 'llm_probe', 'selections': selections})
    assert state['batch']['status'] == 'running' and state['batch']['done'] == 0
    assert state['scope_valid'] and state['criteria'] == ac.DEFAULT_CRITERIA
    with pytest.raises(WorkspaceBusy):
        store.begin_clustering('llm_probe', state['criteria'], 1, state['data_revision'], selections, 'cluster', ac.DEFAULT_CRITERIA)
    stale = axes_clustering_jobs.state({'project': 'llm_probe', 'selections': [{'pool_index': 0, 'request_key': 'outdated'}]})
    assert not stale['scope_valid'] and stale['result'] is None
    assert stale['batch']['total'] == 1  # 过期页面仍能看到最新任务进度，但不能混用聚类结果。


def test_clustering_stage_and_request_limit_persist_without_fake_fraction(tmp_path, clock):
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    state = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)
    store.begin_clustering('llm_probe', state['criteria'], 1, state['data_revision'], [], 'cluster', ac.DEFAULT_CRITERIA)
    clock[0] = 1005
    store.clustering_progress('llm_probe', 'cluster', 'model_request', 'waiting', 600)
    clock[0] = 1015
    progress = store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)['progress']
    assert progress['stage'] == 'model_request' and progress['request_timeout_seconds'] == 600
    assert progress['elapsed_seconds'] == 15 and progress['no_event_seconds'] == 10
    assert progress['eta_seconds'] is None and progress['completed'] is None
    store.clustering_progress('llm_probe', 'cluster', 'validating', 'validating refs')
    store.finish_clustering('llm_probe', 'cluster', result={'axes': []})
    assert store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)['progress']['stage'] == 'completed'
    clock[0] = 1020
    store.clustering_progress('llm_probe', 'cluster', 'model_request', 'late event')
    assert store.clustering_state('llm_probe', ac.DEFAULT_CRITERIA)['progress']['last_event_at'] == 1015
