from dataclasses import replace, asdict
from pathlib import Path
import json, hashlib, time, sys
ROOT=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
sys.path.insert(0,str(ROOT))
OUT=ROOT/'report/expectations-20261006/B-low'
OUT.mkdir(parents=True,exist_ok=False)
from impl.core import config, context_store
from impl.core.config_schema import LlmRolePolicyOverride
from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace
from impl.projects.llm_probe.eval_axes import build_report
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.eval_axes.adapters.process_common import _scenario_entry
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
resolved=config.get_runtime_config()
policies=dict(resolved.llm.role_policies)
policies['judge']=replace(policies.get('judge',LlmRolePolicyOverride()),reasoning_effort='low')
config._RUNTIME_CONFIG=replace(resolved,llm=replace(resolved.llm,role_policies=policies))
raw=(ROOT/'report/llmtracing-calibration-draft/frozen-inputs/B.trace.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='69e8a0513dec857fab62e3c5db92709782cc9e8ea7ccd8faec664de314ef3831'
trace=normalize_run_trace(json.loads(raw));spec=load_project('llm_probe')
(OUT/'replay-harness.py').write_text(Path(__file__).read_text())
ctx=OUT/'evaluator-context';ctx.mkdir()
def capture(record):
 p=ctx/(record.record_id+'.json');p.write_text(json.dumps(asdict(record),ensure_ascii=False,indent=2,default=str));return str(p)
context_store.save_context=capture
runtime=AxisRuntime(spec,'expectations-B-low',trace.trace_id,trace.normalized_request['capability_ref'],trace.case_id)
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
save('requirements.json',project_requirements(trace,_scenario_entry(runtime)))
save('manifest.json',{'trace_sha256':hashlib.sha256(raw).hexdigest(),'reasoning_effort':'low','six_axis_seconds':1200,'six_axis_tool_calls':40,
 'baseline':'report/process-axes-protocol-20261006/B-r3-low/result.json','scope':'B only; frozen trace, no business execution',
 'extra_stages':['expectations (max 2 calls)','process projection (max 2 calls)'], 'started_at':time.time()})
print('Replay started; B only',flush=True)
started=time.monotonic()
report=build_report(spec,trace,run_id='expectations-B-low')
save('result.json',{'report':report,'elapsed_seconds':time.monotonic()-started})
for row in report['results']:
 if row['type_id']=='expectations' and row.get('output'):save('expectations.json',row['output'])
print(json.dumps({r['type_id']:{'status':r['status'],'verdict':r.get('verdict'),'error':r.get('error'),'usage':r.get('usage')} for r in report['results']},ensure_ascii=False),flush=True)
