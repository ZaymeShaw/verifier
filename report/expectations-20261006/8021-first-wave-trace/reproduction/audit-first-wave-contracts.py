import json,sys,collections,difflib
from pathlib import Path
root=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier');sys.path.insert(0,str(root))
from impl.projects.llm_probe.business_trace.dossier import expand_content
from impl.projects.llm_probe.eval_axes.adapters.process_common import _expand
out=root/'report/expectations-20261006/8021-first-wave-trace'
runs=[e['run'] for e in json.loads((out/'first-wave-results.json').read_text())]
def contains(body,value):
 if body==value:return True
 if isinstance(body,str) and isinstance(value,str):return value in body
 if isinstance(body,str):
  try:body=json.loads(body)
  except ValueError:return False
 if isinstance(body,dict):
  if isinstance(value,dict) and all(k in body and contains(body[k],v) for k,v in value.items()):return True
  return any(contains(v,value) for v in body.values())
 if isinstance(body,list):return any(contains(v,value) for v in body)
 return False
audit=[]
for run in runs:
 e=next(a['output'] for a in run['eval_axes']['results'] if a['axis_id']=='expectations');dossier=next(a['output']['dossier'] for a in run['eval_axes']['results'] if a['axis_id']=='trace_analysis');rows={r['id']:r for r in dossier['records']};entries={r['expectation_id']:r for r in e['expectations']};sources={r['id']:r for r in e['sources']}
 for dr in (out/'contexts').glob('axes-*'+run['trace_id']):
  for f in sorted(dr.glob('*.json')):
   x=json.loads(f.read_text());stage=x['response'].get('runtime',{}).get('stage','');raw=x['response'].get('content');
   if not stage.startswith('llm_probe_process_'):continue
   user=next(m['content'] for m in reversed(x['messages']) if m['role']=='user');u=json.loads(user.split('\n上次输出格式错误')[0]);payload=json.loads(raw) if isinstance(raw,str) else raw
   links={l['link_id']:l for l in u['links']['links']+u['links']['match_candidates']}
   if '上次输出格式错误' in user and '引用未交付正文' in user:
    import ast
    refs=ast.literal_eval(user.split('引用未交付正文：')[-1]);delivered={r['id']:r for r in u['dossier_view']['records']};extras=u['dossier_view'].get('contents',{});matches=[]
    for ref in refs:
     parents=[p for p in delivered if ref.startswith(p+'/')]
     matches.append({'ref':ref,'delivered_parents':parents,'parent_fields':{p:list(delivered[p].get('fields',{})) for p in parents}})
    audit.append({'kind':'reference_granularity','case_id':run['case_id'],'stage':stage,'record':str(f.relative_to(out)),'refs':matches})
   if stage.startswith('llm_probe_process_model_capability'):
    misses=[]
    for r in _expand(payload['results']):
     if r['outcome'] not in ['pass','fail']:continue
     link=links.get(r.get('matched_link_id')or r['link_id'],{});actual=[expand_content((rows.get(end['ref'],{}).get('fields',{}).get(end['field'])or {}).get('value'),dossier.get('contents',{})) for end in link.get('input',[])]
     for check in r['expectation_checks']:
      if check['outcome'] not in ['pass','fail']:continue
      for ref in entries[check['expectation_id']]['source_refs']:
       source=sources[ref]
       if source['side']=='history' or any(contains(body,source['value']) for body in actual):continue
       value=source['value'];best=0
       if isinstance(value,str):
        strings=[]
        def strings_in(body):
         if isinstance(body,str):strings.append(body)
         elif isinstance(body,dict):
          for v in body.values():strings_in(v)
         elif isinstance(body,list):
          for v in body:strings_in(v)
        for body in actual:strings_in(body)
        best=max([difflib.SequenceMatcher(None,value,v,autojunk=False).ratio() for v in strings]or[0]) if len(value)<20000 else None
       misses.append({'expectation_id':check['expectation_id'],'check_outcome':check['outcome'],'link_id':r['link_id'],'matched_link_id':r['matched_link_id'],'source_ref':ref,'source_side':source['side'],'source_component':source['component'],'source_type':type(value).__name__,'source_chars':len(json.dumps(value,ensure_ascii=False)),'actual_input_refs':link.get('input'),'actual_types':[type(b).__name__ for b in actual],'best_string_similarity':best})
    audit.append({'kind':'mu_source_contains','case_id':run['case_id'],'stage':stage,'record':str(f.relative_to(out)),'misses':misses})
(out/'contract-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
for item in audit:
 if item['kind']=='reference_granularity':print(json.dumps(item,ensure_ascii=False)[:1500])
 elif item['misses']:print('MU_MISSING',item['case_id'],item['stage'],len(item['misses']),json.dumps(item['misses'][:2],ensure_ascii=False))
