"""Does the slim pass shape bias the judge from input_invalid toward pass?

Replays the recorded model_capability request of live11 (old schema) and live12 (slim schema):
same case, same upstream issue tool_execution:p1; only the output schema differs.
usage: python invalid_bias.py [repeats]
"""
import collections, concurrent.futures as cf, glob, json, sys, time, urllib.request
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from impl.core.llm_client import extract_json

env = dict(l.rstrip('\n').split('=', 1) for l in open(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_primary') if '=' in l and not l.startswith('#'))
BASE, KEY = env['UPSTREAM_API_BASE'].strip('"'), env['UPSTREAM_API_KEY'].strip('"')
RUNS = {'旧结构(live11)': 'expectations-v2-axes-live11-20261008', '精简结构(live12)': 'expectations-v2-axes-live12-slim-20261008'}
reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3

def request(run):
    for f in glob.glob(str(ROOT / 'report/expectations-20261006' / run / 'contexts/llm_probe/*/*.json')):
        row = json.loads(Path(f).read_text())
        if row['governance']['snapshot']['stage'].startswith('llm_probe_process_model_capability'):
            return row['messages'], row['llm_model']
    raise SystemExit(run)

def call(label, messages, model):
    body = {'model': model, 'messages': messages, 'temperature': 0, 'stream': True, 'stream_options': {'include_usage': True}}
    req = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t = time.time(); text = []; usage = {}
    try:
        with urllib.request.urlopen(req, timeout=1200) as r:
            for raw in r:
                l = raw.decode('utf-8', 'ignore').strip()
                if not l.startswith('data:') or l == 'data: [DONE]': continue
                try: j = json.loads(l[5:])
                except Exception: continue
                if j.get('usage'): usage = j['usage']
                for ch in j.get('choices') or []:
                    if (ch.get('delta') or {}).get('content'): text.append(ch['delta']['content'])
    except Exception as e:
        return dict(label=label, error=f'{type(e).__name__}: {str(e)[:100]}')
    res = dict(label=label, elapsed=round(time.time() - t), reasoning=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'))
    try:
        o = extract_json(''.join(text))
        res['outcomes'] = dict(collections.Counter(c['outcome'] for u in o['units'] for c in u.get('checks', [])))
        res['rule_outcomes'] = dict(collections.Counter(r['outcome'] for u in o['units'] for r in u.get('rules', [])))
    except Exception as e:
        res['error'] = f'parse {type(e).__name__}'
    return res

jobs = [(f'{name}|{i}', *request(run)) for name, run in RUNS.items() for i in range(reps)]
with cf.ThreadPoolExecutor(len(jobs)) as ex:
    res = list(ex.map(lambda j: call(*j), jobs))
for r in res: print(json.dumps(r, ensure_ascii=False), flush=True)
(OUT / 'invalid_bias_results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
