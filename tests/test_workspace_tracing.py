import gzip
import json
from types import SimpleNamespace
import pytest

from impl.core.run_store import LatestRunStore
from impl.core.tracing_retention import cleanup, workspace_trace_selection
from scripts import tracing


def completed(store, project, job, cases, indexes=None):
    ids = store.start(project, job, cases, indexes)
    for identity in ids:
        store.save_run(project, job, identity, {'status': 'fulfilled'})
    store.finish(project, job)
    return ids


def test_partial_rerun_excludes_old_failure_even_for_duplicate_case_names(tmp_path):
    store = LatestRunStore(tmp_path / 'data/latest_runs.sqlite3')
    cases = [{'id': 'same', 'input': 'a'}, {'id': 'same', 'input': 'b'}]
    completed(store, 'p', 'initial', cases)
    completed(store, 'p', 'retry', [cases[1]], [1])
    completed(store, 'q', 'other-project', [{'id': 'q'}])
    assert workspace_trace_selection(store.path, 'p')['execution_ids'] == ['initial:0', 'retry:0']
    archive = tmp_path / 'logs/primary/llm_calls_20200101.jsonl.gz'
    archive.parent.mkdir(parents=True)
    records = [{'execution_id': eid, 'call_id': eid, 'event': 'pre_api_call'}
               for eid in ['discard:0', 'initial:0', 'initial:1', 'retry:0', 'other-project:0']]
    records.append({'call_id': 'initial:0', 'event': 'success'})
    records.append({'call_id': 'initial:1', 'event': 'failure'})
    with gzip.open(archive, 'wt') as stream:
        stream.write(''.join(json.dumps(rec)+'\n' for rec in records))
    for label, executions in [('stale', ['initial:0', 'initial:1']),
                              ('current', ['initial:0', 'retry:0'])]:
        report = tmp_path / 'reports' / label
        report.mkdir(parents=True)
        (report / 'verifier-report.json').write_text(json.dumps({'execution_ids': executions}))
    ctl = SimpleNamespace(discover=lambda _: [])
    result = cleanup(tmp_path, ctl, database=store.path)
    assert set(result['keep_execution_ids']) == {'initial:0', 'retry:0', 'other-project:0'}
    with gzip.open(archive, 'rt') as stream:
        kept = [json.loads(line) for line in stream]
    assert len(kept) == 4
    assert not any(rec['call_id'] == 'initial:1' for rec in kept)
    assert {'call_id': 'initial:0', 'event': 'success'} in kept
    assert not (tmp_path / 'reports/stale').exists()
    assert (tmp_path / 'reports/current').exists()
    completed(store, 'p', 'replacement', cases, [0, 1])
    assert workspace_trace_selection(store.path, 'p')['execution_ids'] == ['replacement:0', 'replacement:1']
    cleanup(tmp_path, ctl, database=store.path)
    with gzip.open(archive, 'rt') as stream:
        assert [json.loads(line)['execution_id'] for line in stream] == ['other-project:0']


@pytest.mark.parametrize('logged_ids', [['initial:0', 'initial:1', 'retry:0', 'q-job:0'], ['retry:0', 'q-job:0']])
def test_project_report_exports_exact_executions(tmp_path, monkeypatch, logged_ids):
    store = LatestRunStore(tmp_path / 'data/latest_runs.sqlite3')
    cases = [{'id': 'a'}, {'id': 'b'}]
    completed(store, 'p', 'initial', cases)
    completed(store, 'p', 'retry', [cases[1]], [1])
    completed(store, 'q', 'q-job', [{'id': 'q'}])
    monkeypatch.setattr(tracing, 'RUNTIME', tmp_path / 'tracing')
    monkeypatch.setattr(tracing, 'captured_calls', lambda *_: [
        {'execution_id': eid, 'run_id': eid.split(':')[0], 'state': 'succeeded'} for eid in logged_ids])
    out = tmp_path / 'report'; out.mkdir()
    seen = []
    def export(command, **kwargs):
        seen.extend(command)
        (out/'llm_trace.html').write_text('<html><body>retained report</body></html>')
        return 0
    monkeypatch.setattr(tracing.subprocess, 'call', export)
    assert tracing.report(tmp_path, None, out, project='p') == 0
    assert [seen[i+1] for i,v in enumerate(seen) if v=='--execution-id'] == ['initial:0','retry:0']
    assert '--run-id' not in seen
    manifest = json.loads((out/'verifier-report.json').read_text())
    assert manifest['execution_ids'] == ['initial:0','retry:0']
    assert '当前用例池 LLM Trace' in (out/'llm_trace.html').read_text()
    expected_missing = sorted({'initial:0', 'retry:0'} - set(logged_ids))
    assert manifest['missing_execution_ids'] == expected_missing
    assert ('没有可用采集日志' in (out/'llm_trace.html').read_text()) == bool(expected_missing)


def test_running_and_failed_batch_bindings_are_selected(tmp_path):
    store = LatestRunStore(tmp_path / 'data/latest_runs.sqlite3')
    ids = store.start('p', 'running', [{'id': 'a'}, {'id': 'b'}])
    assert workspace_trace_selection(store.path)['execution_ids'] == ['running:0', 'running:1']
    assert cleanup(tmp_path, SimpleNamespace(), database=store.path)['status'] == 'skipped'
    store.save_run('p', 'running', ids[0], {'status': 'not_evaluable'})
    store.finish('p', 'running', error='batch interrupted')
    assert workspace_trace_selection(store.path)['execution_ids'] == ['running:0', 'running:1']


def test_missing_legacy_identity_never_exports_all_logs_or_deletes_logs(tmp_path, monkeypatch):
    store = LatestRunStore(tmp_path / 'data/latest_runs.sqlite3')
    ids = store.start('p', 'old', [{'id': 'a'}])
    ids[0].pop('execution_id')
    store.save_run('p', 'old', ids[0], {'status': 'fulfilled'})
    store.finish('p', 'old')
    log = tmp_path / 'logs/primary/llm_calls.jsonl'
    log.parent.mkdir(parents=True); log.write_text('untouched old log')
    selection = workspace_trace_selection(store.path)
    assert selection['execution_ids'] == []
    assert len(selection['unbound_rows']) == 1
    result = cleanup(tmp_path, SimpleNamespace(), database=store.path)
    assert result['status'] == 'skipped'
    assert log.read_text() == 'untouched old log'
    monkeypatch.setattr(tracing, 'RUNTIME', tmp_path / 'tracing')
    monkeypatch.setattr(tracing, 'captured_calls', lambda *_: [{'execution_id': 'unrelated', 'state': 'succeeded'}])
    monkeypatch.setattr(tracing.subprocess, 'call', lambda *a, **k: pytest.fail('must not export unrelated calls'))
    assert tracing.report(tmp_path, None, tmp_path / 'html', project='p') == 1


def test_compact_run_preserves_execution_identity():
    from impl.server.service import compact_run
    identity = {'run_id': 'initial', 'case_id': 'a', 'execution_id': 'initial:0'}
    assert compact_run({'case_id': 'a', 'llmtracing': identity})['llmtracing'] == identity


def test_web_report_surfaces_missing_identity_message(tmp_path, monkeypatch):
    from impl.server import tracing_reports
    monkeypatch.setattr(tracing_reports, 'tracing_root', lambda: tmp_path)
    message = '旧结果缺少执行身份，无法精确关联日志'
    monkeypatch.setattr(tracing_reports.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stderr=message))
    with pytest.raises(FileNotFoundError, match=message):
        tracing_reports.render_report('p')
