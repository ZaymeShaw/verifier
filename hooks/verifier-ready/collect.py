"""Collect exclusively through llmtrace; preserve its exports verbatim."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

from common import ROOT, now, read_json, safe_id, write_json


class TraceExportError(RuntimeError):
    reason = 'trace_export'


def _validate(envelope, execution_ids):
    if (not isinstance(envelope, dict) or envelope.get('schema') != 'llmtrace.calls/v1'
            or envelope.get('status') != 'complete' or envelope.get('pending_call_ids')
            or envelope.get('conflicts') or not isinstance(envelope.get('calls'), list)):
        raise TraceExportError('trace_export: incomplete or invalid llmtrace.calls/v1 envelope')
    ids = []
    for call in envelope['calls']:
        try:
            ids.append(safe_id(call['call_id']))
        except (KeyError, ValueError, TypeError) as exc:
            raise TraceExportError('trace_export: invalid call identity') from exc
        if call.get('execution_id') not in execution_ids or call.get('state') == 'pending':
            raise TraceExportError('trace_export: call outside selected executions or pending')
    if len(ids) != len(set(ids)):
        raise TraceExportError('trace_export: duplicate call identity')


def collect(out: Path, execution_ids: list[str], instance_id: str):
    from impl.core.instances import instance_root
    from impl.core.tracing_retention import log_lock

    out = Path(out)
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    if not execution_ids or any(not isinstance(e, str) or not e for e in execution_ids):
        raise TraceExportError('trace_export: execution IDs must come from batch_start')
    cfg = yaml.safe_load((ROOT / 'tracing/config.yaml').read_text(encoding='utf-8'))
    dependency = (ROOT / cfg['llmtracing_root']).resolve()
    prefix = [str(dependency / 'llm_gateway/.venv/bin/python'), str(dependency / 'llmtrace'), 'query']
    runtime = instance_root(instance_id)
    logs = ['--log', str(runtime / 'tracing/logs'), '--include-rotated']
    selection = ['--execution-id', ','.join(execution_ids)]
    manifest = {'execution_ids': execution_ids, 'instance_id': instance_id, 'commands': [], 'status': 'running'}

    def command(argv, destination):
        entry = {'argv': argv, 'started_at': now(), 'exit_code': None}
        manifest['commands'].append(entry)
        try:
            # Neither stdout nor stderr is emitted into a harness transcript.
            with destination.open('wb') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.PIPE, timeout=300)
            entry['exit_code'] = result.returncode
            if result.returncode != 0:
                raise TraceExportError(f'trace_export: llmtrace command exited {result.returncode}')
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TraceExportError(f'trace_export: {type(exc).__name__}') from exc
        finally:
            entry['ended_at'] = now()

    try:
        with tempfile.TemporaryDirectory(prefix='.trace-export-', dir=raw) as staging:
            stage = Path(staging)
            with log_lock(runtime / 'tracing'):
                # A late callback gets a second supported CLI settle, never a log parser.
                for attempt in range(2):
                    try:
                        command([*prefix, 'calls', *logs, *selection, '--format', 'json', '--settle', '30'], stage / 'calls.json')
                        envelope = read_json(stage / 'calls.json')
                        _validate(envelope, execution_ids)
                        break
                    except (TraceExportError, json.JSONDecodeError) as exc:
                        if attempt or (isinstance(exc, TraceExportError) and manifest['commands'][-1]['exit_code'] not in (0, 3)):
                            raise TraceExportError('trace_export: invalid or incomplete call export') from exc
                (stage / 'calls').mkdir()
                for call in envelope['calls']:
                    command([*prefix, 'show', call['call_id'], '--full', *logs], stage / 'calls' / (call['call_id'] + '.txt'))
                    try:
                        (stage / 'calls' / (call['call_id'] + '.txt')).read_bytes().decode('utf-8')
                    except UnicodeDecodeError as exc:
                        raise TraceExportError('trace_export: full call is not valid UTF-8') from exc
                command([*prefix, 'calls', *logs, *selection, '--html', str(stage / 'html')], stage / 'html-command.txt')
                if not (stage / 'html/llm_trace.html').is_file():
                    raise TraceExportError('trace_export: HTML export missing')
            # Publish only after every full-call and HTML command succeeded.
            for name in ('calls', 'html'):
                target = raw / name
                if target.exists():
                    shutil.rmtree(target)
                (stage / name).replace(target)
            (stage / 'calls.json').replace(raw / 'calls.json')
            prepare_chunks(out)
        manifest['status'] = 'complete'
        return envelope
    except Exception:
        manifest['status'] = 'failed'
        manifest['reason'] = 'trace_export'
        raise
    finally:
        write_json(raw / 'export-manifest.json', manifest)


def chunk_file(source: Path):
    """Split UTF-8 at code point boundaries; offsets and digest refer to payload."""
    source = Path(source).resolve()
    data = source.read_bytes()
    data.decode('utf-8')  # reject invalid bytes rather than silently replacing them
    folder = source.with_suffix('.chunks')
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('chunk-*.txt'):
        old.unlink()
    label = str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source)
    descriptors = []
    start = 0
    # Reserve header space, then calculate the actual serialized size too.
    while start < len(data) or not descriptors:
        end = min(len(data), start + 39000)
        while end < len(data) and data[end] & 0xC0 == 0x80:
            end -= 1
        payload = data[start:end]
        if payload.count(b'\n') > 1694:
            cursor = start
            for _ in range(1694):
                cursor = data.index(b'\n', cursor, end) + 1
            end = cursor
            payload = data[start:end]
        sha = hashlib.sha256(payload).hexdigest()
        header = f'Source: {label}\nBytes: [{start}, {end})\nSHA256: {sha}\n--- payload ---\n'.encode('utf-8')
        if len(header) + len(payload) > 40000:
            # Only exceptionally long source paths can use the reserved 1KB.
            end = start + max(0, 40000 - len(header))
            while end < len(data) and data[end] & 0xC0 == 0x80:
                end -= 1
            if end <= start and data:
                raise ValueError('Chunk source label is too long')
            payload = data[start:end]
            sha = hashlib.sha256(payload).hexdigest()
            header = f'Source: {label}\nBytes: [{start}, {end})\nSHA256: {sha}\n--- payload ---\n'.encode('utf-8')
        path = folder / f'chunk-{len(descriptors) + 1:04d}.txt'
        path.write_bytes(header + payload)
        descriptors.append({'path': str(path), 'start_byte': start, 'end_byte': end, 'sha256': sha})
        start = end
        if start == len(data):
            break
    return descriptors


def prepare_chunks(out):
    out = Path(out).resolve()
    envelope = read_json(out / 'raw/calls.json')
    manifest = {'calls': {}}
    for call in envelope['calls']:
        call_id = safe_id(call['call_id'])
        chunks = chunk_file(out / 'raw/calls' / (call_id + '.txt'))
        for chunk in chunks:
            chunk['path'] = str(Path(chunk['path']).relative_to(out))
        manifest['calls'][call_id] = chunks
    write_json(out / 'raw/calls/chunks-manifest.json', manifest)
    return manifest
