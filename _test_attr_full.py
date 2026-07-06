import json, urllib.request, sys
BASE='http://127.0.0.1:8021'
def call(p,b):
    req=urllib.request.Request(f'{BASE}{p}',data=json.dumps(b).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=900) as r: return json.loads(r.read().decode())

# marketting-planning-intent case 0 (从之前的 api-check 知道是 incorrect/not_fulfilled)
project='marketting-planning-intent'
cases=call('/api/mock_cases',{'project':project})['cases']
print('case:', cases[0].get('id'))
sys.stdout.flush()

# 跑 run_chain (可能很慢)
run=call('/api/run_chain',{'project':project,'input':cases[0]})
j=run['judge']
print('verdict:', j.get('verdict'), 'fulfillment:', (j.get('overall_fulfillment') or {}).get('status'))
sys.stdout.flush()

# attribute
attr=call('/api/attribute',{'project':project,'trace':run['trace'],'judge':j})
tcl=attr.get('tool_call_log')
print('causal:', attr.get('causal_category'))
print('tool_call_log count:', len(tcl) if tcl else 0)
if tcl:
    for e in tcl:
        print('  tool:', e.get('tool_name'), 'status:', e.get('status'))
        args = e.get('arguments')
        if args: print('    args:', json.dumps(args, ensure_ascii=False)[:100])
        result = e.get('result')
        if result: print('    result:', str(result)[:150])
