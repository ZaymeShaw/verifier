"""Hard checks and volume references computed from exported metadata only."""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re


def select_executions(batch, execution_ids):
    selected = set(execution_ids)
    return {**batch,
            'identities': [item for item in batch.get('identities', []) if item.get('execution_id') in selected],
            'events': [event for event in batch.get('events', []) if event.get('run', {}).get('execution_id') in selected]}


def case_runs(batch):
    return {event['run'].get('case_id') or event['run'].get('request_case_id'): event['run']
            for event in batch.get('events', []) if isinstance(event.get('run'), dict)}


def business_unreachable(run):
    trace = run.get('trace') or {}
    flags = [flag for fallback in trace.get('fallbacks', []) for flag in fallback.get('quality_flags', [])]
    return bool(run.get('error') and (
        not trace or 'live_service_unavailable' in flags
        or 'live_service_unavailable' in str(run['error'])
        or trace.get('error') == run['error'] and not trace.get('steps') and not trace.get('records')
    ))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def evaluate(calls, batch, profile, elapsed_s, baseline=None):
    records = calls['calls']
    hard, reference, failures = [], [], []
    thresholds = profile['hard_checks']
    groups = defaultdict(list)
    for call in records:
        groups[call.get('case_id')].append(call)
    runs = case_runs(batch)
    identities = [i.get('request_case_id') or i.get('case_id') for i in batch.get('identities', [])]
    case_ids = dict.fromkeys([*identities, *runs, *groups])

    def check(ident, value, threshold, passed, case=None, **extra):
        record = {'id': ident, 'pass': bool(passed), 'value': value, 'threshold': threshold, **extra}
        if case is not None:
            record['case'] = case
        hard.append(record)
        if not passed:
            failures.append(f'{ident}:{case}' if case is not None else ident)

    def ref(ident, case, value, cap=None, **extra):
        row = {'id': ident, 'case': case, 'value': value, **extra}
        if cap is not None:
            row['reference'] = cap
        reference.append(row)

    for case in case_ids:
        if case is None:
            check('trace_case_identity', None, 'case_id present', False)
            continue
        run = runs.get(case)
        scoped = groups[case]
        if run and business_unreachable(run):
            check('business_unreachable', run['error'], 'business reachable', False, case)
        else:
            axes = (run or {}).get('eval_axes') or {}
            enabled = [a['type'] for a in axes.get('axes', []) if a.get('enabled') is True]
            results = {a.get('axis_id'): a for a in axes.get('results', [])}
            statuses = {axis: results.get(axis, {}).get('status') for axis in enabled}
            judge = (run or {}).get('judge')
            judge_ok = bool(judge) and not judge.get('error') and not (run or {}).get('error')
            check('U1', {'axes': statuses, 'judge_present': bool(judge), 'error': (run or {}).get('error')},
                  'enabled axes succeeded; main judge present without error',
                  run is not None and isinstance(axes.get('axes'), list)
                  and all(s == 'succeeded' for s in statuses.values()) and judge_ok, case)
            timings = (run or {}).get('stage_timings') or {}
            axis_ms, judge_ms = timings.get('eval_axes_ms'), timings.get('judge_ms')
            duration = (axis_ms + judge_ms) / 1000 if _number(axis_ms) and _number(judge_ms) else None
            check('L1', duration, thresholds['case_eval_s'], duration is not None and duration <= thresholds['case_eval_s'], case)
            ref('live_s', case, timings.get('live_ms') / 1000 if _number(timings.get('live_ms')) else None)

        stages = Counter(c.get('stage') for c in scoped)
        repeats = sum(count - 1 for stage, count in stages.items() if stage is not None and not re.search(r':s\d+$', stage))
        tokens = [(c.get('usage') or {}).get('prompt_tokens') for c in scoped]
        # Aggregate observed usage; a failed wire call can have no usage at all.
        # Report missing records explicitly and do not allow an incomplete V5 win.
        observed_tokens = [t for t in tokens if _number(t)]
        missing_tokens = len(tokens) - len(observed_tokens)
        v3 = max(observed_tokens, default=0) if observed_tokens or not scoped else None
        v4 = sum(observed_tokens) if observed_tokens or not scoped else None
        ref('V1', case, len(scoped), 14)
        ref('V2', case, repeats, 0)
        ref('V3', case, v3, 80000, missing_calls=missing_tokens)
        ref('V4', case, v4, 500000, missing_calls=missing_tokens)
        ref('non_succeeded', case, sum(c.get('state') != 'succeeded' for c in scoped))
        ref('fallback_calls', case, sum(c.get('gateway') != 'verifier_primary' for c in scoped))
        completion = [(c.get('usage') or {}).get('completion_tokens') for c in scoped]
        ref('completion_tokens', case, sum(t for t in completion if _number(t)), missing_calls=sum(not _number(t) for t in completion))
        ref('by_stage', case, {stage: {'calls': count, 'prompt_tokens': sum((c.get('usage') or {})['prompt_tokens'] for c in scoped
                                      if c.get('stage') == stage and _number((c.get('usage') or {}).get('prompt_tokens'))),
                                      'missing_usage_calls': sum(not _number((c.get('usage') or {}).get('prompt_tokens')) for c in scoped if c.get('stage') == stage)}
                               for stage, count in stages.items()})

    latency = [c.get('latency_ms') for c in records]
    known = bool(latency) and all(_number(value) for value in latency)
    ordered = sorted(latency) if known else []
    p95 = ordered[math.ceil(.95 * len(ordered)) - 1] / 1000 if ordered else None
    maximum = ordered[-1] / 1000 if ordered else None
    check('L2_p95', p95, thresholds['latency_p95_s'], p95 is not None and p95 <= thresholds['latency_p95_s'])
    check('L2_max', maximum, thresholds['latency_max_s'], maximum is not None and maximum <= thresholds['latency_max_s'],
          call_id=max(records, key=lambda c: c.get('latency_ms') or 0)['call_id'] if known else None)
    check('W', elapsed_s, profile['live']['wall_clock_s'], _number(elapsed_s) and elapsed_s <= profile['live']['wall_clock_s'])
    if baseline is not None:
        previous = {(r.get('case'), r['id']): r.get('value') for r in baseline['reference']}
        for row in reference:
            if row['id'] in ('V1', 'V3', 'V4'):
                old = previous.get((row['case'], row['id']))
                limit = old * thresholds['baseline_growth'] if _number(old) else None
                check('V5', row['value'], limit,
                      limit is not None and _number(row['value']) and not row.get('missing_calls') and row['value'] <= limit,
                      row['case'], metric=row['id'], baseline=old)
    return {'hard_checks': hard, 'reference': reference, 'failures': failures}
