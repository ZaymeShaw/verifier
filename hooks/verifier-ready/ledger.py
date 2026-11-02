"""Indexes exported calls and dereferences only evidence present in raw batch data."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from common import read_json, safe_id, write_json
from metrics import business_unreachable, case_runs, select_executions


def _dereference(run):
    axes = (run.get('eval_axes') or {}).get('results', [])
    index = {}
    contents = {}

    def register(value, namespace='record', identify=True):
        if isinstance(value, list):
            for child in value:
                register(child, namespace, identify)
        elif isinstance(value, dict):
            if 'id' in value and identify:
                index.setdefault(str(value['id']), []).append(value)
            for key, prefix in (('expectation_id', 'expectation:'), ('obligation_id', 'obligation:')):
                if key in value and namespace == 'definition' and identify:
                    index.setdefault(prefix + str(value[key]), []).append(value)
                    index.setdefault(str(value[key]), []).append(value)
            if value.get('ref') and 'status' in value:
                index.setdefault(str(value['ref']), []).append(value)
            for child in value.values():
                if isinstance(child, (list, dict)):
                    register(child, namespace, False)

    for axis in axes:
        output = axis.get('output') or {}
        if not isinstance(output, dict):
            continue
        dossier = output.get('dossier') or {}
        contents.update(dossier.get('contents') or {})
        register(dossier.get('records', []))
        register(dossier.get('sources', []))
        for key in ('expectations', 'sources', 'obligations'):
            register(output.get(key, []), 'definition')

    unresolved_contents = set()

    def expand(value, stack=()):
        if isinstance(value, list):
            return [expand(child, stack) for child in value]
        if isinstance(value, dict):
            if set(value) == {'content_ref'}:
                ref = value['content_ref']
                if ref in stack or ref not in contents:
                    unresolved_contents.add(ref)
                    return {'content_ref': ref, 'resolution': 'missing' if ref not in contents else 'cycle'}
                return expand(contents[ref], (*stack, ref))
            return {key: expand(child, stack) for key, child in value.items()}
        return value

    resolved_axes = []
    missing = []
    for axis in axes:
        references = []
        axis_id = axis.get('axis_id')

        def find(value, path='output'):
            if isinstance(value, list):
                for i, child in enumerate(value):
                    find(child, f'{path}[{i}]')
            elif isinstance(value, dict):
                for key, child in value.items():
                    if (key in ('input_refs', 'output_refs', 'source_refs', 'expectation_ids')
                            or key in ('input', 'output') and path.endswith('.evidence')):
                        for ref in child if isinstance(child, list) else []:
                            hits = index.get(str(ref), [])
                            # Identical definitions may recur in several axis exports.
                            unique = []
                            for hit in hits:
                                if hit not in unique:
                                    unique.append(hit)
                            record = {'path': f'{path}.{key}', 'ref': ref,
                                      'status': 'resolved' if len(unique) == 1 else 'ambiguous' if unique else 'missing',
                                      'targets': [expand(hit) for hit in unique]}
                            references.append(record)
                            if record['status'] != 'resolved':
                                missing.append({'axis_id': axis_id, **record})
                    elif key == 'obligation_id':
                        ref = 'obligation:' + str(child)
                        hits = index.get(ref, [])
                        unique = []
                        for hit in hits:
                            if hit not in unique:
                                unique.append(hit)
                        record = {'path': f'{path}.{key}', 'ref': ref,
                                  'status': 'resolved' if len(unique) == 1 else 'ambiguous' if unique else 'missing',
                                  'targets': [expand(hit) for hit in unique]}
                        references.append(record)
                        if record['status'] != 'resolved':
                            missing.append({'axis_id': axis_id, **record})
                    elif key not in ('dossier', 'sources', 'expectations', 'obligations'):
                        find(child, f'{path}.{key}')

        find(axis.get('output'))
        resolved_axes.append({'axis_id': axis_id, 'status': axis.get('status'),
                              'output': axis.get('output'), 'references': references})
    return {'case_id': run.get('case_id'), 'axes': resolved_axes, 'unresolved': missing,
            'unresolved_content_refs': sorted(unresolved_contents), 'trace': run.get('trace')}


def build(out: Path):
    out = Path(out)
    calls = read_json(out / 'raw/calls.json')['calls']
    batch = read_json(out / 'raw/batch-status.json')
    requests = read_json(out / 'raw/requests.json')
    runs = case_runs(select_executions(batch, [request['execution_id'] for request in requests]))
    mapping = {}
    for request in requests:
        case = request.get('request_case_id') or request.get('case_id')
        if not case:
            raise ValueError('Batch request lacks case identity')
        safe_id(case)
        mapping.setdefault(case, {'case_id': case, 'execution_ids': [], 'calls': []})['execution_ids'].append(request['execution_id'])
    for call in calls:
        case = safe_id(call['case_id'])
        if case not in mapping or call.get('execution_id') not in mapping[case]['execution_ids']:
            raise ValueError('Call lies outside raw batch requests')
        mapping[case]['calls'].append(dict(call))
    for case, ledger in mapping.items():
        stages, previous, failed_stages = Counter(), {}, set()
        ledger['calls'].sort(key=lambda c: (c.get('ts') or '', c['call_id']))
        for i, row in enumerate(ledger['calls'], 1):
            call_id = safe_id(row['call_id'])
            path = out / 'raw/calls' / (call_id + '.txt')
            if not path.is_file():
                raise ValueError(f'Full call export missing: {call_id}')
            stage = row.get('stage')
            stages[stage] += 1
            prompt = (row.get('usage') or {}).get('prompt_tokens')
            prior = previous.get(stage)
            row.update(sequence=i, raw_path=str(path.relative_to(out)), stage_occurrence=stages[stage],
                       prompt_tokens=prompt, completion_tokens=(row.get('usage') or {}).get('completion_tokens'),
                       prompt_tokens_delta=prompt - prior if isinstance(prompt, (int, float)) and isinstance(prior, (int, float)) else None,
                       follows_failed_stage=stage in failed_stages)
            previous[stage] = prompt
            if row.get('state') != 'succeeded':
                failed_stages.add(stage)
        run = runs.get(case)
        ledger['business_unreachable'] = bool(run and business_unreachable(run))
        ledger['missing_run'] = run is None
        ledger['reading_order'] = [row['call_id'] for row in sorted(ledger['calls'], key=lambda row: (
            not (row['stage_occurrence'] == 1 or row.get('state') != 'succeeded' or row['follows_failed_stage']
                 or row.get('stage') in ('llm_probe_expectations', 'llm_probe_judge')
                 or row.get('gateway') != 'verifier_primary'), row['sequence']))]
        write_json(out / 'ledger' / (case + '.json'), ledger)
        write_json(out / 'ledger' / (case + '.deref.json'), _dereference(run) if run else {'case_id': case, 'axes': [], 'unresolved': [], 'missing_run': True})
    return mapping
