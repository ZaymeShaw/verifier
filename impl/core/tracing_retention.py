"""Verifier owns retention of its relay output; llmtracing remains unchanged."""
from contextlib import contextmanager
import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3

from .instances import data_root, tracing_root


@contextmanager
def log_lock(runtime=None, *, exclusive=False):
    runtime = runtime or tracing_root()
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / '.logs.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def _alive(pid):
    try:
        os.kill(pid, 0); return True
    except ProcessLookupError:
        return False


def workspace_trace_selection(database, project=None):
    """Current row executions, including pending rows bound by the active batch."""
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        where, params = (' WHERE project=?', (project,)) if project else ('', ())
        bindings = {}
        for pid, raw in db.execute('SELECT project,identities_json FROM current_batches' + where, params):
            for identity in json.loads(raw):
                bindings[(pid, identity['request_key'])] = identity
        executions, unbound = set(), []
        for pid, position, key, raw in db.execute(
                'SELECT project,position,request_key,run_json FROM current_cases' + where, params):
            if not key:
                continue  # Never submitted, or the workspace was explicitly cleared.
            run = json.loads(raw) if raw else {}
            identity = run.get('llmtracing') or run or bindings.get((pid, key), {})
            execution = identity.get('execution_id')
            if execution:
                executions.add(execution)
            else:
                unbound.append({'project': pid, 'position': position, 'request_key': key})
        return {'execution_ids': sorted(executions), 'unbound_rows': unbound}


def cleanup(runtime, ctl, *, database=None, dry_run=False):
    database = database or data_root() / 'latest_runs.sqlite3'
    # No authority to remove logs before any batch workspace exists.
    if not database.is_file():
        return {'status': 'skipped', 'reason': 'no batch database'}
    with log_lock(runtime, exclusive=True):
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
            rows = db.execute('SELECT job_id,owner_pid,status FROM current_batches').fetchall()
        if any(status in ('pending', 'running') and _alive(pid) for _, pid, status in rows):
            return {'status': 'skipped', 'reason': 'a batch is running in this instance'}
        selection = workspace_trace_selection(database)
        # Older compact results discarded their identity. Do not guess by case name
        # or delete potentially referenced logs until these rows have been rerun.
        if selection['unbound_rows']:
            return {'status': 'skipped', 'reason': 'current rows lack execution identities', **selection}
        keep = set(selection['execution_ids'])
        if dry_run:
            return {'status': 'preview', 'keep_execution_ids': sorted(keep),
                    'logs_bytes': sum(p.stat().st_size for p in (runtime / 'logs').rglob('*') if p.is_file())}
        for gateway in ctl.discover(runtime):
            ctl.rotate(gateway)  # existing supported rotate; late appends stay in live log
        archives = sorted((runtime / 'logs').rglob('llm_calls_*.jsonl.gz'))
        calls = set()
        for archive in archives:
            with gzip.open(archive, 'rt') as source:
                for line in source:
                    record = json.loads(line)
                    if record.get('execution_id') in keep and record.get('call_id'):
                        calls.add(record['call_id'])
        # Preserve id-only terminal events when their request belongs to a kept execution.
        before = sum(p.stat().st_size for p in archives)
        for archive in archives:
            temporary = archive.with_name(archive.name + '.retaining')
            count = 0
            try:
                with gzip.open(archive, 'rt') as source, gzip.open(temporary, 'wt') as dest:
                    for line in source:
                        record = json.loads(line)
                        if record.get('execution_id') in keep or record.get('call_id') in calls:
                            dest.write(line); count += 1
                if count:
                    temporary.replace(archive)
                else:
                    archive.unlink(); temporary.unlink()
            finally:
                temporary.unlink(missing_ok=True)
        # Saved CLI reports declare their execution IDs; web reports are temporary.
        for manifest in (runtime / 'reports').glob('*/verifier-report.json'):
            metadata = json.loads(manifest.read_text())
            report_executions = set(metadata.get('execution_ids') or [])
            if not report_executions or not report_executions.issubset(keep):
                shutil.rmtree(manifest.parent)
        after = sum(p.stat().st_size for p in archives if p.exists())
        return {'status': 'cleaned', 'keep_execution_ids': sorted(keep), 'archive_bytes_before': before,
                'archive_bytes_after': after}
