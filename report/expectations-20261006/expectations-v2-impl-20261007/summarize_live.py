"""Summarize captured real runs without making requests; stage scopes are explicit."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import sys

out = Path(sys.argv[1])
result = json.loads((out / 'result.json').read_text())
rows = [json.loads(line) for line in (out / 'gateway-events.jsonl').read_text().splitlines()]
requests = {r['call_id']: r for r in rows if r['event'] == 'pre_api_call'}
attempts = Counter(r['call_id'] for r in rows if r['event'] == 'pre_api_call')
failed_stages = {r['stage'] for r in rows if r['event'] == 'failure'}
success = {r['call_id']: r for r in rows if r['event'] == 'success'}

def phase(stage):
    if stage == 'llm_probe_expectations': return 'expectations'
    if stage.startswith('trace_analysis:'): return 'analysis'
    if stage == 'llm_probe_expectations_process_projection': return 'projection'
    if stage.startswith('llm_probe_process_'): return 'six_axes'
    if stage.startswith('llm_probe_need_'): return 'main_judge'
    return 'other'

stats = {}
for ident, request in requests.items():
    name = phase(request.get('stage', ''))
    s = stats.setdefault(name, dict(calls=0, logical_requests=0, transport_retries=0, route_retries=0,
                                   correction_requests=0, raw_invalid_json=0, output_chars=0, tool_submissions=Counter(), models=Counter()))
    s['calls'] += attempts[ident]
    s['logical_requests'] += 1
    s['transport_retries'] += attempts[ident] - 1
    messages = request.get('messages') or []
    last = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), '')
    if any(text in str(last) for text in ('修正无效投影：', '上次输出未通过程序检查', '上次输出无效')):
        s['correction_requests'] += 1
    response = success.get(ident, {}).get('response') or {}
    s['models'][response.get('model', request.get('model', 'unknown'))] += attempts[ident]
    for choice in response.get('choices', []):
        message = choice.get('message') or {}
        content = message.get('content') or ''
        s['output_chars'] += len(content)
        if name in {'expectations', 'projection', 'six_axes', 'main_judge'} and content:
            try: json.loads(content)
            except (ValueError, TypeError): s['raw_invalid_json'] += 1
        for call in message.get('tool_calls') or []:
            function = call.get('function') or {}
            args = function.get('arguments') or ''
            s['output_chars'] += len(args)
            s['tool_submissions'][function.get('name', '')] += 1
            try: json.loads(args)
            except (ValueError, TypeError): s['raw_invalid_json'] += 1
for stage in failed_stages:
    identities = [r for r in requests.values() if r['stage'] == stage]
    stats[phase(stage)]['route_retries'] += max(0, len(identities) - 1)
for s in stats.values():
    s['submission_retries'] = sum(max(0, n-1) for tool,n in s['tool_submissions'].items() if tool.startswith('submit_'))
    s['retries'] = s['correction_requests'] + s['submission_retries'] + s['transport_retries'] + s['route_retries']
axes = (result.get('axes') or {}).get('results', [])
need = next((a for a in axes if a.get('type_id') == 'expectations'), {})
def elapsed(axis):
    if axis.get('started_at') and axis.get('finished_at'):
        return (datetime.fromisoformat(axis['finished_at']) - datetime.fromisoformat(axis['started_at'])).total_seconds()
expectations = (need.get('output') or {}).get('expectations', [])
process = [a for a in axes if a.get('type_id') not in {'expectations', 'trace_analysis'}]
summary = dict(run_id=result['run_id'], elapsed_seconds=result['elapsed_seconds'],
    expectation_count=len(expectations), expectation_seconds=elapsed(need),
    expectation_verdict=need.get('verdict'), expectations=expectations,
    stages=stats, total={key:sum(s[key] for s in stats.values()) for key in ('calls','retries','raw_invalid_json','output_chars')},
    six_axes_succeeded=sum(a['status']=='succeeded' for a in process), six_axes_total=len(process),
    axes=[{k:a.get(k) for k in ('type_id','status','verdict','error')} for a in process],
    main_judge=(result.get('judge') or {}).get('overall_fulfillment'),
    counting='Gateway pre_api_call attempts (also report unique logical_requests); output chars = assistant content + tool arguments, excludes reasoning. Invalid JSON before repair, analysis plain tool-use content excluded. Retries = explicit correction requests + resubmitted submit_* tools + repeated transport attempts + failed-stage route changes. Repeated independent preparations after a previous axis failed are shown as calls, not schema correction rounds. No business calls.')
(out / 'metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in {'expectations','axes'}},ensure_ascii=False,indent=2))
