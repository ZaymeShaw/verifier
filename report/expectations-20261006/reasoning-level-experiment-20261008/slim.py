"""Slim-output experiment: does asking for less output on passing units reduce reasoning?

Replays recorded six-axis requests of one case verbatim vs with one appended instruction.
Same model and params; validates each reply with the project's output_spec and compares outcomes.
usage: python slim.py <trace2.json> <case-substring> [repeats]
"""
import concurrent.futures as cf, json, sys, time, urllib.request
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from impl.core.llm_client import extract_json
from impl.core.structured_output import validate_output
from impl.projects.llm_probe.eval_axes.adapters.process_output import OUTPUT

env = dict(l.rstrip('\n').split('=', 1) for l in open(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_primary') if '=' in l and not l.startswith('#'))
BASE, KEY = env['UPSTREAM_API_BASE'].strip('"'), env['UPSTREAM_API_KEY'].strip('"')
SLIM = ('\n补充（输出精简）：判为 pass 的判准，fact 只写一句不超过 40 字的结论，并带上支撑它的记录编号，不复述返回内容；'
        '所有判准都是 pass 的单位不填 rules。非 pass 的判准和问题记录照常完整写。')
AXES = ('tool_execution', 'model_capability', 'context_memory')
trace = json.load(open(sys.argv[1])); case_key = sys.argv[2]; reps = int(sys.argv[3]) if len(sys.argv) > 3 else 3
case = next(c for c in trace['cases'] if case_key in c['identity']['case_id'])

def call(label, body):
    body = dict(body, stream=True, stream_options={'include_usage': True})
    req = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t = time.time(); usage = {}; content = []
    try:
        with urllib.request.urlopen(req, timeout=1200) as r:
            for raw in r:
                l = raw.decode('utf-8', 'ignore').strip()
                if not l.startswith('data:') or l == 'data: [DONE]': continue
                try: j = json.loads(l[5:])
                except Exception: continue
                if j.get('usage'): usage = j['usage']
                for ch in j.get('choices') or []:
                    if (ch.get('delta') or {}).get('content'): content.append(ch['delta']['content'])
    except Exception as e:
        return dict(label=label, error=f'{type(e).__name__}: {str(e)[:120]}', elapsed=round(time.time() - t))
    text = ''.join(content); res = dict(label=label, elapsed=round(time.time() - t), reasoning=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                                        completion=usage.get('completion_tokens'), chars=len(text))
    try:
        o = extract_json(text); res['schema_errors'] = validate_output(o, OUTPUT)[:2]
        res['outcomes'] = {f"{u['unit']}/{c['criterion']}": c['outcome'] for u in o.get('units', []) for c in u.get('checks', [])}
        res['problems'] = len(o.get('problems', []))
    except Exception as e:
        res['schema_errors'] = [f'parse: {type(e).__name__}']
    return res

jobs = []
for x in case['calls']:
    st = (x.get('raw_request') or {}).get('stage') or ''
    axis = next((a for a in AXES if st.startswith('llm_probe_process_' + a)), None)
    if not axis: continue
    base = x['raw_request']['client_request']
    slim = json.loads(json.dumps(base)); assert slim['messages'][0]['role'] == 'system'
    slim['messages'][0]['content'] += SLIM
    for i in range(reps):
        jobs += [(f'{axis}|原样|{i}', base), (f'{axis}|精简|{i}', slim)]
res = []
with cf.ThreadPoolExecutor(len(jobs)) as ex:
    for r in ex.map(lambda j: call(*j), jobs):
        res.append(r); print(json.dumps({k: v for k, v in r.items() if k != 'outcomes'}, ensure_ascii=False), flush=True)
(OUT / 'slim_results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
