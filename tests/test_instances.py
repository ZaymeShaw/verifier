import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from impl.core import instances
from impl.core.run_store import LatestRunStore
from impl.core.tracing_retention import cleanup


def test_port_bindings_are_stable_and_locks_exclude_other_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(instances, 'ROOT', tmp_path)
    monkeypatch.setattr(instances, '_port_available', lambda port: True)
    first = instances.resolve_instance(18021)
    second = instances.resolve_instance(18022)
    assert instances.resolve_instance(18021) == first
    assert first['id'] != second['id']
    assert set(first['relay_ports']).isdisjoint(second['relay_ports'])
    with instances.instance_lock(first):
        code = "from impl.core.instances import instance_lock; from pathlib import Path; import json,sys;\nwith instance_lock(json.loads(sys.argv[1]),repository_root=Path(sys.argv[2])): pass"
        child = subprocess.run([sys.executable, '-c', code, json.dumps(first), str(tmp_path)], capture_output=True, text=True)
        assert child.returncode != 0 and 'already owned' in child.stderr
        with pytest.raises(ValueError, match='already owned'):
            instances.rebind_port(18021, 18023)
    # OS lock release permits restart/rebind; data identity does not change.
    with instances.instance_lock(first):
        pass
    assert instances.rebind_port(18021, 18023) == first['id']
    assert instances.resolve_instance(18023)['id'] == first['id']


def test_new_instance_starts_from_repository_project_data(tmp_path, monkeypatch):
    monkeypatch.setattr(instances, 'ROOT', tmp_path)
    monkeypatch.setattr(instances, '_port_available', lambda port: True)
    (tmp_path / 'impl/projects/demo').mkdir(parents=True)
    data = tmp_path / 'impl/data'
    (data / 'demo/axis_code/x/__pycache__').mkdir(parents=True)
    (data / 'demo/axis_definitions.json').write_text('{}')
    (data / 'demo/axis_code/x/checks.py').write_text('')
    (data / 'demo/capability_map.json.bak_1').write_text('')
    (data / 'context_store').mkdir()
    (data / 'latest_runs.sqlite3').write_text('')
    first = instances.resolve_instance(18031)
    seeded = instances.instance_root(first['id'], tmp_path) / 'data'
    assert sorted(str(p.relative_to(seeded)) for p in seeded.rglob('*')) == [
        'demo', 'demo/axis_code', 'demo/axis_code/x', 'demo/axis_code/x/checks.py', 'demo/axis_definitions.json']
    (seeded / 'demo/axis_definitions.json').write_text('{"edited": true}')
    assert instances.resolve_instance(18031) == first          # 已绑定的端口不再拷，实例里的改动保留
    assert (seeded / 'demo/axis_definitions.json').read_text() == '{"edited": true}'


def test_instance_data_and_registered_artifacts_are_disjoint(tmp_path, monkeypatch):
    from impl.core.active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY as registry
    from impl.core import case_pool, findings_ledger, session_store, capability_store, materials_store
    first, second = 'inst-' + 'a'*16, 'inst-' + 'b'*16
    for identity in (first, second):
        monkeypatch.setenv(instances.INSTANCE_ENV, identity)
        ctx = registry.context(tmp_path)
        expected = instances.instance_root(identity, tmp_path) / 'data'
        assert registry.family('case_pool_store').base_path(ctx) == expected
        assert registry.family('materials_store').base_path(ctx) == expected
        registry.write_json('findings_ledger', expected/'QA/ledger.json', [], context=ctx)
        db = LatestRunStore(expected/'latest_runs.sqlite3')
        db.start('QA', identity, [{'id': identity}])
        db.finish('QA', identity)
        for module in (findings_ledger, session_store, capability_store, materials_store):
            monkeypatch.setattr(module, 'ROOT', tmp_path/'impl')
        assert session_store.sessions_dir('QA').is_relative_to(expected)
    a = LatestRunStore(instances.instance_root(first, tmp_path)/'data/latest_runs.sqlite3')
    b = LatestRunStore(instances.instance_root(second, tmp_path)/'data/latest_runs.sqlite3')
    a.clear('QA', keep_cases=False)
    assert a.load('QA')['cases'] == []
    assert b.load('QA')['batch']['job_id'] == second
    assert b.load('QA')['cases'][0]['case']['id'] == second


def test_retention_preserves_latest_projects_and_does_not_touch_other_instance(tmp_path):
    a, b = tmp_path/'a', tmp_path/'b'
    archive = a/'logs/primary/llm_calls_20200101.jsonl.gz'
    archive.parent.mkdir(parents=True)
    b.mkdir(); untouched=b/'llm_calls.jsonl';untouched.write_text('other-instance')
    records = [{'run_id': rid, 'execution_id': rid+':0', 'call_id': rid+'-call', 'event':'pre_api_call'} for rid in ['old', 'latest-a', 'latest-b']]
    records += [{'call_id':'latest-a-call', 'event':'success'}]
    with gzip.open(archive, 'wt') as f:
        for record in records:f.write(json.dumps(record)+'\n')
    db = LatestRunStore(a/'data/latest_runs.sqlite3')
    for project,job in [('QA','latest-a'),('llm_probe','latest-b')]:
        db.start(project,job,[{'id':project}]);db.finish(project,job)
    ctl = SimpleNamespace(discover=lambda _: [])
    result=cleanup(a,ctl,database=db.path)
    assert result['status']=='cleaned'
    with gzip.open(archive,'rt') as f:kept=[json.loads(line) for line in f]
    assert len(kept)==3
    assert {r.get('run_id') for r in kept if r.get('run_id')}=={'latest-a','latest-b'}
    assert untouched.read_text()=='other-instance'
    before=archive.read_bytes()
    db.start('QA','running',[])
    assert cleanup(a,ctl,database=db.path)['status']=='skipped'
    assert archive.read_bytes()==before


def test_retention_rotates_real_relay_logs_and_preserves_latest(tmp_path):
    from scripts.tracing import settings, controller
    _, dependency = settings()
    ctl = controller(dependency)
    runtime = tmp_path/'tracing'
    runtime.mkdir()
    (runtime/'config.yaml').write_text('{}\n')
    logdir=runtime/'logs/verifier_primary';logdir.mkdir(parents=True)
    profile = dict(UPSTREAM_API_BASE='https://example.invalid/v1', UPSTREAM_API_KEY='test',
                   UPSTREAM_MODEL='test', UPSTREAM_PROTOCOL='openai', LITELLM_PORT='4005',
                   LITELLM_HOST='127.0.0.1', LITELLM_MASTER_KEY='test', LITELLM_CONFIG='./config.yaml',
                   LLM_GATEWAY_LOG_DIR=str(logdir))
    (runtime/'.env.verifier_primary').write_text(''.join(f'{k}={v}\n' for k,v in profile.items()))
    records=[{'event':'pre_api_call','run_id':rid,'execution_id':rid+':0','call_id':rid} for rid in ['old','latest']]
    (logdir/'llm_calls.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    store=LatestRunStore(tmp_path/'data/latest_runs.sqlite3')
    store.start('QA','latest',[{'id':'a'}]);store.finish('QA','latest')
    assert cleanup(runtime,ctl,database=store.path)['status']=='cleaned'
    archives=list(logdir.glob('*.jsonl.gz'));assert len(archives)==1
    with gzip.open(archives[0],'rt') as f:
        assert [json.loads(line)['run_id'] for line in f]==['latest']
