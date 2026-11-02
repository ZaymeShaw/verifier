#!/usr/bin/env python3
"""Standalone verifier-ready command. It never installs a hook or edits the main flow."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import ROOT, HERE, now, load_profile, fingerprint, read_json, write_json, digest
import verdict

CURRENT = ROOT / 'report/verifier-ready/current/progress.json'


@contextmanager
def report_lock(out):
    with (Path(out) / '.gate.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another command is already writing this report') from exc
        yield


def progress(out, phase):
    write_json(CURRENT, {'report': str(out), 'phase': phase, 'pid': os.getpid(), 'at': now()})


@contextmanager
def report_operation(out):
    """Record failure before releasing this operation's exclusive report lock."""
    with report_lock(out):
        try:
            yield
        except (ValueError, OSError, RuntimeError) as exc:
            save_run(out, phase='failed', error=str(exc), ended_at=now())
            progress(out, 'failed')
            raise


def new_report(path, profile, previous=None):
    out = Path(path).resolve() if path else ROOT / 'report/verifier-ready' / (now().replace(':', '').replace('+', '_') + '-' + uuid.uuid4().hex[:6])
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'run.json', {'created_at': now(), 'phase': 'created', 'mode': 'standalone',
                                'fingerprint': fingerprint(profile=profile), 'previous': str(previous) if previous else None})
    return out


def save_run(out, **fields):
    path = out / 'run.json'
    run = read_json(path)
    run.update(fields)
    write_json(path, run)
    return run


def baseline():
    path = HERE / 'baseline/metrics.json'
    return read_json(path) if path.exists() else None


def finish_collection(out, profile, elapsed):
    import ledger
    import metrics
    ledger.build(out)
    envelope = read_json(out / 'raw/calls.json')
    batch_path = out / 'raw/batch-status.json'
    batch = read_json(batch_path) if batch_path.exists() else {}
    selected = {item['execution_id'] for item in read_json(out / 'raw/requests.json')}
    # Preserve the raw batch verbatim while evaluating only the selected executions.
    batch = metrics.select_executions(batch, selected)
    result = metrics.evaluate(envelope, batch, profile, elapsed, baseline())
    models = {'judge': sorted({call['model'] for call in envelope['calls'] if call.get('model')}),
              'reviewer': profile['reviewer']['model']}
    result['models'] = models
    prior = baseline()
    result['baseline_stale'] = bool(prior and prior.get('models') != models)
    write_json(out / 'metrics.json', result)
    recorded = read_json(out / 'run.json')['fingerprint']
    recorded['models'] = models
    save_run(out, phase='collected', fingerprint=recorded, input_hashes=verdict.input_hashes(out), metrics_sha256=digest(out / 'metrics.json'))


def perform_review(out, profile, previous=None, case_id=None):
    import review
    run = read_json(out / 'run.json')
    current = fingerprint(profile=profile)
    if any(run['fingerprint'].get(k) != current.get(k) for k in ('code', 'engine', 'profile', 'role_card')):
        raise ValueError('Code or review configuration changed; collect a new run instead of reviewing stale material')
    if run.get('input_hashes') != verdict.input_hashes(out):
        raise ValueError('Frozen captured inputs changed; this report cannot be reviewed')
    progress(out, 'reviewing')
    save_run(out, phase='reviewing')
    # Parent writes no files inside out while reviewer scope snapshots are active.
    result = review.run(out, profile, previous=previous, case_id=case_id)
    write_json(out / 'review-summary.json', result)
    metrics = read_json(out / 'metrics.json')
    metrics['reference'] = [row for row in metrics['reference'] if row['id'] != 'review_cost']
    for shard, entry in result['shards'].items():
        meta = read_json(out / entry['meta'])
        metrics['reference'].append({'id': 'review_cost', 'case': shard,
            'value': {'wall_s': meta.get('elapsed_s'), 'tool_calls': meta.get('tool_call_count'),
                      'model_requests': meta.get('model_requests'), 'usage': meta.get('usage', {})}})
    write_json(out / 'metrics.json', metrics)
    save_run(out, phase='completed', ended_at=now(), review_summary_sha256=digest(out / 'review-summary.json'),
             metrics_sha256=digest(out / 'metrics.json'))
    published = verdict.publish(out, profile)
    progress(out, 'completed')
    return published


def resolve_report(path):
    if path:
        out = Path(path).resolve()
    elif CURRENT.exists():
        out = Path(read_json(CURRENT)['report'])
    else:
        raise ValueError('No report exists; supply --out or collect a run first')
    if not (out / 'run.json').exists():
        raise ValueError('Not a verifier-ready report')
    return out


def status(out, profile, *, root=ROOT):
    if CURRENT.exists():
        state = read_json(CURRENT)
        if state['report'] == str(out) and state['phase'] in {'collecting', 'reviewing'}:
            try:
                os.kill(state['pid'], 0)
                return {'status': 'running', 'gate': 'FAIL', 'release_allowed': False, 'progress': state}
            except ProcessLookupError:
                pass
    return verdict.compute(out, profile, root=root)


def previous_report(explicit=None):
    if explicit:
        return resolve_report(explicit)
    if not CURRENT.exists():
        return None
    candidate = Path(read_json(CURRENT)['report'])
    seen = set()
    while candidate not in seen and (candidate / 'run.json').exists():
        seen.add(candidate)
        if (candidate / 'review-summary.json').exists():
            return candidate
        run = read_json(candidate / 'run.json')
        if not run.get('previous'):
            break
        candidate = Path(run['previous'])
    return None


