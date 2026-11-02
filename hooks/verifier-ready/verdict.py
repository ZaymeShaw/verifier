"""Recompute standalone verdicts; human release never changes observed consistency."""
from __future__ import annotations

from pathlib import Path
from typing import Literal
import copy
import getpass
import sys

from pydantic import BaseModel, ConfigDict, Field

from common import ROOT, fingerprint, digest, read_json, write_json, now


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    call_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Response(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    finding: str = Field(min_length=1)
    status: Literal['fixed', 'refuted']
    note: str = Field(min_length=1)
    counter_evidence: list[Evidence] = Field(default_factory=list)


class Responses(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    responses: list[Response]


def input_hashes(out):
    out = Path(out)
    return {str(path.relative_to(out)): digest(path) for folder in ('raw', 'ledger')
            for path in sorted((out / folder).rglob('*')) if path.is_file()}


def responses_for(out, findings, calls):
    path = Path(out) / 'response.json'
    entries = Responses.model_validate(read_json(path)).responses if path.exists() else []
    by_key = {entry.finding: entry for entry in entries}
    if len(by_key) != len(entries):
        raise ValueError('Duplicate response finding identity')
    known = {f['key']: f for f in findings}
    if set(by_key) - set(known):
        raise ValueError('Response refers to an unknown finding')
    call_ids = {call['call_id'] for call in calls}
    for entry in entries:
        if not entry.note.strip() or any(not e.quote.strip() or e.call_id not in call_ids for e in entry.counter_evidence):
            raise ValueError('Response requires a reason and valid original call references')
    return by_key


def adjudications(out):
    path = Path(out) / 'adjudication.json'
    return read_json(path)['entries'] if path.exists() else []


def compute(out, profile, *, root=ROOT):
    out = Path(out)
    run = read_json(out / 'run.json')
    calls = read_json(out / 'raw/calls.json')['calls'] if (out / 'raw/calls.json').exists() else []
    metrics = read_json(out / 'metrics.json') if (out / 'metrics.json').exists() else {'hard_checks': [], 'failures': ['Collection has not completed'], 'reference': []}
    summary = read_json(out / 'review-summary.json') if (out / 'review-summary.json').exists() else {
        'valid': False, 'shards': {}, 'findings': [], 'carry_over': [],
        'consistency': {'pass': False, 'calls_total': len(calls), 'full': 0, 'partial': 0,
                        'unverifiable': len(calls), 'missing_relation': 0, 'missing_common_rules': 0,
                        'confirmed': dict(blocking=0, high=0, diagnostic=0), 'explained': 0,
                        'open_key': 0, 'open_other': 0, 'invalid_ref': 0}}
    failures = list(metrics['failures'])
    current = fingerprint(root, profile)
    stale = any(run['fingerprint'].get(key) != current.get(key) for key in ('code', 'engine', 'profile', 'role_card'))
    if run.get('input_hashes') is not None and run['input_hashes'] != input_hashes(out):
        stale = True
        failures.append('Captured input material changed since collection')
    if stale:
        failures.append('Report fingerprint is stale')
    completed = run.get('phase') == 'completed'
    if not completed:
        failures.append('The complete collection and review command has not finished successfully')
    review_valid = bool(summary['valid'])
    if run.get('review_summary_sha256') != (digest(out / 'review-summary.json') if (out / 'review-summary.json').exists() else None):
        review_valid = False
    if (out / 'metrics.json').exists() and run.get('metrics_sha256') != digest(out / 'metrics.json'):
        stale = True
        failures.append('Captured hard-check results changed')
    for shard in summary['shards'].values():
        review_path = out / shard['path']
        meta_path = out / shard['meta']
        if not review_path.exists() or not meta_path.exists():
            review_valid = False
            continue
        meta = read_json(meta_path)
        review = read_json(review_path)
        if (not meta.get('has_result') or meta.get('exit_code') != 0 or not meta.get('scope_valid')
                or meta.get('review_sha256') != digest(review_path) or meta.get('spawn_id') != review.get('spawn_id')):
            review_valid = False
    snap_path = out / 'review/snapshot.json'
    if not snap_path.exists() or not read_json(snap_path).get('scope_valid'):
        review_valid = False
    if not review_valid:
        failures.append('Review is absent or invalid')

    findings = summary['findings']
    responses = responses_for(out, findings, calls)
    history = adjudications(out)
    rulings = {e['finding']: e for e in history if e.get('finding')}
    eligible = {f['key'] for f in findings}
    if set(rulings) - eligible:
        raise ValueError('Adjudication refers to an unknown finding')
    withdrawn = {key for key, e in rulings.items() if e['rule'] == 'withdrawn'}
    waived = {key for key, e in rulings.items() if e['rule'] == 'waived-by-human'}
    # Withdrawals correct a review error; waivers do not alter actual observations.
    effective = [{**f, 'verdict': 'confirmed'} if rulings.get(f['key'], {}).get('rule') == 'confirmed' else f
                 for f in findings if f['key'] not in withdrawn]
    consistency = copy.deepcopy(summary['consistency'])
    consistency['confirmed'] = {severity: sum(f['verdict'] == 'confirmed' and f['severity'] == severity for f in effective)
                                for severity in ('blocking', 'high', 'diagnostic')}
    consistency['open_key'] = sum(f['verdict'] == 'open' and f['severity'] in {'blocking', 'high'} for f in effective)
    consistency['open_other'] = sum(f['verdict'] == 'open' and f['severity'] == 'diagnostic' for f in effective)
    coverage_ok = (consistency['full'] == consistency['calls_total'] and not any(
        consistency.get(k, 0) for k in ('partial', 'unverifiable', 'missing_relation', 'missing_common_rules', 'unknown_common_rules', 'invalid_ref')))
    unresolved = [f for f in effective if f['verdict'] == 'confirmed' or
                  (f['verdict'] == 'open' and f['severity'] in {'blocking', 'high'})]
    blocking = [f for f in unresolved if f['key'] not in waived]
    carry = summary.get('carry_over', [])
    carry_unclosed = [f for f in carry if f.get('severity') in {'blocking', 'high'} and
                      f.get('ruling') != 'resolved' and f.get('key') not in withdrawn | waived]
    consistency['pass'] = bool(completed and review_valid and coverage_ok and not unresolved and not carry_unclosed)
    required = {f['key'] for f in effective if f['verdict'] in {'confirmed', 'open'} and f['severity'] in {'blocking', 'high'}}
    unanswered = required - set(responses) - set(rulings)
    pending = [key for key, response in responses.items() if response.status == 'refuted' and key not in rulings]
    if not coverage_ok:
        failures.append('Context review coverage is incomplete')
    if blocking:
        failures.append('Confirmed inconsistency or key uncertainty remains: ' + ', '.join(f['key'] for f in blocking))
    if carry_unclosed:
        failures.append('Previous key findings have not been verified resolved')
    if unanswered:
        failures.append('Findings need responses: ' + ', '.join(sorted(unanswered)))
    if pending:
        failures.append('Human adjudication required: ' + ', '.join(pending))
    hard_pass = bool(metrics['hard_checks']) and all(c['pass'] for c in metrics['hard_checks'])
    normal_release = completed and not stale and hard_pass and review_valid and coverage_ok and not blocking and not carry_unclosed and not unanswered and not pending
    override = any(e['rule'] == 'override-release' for e in history)
    # A human override is valid only for the unchanged, completed report it names.
    release = (normal_release or (override and not stale and run.get('phase') == 'completed'))
    gate = ('PASS_WITH_EXCEPTION' if (waived or override) else 'PASS') if release else 'NEEDS_HUMAN' if pending else 'FAIL'
    status = ('stale' if stale else 'needs_human' if pending else 'review_invalid' if not completed or not review_valid else
              'coverage_incomplete' if not coverage_ok else 'hard_fail' if not hard_pass else
              'inconsistent' if blocking or carry_unclosed else 'unanswered' if unanswered else 'pass')
    result = {'gate': gate, 'release_allowed': release, 'status': 'pass_with_exception' if release and (waived or override) else status,
              'generated_at': now(), 'fingerprint': run['fingerprint'], 'hard_checks': metrics['hard_checks'],
              'reference': metrics['reference'], 'baseline_stale': metrics.get('baseline_stale', False),
              'review': {'valid': review_valid, 'shards': summary['shards']},
              'consistency': consistency, 'response': {'unanswered': sorted(unanswered), 'refuted_pending': pending},
              'adjudication': {'withdrawn': len(withdrawn), 'waived_by_human': len(waived), 'override': override},
              'carry_over': carry, 'live': run.get('live'), 'failures': failures}
    return result


def publish(out, profile, *, root=ROOT):
    out = Path(out)
    result = compute(out, profile, root=root)
    write_json(out / 'verdict.json', result)
    lines = ['# Standalone verifier-ready result', '', f"Gate: **{result['gate']}**",
             f"Actual context consistency: **{'PASS' if result['consistency']['pass'] else 'NOT VERIFIED / FAIL'}**", '']
    if result['adjudication']['waived_by_human'] or result['adjudication']['override']:
        lines += ['Human release with exceptions. Existing inconsistencies have not been erased.', '']
    if result['baseline_stale']:
        lines += ['Models differ from the promoted baseline; volume regression checks still apply.', '']
    lines += [f"Read coverage: {result['consistency']['full']}/{result['consistency']['calls_total']} calls.", '',
              'This standalone command does not install hooks or change the business flow.', '']
    lines.extend('- ' + failure for failure in result['failures'])
    if adjudications(out):
        lines += ['', '## Human rulings', '']
        lines.extend(f"- {e.get('finding') or 'report'}: {e['rule']} — {e['note']}" for e in adjudications(out))
    summary_path = out / 'review-summary.json'
    if summary_path.exists():
        lines += ['', '## Findings', '']
        lines.extend(f"- {f['key']}: {f['verdict']} / {f['severity']} — {f.get('exclusive', '')}"
                     for f in read_json(summary_path)['findings'])
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


def adjudicate(out, key, rule, note):
    if not sys.stdin.isatty():
        raise ValueError('Human adjudication requires an interactive terminal; agents may not invoke it')
    if not note.strip():
        raise ValueError('A human ruling requires a reason')
    summary = read_json(Path(out) / 'review-summary.json')
    if rule not in {'confirmed', 'withdrawn', 'waived-by-human', 'override-release'}:
        raise ValueError('Unknown human ruling')
    keys = {f['key'] for f in summary['findings']}
    if rule != 'override-release' and key not in keys:
        raise ValueError('Specify the full shard::finding identity')
    entries = adjudications(out)
    entries.append({'finding': key if rule != 'override-release' else None, 'rule': rule, 'note': note,
                    'user': getpass.getuser(), 'at': now()})
    write_json(Path(out) / 'adjudication.json', {'entries': entries})
