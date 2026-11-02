"""trace 场景改走 /api/run_chain（服务端一次跑完 live→judge→…，业务 trace 不经接口丢失）。"""
import json, time, uuid, urllib.request, urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
BASE = 'http://127.0.0.1:8031'; OUT = Path(__file__).parent / 'insurance-chain'; OUT.mkdir(exist_ok=True)
def post(path, body, timeout=3600):
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode(), headers={'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {'http_error': e.code, 'body': e.read().decode()[:1500]}
QUESTIONS = [("bizno", "客户号C92200000884对应的客户是谁？"), ("fuyunping-policies", "伏云平名下有哪些保单？")]
SCENARIOS = ["verify-insurance-langfuse", "verify-insurance-agno"]
def run(qid, q, scen):
    name = f'{scen.replace("verify-insurance-", "")}-{qid}'
    body = {"messages": [{"role": "user", "content": q}], "session_id": f"verify-{uuid.uuid4().hex[:12]}", "stream": False,
            "user_id": "1050900009", "empno": "1050900009", "agentno": "1050900009", "trace_id": f"verify-{uuid.uuid4().hex}"}
    t0 = time.time(); res = post('/api/run_chain', {"project": "llm_probe", "input": {"capability_ref": scen, "body": body}}); t1 = time.time()
    j = res.get('judge') or {}; row_t = res.get('table_row') or {}
    row = {'name': name, 'total_s': round(t1 - t0, 1), 'http_error': res.get('http_error'),
           'verdict': (j.get('overall_fulfillment') or {}).get('status'),
           'stage_timings': row_t.get('stage_timings') or (res.get('trace') or {}).get('stage_timings'),
           'answer': str(((res.get('trace') or {}).get('raw_response') or ''))[:150],
           'reason': (j.get('reasoning_summary') or res.get('body') or '')[:600]}
    (OUT / f'{name}.json').write_text(json.dumps({'row': row, 'response': res}, ensure_ascii=False, indent=1))
    print(json.dumps(row, ensure_ascii=False), flush=True)
with ThreadPoolExecutor(max_workers=4) as pool:
    for f in [pool.submit(run, qid, q, s) for qid, q in QUESTIONS for s in SCENARIOS]: f.result()
print('done', flush=True)
