"""Clarity experiment: replay two recorded six-axis requests verbatim vs with one clarifying sentence.

Same model and params as the recorded run; only the system prompt differs. Measures reasoning tokens.
usage: python clarity.py <trace2.json> [repeats]
"""
import concurrent.futures as cf, json, sys, time, urllib.request
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
env = dict(l.rstrip('\n').split('=', 1) for l in open(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_primary') if '=' in l and not l.startswith('#'))
BASE, KEY = env['UPSTREAM_API_BASE'].strip('"'), env['UPSTREAM_API_KEY'].strip('"')
AMBIG = '不要把模型输出格式错误写为业务问题。'
CASES = {
    # context_memory, anjinning: loss happened upstream inside this axis, no recorded issue id yet
    'cm_anjinning': ('llm_probe_process_context_memory', 'smoke-multi-policy-anjinning', 48384,
                     '\n补充：传递/交付类单位只判这一步自己有没有把收到的内容原样交出。内容在更上游就已缺失时，这一步判 pass，fact 写明收到的已不完整；缺失写成问题，挂在实际丢失内容的那一步对应的单位上。'),
    # model_capability, wrong-empno: ambiguous "format error" sentence
    'mc_wrong_empno': ('llm_probe_process_model_capability', 'smoke-neg-wrong-empno', 43941,
                       None),
}
trace = json.load(open(sys.argv[1])); reps = int(sys.argv[2]) if len(sys.argv) > 2 else 2

def find(stage, case, reason):
    for c in trace['cases']:
        for x in c['calls']:
            st = (x.get('raw_request') or {}).get('stage') or ''
            r = ((x.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
            if st.startswith(stage) and case in c['identity']['case_id'] and r == reason:
                return x['raw_request']['client_request']
    raise SystemExit(f'not found {stage} {case}')

def variant(req, name, extra):
    req = json.loads(json.dumps(req)); sys_msg = req['messages'][0]
    assert sys_msg['role'] == 'system'
    if extra:
        sys_msg['content'] += extra
    else:
        assert AMBIG in sys_msg['content']
        sys_msg['content'] = sys_msg['content'].replace(AMBIG, '你自己的 JSON 写坏不算业务问题；被评测的业务模型违反它的输出约定，属于本轴要判的问题。')
    return req

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
    return dict(label=label, elapsed=round(time.time() - t), reasoning=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                completion=usage.get('completion_tokens'), prompt=usage.get('prompt_tokens'), content=''.join(content))

jobs = []
for key, (stage, case, reason, extra) in CASES.items():
    base = find(stage, case, reason)
    for i in range(reps):
        jobs.append((f'{key}|原样|{i}', base)); jobs.append((f'{key}|澄清|{i}', variant(base, key, extra)))
res = []
with cf.ThreadPoolExecutor(len(jobs)) as ex:
    for r in ex.map(lambda j: call(*j), jobs):
        res.append(r); print(json.dumps({k: v for k, v in r.items() if k != 'content'}, ensure_ascii=False), flush=True)
(OUT / 'clarity_results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
