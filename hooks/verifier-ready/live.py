"""A dedicated verifier instance, with relay and service cleanup on every exit."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from collect import collect
from common import ROOT, read_json, write_json


def _request(port, path, payload=None):
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(f'http://127.0.0.1:{port}{path}', data=body,
                      headers={'Content-Type': 'application/json'} if body is not None else {})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def _health(port):
    try:
        return _request(port, '/health')
    except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None


def _free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Dedicated gate port {port} is already in use') from exc


@contextmanager
def _ownership(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / '.gate-live.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another gate owns this dedicated instance') from exc
        try:
            # The server acquires this existing ownership lock itself at launch.
            with (runtime / 'server.lock').open('a') as server:
                try:
                    fcntl.flock(server, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError('Dedicated instance already has a server owner') from exc
                fcntl.flock(server, fcntl.LOCK_UN)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _seed(runtime):
    destination = runtime / 'data/llm_probe'
    if (destination / 'materials').exists():
        return
    source = ROOT / 'impl/data/llm_probe'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'materials', destination / 'materials')
    for name in ('capability_map.json', 'mock_cases.json'):
        shutil.copy2(source / name, destination / name)


def _stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def run(out: Path, profile):
    from impl.core.instances import instance_root, resolve_instance

    out = Path(out)
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    config = profile['live']
    port = config['port']
    if _health(port):
        raise RuntimeError(f'Dedicated gate port {port} already hosts a healthy server')
    _free_port(port)
    instance = resolve_instance(port)
    runtime = instance_root(instance['id'])
    cases_by_id = {case['id']: case for case in read_json(ROOT / 'impl/data/llm_probe/mock_cases.json')}
    cases = [cases_by_id[case_id] for case_id in config['cases']]
    started = time.monotonic()
    deadline = started + config['wall_clock_s']
    process = None
    execution_ids = []
    launch = ['bash', 'run.sh', 'tracing', 'run', 'server', '--port', str(port)]
    job_id = None

    def wait():
        if time.monotonic() >= deadline:
            raise TimeoutError('Verifier-ready live wall clock exceeded')
        if process.poll() is not None:
            raise RuntimeError('Dedicated verifier service exited before batch completion')
        time.sleep(min(config['poll_s'], max(0, deadline - time.monotonic())))

    with _ownership(runtime):
        # Refuse existing relay owners: tracing run can reuse live relays.
        for relay_port in instance['relay_ports']:
            _free_port(relay_port)
        _seed(runtime)
        with (raw / 'server.log').open('wb') as log:
            os.chmod(raw / 'server.log', 0o600)
            try:
                process = subprocess.Popen(launch, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
                while True:
                    health = _health(port)
                    if health:
                        if health.get('instance_id') != instance['id']:
                            raise RuntimeError('Health response belongs to a different instance')
                        break
                    wait()
                response = _request(port, '/api/batch_start', {'project': 'llm_probe', 'cases': cases, 'concurrency': config['concurrency']})
                job_id = response['job_id']
                requests = response['requests']
                write_json(raw / 'requests.json', requests)
                execution_ids = [request['execution_id'] for request in requests]
                if len(requests) != len(cases) or len(set(execution_ids)) != len(cases):
                    raise ValueError('batch_start did not return one execution identity per case')
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Verifier-ready live wall clock exceeded')
                    status = _request(port, '/api/batch_status', {'project': 'llm_probe', 'job_id': job_id})
                    write_json(raw / 'batch-status.json', status)
                    if status.get('status') == 'completed':
                        break
                    if status.get('status') == 'failed':
                        raise RuntimeError('Dedicated verifier batch failed')
                    wait()
                # llmtrace --settle handles late callbacks while the service stays alive.
                collect(out, execution_ids, instance['id'])
                completed = {'job_id': job_id, 'instance': instance['id'], 'port': port,
                             'execution_ids': execution_ids, 'cases': config['cases']}
            except Exception as exc:
                write_json(raw / 'live-error.json', {'reason': type(exc).__name__, 'job_id': job_id, 'execution_ids': execution_ids})
                raise
            finally:
                if process is not None:
                    try:
                        _stop(process)
                    finally:
                        cleanup = subprocess.run(['bash', 'run.sh', 'tracing', 'down', '--port', str(port)],
                                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
                        write_json(raw / 'cleanup.json', {'port': port, 'exit_code': cleanup.returncode})
                        if cleanup.returncode:
                            raise RuntimeError('Dedicated tracing cleanup failed')
    completed['elapsed_s'] = time.monotonic() - started
    return completed
