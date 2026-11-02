"""Rebuild one readable, complete case file per case from an exported verifier job (trace JSON).

The six-axis prompts of one case each carry a different slice of the dossier, with per-call
`shared#N` numbering. Resolve the shared references inside each call first, then merge the
records by id (keep the most complete version). Nothing is summarized or truncated.
usage: python build_case_files.py <exported-trace.json> <out-dir>
"""
import json, re, sys
from pathlib import Path

CASES = {'renyanlin': 'smoke-policy-detail-renyanlin', 'D01': 'main-D01-same-surname-clarify'}


def resolve(value, shared):
    if isinstance(value, dict):
        if set(value) == {'shared_ref'}:
            return resolve(shared.get(value['shared_ref']), shared)
        return {k: resolve(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, shared) for v in value]
    if isinstance(value, str) and value[:1] in '{[':
        try:
            return resolve(json.loads(value), shared)
        except ValueError:
            return value
    return value


def flatten_record(rec, shared):
    out = {k: v for k, v in rec.items() if k not in ('fields', 'pairing') and v not in (None, 'None', '')}
    for name, info in (rec.get('fields') or {}).items():
        if not isinstance(info, dict):
            continue
        if info.get('status') == 'available' and 'value' in info:
            out[name] = resolve(info['value'], shared)
        elif info.get('same_as'):
            out[name] = {'same_as': info['same_as']}
    return out


def build(trace_path, out_dir):
    data = json.load(open(trace_path))
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    for tag, key in CASES.items():
        case = next(c for c in data['cases'] if key in c['identity']['case_id'])
        records, exps, sources = {}, {}, {}
        for call in case['calls']:
            stage = call['raw_request'].get('stage') or ''
            if not stage.startswith('llm_probe_process_') or not call.get('assistant'):
                continue
            text = next(m['content'] for m in call['raw_request']['client_request']['messages'] if m['role'] == 'user')
            body, _ = json.JSONDecoder().raw_decode(text)  # a correction round appends a sentence after the JSON
            for e in body['expectations']:
                exps[e['expectation_id']] = e
            for s in body['expectation_sources']:
                sources[s['id']] = s
            dv = body['dossier_view']
            shared = dv.get('shared_contents') or {}
            if isinstance(shared, list):
                shared = {r['id']: r.get('body') for r in shared}
            for rec in dv.get('records', []):
                flat = flatten_record(rec, shared)
                old = records.get(rec['id'])
                if old is None or len(json.dumps(flat, ensure_ascii=False)) > len(json.dumps(old, ensure_ascii=False)):
                    records[rec['id']] = flat
        order = sorted(records, key=lambda i: [int(p) if p.isdigit() else p for p in re.split(r'[/.]', i)])
        casefile = {'case_id': case['identity']['case_id'], 'expectation_sources': list(sources.values()),
                    'expectations': list(exps.values()), 'records': {i: records[i] for i in order}}
        (out_dir / f'case_{tag}.json').write_text(json.dumps(casefile, ensure_ascii=False, indent=1))
        print(tag, 'records', len(records), 'chars', len(json.dumps(casefile, ensure_ascii=False)))


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
