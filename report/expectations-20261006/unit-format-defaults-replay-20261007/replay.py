"""Offline replay of schema/expansion only; no model calls or full-axis acceptance."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from impl.core.llm_client import extract_json
from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.eval_axes.adapters.process_output import AxisJudgment, expand

SOURCE = ROOT / 'report/expectations-20261006/unit-format-full-live-20261007/contexts'
spec = StructuredOutputSpec.from_dataclass(AxisJudgment, required_nonempty=['reason', 'scope_note'])
results = []
for path in sorted(SOURCE.rglob('*.json')):
    record = json.loads(path.read_text())
    response = record.get('response') or {}
    content = response.get('content')
    if not isinstance(content, str):
        continue
    payload = extract_json(content)
    if not isinstance(payload, dict) or 'units' not in payload:
        continue
    # The client can append output constraints after the request JSON.
    request, _ = json.JSONDecoder().raw_decode(next(m['content'] for m in record['messages'] if m['role'] == 'user'))
    axis = request['dimension']
    entry = {'axis': axis, 'source': str(path.relative_to(ROOT)),
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'omitted_unit_fields': {k: sum(k not in u for u in payload['units'])
                                     for k in ('matched', 'missing', 'upstream')}}
    try:
        enforce_output(payload, spec, caller=axis)
        entry['schema'] = 'passed'
        units = {uid: {'obligation_id': u['obligation'], 'link_id': u['link'], 'criteria': u['criteria']}
                 for uid, u in request['units'].items()}
        links = {link['link_id']: link for link in
                 request['links']['links'] + request['links']['match_candidates']}
        view = request['dossier_view']
        # Reconstruct the read receipt IDs from delivered values; shape-only
        # records and shared-content storage IDs are not independent evidence.
        readable = ({r['id'] for r in view['records']
                     if any('value' in f for f in r.get('fields', {}).values())}
                    | set(view['contents']) | {g['id'] for g in view['gaps']})
        rows = expand(payload, units, request['criteria'], links, readable, axis_id=axis, first_problem=1)
        entry.update(expansion='passed', rows=len(rows))
    except ValueError as exc:
        entry.update(expansion='rejected', error=str(exc))
    results.append(entry)

assert len({r['axis'] for r in results}) == 6, 'Expected responses covering all six process axes'
report = {'scope': 'Saved responses: existing JSON extraction, strict schema and expansion only. '
          'Does not run downstream evidence/expectation validation, correction rounds, other batches or final judge.',
          'results': results}
Path(__file__).with_name('result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
for result in results:
    print(result['axis'], result.get('schema'), result['expansion'], result.get('error', ''))
