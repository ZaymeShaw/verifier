from pathlib import Path
import json, collections, statistics, datetime, hashlib

root=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
out=root/'report/expectations-20261006/8021-first-wave-trace'
runs=[e['run'] for e in json.loads((out/'first-wave-results.json').read_text())]
pairs=[json.loads(s) for s in (out/'raw-pairs.jsonl').read_text().splitlines()]
def dt(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def dumps(x):return json.dumps(x,ensure_ascii=False)
def phase(s):
 if s.startswith('trace_analysis:'):return 'trace_analysis'
 if s.startswith('llm_probe_process_'):return s.removeprefix('llm_probe_process_').rsplit('_batch',1)[0]
 return s or 'main_judge'
def content(x):
 if isinstance(x,str):
  try:return json.loads(x)
  except ValueError:return None
 return x
calls=[]
for p in pairs:
 req=p.get('request')or {};cr=req.get('client_request')or {};resp=p.get('response')or {};usage=resp.get('usage')or {}
 completion=usage.get('completion_tokens');reasoning=(usage.get('completion_tokens_details')or {}).get('reasoning_tokens')
 response=resp.get('response') or {}; choices=response.get('choices') or []; message=(choices[0].get('message') or {}) if choices else {}
 calls.append({'call_id':p['call_id'],'execution_id':p['execution_id'],'case_id':p['case_id'],'stage':p.get('stage'),'phase':phase(p.get('stage')or ''),'trace_id':p.get('verifier_trace_id'),'started_at':p.get('ts'),'ended_at':p.get('ended_at'),'elapsed_ms':p.get('latency_ms'),'first_frame_ms':p.get('first_frame_ms'),'first_frame_kind':p.get('first_frame_kind'),'state':p.get('state'),'gateway':p.get('gateway'),'model':p.get('model'),'reasoning_effort':cr.get('reasoning_effort'),'request_message_chars':sum(len(m.get('content','')) if isinstance(m.get('content'),str) else len(dumps(m.get('content'))) for m in req.get('messages',[])),'request_chars':len(dumps(cr)),'native_response_format':cr.get('response_format'),'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':completion,'reasoning_tokens':reasoning,'reported_total_tokens':usage.get('total_tokens'),'usage_reasoning_exceeds_completion':isinstance(completion,int) and isinstance(reasoning,int) and reasoning>completion,'response_reasoning_chars':len(message.get('reasoning_content') or ''),'response_content_chars':len(message.get('content') or ''),'usage_present':bool(usage)})
contexts=[]
for r in runs:
 cid=r['case_id'];eid=r['execution_id']
 for dr in sorted((out/'contexts').glob('*'+r['trace_id'])):
  for f in sorted(dr.glob('*.json')):
   x=json.loads(f.read_text());rt=x.get('response',{}).get('runtime',{});stage=rt.get('stage')or '';messages=x.get('messages',[])
   user=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
   system='\n'.join(str(m.get('content','')) for m in messages if m.get('role')=='system')
   repair=None
   for marker in ['上次输出格式错误，请按原任务重新输出 JSON：','修正无效投影：']:
    if marker in user:repair=user[user.rfind(marker)+len(marker):]
   u=content(user.split('\n上次输出格式错误')[0]);c=content(x.get('response',{}).get('content'))
   row={'execution_id':eid,'case_id':cid,'record_path':str(f.relative_to(out)),'record_id':x.get('record_id'),'stage':stage,'phase':phase(stage),'created_at':x['created_at'],'elapsed_ms':x.get('elapsed_ms',0),'prompt_chars':x.get('prompt_size'),'user_chars':len(user),'system_chars':len(system),'repair_error':repair,'runtime_attempts':rt.get('attempts',[]),'matched_gateway_call_ids':[]}
   end=dt(x['created_at']);start=end-datetime.timedelta(milliseconds=row['elapsed_ms'])
   for call in calls:
    if call['execution_id']==eid and (call['stage']or '')==stage and call['trace_id']==x.get('trace_id') and start-datetime.timedelta(seconds=2)<=dt(call['started_at'])<=end+datetime.timedelta(seconds=2):row['matched_gateway_call_ids'].append(call['call_id'])
   if isinstance(u,dict) and isinstance(u.get('dossier_view'),dict):
    view=u['dossier_view'];links=u.get('links',{})
    row['sections_chars']={k:len(dumps(v)) for k,v in u.items()};row['actual_links']=sum(l.get('origin')!='expectation_deduction' for l in links.get('links',[]));row['expected_links']=sum(l.get('origin')=='expectation_deduction' for l in links.get('links',[]));row['match_candidates']=len(links.get('match_candidates',[]));row['pending_pairs']=sum(len(v) for v in u.get('pending',{}).values());row['contracts']=len(u.get('expectations',[]));row['record_ids']=[z['id'] for z in view.get('records',[])];row['record_fields']={z['id']:list(z.get('fields',{})) for z in view.get('records',[])};row['body_hashes']={k:hashlib.sha256(dumps(v).encode()).hexdigest() for k,v in view.get('shared_contents',{}).items()};row['delivered_view_chars']=len(dumps(view))
    row['missing_contract_ids']=sorted({a['expectation_id'] for a in u.get('expectations',[])}-{a for group in (c or {}).get('results',[]) for a in group.get('expectation_ids',[])}) if isinstance(c,dict) else []
   if isinstance(c,dict):
    row['result_groups']=len(c.get('results',[]));row['matched_link_id_missing']=sum('matched_link_id' not in z for z in c.get('results',[]))
    row['bad_attribution_axes']=[{'problem_id':p.get('problem_id'),'axes':p.get('attribution_axes')} for z in c.get('results',[]) for p in z.get('problems',[]) if set(p.get('attribution_axes',[]))-{'intent_understanding','planning_routing','tool_execution','knowledge_data','model_capability','context_memory'} or len(p.get('attribution_axes',[]))!=len(set(p.get('attribution_axes',[])))]
   contexts.append(row)
summary=[]
for run in runs:
 eid=run['execution_id'];gs=[r for r in calls if r['execution_id']==eid];cs=[r for r in contexts if r['execution_id']==eid];usage=[r for r in gs if r['usage_present']]
 axes=run['eval_axes']['results'];phases={}
 for p in sorted({r['phase'] for r in cs}):
  rs=[r for r in cs if r['phase']==p];gg=[r for r in gs if r['phase']==p]
  phases[p]={'logical_calls':len(rs),'gateway_calls':len(gg),'context_ms':sum(r['elapsed_ms'] for r in rs),'gateway_ms':sum(r.get('elapsed_ms')or 0 for r in gg),'repair_calls':sum(bool(r['repair_error']) for r in rs),'repair_context_ms':sum(r['elapsed_ms'] for r in rs if r['repair_error'])}
 summary.append({'execution_id':eid,'case_id':run['case_id'],'status':run['status'],'started_at':run['llmtracing']['started_at'],'live_ms':run['stage_timings']['live_ms'],'judge_ms':run['stage_timings']['judge_ms'],'end_to_end_ms':run['stage_timings']['live_ms']+run['stage_timings']['judge_ms'],'gateway_calls':len(gs),'context_calls':len(cs),'sum_context_ms':sum(r['elapsed_ms'] for r in cs),'repair_calls':sum(bool(r['repair_error']) for r in cs),'repair_context_ms':sum(r['elapsed_ms'] for r in cs if r['repair_error']),'prompt_chars':sum(r.get('prompt_chars')or 0 for r in cs),'prompt_tokens':sum(r.get('prompt_tokens')or 0 for r in gs),'completion_tokens':sum(r.get('completion_tokens')or 0 for r in gs),'reasoning_tokens':sum(r.get('reasoning_tokens')or 0 for r in gs),'usage_available_calls':len(usage),'phases':phases,'axes':[{'axis_id':a['axis_id'],'status':a['status'],'verdict':a.get('summary',{}).get('verdict',a.get('verdict')),'error':a.get('error'),'usage':a.get('usage'),'finished_at':a.get('finished_at')} for a in axes]})
(out/'call-stats.json').write_text(json.dumps({'gateway_calls':calls,'context_calls':contexts,'cases':summary},ensure_ascii=False,indent=2))
print('CASES',dumps([{k:v for k,v in r.items() if k not in ['axes','phases']} for r in summary]))
print('PHASE_TOTALS',dumps({p:{'logical_calls':sum(r['phase']==p for r in contexts),'context_ms':sum(r['elapsed_ms'] for r in contexts if r['phase']==p)} for p in sorted({r['phase'] for r in contexts})}))
print('REPAIRS',dumps([{'case':r['case_id'].removeprefix('llm-probe-insurance-real-smoke-'),'stage':r['stage'],'ms':r['elapsed_ms'],'error':r['repair_error'],'calls':r['matched_gateway_call_ids']} for r in contexts if r['repair_error']]))
print('MATCHED',len({c for r in contexts for c in r['matched_gateway_call_ids']}),'of',len(calls))
print('TOKEN_TOTALS',{k:sum(r.get(k)or 0 for r in calls) for k in ['prompt_tokens','completion_tokens','reasoning_tokens']})
print('FIRST_FRAMES',{'median_ms':statistics.median(r['first_frame_ms'] for r in calls if isinstance(r.get('first_frame_ms'),(int,float))),'max_ms':max(r['first_frame_ms'] for r in calls if isinstance(r.get('first_frame_ms'),(int,float))),'kinds':dict(collections.Counter(r.get('first_frame_kind') for r in calls))})
print('LONGEST',dumps(sorted(calls,key=lambda r:r.get('elapsed_ms')or 0,reverse=True)[:5]))
