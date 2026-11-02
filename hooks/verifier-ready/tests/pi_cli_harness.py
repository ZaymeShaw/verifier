"""Full pi CLI sessions against a loopback scripted provider, in disposable repositories.

The gate backend and hook are copied unchanged. Only the provider and verdict inputs
are synthetic. No global pi configuration, source workspace or external model is used.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import HERE, ROOT, digest, fingerprint, load_profile, snapshot, write_json
import verdict


def projected_report(root, status):
    """Explicitly synthetic verdict fixture, never promoted or used as real review evidence."""
    out = root / 'report/verifier-ready/fixture'
    write_json(out / 'raw/calls.json', {'calls': [{'call_id': 'fixture-call', 'case_id': 'fixture-case'}]})
    write_json(out / 'raw/requests.json', [{'execution_id': 'fixture-exec'}])
    write_json(out / 'metrics.json', {'hard_checks': [{'id': 'U1', 'pass': status != 'hard_fail'}],
                                    'reference': [], 'failures': ['synthetic U1 failure'] if status == 'hard_fail' else []})
    write_json(out / 'review/fixture-case.json', {'spawn_id': 'fixture-spawn', 'findings': []})
    write_json(out / 'spawn/fixture-case/meta.json', {'spawn_id': 'fixture-spawn', 'has_result': True,
               'exit_code': 0, 'scope_valid': True, 'review_sha256': digest(out / 'review/fixture-case.json')})
    write_json(out / 'review/snapshot.json', {'scope_valid': True})
    finding = {'key': 'fixture-case::F-01', 'shard': 'fixture-case', 'id': 'F-01', 'severity': 'high', 'verdict': 'confirmed'}
    summary = {'valid': status != 'review_invalid',
        'shards': {'fixture-case': {'path': 'review/fixture-case.json', 'meta': 'spawn/fixture-case/meta.json', 'valid': True}},
        'findings': [finding] if status in {'inconsistent', 'needs_human', 'pass_with_exception'} else [], 'carry_over': [],
        'consistency': {'pass': True, 'calls_total': 1, 'full': 0 if status == 'coverage_incomplete' else 1,
            'partial': 1 if status == 'coverage_incomplete' else 0, 'unverifiable': 0, 'missing_relation': 0,
            'missing_common_rules': 0, 'invalid_ref': 0, 'confirmed': {'blocking': 0, 'high': 0, 'diagnostic': 0},
            'explained': 0, 'open_key': 0, 'open_other': 0}}
    write_json(out / 'review-summary.json', summary)
    if status == 'needs_human':
        write_json(out / 'response.json', {'responses': [{'finding': finding['key'], 'status': 'refuted',
            'note': 'synthetic counterexample', 'counter_evidence': [{'call_id': 'fixture-call', 'quote': 'synthetic'}]}]})
    if status == 'pass_with_exception':
        write_json(out / 'adjudication.json', {'entries': [{'finding': finding['key'], 'rule': 'waived-by-human',
                                                          'note': 'synthetic fixture, not a real human adjudication'}]})
    fp = fingerprint(root=root, profile=load_profile())
    if status == 'stale': fp['code'] = '0' * 64
    write_json(out / 'run.json', {'phase': 'completed', 'fingerprint': fp, 'input_hashes': verdict.input_hashes(out),
        'review_summary_sha256': digest(out / 'review-summary.json'), 'metrics_sha256': digest(out / 'metrics.json')})
    write_json(root / 'report/verifier-ready/current/progress.json', {'report': str(out),
        'phase': 'reviewing' if status == 'running' else 'completed', 'pid': os.getpid()})
    return out


class ScriptedProvider:
    def __init__(self, root, status, path):
        self.root, self.status, self.path = root, status, path
        self.requests, self.before_report, self.report = [], None, None
        self.phase_requests = 0
        self.write_first = True

    def respond(self, payload):
        self.requests.append(payload)
        self.phase_requests += 1
        if self.phase_requests == 1 and self.write_first:
            return {'tool_calls': [{'index': 0, 'id': 'fixture-write', 'type': 'function',
                'function': {'name': 'write', 'arguments': json.dumps({'path': self.path, 'content': '# synthetic fixture\n'})}}]}, 'tool_calls'
        if self.phase_requests == 2 and self.write_first:
            if self.status not in {'no_report', 'docs_only', 'at_noop'}:
                self.report = projected_report(self.root, self.status)
                self.before_report = {str(p.relative_to(self.report)): digest(p) for p in self.report.rglob('*') if p.is_file()}
        return {'content': 'Synthetic completion; no real work claimed.'}, 'stop'

    def next_phase(self, write_first):
        self.phase_requests, self.write_first = 0, write_first


def server_for(provider):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            delta, finish = provider.respond(payload)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            base = {'id': 'synthetic-completion', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'fixture'}
            for fragment, reason in [({'role': 'assistant'}, None), (delta, None), ({}, finish)]:
                event = {**base, 'choices': [{'index': 0, 'delta': fragment, 'finish_reason': reason}]}
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.write(('data: ' + json.dumps({**base, 'choices': [], 'usage': {'prompt_tokens': 1,
                'completion_tokens': 1, 'total_tokens': 2}}) + '\n\ndata: [DONE]\n\n').encode())
            self.wfile.flush()
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def session_entries(root, session_id):
    for path in (root / 'sessions').rglob('*.jsonl'):
        entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if entries and entries[0].get('id') == session_id: return path, entries
    raise AssertionError('pi did not persist the requested disk session')


def run_case(dest, status):
    with tempfile.TemporaryDirectory(prefix='verifier-ready-hook-cli-') as temp:
        root = Path(temp)
        gate_dir = root / 'hooks/verifier-ready'
        shutil.copytree(HERE, gate_dir, ignore=shutil.ignore_patterns('tests', '__pycache__', '*.pyc', 'baseline'))
        # The temporary launcher only supplies the already selected Python interpreter.
        (root / 'run.sh').write_text('#!/bin/bash\nset -eu\n[ "$1" = python ]\nshift\nexec ' +
                                    json.dumps(sys.executable) + ' "$@"\n')
        path = 'spec/control.md' if status == 'docs_only' else '@impl/fixture.py' if status == 'at_noop' else 'impl/fixture.py'
        if status == 'at_noop':
            (root / 'impl').mkdir()
            (root / 'impl/fixture.py').write_text('# synthetic fixture\n')
        provider = ScriptedProvider(root, status, path)
        server = server_for(provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        agent = root / 'private-agent'
        write_json(agent / 'models.json', {'providers': {'hook-fixture': {'baseUrl': f'http://127.0.0.1:{server.server_port}/v1',
            'api': 'openai-completions', 'apiKey': 'synthetic-local-only', 'models': [
                {'id': 'fixture', 'contextWindow': 1048576, 'maxTokens': 512, 'reasoning': False,
                 'input': ['text'], 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}})
        write_json(agent / 'settings.json', {'telemetry': {'enabled': False}, 'retry': {'enabled': False}})
        observer = root / 'observer.ts'
        observer.write_text("export default function(pi) { pi.on('tool_result', (event, ctx) => pi.appendEntry('fixture-tool-event', {toolName:event.toolName,input:event.input,isError:event.isError,cwd:ctx.cwd})); }\n")
        env = {**os.environ, 'PI_CODING_AGENT_DIR': str(agent), 'PI_OFFLINE': '1', 'PI_TELEMETRY': '0'}
        session_id = str(uuid.uuid4())
        argv = ['pi', '-p', '--mode', 'json', '--offline', '--no-context-files', '--no-skills', '--no-prompt-templates',
                '--no-extensions', '--extension', str(gate_dir / 'adapters/pi_before_settle.ts'),
                '--extension', str(observer),
                '--model', 'hook-fixture/fixture', '--thinking', 'off', '--tools', 'write',
                '--session-dir', str(root / 'sessions'), '--session-id', session_id, 'Run the synthetic hook fixture.']
        try:
            result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=60)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / 'stdout.jsonl').write_text(result.stdout)
            (dest / 'stderr.txt').write_text(result.stderr)
            assert result.returncode == 0, result.stderr + result.stdout[-3000:]
            source, entries = session_entries(root, session_id)
            shutil.copyfile(source, dest / 'session.jsonl')
            notices = [e for e in entries if e.get('type') == 'custom_message' and e.get('customType') == 'verifier-ready-gate']
            allowed = status in {'pass', 'pass_with_exception', 'docs_only'}
            expected_requests = 2 if allowed else 8
            assert len(provider.requests) == expected_requests, (status, len(provider.requests), notices)
            assert len(notices) == (0 if allowed else 7), (status, notices)
            if not allowed:
                assert [e['details']['blocks'] for e in notices] == [1, 2, 3, 4, 5, 6, 6]
                assert notices[-1]['details']['capped'] and '已达拦截上限' in notices[-1]['content']
                expected_status = 'no_report' if status == 'at_noop' else status
                assert all(e['details']['status'] == expected_status for e in notices)
                # The actual provider receives all six injected continuation messages.
                assert all(any('verifier 完工门未通过' in str(m.get('content', '')) for m in p['messages'])
                           for p in provider.requests[2:])
            if provider.report:
                after = {str(p.relative_to(provider.report)): digest(p) for p in provider.report.rglob('*') if p.is_file()}
                assert after == provider.before_report, 'hook wrote into the frozen verdict fixture'
            record = {'status_fixture': status, 'pi_exit': result.returncode, 'provider_requests': len(provider.requests),
                      'blocks': len([e for e in notices if not e['details']['capped']]),
                      'cap_notices': len([e for e in notices if e['details']['capped']]), 'report_unchanged': True,
                      'disk_resume_verified': False}
            if status == 'no_report':
                provider.next_phase(False)
                resumed = subprocess.run([*argv[:-1], 'Resume the synthetic session.'], cwd=root, env=env,
                                         capture_output=True, text=True, timeout=60)
                (dest / 'resume-stdout.jsonl').write_text(resumed.stdout)
                assert resumed.returncode == 0, resumed.stderr
                assert provider.phase_requests == 1, 'disk resume reset the block limit'
                _, resumed_entries = session_entries(root, session_id)
                resumed_notices = [e for e in resumed_entries if e.get('type') == 'custom_message' and e.get('customType') == 'verifier-ready-gate']
                assert len(resumed_notices) == 8 and resumed_notices[-1]['details']['capped']
                record['disk_resume_verified'] = True
                (dest / 'resumed-session.jsonl').write_text('\n'.join(json.dumps(e) for e in resumed_entries) + '\n')
            write_json(dest / 'provider-requests.json', provider.requests)
            write_json(dest / 'result.json', record)
            return record
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def run_suite(out, cases):
    protected = {str(p): digest(p) for p in (ROOT / 'run.sh', ROOT / 'AGENTS.md', ROOT / 'spec/verifier-ready-gate.md') if p.exists()}
    code = snapshot()
    global_files = [Path.home() / '.pi/agent' / name for name in ('models.json', 'auth.json', 'settings.json', 'trust.json')]
    private = {str(p): digest(p) if p.exists() else None for p in global_files}
    records = []
    for case in cases:
        print(f'Running full pi CLI fixture: {case}', flush=True)
        records.append(run_case(out / case, case))
    assert snapshot() == code, 'source workspace code changed during isolated hook verification'
    assert all(digest(Path(p)) == sha for p, sha in protected.items())
    assert all((digest(Path(p)) if Path(p).exists() else None) == sha for p, sha in private.items())
    assert not (ROOT / '.pi/extensions/verifier-ready.ts').exists()
    summary = {'mechanism': 'real pi CLI + builtin write + actual hook + actual gate backend; scripted loopback provider',
        'external_model_calls': 0, 'registered_into_project': False, 'source_and_global_pi_unchanged': True, 'cases': records}
    write_json(out / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--case', action='append')
    args = parser.parse_args()
    run_suite(args.out, args.case or ['no_report', 'docs_only', 'at_noop', 'pass', 'pass_with_exception',
        'stale', 'running', 'review_invalid', 'coverage_incomplete', 'hard_fail', 'inconsistent', 'needs_human'])
