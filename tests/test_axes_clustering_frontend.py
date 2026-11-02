"""真实页面/API/SQLite，LLM 用可控替身；验证标准同步、任务恢复和语义目录接线。"""
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from impl.core import axes_clustering as ac, run_store
from impl.core.run_store import LatestRunStore
from impl.server import service
from impl.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_clustering_editor_and_regenerate_roundtrip(monkeypatch, tmp_path):
    cli = shutil.which('playwright-cli')
    if not cli:
        pytest.skip('browser regression requires playwright-cli')
    module = Path(cli).resolve().parent / 'node_modules' / 'playwright'
    if not module.exists():
        pytest.skip('Playwright library is unavailable')
    store = LatestRunStore(tmp_path / 'latest.sqlite3')
    monkeypatch.setattr(run_store, 'STORE', store)
    types = [{'type_id': axis, 'title': axis, 'verdict_scope': 'axis', 'verdict_enum': [{'value': 'value'}]}
             for axis in ['alpha', 'beta']]
    monkeypatch.setattr(service, 'projects', lambda: {'projects': ['llm_probe']})
    monkeypatch.setattr(service, 'list_case_pools', lambda _: {'pools': []})
    monkeypatch.setattr(service, 'eval_axes_types', lambda _: {'types': types})
    cases = [{'id': 'same-id', 'project_id': 'llm_probe', 'scenario': 'test', 'intent': None,
              'live_request': {'q': f'input-{i}'}, 'output': None, 'reference': None} for i in range(2)]
    ids = store.start('llm_probe', 'source-job', cases)
    for i, identity in enumerate(ids):
        store.save_run('llm_probe', 'source-job', identity, {
            'status': 'done', 'trace': {'trace_id': f't{i}', 'project_id': 'llm_probe', 'input': cases[i]['live_request'],
                                      'normalized_request': {}, 'extracted_output': {'answer': f'output-{i}'}},
            'table_row': {'id': 'same-id', 'input': f'input-{i}', 'status': 'fulfilled', 'fulfillment_status': 'fulfilled',
                          'eval_axes_summary': [{'type_id': axis, 'status': 'succeeded', 'verdict': 'value', 'text': f'{axis} reason-{i}'} for axis in ['alpha', 'beta']]}})
    store.finish('llm_probe', 'source-job', {})
    gate = threading.Event()
    calls = []

    def fake_llm(project, criteria, material, *, on_progress=None):
        calls.append(criteria)
        if on_progress:
            on_progress('model_request', 'synthetic waiting for model', request_timeout_seconds=600)
        if criteria == 'pause standard':
            assert gate.wait(60)
        output = {'axes': [{'axis_id': axis['axis_id'], 'priority_reason': 'axis priority', 'labels': [
            {'value': label['value'], 'priority_reason': 'label priority', 'clusters': [
                {'name': 'situation-' + record['ref'], 'description': 'common situation according to ' + criteria,
                 'priority_reason': 'cluster priority', 'member_refs': [record['ref']]}
                for record in reversed(label['records'])]}
            for label in axis['labels']]} for axis in reversed(material['axes'])]}
        return ac.validate_result(output, material)
    monkeypatch.setattr(ac, 'cluster_with_llm', fake_llm)
    app = create_app()

    @app.post('/test/release')
    def release():
        gate.set()
        return {'ok': True}

    @app.get('/test/calls')
    def count():
        return {'criteria': list(calls)}

    held_batch = {}

    @app.post('/test/hold-batch')
    def hold_batch():
        latest_cases = [entry['case'] for entry in store.load('llm_probe')['cases']]
        held_batch['ids'] = store.start('llm_probe', 'progress-test', latest_cases)
        return {'ok': True}

    @app.post('/test/finish-batch')
    def finish_batch():
        for identity in held_batch['ids']:
            store.save_run('llm_probe', 'progress-test', identity, {'status': 'done', 'table_row': {}})
        store.finish('llm_probe', 'progress-test', {})
        return {'ok': True}

    sock = socket.socket();sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.02)
        assert server.started
        result = subprocess.run(['node', str(ROOT / 'tests/axes_clustering_browser.js')],
                                env={**os.environ, 'CLUSTER_TEST_URL': f'http://127.0.0.1:{port}', 'PLAYWRIGHT_MODULE': str(module)},
                                text=True, capture_output=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert calls == ['pause standard', 'new standard']
    finally:
        gate.set();server.should_exit = True;thread.join(10);sock.close()
