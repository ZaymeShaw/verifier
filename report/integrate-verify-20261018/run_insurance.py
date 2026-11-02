"""经服务 API 跑 Insurance 三个验证场景（Langfuse trace / Agno trace / MCP 知识），记耗时、调用、结论。"""
import json, time, uuid, urllib.request, urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
BASE = 'http://127.0.0.1:8031'; OUT = Path(__file__).parent / 'insurance'; OUT.mkdir(exist_ok=True)
def post(path, body, timeout=1800):
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode(), headers={'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {'http_error': e.code, 'body': e.read().decode()[:1500]}
QUESTIONS = [("bizno", "客户号C92200000884对应的客户是谁？"), ("fuyunping-policies", "伏云平名下有哪些保单？")]
SCENARIOS = ["verify-insurance-langfuse", "verify-insurance-agno", "verify-insurance-mcp"]
def run(qid, q, scen):
    name = f'{scen.replace("verify-insurance-", "")}-{qid}'
    body = {"messages": [{"role": "user", "content": q}], "session_id": f"verify-{uuid.uuid4().hex[:12]}", "stream": False,
            "user_id": "1050900009", "empno": "1050900009", "agentno": "1050900009", "trace_id": f"verify-{uuid.uuid4().hex}"}
    t0 = time.time(); trace = post('/api/live_run', {"project": "llm_probe", "input": {"capability_ref": scen, "body": body}}); t1 = time.time()
    row = {'name': name, 'live_status': trace.get('status'), 'live_error': str(trace.get('error'))[:200], 'live_s': round(t1 - t0, 1)}
    bt = (trace.get('project_fields') or {}).get('business_trace') or {}
    if bt:
        content_gap = next(((l.get('items') or []) for k, l in ((bt.get('coverage') or {}).get('limitations') or {}).items() if k == 'content'), None)
        row.update(trace_status=bt.get('status'), trace_errors=bt.get('errors'), trace_provider=bt.get('provider'),
                   gap_items=len(content_gap) if isinstance(content_gap, list) else None)
    try:
        row['answer'] = (trace.get('raw_response') or {}).get('answer', '')[:160]
    except Exception:
        row['answer'] = str(trace.get('raw_response'))[:160]
    if scen.endswith('mcp'):
        rep = post('/api/eval_axes/run', {"project": "llm_probe", "trace": trace}); t2 = time.time()
        res = {r['type_id']: r for r in (rep.get('report') or rep).get('results', [])}
        row.update(axes_s=round(t2 - t1, 1), axis_status={k: v.get('status') for k, v in res.items()},
                   usage={k: {u: (v.get('usage') or {}).get(u) for u in ('llm_calls', 'tool_calls')} for k, v in res.items()},
                   claims=[(c.get('verdict'), (c.get('text') or '')[:40]) for c in ((res.get('truthfulness') or {}).get('output') or {}).get('claims') or []],
                   verdict=(((res.get('fulfillment') or {}).get('output') or {}).get('overall_fulfillment') or {}).get('status'),
                   reason=(((res.get('fulfillment') or {}).get('output') or {}).get('reasoning_summary') or '')[:300])
        payload = {'row': row, 'trace': trace, 'report': rep}
    else:
        judge = post('/api/judge', {"project": "llm_probe", "trace": trace}); t2 = time.time()
        j = judge.get('judge') or judge
        report = (j.get('process_report') or trace.get('_pending_process_report') or {})
        row.update(judge_s=round(t2 - t1, 1), verdict=(j.get('overall_fulfillment') or {}).get('status'),
                   reason=(j.get('reasoning_summary') or '')[:300], judge_keys=list(j.keys())[:12])
        payload = {'row': row, 'trace': trace, 'judge': judge}
    (OUT / f'{name}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(json.dumps(row, ensure_ascii=False), flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:
    for f in [pool.submit(run, qid, q, s) for qid, q in QUESTIONS for s in SCENARIOS]: f.result()
print('done', flush=True)
