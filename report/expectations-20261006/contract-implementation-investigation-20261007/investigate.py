"""Read-only feasibility probes against saved evidence and current consumer contracts.

Run from any directory with the project's Python environment. No provider requests.
"""
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from impl.core.llm_client import extract_json
from impl.projects.llm_probe.business_trace.dossier import expand_content
from impl.projects.llm_probe.business_trace.links import build_links
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.process_contract import source_in_inputs
from impl.projects.llm_probe.process_loop import expectation_projection as projection

SOURCE = ROOT / 'report/expectations-20261006/unit-format-full-live-20261007'
raw = json.loads((SOURCE / 'result.json').read_text())
axes = {r['axis_id']: r for r in raw['axes']['results']}
e = axes['expectations']['output']
dossier = axes['trace_analysis']['output']['dossier']
sources = {s['id']: s for s in e['sources']}
rows = {r['id']: r for r in dossier['records']}

report = {
    'scope': 'Offline investigation only; no new semantic judgment or live acceptance.',
    'source_sha256': hashlib.sha256((SOURCE / 'result.json').read_bytes()).hexdigest(),
    'expectations': {
        'total': len(e['expectations']),
        'by_side': dict(Counter(projection.sides(e).values())),
        'source_scopes': dict(Counter(s.get('scope') for s in sources.values())),
        'source_count': len(sources),
        'extraction_elapsed_s': (datetime.fromisoformat(axes['expectations']['finished_at'])
                                 - datetime.fromisoformat(axes['expectations']['started_at'])).total_seconds(),
    },
    'model_boundaries': [], 'saved_requests': [], 'ablation': [],
}
for link in build_links(dossier, axis_id='model_capability')['links']:
    inputs = [expand_content((rows[end['ref']]['fields'].get(end['field']) or {}).get('value'),
                             dossier['contents']) for end in link['input']]
    matched = [s['id'] for s in sources.values() if s['side'] == 'commitment' and source_in_inputs(s, inputs)]
    report['model_boundaries'].append({
        'link_id': link['link_id'], 'input_source': link['facts'].get('input_source'),
        'input_refs': link['input'], 'output_refs': link['output'],
        'input_chars': sum(len(json.dumps(v, ensure_ascii=False)) for v in inputs),
        'declaration_source_matches': matched,
        'note': 'source_in_inputs matches delivery of source content only, not applicability, version or semantic completeness.',
    })

for path in sorted((SOURCE / 'contexts').rglob('*.json')):
    record = json.loads(path.read_text())
    user = next((m['content'] for m in record['messages'] if m['role'] == 'user'), '')
    try:
        request, _ = json.JSONDecoder().raw_decode(user)
    except ValueError:
        continue
    if not isinstance(request, dict) or 'units' not in request:
        continue
    content = (record.get('response') or {}).get('content')
    response = extract_json(content) if isinstance(content, str) else {}
    catalog = request['reference_catalog']
    readable = set(catalog['readable_ids']) | set(catalog['gap_ids'])
    shared = set(request['dossier_view']['shared_contents'])
    citations = {ref for p in response.get('problems', []) for ref in p.get('evidence', [])}
    pool = request['dossier_view']['shared_contents']
    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {'shared_ref'}:
                return resolve(pool[value['shared_ref']])
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value
    collisions = []
    for ident in sorted(shared & readable):
        if ident in request['dossier_view']['contents']:
            canonical = resolve(request['dossier_view']['contents'][ident])
            storage = resolve(pool[ident])
            collisions.append({'id': ident, 'same_body': canonical == storage})
    report['saved_requests'].append({
        'source': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'axis': request['dimension'], 'request_chars': len(user), 'units': len(request['units']),
        'criteria': len(request['criteria']), 'local_expectations': len(request['expectations']),
        'expectation_chars': len(json.dumps(request['expectations'], ensure_ascii=False)),
        'expectation_source_chars': len(json.dumps(request['expectation_sources'], ensure_ascii=False)),
        'material_chars': len(json.dumps(request['dossier_view'], ensure_ascii=False)),
        'readable_ids': len(readable), 'shared_ids': len(shared),
        'shared_and_readable_overlap': sorted(shared & readable),
        'shared_and_readable_bodies': collisions,
        'invalid_extra_evidence': sorted(citations - readable),
        'invalid_evidence_that_is_shared_storage': sorted((citations - readable) & shared),
    })

