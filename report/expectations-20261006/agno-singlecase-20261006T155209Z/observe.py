"""Read-only observation of one authorized live case; writes only this report directory."""
import argparse
import collections
import datetime
import json
from pathlib import Path
import sqlite3
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'
JOB = json.loads((OUT / 'batch-start.json').read_text())['job_id']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wait', type=int, default=0)
    args = parser.parse_args()
    if args.wait:
        time.sleep(args.wait)
    cursor_path = OUT / 'observation-cursors.json'
    cursors = json.loads((cursor_path if cursor_path.exists() else OUT / 'log-start-offsets.json').read_text())
    events_path = OUT / 'observed-event-metadata.jsonl'
    collected = []
    for relative, offset in cursors.items():
        path = ROOT / relative
        if not path.exists():
            continue
        with path.open('rb') as stream:
            stream.seek(offset if path.stat().st_size >= offset else 0)
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line:
                    break
                if not line.endswith(b'\n'):
                    stream.seek(start)
                    break
                if JOB.encode() not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('run_id') != JOB:
                    continue
                item = {key: row.get(key) for key in (
                    'event', 'ts', 'call_id', 'run_id', 'execution_id', 'stage', 'gateway',
                    'model', 'latency_ms', 'first_frame_ms', 'first_frame_kind', 'status_code')}
                request = row.get('client_request') or {}
                if request:
                    item.update(request_chars=len(json.dumps(request, ensure_ascii=False)),
                                message_count=len(request.get('messages') or []),
                                reasoning_effort=request.get('reasoning_effort'),
                                native_response_format=bool(request.get('response_format')))
                error = row.get('error') or {}
                if isinstance(error, dict):
                    item['error_type'] = error.get('type')
                collected.append(item)
            cursors[relative] = stream.tell()
    if collected:
        with events_path.open('a') as stream:
            for row in collected:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    cursor_path.write_text(json.dumps(cursors, indent=2) + '\n')
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    db = sqlite3.connect((INSTANCE / 'data/latest_runs.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    batch = dict(db.execute("SELECT project,job_id,status,error FROM current_batches WHERE project='llm_probe'").fetchone())
    progress = dict(db.execute("SELECT stage,completed,total,started_at,last_event_at,finished_at FROM task_progress WHERE project='llm_probe' AND kind='batch'").fetchone())
    case = db.execute("SELECT status,error,run_json FROM current_cases WHERE project='llm_probe' AND position=24").fetchone()
    result = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), target_job=JOB,
                  batch=batch, progress=progress, case_status=case['status'],
                  event_counts=dict(collections.Counter(e['event'] for e in events)), recent=events[-6:])
    if case['run_json']:
        run = json.loads(case['run_json'])
        if run.get('job_id') == JOB:
            (OUT / 'run-result.json').write_text(json.dumps(run, ensure_ascii=False, indent=2) + '\n')
            result['timings'] = run.get('stage_timings')
            result['axes'] = [{k: a.get(k) for k in ('axis_id', 'status', 'verdict', 'error', 'started_at', 'finished_at')}
                              for a in (run.get('eval_axes') or {}).get('results', [])]
    (OUT / 'observation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
