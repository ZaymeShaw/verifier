from pathlib import Path
from dataclasses import asdict
import json,copy,sys,hashlib,time
ROOT=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier');sys.path.insert(0,str(ROOT))
from impl.core.schema import normalize_run_trace
from impl.core.tool_loop import Step
from impl.core.project_loader import load_project
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS,_scenario_entry
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation
source=ROOT/'report/expectations-20261006/B-r2-low';out=ROOT/'report/expectations-20261006/B-r2-recorded-replay';out.mkdir(exist_ok=True)
records=[json.loads(p.read_text()) for p in sorted((source/'evaluator-context').glob('*.json'),key=lambda p:p.stat().st_mtime)]
last=records[-1];initial=json.loads(next(m['content'] for m in last['messages'] if m['role']=='user'))
projection=json.loads(next(r['response']['content'] for r in records if r['response']['runtime']['stage']=='llm_probe_expectations_process_projection'))
expectations=json.loads((source/'expectations.json').read_text())
steps=[{k:copy.deepcopy(v) for k,v in m.items() if k in {'role','content','tool_calls'}} for m in last['messages'] if m['role']=='assistant']
class RecordedClient:
 def __init__(self):self.steps=iter(steps);self.calls=0
 def complete_step(self,*a,**kw):self.calls+=1;return Step(next(self.steps))
 def usage(self):return {'llm_calls':self.calls}
raw=(ROOT/'report/llmtracing-calibration-draft/frozen-inputs/B.trace.json').read_bytes();trace=normalize_run_trace(json.loads(raw))
spec=load_project('llm_probe');runtime=AxisRuntime(spec,'recorded-replay',trace.trace_id,trace.normalized_request['capability_ref'],trace.case_id)
client=RecordedClient();axes={a['axis']:PROCESS_SPECS[a['axis']] for a in initial['axes']};criteria={a['axis']:a['criterion'] for a in initial['axes']}
started=time.monotonic();run=TranscriptEvaluation(build_transcript(trace,trace.project_fields['business_trace']),axes,criteria,_scenario_entry(runtime),client,expectations=expectations,projection=projection,trace_id='B-r2-recorded-replay')
result=run.run();data={'kind':'deterministic replay of recorded model tool submissions; no external model request; not a new semantic evaluation',
 'source':'B-r2-low','trace_sha256':hashlib.sha256(raw).hexdigest(),'recorded_model_steps_available':len(steps),'steps_consumed':client.calls,
 'original_six_axis_limits':{'seconds':1200,'tool_calls':40},'wall_clock_reproduced':False,'elapsed_seconds':time.monotonic()-started,
 'axes':{a:asdict(value) for a,value in result.items()}}
(out/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n');(out/'replay-harness.py').write_text(Path(__file__).read_text())
print(json.dumps({a:{'failed':v.failed,'reason':v.failure_reason,'verdict':v.output.get('assessment',{}).get('verdict'),'results':len(v.output.get('results',[]))} for a,v in result.items()},ensure_ascii=False));print('Steps',client.calls,'of',len(steps));print('Completion',run.completion_hook.checks)