def rejection(name, fn):
    try:
        fn()
    except (ValueError, KeyError) as exc:
        report['ablation'].append({'probe': name, 'result': 'rejected', 'error': str(exc)})
    else:
        raise AssertionError(f'{name}: consumer unexpectedly accepted incompatible input')

# A synthetic minimal contract demonstrates the API dependency without attributing
# artificial results to the real business trace.
small = {'sources': [dict(id='u', side='want', turn='t1', component='user', value='查询金额'),
                     dict(id='tool', side='commitment', turn='t1', component='tools', value={'name': 'lookup'})],
         'expectations': [dict(expectation_id='Q', source_refs=['u']),
                          dict(expectation_id='T', source_refs=['tool'])], 'missing': []}
join = {'data_needs': [dict(expectation_id='Q', need='tool', tool_expectation_ids=['T'], reason='工具声明')],
        'contracts': [dict(expectation_id='T', obligation_id='result_matches_request')]}
projection.validate_join(join, small)
only_want = copy.deepcopy(small)
only_want['expectations'] = only_want['expectations'][:1]
rejection('remove_commitment_expectations_keep_projection', lambda: projection.validate_join(join, only_want))
without_contracts = copy.deepcopy(join)
without_contracts['contracts'] = []
rejection('remove_contract_bindings_but_data_needs_still_cite_T', lambda: projection.validate_join(without_contracts, only_want))

ob = common.Obligation('local_format', 'model_capability', '模型返回', '遵守格式', source='trace')
group = dict(obligation_id=ob.obligation_id, link_ids=['call'], matched_link_id='',
             criterion_checks=[dict(criterion_ref='obligation:local_format', outcome='pass', observed='完整 JSON')],
             source_refs=['actual-request'], input_refs=['actual-request'], output_refs=['actual-response'],
             missing=[], problems=[], upstream_issue_ids=[], origin='runtime_recall')
expanded = common._expand([group])
rejection('raw_rule_citation_without_expectation_not_accepted_by_binder',
          lambda: projection.bind_results(expanded, {ob.obligation_id: ob}, {'expectations': []}))

conditional = {'expectations': [dict(expectation_id='Q', about='格式', statement='输出 JSON',
                                   condition='仅最终响应', source_refs=['u'])]}
row = common._expand([{**group, 'criterion_checks': [dict(criterion_ref='expectation:Q', outcome='fail', observed='文本')]}])[0]
row['problems'] = [dict(expectation_ids=['Q'], source_refs=[])]
projection.bind_results([row], {ob.obligation_id: ob}, conditional)
report['condition_projection'] = {'unit_expected': row['expected'],
                                  'problem_expected': row['problems'][0]['expected'],
                                  'condition_retained_in_problem_expected': '仅最终响应' in row['problems'][0]['expected']}

report['implementation_sha256'] = {
    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in [
        'impl/projects/llm_probe/business_trace/expectation_material.py',
        'impl/projects/llm_probe/process_loop/expectation_projection.py',
        'impl/projects/llm_probe/eval_axes/adapters/process_common.py',
        'impl/projects/llm_probe/process_contract.py',
        'impl/projects/llm_probe/business_trace/materials.py',
    ]}
Path(__file__).with_name('evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('expectations', 'model_boundaries', 'ablation')}, ensure_ascii=False, indent=2))
print('Saved process requests:', len(report['saved_requests']))
