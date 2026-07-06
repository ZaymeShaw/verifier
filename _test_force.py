import json, urllib.request, sys
BASE='http://127.0.0.1:8021'
def call(p,b):
    req=urllib.request.Request(f'{BASE}{p}',data=json.dumps(b).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=900) as r: return json.loads(r.read().decode())

# 直接用 client_search，mock case[0]
cases=call('/api/mock_cases',{'project':'client_search'})['cases']
print('case:', cases[0].get('id'))
sys.stdout.flush()

run=call('/api/run_chain',{'project':'client_search','input':cases[0]})
trace=run['trace']
judge=run['judge']
print('orig verdict:', judge.get('verdict'), 'fulfillment:', (judge.get('overall_fulfillment') or {}).get('status'))
sys.stdout.flush()

# 强制改成 not_fulfilled 触发 attribute LLM (走 tool 路径)
judge['verdict']='incorrect'
judge['overall_fulfillment']={'status':'not_fulfilled','assessment_count':1}
# 确保 fulfillment_assessments 也都是 not_fulfilled
assessments = judge.get('fulfillment_assessments') or []
if not assessments:
    bes = judge.get('business_expectations') or []
    assessments = [{'expectation_id': (be.get('expectation_id') if isinstance(be,dict) else be.get('id')) or 'exp_1', 'status':'not_fulfilled','blocking':True} for be in bes]
    if not assessments:
        assessments = [{'expectation_id':'exp_1','status':'not_fulfilled','blocking':True}]
for a in assessments:
    a['status']='not_fulfilled'
    a['blocking']=True
judge['fulfillment_assessments']=assessments
judge['reasoning_summary']='forced not_fulfilled for tool_call_log test'

attr=call('/api/attribute',{'project':'client_search','trace':trace,'judge':judge})
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
# dump full attr to a file for inspection
open('/tmp/attr_dump.json','w').write(json.dumps(attr, ensure_ascii=False, indent=2))
print('full attr dumped to /tmp/attr_dump.json')
