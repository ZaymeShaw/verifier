"""经服务 API（与前端 live 页同一调用）跑 ES 知识场景：live_run → eval_axes/run，记耗时与结论。"""
import json, sys, time, urllib.request
from pathlib import Path
BASE = 'http://127.0.0.1:8031'
OUT = Path(__file__).parent / 'es'; OUT.mkdir(exist_ok=True)
def post(path, body, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode(), headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())
def body(q):
    return {"model": "qwen-turbo", "input": {"messages": [{"role": "user", "content": q}]}, "parameters": {"result_format": "message", "incremental_output": False}}
CASES = [
    ("hr-housing", "hr-handbook-qa", "公司有没有住房补贴？每月多少？"),
    ("hr-annual", "hr-handbook-qa", "按公司员工手册，我累计工龄3年，年休假有几天？只回答天数。"),
    ("clause-cashvalue", "policy-clause-qa", "用一句话回答：康宁终身险的现金价值是怎么计算的？请给出具体比例。"),
    ("clause-hesitation", "policy-clause-qa", "仅依据下面的条款用一句话回答。条款：『康宁终身险：本产品犹豫期为二十日，自投保人签收保险单之日起计算。』问题：康宁终身险的犹豫期是多少天？"),
]
for cid, cap, q in CASES:
    t0 = time.time(); trace = post('/api/live_run', {"project": "llm_probe", "input": {"capability_ref": cap, "body": body(q)}}); t1 = time.time()
    report = post('/api/eval_axes/run', {"project": "llm_probe", "trace": trace}); t2 = time.time()
    try:
        answer = json.loads(trace['extracted_output']['output_text'])['output']['choices'][0]['message']['content']
    except Exception:
        answer = str((trace.get('extracted_output') or {}).get('output_text'))[:200]
    res = {r['type_id']: r for r in (report.get('report') or report).get('results', [])}
    truth = res.get('truthfulness') or {}; ful = res.get('fulfillment') or {}; ke = res.get('knowledge_evidence') or {}
    row = {'case': cid, 'scenario': cap, 'live_status': trace.get('status'), 'live_s': round(t1 - t0, 1), 'axes_s': round(t2 - t1, 1),
           'answer': answer, 'claims': [(c.get('verdict'), (c.get('text') or '')[:40]) for c in (truth.get('output') or {}).get('claims') or []],
           'fulfillment': ((ful.get('output') or {}).get('overall_fulfillment') or {}).get('status'),
           'axis_status': {k: v.get('status') for k, v in res.items()},
           'usage': {k: {u: (v.get('usage') or {}).get(u) for u in ('llm_calls', 'tool_calls')} for k, v in res.items()},
           'fulfillment_reason': ((ful.get('output') or {}).get('reasoning_summary') or '')[:220]}
    (OUT / f'{cid}.json').write_text(json.dumps({'row': row, 'trace': trace, 'report': report}, ensure_ascii=False, indent=1))
    print(json.dumps(row, ensure_ascii=False), flush=True)
