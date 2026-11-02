import hashlib
import json
from pathlib import Path
import subprocess
from contextlib import nullcontext

import pytest

import collect
import ledger
from common import ROOT, write_json


def envelope():
    return {'schema': 'llmtrace.calls/v1', 'status': 'complete', 'pending_call_ids': [], 'conflicts': [],
            'calls': [{'call_id': 'call-1', 'execution_id': 'exec-1', 'case_id': 'case-1', 'stage': 'judge',
                       'state': 'succeeded', 'gateway': 'verifier_primary', 'ts': '2026-10-06',
                       'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}]}


def test_utf8_long_line_and_many_lines_are_lossless(tmp_path):
    source = tmp_path / 'call.txt'
    payload = ('长行🙂' * 16000 + '\n' + '短行\n' * 5000).encode('utf-8')
    source.write_bytes(payload)
    chunks = collect.chunk_file(source)
    recovered = []
    for chunk in chunks:
        data = Path(chunk['path']).read_bytes()
        data.decode('utf-8')
        assert len(data) <= 40000
        assert len(data.splitlines()) <= 1700
        body = data.split(b'--- payload ---\n', 1)[1]
        assert body == payload[chunk['start_byte']:chunk['end_byte']]
        assert hashlib.sha256(body).hexdigest() == chunk['sha256']
        recovered.append(body)
    assert b''.join(recovered) == payload
    assert len(chunks) > 5


@pytest.mark.parametrize('failure', ['exit', 'schema', 'show', 'html'])
def test_failed_export_preserves_existing_trace(tmp_path, monkeypatch, failure):
    import impl.core.instances as instances
    import impl.core.tracing_retention as retention
    monkeypatch.setattr(instances, 'instance_root', lambda _: tmp_path / 'instance')
    monkeypatch.setattr(retention, 'log_lock', lambda *_: nullcontext())
    raw = tmp_path / 'raw'
    write_json(raw / 'calls.json', {'previous': True})
    (raw / 'calls').mkdir()
    (raw / 'calls/previous.txt').write_text('previous trace')

    def fake_run(argv, **kwargs):
        if '--format' in argv:
            data = envelope()
            if failure == 'schema':
                data['schema'] = 'changed/v2'
            kwargs['stdout'].write(json.dumps(data).encode())
            return subprocess.CompletedProcess(argv, 2 if failure == 'exit' else 0)
        if 'show' in argv:
            kwargs['stdout'].write(b'full original call')
            return subprocess.CompletedProcess(argv, 2 if failure == 'show' else 0)
        html = Path(argv[argv.index('--html') + 1])
        html.mkdir()
        (html / 'llm_trace.html').write_text('HTML')
        return subprocess.CompletedProcess(argv, 2 if failure == 'html' else 0)

    monkeypatch.setattr(collect.subprocess, 'run', fake_run)
    with pytest.raises(collect.TraceExportError):
        collect.collect(tmp_path, ['exec-1'], 'inst-0123456789abcdef')
    assert json.loads((raw / 'calls.json').read_text()) == {'previous': True}
    assert (raw / 'calls/previous.txt').read_text() == 'previous trace'
    assert json.loads((raw / 'export-manifest.json').read_text())['status'] == 'failed'


def test_supported_cli_export_builds_manifest_and_zero_call_ledger(tmp_path, monkeypatch):
    import impl.core.instances as instances
    import impl.core.tracing_retention as retention
    monkeypatch.setattr(instances, 'instance_root', lambda _: tmp_path / 'instance')
    monkeypatch.setattr(retention, 'log_lock', lambda *_: nullcontext())
    commands = []

    def fake_run(argv, **kwargs):
        commands.append(argv)
        assert '--include-rotated' in argv
        if '--format' in argv:
            kwargs['stdout'].write(json.dumps(envelope()).encode())
        elif 'show' in argv:
            assert '--full' in argv
            kwargs['stdout'].write('请求\n模型响应'.encode())
        else:
            html = Path(argv[argv.index('--html') + 1])
            html.mkdir()
            (html / 'llm_trace.html').write_text('HTML')
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(collect.subprocess, 'run', fake_run)
    collect.collect(tmp_path, ['exec-1', 'exec-empty'], 'inst-0123456789abcdef')
    assert len(commands) == 3
    assert commands[0][commands[0].index('--execution-id') + 1] == 'exec-1,exec-empty'
    write_json(tmp_path / 'raw/requests.json', [{'execution_id': 'exec-1', 'request_case_id': 'case-1'},
                                              {'execution_id': 'exec-empty', 'request_case_id': 'case-empty'}])
    write_json(tmp_path / 'raw/batch-status.json', {'events': []})
    result = ledger.build(tmp_path)
    assert result['case-empty']['calls'] == []
    assert result['case-empty']['missing_run'] is True
    assert result['case-1']['calls'][0]['raw_path'] == 'raw/calls/call-1.txt'
    manifest = json.loads((tmp_path / 'raw/calls/chunks-manifest.json').read_text())
    assert manifest['calls']['call-1'][0]['path'].startswith('raw/calls/call-1.chunks/')


def test_dereference_resolves_raw_evidence_and_exposes_missing():
    run = {'case_id': 'c', 'eval_axes': {'results': [
        {'axis_id': 'trace_analysis', 'output': {'dossier': {'records': [{'id': 'r1', 'value': {'content_ref': 'body'}}],
                                                           'contents': {'body': 'original supplied body'}}}},
        {'axis_id': 'expectations', 'output': {'expectations': [{'expectation_id': 'E1', 'statement': 'supplied expectation'}]}},
        {'axis_id': 'process', 'output': {'obligations': [{'obligation_id': 'O1', 'duty': 'supplied duty'}],
            'results': [{'evidence': {'input': ['r1'], 'output': ['missing']}, 'expectation_ids': ['E1'], 'obligation_id': 'O1'}]}}
    ]}}
    result = ledger._dereference(run)
    refs = result['axes'][2]['references']
    assert refs[0]['targets'][0]['value'] == 'original supplied body'
    assert [r['ref'] for r in result['unresolved']] == ['missing']
    assert all(ref['status'] == 'resolved' for ref in refs if ref['ref'] != 'missing')


def test_ledger_preserves_retries_usage_delta_and_raw_fields(tmp_path):
    export = envelope()
    export['calls'].append({**export['calls'][0], 'call_id': 'call-2', 'ts': '2026-10-07',
                            'state': 'failed', 'error': 'supplied error', 'usage': {'prompt_tokens': 80, 'completion_tokens': 3}})
    write_json(tmp_path / 'raw/calls.json', export)
    write_json(tmp_path / 'raw/requests.json', [{'execution_id': 'exec-1', 'request_case_id': 'case-1'}])
    write_json(tmp_path / 'raw/batch-status.json', {'events': []})
    for record in export['calls']:
        path = tmp_path / 'raw/calls' / (record['call_id'] + '.txt')
        path.parent.mkdir(exist_ok=True)
        path.write_text('supplied full call')
    rows = ledger.build(tmp_path)['case-1']['calls']
    assert [r['stage_occurrence'] for r in rows] == [1, 2]
    assert rows[1]['prompt_tokens_delta'] == 70
    assert rows[1]['state'] == 'failed' and rows[1]['error'] == 'supplied error'
