"""Reasoning-level experiment: same real six-axis prompts, different relay model tiers.

Calls the relay directly (no gateway, no code/config change). Each prompt is the system+user the
current code builds (output-constraint appended exactly as complete_json does). Validation uses the
project's own output_spec so "does it still produce a valid judgment" is measured, not assumed.
usage: python run.py [model ...]
"""
import concurrent.futures as cf, json, os, sys, time, urllib.request
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from impl.core.structured_output import render_output_constraint, validate_output
from impl.core.llm_client import extract_json
from impl.projects.llm_probe.eval_axes.adapters.process_output import OUTPUT

env = {}
for line in open(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_primary'):
    if '=' in line and not line.startswith('#'):
        k, v = line.rstrip('\n').split('=', 1); env[k] = v.strip('"')
BASE, KEY = env['UPSTREAM_API_BASE'], env['UPSTREAM_API_KEY']
PROMPTS = ['tool_execution_batch1', 'model_capability_batch1', 'intent_understanding_batch1']
MODELS = sys.argv[1:] or ['gemini-3.8-flash-medium', 'gemini-3.8-flash-low', 'gemini-3.8-flash-high', 'gemini-3.8-flash-tiered']
constraint = render_output_constraint(OUTPUT)

def call(model, name):
    p = json.load(open(ROOT / f'report/expectations-20261006/context-replay-20261008/prompts/llm_probe_process_{name}.json'))
    body = {'model': model, 'temperature': 0, 'max_tokens': 60000, 'stream': True, 'stream_options': {'include_usage': True},
            'messages': [{'role': 'system', 'content': p['system'] + '\n\n' + constraint}, {'role': 'user', 'content': p['user']}]}
    req = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t0 = time.time(); ttft = None; text = []; usage = {}
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            for raw in r:
                line = raw.decode('utf-8', 'ignore').strip()
                if not line.startswith('data:') or line == 'data: [DONE]': continue
                try: j = json.loads(line[5:])
                except Exception: continue
                if j.get('usage'): usage = j['usage']
                for ch in j.get('choices') or []:
                    d = ch.get('delta') or {}
                    if ttft is None and (d.get('content') or d.get('reasoning_content') or d.get('tool_calls')): ttft = time.time() - t0
                    if d.get('content'): text.append(d['content'])
    except Exception as e:
        return dict(model=model, prompt=name, error=f'{type(e).__name__}: {str(e)[:160]}', elapsed=time.time() - t0)
    content = ''.join(text); det = usage.get('completion_tokens_details') or {}
    res = dict(model=model, prompt=name, elapsed=round(time.time() - t0, 1), ttft=round(ttft or 0, 1), prompt_tokens=usage.get('prompt_tokens'),
               completion_tokens=usage.get('completion_tokens'), reasoning_tokens=det.get('reasoning_tokens'), content_chars=len(content))
    try:
        parsed = extract_json(content); errs = validate_output(parsed, OUTPUT)
        res['schema_errors'] = errs[:3]; res['valid_schema'] = not errs
        units = {u['unit']: [(c['criterion'], c['outcome']) for c in u.get('checks', [])] for u in parsed.get('units', [])}
        res['outcomes'] = units
    except Exception as e:
        res['valid_schema'] = False; res['schema_errors'] = [f'parse: {type(e).__name__}: {str(e)[:100]}']
    (OUT / f'raw_{model}_{name}.txt').write_text(content)
    return res

jobs = [(m, n) for n in PROMPTS for m in MODELS]
results = []
with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
    for fut in cf.as_completed([ex.submit(call, m, n) for m, n in jobs]):
        r = fut.result(); results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != 'outcomes'}, ensure_ascii=False), flush=True)
(OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
