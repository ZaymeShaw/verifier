import json,time
from pathlib import Path
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace,to_dict
from impl.projects.llm_probe import eval_axes as pkg
from impl.projects.llm_probe.eval_axes import validate as vm
out=Path('report/axes-validation-20260909/fixed');d=json.loads((out/'fixed-kn-wrong.json').read_text());p=d['overlay'];p['axes']=[a for a in p['axes'] if a['type']=='fulfillment']
pkg.load_capability_map=vm.load_capability_map=lambda _: {'fixed_probe':p}
c=d['case'];t=RunTrace(trace_id='fixed-kn-wrong-no-truth',project_id='llm_probe',case_id='fixed-kn-wrong-no-truth',normalized_request={'capability_ref':'fixed_probe','body':{'user_text':c['question']}},extracted_output={'output_text':c['answer']})
s=time.monotonic();r=pkg.build_report(load_project('llm_probe'),t,run_id=t.trace_id)
(out/'control-no-truth.json').write_text(json.dumps({'case':c,'provenance':d['provenance'],'trace':to_dict(t),'overlay':p,'eval_axes':r,'elapsed_s':round(time.monotonic()-s,1)},ensure_ascii=False,indent=2,default=str))
print([(a['type_id'],a['status'],a['verdict'],a['usage']) for a in r['results']])