def hook_state(profile, *, root=ROOT):
    """Read-only bridge for the independent pi adapter; never collects or reviews."""
    limit = profile['hook']['max_blocks']
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError('hook.max_blocks must be a positive integer')
    code = fingerprint(root=root, profile=profile)['code']
    if not CURRENT.exists():
        return {'code': code, 'max_blocks': limit, 'report': None, 'status': 'no_report',
                'gate': 'FAIL', 'release_allowed': False, 'failures': ['No verifier-ready report exists']}
    out = resolve_report(None)
    return {'code': code, 'max_blocks': limit, 'report': str(out), **status(out, profile, root=root)}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group()
    action.add_argument('--all', action='store_true', help='Dedicated live run, capture, review and verdict')
    action.add_argument('--live', action='store_true', help='Dedicated live run and capture, without review')
    action.add_argument('--collect', action='store_true', help='Export an explicitly selected existing instance/executions')
    action.add_argument('--review', action='store_true', help='Review an already captured report')
    action.add_argument('--status', action='store_true', help='Recompute status without running models')
    action.add_argument('--hook-status', action='store_true', help='Read-only pi hook state, code digest and block limit')
    p.add_argument('--out', type=Path, help='New report directory for collection, existing report for review/status')
    p.add_argument('--previous', type=Path, help='Previous report with findings to verify on this new run')
    p.add_argument('--case', dest='case_id', help='Re-review a single case; common-rule aggregation is recomputed')
    p.add_argument('--instance', help='Existing verifier instance ID for --collect')
    p.add_argument('--execution-id', action='append', help='Opaque execution ID for --collect; repeat for each execution')
    p.add_argument('--batch-status', type=Path, help='Original archived batch status for --collect')
    p.add_argument('--wall-clock-s', type=float, help='Known measured wall clock for archived collection')
    p.add_argument('--json', action='store_true', help='Output structured status')
    p.add_argument('--agent-dir', type=Path, help='Explicit private pi agent configuration directory')
    sub = p.add_subparsers(dest='command')
    human = sub.add_parser('adjudicate', help='Human terminal only; never invoked by implementation agents')
    human.add_argument('report', type=Path)
    human.add_argument('finding', nargs='?', help='Full shard::finding identity')
    human.add_argument('--rule', choices=['confirmed', 'withdrawn', 'waived-by-human'])
    human.add_argument('--override-release', action='store_true')
    human.add_argument('--note', required=True)
    promote = sub.add_parser('promote-baseline', help='Explicitly promote a fully consistent passing report')
    promote.add_argument('report', type=Path)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    profile = load_profile()
    if args.agent_dir:
        profile['reviewer']['agent_dir'] = str(args.agent_dir.resolve())
    if not any((args.all, args.live, args.collect, args.review, args.status, args.hook_status, args.command)):
        p.print_help()
        return 0
    out = None
    try:
        if args.command == 'adjudicate':
            out = resolve_report(args.report)
            with report_lock(out):
                rule = 'override-release' if args.override_release else args.rule
                verdict.adjudicate(out, args.finding, rule, args.note)
                result = verdict.publish(out, profile)
        elif args.command == 'promote-baseline':
            out = resolve_report(args.report)
            result = verdict.compute(out, profile)
            if result['gate'] != 'PASS' or not result['consistency']['pass']:
                raise ValueError('Baseline requires an unchanged, fully consistent PASS without exceptions')
            write_json(HERE / 'baseline/metrics.json', read_json(out / 'metrics.json'))
            shutil.copyfile(out / 'summary.md', HERE / 'baseline/review-summary.md')
        elif args.hook_status:
            result = hook_state(profile)
        elif args.status:
            result = status(resolve_report(args.out), profile)
        elif args.review:
            out = resolve_report(args.out)
            with report_operation(out):
                run = read_json(out / 'run.json')
                previous = args.previous or (Path(run['previous']) if run.get('previous') else None)
                result = perform_review(out, profile, previous, args.case_id)
        else:
            if args.collect and (not args.instance or not args.execution_id or not args.batch_status or args.wall_clock_s is None):
                raise ValueError('--collect requires --instance, --execution-id, --batch-status and measured --wall-clock-s')
            previous = previous_report(args.previous) if not args.collect else resolve_report(args.previous) if args.previous else None
            out = new_report(args.out, profile, previous)
            with report_operation(out):
                progress(out, 'collecting')
                save_run(out, phase='collecting')
                if args.collect:
                    import collect
                    (out / 'raw').mkdir()
                    shutil.copyfile(args.batch_status, out / 'raw/batch-status.json')
                    archived = read_json(args.batch_status)
                    identities = [item for item in archived.get('identities', []) if item.get('execution_id') in args.execution_id]
                    if {item.get('execution_id') for item in identities} != set(args.execution_id):
                        raise ValueError('Selected executions must exist in the archived batch identities')
                    write_json(out / 'raw/requests.json', identities)
                    collect.collect(out, args.execution_id, args.instance)
                    elapsed = args.wall_clock_s
                    save_run(out, live={'instance': args.instance, 'execution_ids': args.execution_id, 'elapsed_s': elapsed,
                                        'source': 'explicit archived export'})
                else:
                    import live
                    runtime = live.run(out, profile)
                    elapsed = runtime['elapsed_s']
                    save_run(out, live=runtime)
                finish_collection(out, profile, elapsed)
                if args.all:
                    result = perform_review(out, profile, previous)
                else:
                    result = verdict.publish(out, profile)
                    progress(out, 'collected')
        print(json.dumps({'report': str(out) if out else str(args.out) if args.out else None, **result}, ensure_ascii=False, indent=2))
        return 0 if result.get('release_allowed') else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'error', 'release_allowed': False, 'report': str(out) if out else None,
                          'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
