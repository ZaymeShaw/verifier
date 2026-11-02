"""What the current unit-based pipeline concluded for the two cases (last attempt per stage = the accepted one).
usage: python current_pipeline_summary.py <exported-trace.json> > current_pipeline.json
"""
import collections, json, re, sys
data = json.load(open(sys.argv[1]))
out = {}
for tag, key in {'renyanlin': 'smoke-policy-detail-renyanlin', 'D01': 'main-D01-same-surname'}.items():
    case = next(c for c in data['cases'] if key in c['identity']['case_id'])
    last = {}
    for call in case['calls']:
        stage = call['raw_request'].get('stage') or ''
        if stage.startswith('llm_probe_process_') and call.get('assistant'):
            last[re.sub(r'_batch\d+$', '', stage[18:])] = call
    per = {}
    for axis, call in last.items():
        o = json.loads(call['assistant'])
        outcomes = collections.Counter(c['outcome'] for u in o['units'] for c in u['checks'])
        per[axis] = dict(units=len(o['units']), checks=sum(outcomes.values()), outcomes=dict(outcomes), reason=o['reason'],
                         problems=[p['phenomenon'] for p in o['problems']], output_chars=len(call['assistant']),
                         latency_s=round(call['latency_ms'] / 1000))
    out[tag] = per
print(json.dumps(out, ensure_ascii=False, indent=1))
