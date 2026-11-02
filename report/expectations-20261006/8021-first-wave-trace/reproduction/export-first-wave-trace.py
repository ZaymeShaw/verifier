from pathlib import Path
import json, subprocess, shutil, hashlib, datetime

root=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
dep=Path('/Users/xiaozijian/WorkSpace/package/llmtracing')
inst=root/'.runtime/instances/inst-16fa340ac786414f'
out=root/'report/expectations-20261006/8021-first-wave-trace'
job='b9712b378fba4f1cbb08e4ca22d94293'
status=json.loads(Path('/private/tmp/verifier-8021-latest-status.json').read_text())
events=[e for e in status.get('events',[]) if e.get('request_index') in range(4)]
assert status['job_id']==job and {e['request_index'] for e in events}==set(range(4))
assert {e['run']['execution_id'] for e in events}=={job+':'+str(i) for i in range(4)}
assert all(e['run']['status'] not in ('running','pending','queued') for e in events)
out.mkdir(parents=True,exist_ok=True)
(out/'first-wave-results.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
(out/'batch-status-at-export.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
base=[str(dep/'llm_gateway/.venv/bin/python'),str(dep/'llmtrace'),'query','calls','--log',str(inst/'tracing/logs'),'--include-rotated']
for i in range(4):base+=['--execution-id',job+':'+str(i)]
codes=[]
for name,args in [('raw-pairs.jsonl',['--format','pairs','--html',str(out)]),('gateway-events.json',['--format','json','--events'])]:
 with (out/name).open('w') as stream, (out/(name+'.stderr.log')).open('w') as err:
  result=subprocess.run(base+args,stdout=stream,stderr=err,cwd=dep,timeout=120)
 codes.append({'name':name,'exit_code':result.returncode,'argv':base+args})
contexts=[]
for e in events:
 r=e['run']; ids={r['trace_id']}|{a['execution_trace_ref'] for a in r['eval_axes']['results'] if a.get('execution_trace_ref')}
 for trace in sorted(ids):
  source=inst/'data/context_store/llm_probe'/trace
  if not source.is_dir():continue
  target=out/'contexts'/trace
  shutil.copytree(source,target,dirs_exist_ok=True)
  contexts.append({'execution_id':r['execution_id'],'trace_id':trace,'files':len(list(target.glob('*.json')))})
manifest={'job_id':job,'execution_ids':[job+':'+str(i) for i in range(4)],'exported_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exports':codes,'contexts':contexts}
manifest['files']=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.rglob('*')) if p.is_file()]
(out/'export-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'exports':codes,'contexts':contexts,'files':len(manifest['files'])},ensure_ascii=False))
