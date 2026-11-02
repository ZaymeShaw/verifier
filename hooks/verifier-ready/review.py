"""Validate evidence-backed reviewer shards, aggregate common rules, and count findings."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common import CATEGORIES, HERE, ROOT, RULE_KEYS, SEVERITIES, digest, read_json, safe_id, snapshot, write_json
import spawn_reviewer


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class End(Record):
    call_id: str = Field(min_length=1)
    side: Literal['request', 'response']
    where: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=300)


class Finding(Record):
    id: str = Field(min_length=1)
    verdict: Literal['confirmed', 'explained', 'open']
    severity: Literal['blocking', 'high', 'diagnostic']
    category: int = Field(ge=1, le=7)
    ends: list[End]
    scope: str = Field(min_length=1)
    exclusive: str = Field(min_length=1)
    counter_evidence: str
    impact: str = Field(min_length=1)
    remediation: str


class Coverage(Record):
    call_id: str = Field(min_length=1)
    depth: Literal['full', 'partial', 'unverifiable']
    note: str


class Relation(Record):
    call_id: str = Field(min_length=1)
    category: int = Field(ge=1, le=7)
    result: Literal['ok', 'finding', 'n/a']
    finding_ids: list[str]
    note: str


class Scope(Record):
    role: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Rule(Record):
    key: Literal['role', 'output_structure', 'axis_identifiers', 'reference_format',
                 'coverage', 'evidence_authority', 'outcome_semantics']
    scope: Scope
    status: Literal['present', 'n/a', 'unknown']
    call_id: str | None
    where: str
    quote: str = Field(max_length=300)
    note: str


class Carry(Record):
    finding: str = Field(min_length=1)
    ruling: Literal['resolved', 'persists', 'unverifiable']
    ends: list[End]
    finding_ids: list[str]
    note: str = Field(min_length=1)


class OutputCheck(Record):
    axis: str = Field(min_length=1)
    items: list[str] = Field(min_length=1)


class DiffRuling(Record):
    diff_id: str = Field(min_length=1)
    verdict: Literal['confirmed', 'explained', 'open']
    finding_ids: list[str]
    note: str = Field(min_length=1)


class Review(Record):
    spawn_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    coverage: list[Coverage]
    relations: list[Relation]
    common_rules: list[Rule]
    findings: list[Finding]
    carry_over: list[Carry]
    output_checks: list[OutputCheck]
    diff_rulings: list[DiffRuling] = Field(default_factory=list)
    summary: str = Field(min_length=1)


def tool_records(path):
    try:
        return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line]
    except (OSError, ValueError):
        return []


def bad_return(value):
    if isinstance(value, dict):
        if any(value.get(key) for key in ('truncated', 'firstLineExceedsLimit', 'isError', 'is_error')):
            return True
        return any(bad_return(item) for item in value.values())
    if isinstance(value, list):
        return any(bad_return(item) for item in value)
    return False


def full_chunks(out, call_id, manifest, tools):
    """Require exact returned text, not merely a pathname or a successful tool start."""
    chunks = manifest.get('calls', {}).get(call_id, [])
    if not chunks:
        return False, 'chunk_manifest_missing'
    missing, truncated = False, False
    for chunk in chunks:
        relative = chunk.get('path')
        if not isinstance(relative, str):
            return False, 'chunk_manifest_invalid'
        path = (Path(out) / relative).resolve()
        if not path.is_relative_to(Path(out).resolve() / 'raw/calls') or not path.is_file():
            return False, 'chunk_missing'
        expected = path.read_text(encoding='utf-8')
        matched = False
        for call in tools:
            if not isinstance(call, dict) or call.get('tool') not in {'read', 'Read'}:
                continue
            args = call.get('args', {})
            if not isinstance(args, dict):
                continue
            tool_path = args.get('path', args.get('file_path'))
            if not isinstance(tool_path, str):
                continue
            resolved = (ROOT / tool_path).resolve() if not Path(tool_path).is_absolute() else Path(tool_path).resolve()
            if resolved != path:
                continue
            result = call.get('result')
            if not call.get('completed') or call.get('is_error') or bad_return(result):
                truncated = truncated or bad_return(result)
                continue
            if args.get('offset', 1) != 1:
                continue
            limit = args.get('limit')
            if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)
                                      or limit < len(expected.splitlines())):
                continue
            text = spawn_reviewer.content_text(result.get('content')) if isinstance(result, dict) else ''
            if text == expected:
                matched = True
                break
        missing |= not matched
    return not missing, 'truncated' if truncated and missing else 'chunk_missing' if missing else ''


def synthetic_finding(fid, severity, reason, raw=None):
    finding = {'id': fid, 'verdict': 'open', 'severity': severity, 'category': 6, 'ends': [],
               'scope': 'review validation / previous finding closure', 'exclusive': reason,
               'counter_evidence': '', 'impact': 'Cannot establish evidence-backed consistency.',
               'remediation': 'Rerun reviewer with complete evidence and a valid response.'}
    if raw is not None:
        finding['raw_finding'] = raw
    return finding


def validate(result, meta, calls, out, manifest, expected_carry=None, diffs=None, expected_axes=None):
    expected_carry = expected_carry or []
    aggregate = meta['case_id'] == '_aggregate'
    call_ids = {call['call_id'] for call in calls}
    errors, invalid_ref = [], 0
    try:
        checked = Review.model_validate(result).model_dump()
    except ValidationError as exc:
        checked = {'spawn_id': result.get('spawn_id') if isinstance(result, dict) else None,
                   'case_id': meta['case_id'], 'coverage': [], 'relations': [], 'common_rules': [],
                   'findings': [], 'carry_over': [], 'output_checks': [], 'diff_rulings': [],
                   'summary': 'Invalid reviewer output'}
        errors.append('schema_invalid: ' + ', '.join('.'.join(map(str, issue['loc'])) for issue in exc.errors()))
        for index, raw in enumerate(result.get('findings', []) if isinstance(result, dict) else []):
            if isinstance(raw, dict):
                checked['findings'].append(synthetic_finding(f'F-invalid-{index + 1}', 'high',
                                                             'Invalid finding structure', raw))
    if checked['spawn_id'] != meta['spawn_id'] or checked['case_id'] != meta['case_id']:
        errors.append('identity_mismatch')
    tools = tool_records(meta['tool_calls'])
    findings = checked['findings']
    by_id = {}
    for index, finding in enumerate(findings):
        try:
            safe_id(finding['id'])
        except ValueError:
            finding['raw_id'] = finding['id']
            finding['id'] = f'F-invalid-id-{index + 1}'
            finding['verdict'], finding['severity'] = 'open', 'high'
            errors.append('unsafe_finding_id')
        if finding['id'] in by_id:
            errors.append('duplicate_finding')
            finding['raw_id'] = finding['id']
            candidate = f'F-duplicate-{index + 1}'
            while candidate in by_id:
                candidate += '-duplicate'
            finding['id'] = candidate
            finding['verdict'] = 'open'
            if finding['severity'] == 'diagnostic':
                finding['severity'] = 'high'
        by_id[finding['id']] = finding
        ends = finding['ends']
        needed = 2 if finding['category'] in {1, 2, 4, 6} else 1
        if len(ends) < needed or (finding['verdict'] == 'confirmed' and not finding['counter_evidence'].strip()):
            errors.append('finding_evidence_missing')
            finding['verdict'] = 'open'
            if finding['severity'] == 'diagnostic':
                finding['severity'] = 'high'
        if any(end['call_id'] not in call_ids for end in ends):
            invalid_ref += 1
            finding['verdict'] = 'open'
            finding['invalid_ref'] = True
            if finding['severity'] == 'diagnostic':
                finding['severity'] = 'high'
    coverage, seen = [], set()
    for item in checked['coverage']:
        if item['call_id'] not in call_ids:
            invalid_ref += 1
        if item['call_id'] in seen:
            errors.append('duplicate_coverage')
        seen.add(item['call_id'])
        if item['depth'] == 'partial' and not item['note'].strip():
            errors.append('partial_note_missing')
        if item['depth'] == 'full':
            complete, reason = full_chunks(out, item['call_id'], manifest, tools)
            if not complete:
                item.update(depth='partial', reason=reason)
        if item['call_id'] in call_ids:
            coverage.append(item)
    if not aggregate:
        for call_id in sorted(call_ids - seen):
            coverage.append({'call_id': call_id, 'depth': 'unverifiable', 'note': 'Not reported', 'reason': 'not_reported'})
    checked['coverage'] = coverage
    relation_keys = set()
    for relation in checked['relations']:
        if relation['call_id'] not in call_ids:
            invalid_ref += 1
        key = relation['call_id'], relation['category']
        if key in relation_keys:
            errors.append('duplicate_relation')
        relation_keys.add(key)
        ids = relation['finding_ids']
        if len(ids) != len(set(ids)) or any(fid not in by_id for fid in ids):
            errors.append('invalid_relation_finding')
        if (relation['result'] == 'finding') != bool(ids):
            errors.append('relation_finding_mismatch')
        if relation['result'] == 'n/a' and not relation['note'].strip():
            errors.append('relation_na_reason_missing')
    missing_relation = 0 if aggregate else len({(cid, cat) for cid in call_ids for cat in CATEGORIES} - relation_keys)
    expected_scopes = {(call.get('role') or 'unknown', call.get('stage') or 'unknown') for call in calls}
    rule_keys, seen_rules = set(), set()
    for rule in checked['common_rules']:
        scope = rule['scope']
        identity = rule['key'], scope['role'], scope['stage'], scope['version'], rule['call_id']
        if identity in seen_rules:
            errors.append('duplicate_common_rule')
        seen_rules.add(identity)
        rule_keys.add((rule['key'], scope['role'], scope['stage']))
        if (scope['role'], scope['stage']) not in expected_scopes:
            errors.append('unknown_rule_scope')
        if rule['status'] == 'present':
            if rule['call_id'] not in call_ids:
                invalid_ref += 1
            if not rule['where'].strip() or not rule['quote'].strip():
                errors.append('common_rule_evidence_missing')
        elif not rule['note'].strip():
            errors.append('common_rule_unknown_reason_missing')
        elif rule['call_id'] is not None and rule['call_id'] not in call_ids:
            invalid_ref += 1
    missing_common = 0 if aggregate else len({(key, role, stage) for role, stage in expected_scopes for key in RULE_KEYS} - rule_keys)
    # A reported unknown is honest, but cannot establish a shared rule as consistent.
    unknown_common = sum(rule['status'] == 'unknown' for rule in checked['common_rules'])
    carry_by_id = {}
    for item in checked['carry_over']:
        if item['finding'] in carry_by_id:
            errors.append('duplicate_carry_over')
        carry_by_id[item['finding']] = item
        if any(end['call_id'] not in call_ids for end in item['ends']):
            invalid_ref += 1
            item['ruling'] = 'unverifiable'
        previous_item = next((old for old in expected_carry if old['reference'] == item['finding']), {})
        minimum_ends = 2 if previous_item.get('finding', {}).get('category', 6) in {1, 2, 4, 6} else 1
        if item['ruling'] == 'resolved' and len(item['ends']) < minimum_ends:
            item['ruling'] = 'unverifiable'
            errors.append('carry_resolution_evidence_missing')
        if item['ruling'] == 'persists' and (not item['finding_ids'] or
                any(fid not in by_id or by_id[fid]['verdict'] != 'confirmed' for fid in item['finding_ids'])):
            errors.append('carry_persists_finding_missing')
            item['ruling'] = 'unverifiable'
    if set(carry_by_id) - {item['reference'] for item in expected_carry}:
        errors.append('unexpected_carry_over')
    enriched_carry = []
    for index, previous in enumerate(expected_carry):
        item = carry_by_id.get(previous['reference'], {'finding': previous['reference'],
            'ruling': 'unverifiable', 'ends': [], 'finding_ids': [], 'note': 'Previous finding not addressed'})
        item.update(previous_report=previous['previous_report'], original_key=previous['key'],
                    severity=previous['severity'], shard=meta['case_id'])
        if item['ruling'] == 'resolved':
            item['key'] = previous['reference']
        elif item['ruling'] == 'persists':
            item['key'] = f"{meta['case_id']}::{item['finding_ids'][0]}"
        else:
            fid = f'F-carry-{index + 1}'
            if fid in by_id:
                errors.append('carry_id_collision')
                while fid in by_id:
                    fid += '-unclosed'
            finding = synthetic_finding(fid, previous['severity'], item['note'])
            finding['previous_reference'] = previous['reference']
            findings.append(finding)
            by_id[fid] = finding
            item['key'] = f"{meta['case_id']}::{fid}"
        enriched_carry.append(item)
    checked['carry_over'] = enriched_carry
    axis_names = [item['axis'] for item in checked['output_checks']]
    if len(axis_names) != len(set(axis_names)):
        errors.append('duplicate_output_check')
    if expected_axes is not None and not aggregate and set(axis_names) != set(expected_axes):
        errors.append('output_check_coverage_mismatch')
    if any(not text.strip() for item in checked['output_checks'] for text in item['items']):
        errors.append('empty_output_check')
    diff_seen = set()
    expected_diffs = {item['id'] for item in diffs or []}
    for ruling in checked['diff_rulings']:
        if ruling['diff_id'] not in expected_diffs or ruling['diff_id'] in diff_seen:
            errors.append('invalid_diff_ruling')
        diff_seen.add(ruling['diff_id'])
        if len(ruling['finding_ids']) != len(set(ruling['finding_ids'])):
            errors.append('duplicate_diff_finding')
        if ruling['verdict'] != 'explained' and not ruling['finding_ids']:
            errors.append('diff_finding_missing')
        if any(fid not in by_id or by_id[fid]['verdict'] != ruling['verdict'] for fid in ruling['finding_ids']):
            errors.append('diff_finding_verdict_mismatch')
    if aggregate and expected_diffs != diff_seen:
        errors.append('missing_diff_ruling')
    if not aggregate and checked['diff_rulings']:
        errors.append('unexpected_diff_ruling')
    if invalid_ref:
        errors.append('invalid_ref')
    checked['validation'] = {'valid': not errors, 'errors': errors, 'invalid_ref': invalid_ref,
                             'missing_relation': missing_relation, 'missing_common_rules': missing_common,
                             'unknown_common_rules': unknown_common}
    return checked


def common_rule_diffs(shards):
    groups = {}
    for shard, review in shards.items():
        for rule in review.get('common_rules', []):
            scope = rule['scope']
            key = rule['key'], scope['role'], scope['stage']
            groups.setdefault(key, []).append({'shard': shard, **deepcopy(rule)})
    diffs = []
    for key, entries in sorted(groups.items()):
        values = {(item['status'], item['scope']['version'], ' '.join(item['quote'].split())) for item in entries}
        if len({item['shard'] for item in entries}) > 1 and len(values) > 1:
            diffs.append({'id': f'D-{len(diffs) + 1:03}', 'key': key[0],
                          'scope': {'role': key[1], 'stage': key[2]}, 'entries': entries})
    return diffs


def previous_findings(previous):
    if previous is None:
        return []
    previous = Path(previous)
    summary_path = previous / 'review-summary.json'
    if not summary_path.exists():
        raise ValueError(f'Previous report lacks review-summary.json: {previous}')
    summary = read_json(summary_path)
    response_path, adjudication_path = previous / 'response.json', previous / 'adjudication.json'
    responses = read_json(response_path) if response_path.exists() else {}
    adjudications = read_json(adjudication_path) if adjudication_path.exists() else {}
    # Both gate artifacts are envelopes of keyed entries; the gate owns their detailed validation.
    response_entries = responses.get('responses', []) if isinstance(responses, dict) else []
    adjudication_entries = adjudications.get('entries', []) if isinstance(adjudications, dict) else []
    latest = {item.get('finding'): item for item in adjudication_entries if isinstance(item, dict)}
    closed = {key for key, item in latest.items() if item.get('rule') in {'withdrawn', 'waived-by-human'}}
    result = []
    for finding in summary.get('findings', []):
        if finding.get('verdict') not in {'confirmed', 'open'} or finding.get('severity') not in {'blocking', 'high'}:
            continue
        key = finding['key']
        if key in closed:
            continue
        result.append({'reference': f'{previous.name}::{key}', 'previous_report': str(previous.resolve()),
                       'key': key, 'shard': finding['shard'], 'severity': finding['severity'],
                       'finding': finding, 'response': next((item for item in response_entries
                           if item.get('finding') == key), None)})
    return result


def shard_task(out, shard, calls, manifest, carry):
    role_stages = sorted({(call.get('role') or 'unknown', call.get('stage') or 'unknown') for call in calls})
    paths = [chunk['path'] for call in calls for chunk in manifest.get('calls', {}).get(call['call_id'], [])]
    return f'''报告目录: {Path(out).resolve()}
全部审阅 call_id: {json.dumps([call['call_id'] for call in calls], ensure_ascii=False)}
共同规则 role/stage 范围: {json.dumps(role_stages, ensure_ascii=False)}
账本: {Path(out).resolve() / 'ledger' / (shard + '.json')}
轴输出与解引用: {Path(out).resolve() / 'ledger' / (shard + '.deref.json')}
业务 trace: {Path(out).resolve() / 'raw/batch-status.json'} 的本 case events[].run.trace
硬性结论及体量: {Path(out).resolve() / 'metrics.json'}（只作定位，不抵消一致性 finding）
全部 chunk 路径（相对报告目录，逐一 read，无 offset/limit）:
{json.dumps(paths, ensure_ascii=False, indent=2)}
chunk 清单: {Path(out).resolve() / 'raw/calls/chunks-manifest.json'}
上一轮待闭环 finding（每条 reference 必须回答）:
{json.dumps(carry, ensure_ascii=False, indent=2)}
依角色卡及全部清单输出 JSON。仅能读上述证据与清单，不搜索其他报告或源码。'''


def run(out: Path, profile: dict, previous: Path | None = None, case_id: str | None = None):
    out = Path(out).resolve()
    envelope = read_json(out / 'raw/calls.json')
    if envelope.get('schema') != 'llmtrace.calls/v1' or envelope.get('status') != 'complete':
        raise ValueError('trace_export: incomplete or unsupported calls envelope')
    calls = envelope['calls']
    ids = [call['call_id'] for call in calls]
    if len(ids) != len(set(ids)):
        raise ValueError('trace_export: duplicate call_id')
    manifest = read_json(out / 'raw/calls/chunks-manifest.json')
    ledgers = [read_json(path) for path in sorted((out / 'ledger').glob('*.json')) if not path.name.endswith('.deref.json')]
    if not ledgers:
        raise ValueError('Missing call ledgers')
    cases = [ledger['case_id'] for ledger in ledgers if not ledger.get('business_unreachable')]
    excluded = [ledger['case_id'] for ledger in ledgers if ledger.get('business_unreachable')]
    if len(cases + excluded) != len(set(cases + excluded)):
        raise ValueError('Duplicate ledger case identity')
    if any(call.get('case_id') not in cases + excluded for call in calls):
        raise ValueError('Calls lie outside ledger case identities')
    for case in cases:
        safe_id(case)
    if case_id is not None and case_id not in cases:
        raise ValueError(f'Unknown review case: {case_id}')
    selected = [case_id] if case_id else cases
    carry = previous_findings(previous)
    expected = {case: [entry for entry in carry if entry['shard'] == case] for case in cases}
    expected['_aggregate'] = [entry for entry in carry if entry['shard'] not in cases]
    expected_axes = {case: [axis['axis_id'] for axis in read_json(out / 'ledger' / (case + '.deref.json'))['axes']]
                     for case in cases}
    buffers, checked, shard_calls = {}, {}, {case: [call for call in calls if call.get('case_id') == case] for case in cases}
    before = snapshot(ROOT, out, scope=True)
    # Everything written until the second snapshot stays inside excluded spawn/.
    def spawn(case):
        return spawn_reviewer.run(out, case, profile, shard_task(out, case, shard_calls[case], manifest, expected[case]))
    with ThreadPoolExecutor(max_workers=profile['reviewer']['parallel']) as pool:
        for case, result in zip(selected, pool.map(spawn, selected)):
            buffers[case] = result
    for case in cases:
        if case in buffers:
            buffer = buffers[case]
            checked[case] = validate(buffer['result'], buffer['meta'], shard_calls[case], out, manifest, expected[case], expected_axes=expected_axes[case])
        else:
            path, meta_path = out / 'review' / f'{case}.json', out / 'spawn' / case / 'meta.json'
            if not path.exists() or not meta_path.exists():
                raise ValueError(f'Missing reusable shard: {case}')
            meta = read_json(meta_path)
            if (not meta.get('scope_valid') or meta.get('review_sha256') != digest(path)
                    or meta.get('reviewer_config_sha256') != spawn_reviewer.configuration_digest(profile)):
                raise ValueError(f'Invalid reusable shard: {case}')
            # Revalidate the original structured output; enriched carry is program-produced.
            original = read_json(out / 'spawn' / case / 'result.json')
            checked[case] = validate(original, meta, shard_calls[case], out, manifest, expected[case], expected_axes=expected_axes[case])
            buffers[case] = {'meta': meta, 'result': original, 'task': str(out / 'spawn' / case / 'task.md')}
    diffs = common_rule_diffs(checked)
    if diffs or expected['_aggregate']:
        task = ('共同规则聚合任务。只裁下列差异，每个 diff_id 恰好回答一次。\n'
                + json.dumps({'diffs': diffs, 'common_rules': {case: review['common_rules'] for case, review in checked.items()},
                              'allowed_call_ids': ids, 'carry_over': expected['_aggregate'],
                              'chunks_manifest': str(out / 'raw/calls/chunks-manifest.json')}, ensure_ascii=False, indent=2))
        buffers['_aggregate'] = spawn_reviewer.run(out, '_aggregate', profile, task)
        checked['_aggregate'] = validate(buffers['_aggregate']['result'], buffers['_aggregate']['meta'],
                                         calls, out, manifest, expected['_aggregate'], diffs)
    after = snapshot(ROOT, out, scope=True)
    scope_valid = before == after
    shards = {}
    # Snapshot is complete; adoption is now permitted. Invalid scope results never become review/*.json.
    for case, buffer in buffers.items():
        meta = buffer['meta']
        meta['scope_valid'] = scope_valid and (case in selected or case == '_aggregate' or meta.get('scope_valid', False))
        valid = bool(scope_valid and meta.get('has_result') and meta.get('exit_code') == 0
                     and not meta.get('errors') and checked[case]['validation']['valid'])
        path = out / 'review' / f'{case}.json'
        if scope_valid:
            write_json(path, checked[case])
            meta['review_sha256'] = digest(path)
            task_path = out / 'review-task' / f'{case}.md'
            task_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(buffer['task'], task_path)
        else:
            meta['review_sha256'] = None
        write_json(out / 'spawn' / case / 'meta.json', meta)
        shards[case] = {'path': str(path.relative_to(out)),
                        'meta': str((out / 'spawn' / case / 'meta.json').relative_to(out)), 'valid': valid}
    write_json(out / 'review/snapshot.json', {'before': before, 'after': after, 'scope_valid': scope_valid})
    if scope_valid:
        write_json(out / 'review/common-rules-diff.json', diffs)
        write_json(out / 'carry-over.json', carry)
    findings, carry_results = [], []
    counts = {'calls_total': sum(len(shard_calls[case]) for case in cases), 'full': 0, 'partial': 0, 'unverifiable': 0,
              'missing_relation': 0, 'missing_common_rules': 0, 'unknown_common_rules': 0,
              'invalid_ref': 0, 'relations_recorded': 0,
              'confirmed': {severity: 0 for severity in SEVERITIES}, 'explained': 0,
              'open_key': 0, 'open_other': 0}
    for case, review in checked.items():
        for item in review['findings']:
            finding = {**item, 'key': f"{case}::{item['id']}", 'shard': case}
            findings.append(finding)
            if finding['verdict'] == 'confirmed':
                counts['confirmed'][finding['severity']] += 1
            elif finding['verdict'] == 'explained':
                counts['explained'] += 1
            else:
                counts['open_key' if finding['severity'] in {'blocking', 'high'} else 'open_other'] += 1
        carry_results.extend(review['carry_over'])
        if case != '_aggregate':
            for item in review['coverage']:
                counts[item['depth']] += 1
            counts['relations_recorded'] += len(review['relations'])
        for field in ('missing_relation', 'missing_common_rules', 'unknown_common_rules', 'invalid_ref'):
            counts[field] += review['validation'][field]
    valid = scope_valid and bool(cases) and all(shard['valid'] for shard in shards.values()) and len(shards) >= len(cases)
    counts['pass'] = bool(valid and counts['full'] == counts['calls_total']
                          and not any(counts[field] for field in ('partial', 'unverifiable', 'missing_relation',
                              'missing_common_rules', 'unknown_common_rules', 'invalid_ref', 'open_key'))
                          and sum(counts['confirmed'].values()) == 0)
    return {'valid': valid, 'shards': shards, 'consistency': counts, 'findings': findings,
            'carry_over': carry_results, 'excluded_cases': excluded}
