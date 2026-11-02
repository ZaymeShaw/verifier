import json, time, traceback
from pathlib import Path
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace,to_dict
from impl.projects.llm_probe import eval_axes as pkg
from impl.projects.llm_probe.eval_axes import validate as vm
OUT=Path('report/axes-validation-20260909/fixed')
CASES=[
{'id':'fixed-kn-correct','question':'康宁终身险的犹豫期是几天？','answer':'康宁终身险的犹豫期为二十日。','expect':['verified']},
{'id':'fixed-kn-wrong','question':'康宁终身险的犹豫期是几天？','answer':'康宁终身险的犹豫期为十五日。','expect':['refuted']},
{'id':'fixed-opinion','question':'你喜欢什么样的回答？','answer':'我更喜欢简洁的回答。','expect':[]},
{'id':'fixed-mixed','question':'安心医疗险的等待期、年度免赔额、经社保结算的给付比例分别是多少？','answer':'安心医疗险的等待期为三十日，年度免赔额为两万元，经社保结算按百分之一百给付。','expect':['verified','refuted','verified']},
]
PRESET={'capability':'依据保险条款回答用户的问题，给出条款事实。','axes':[{'type':'truthfulness','enabled':True,'description':'核验回答里的产品条款事实。知识源：{es://clause_kb} 保险产品条款原文。'},{'type':'fulfillment','enabled':True,'description':'回答用户询问的保险条款事项，包括用户询问的期限、金额或比例。'}]}
pkg.load_capability_map=vm.load_capability_map=lambda _: {'fixed_probe':PRESET}
summary=[]
for c in CASES:
 print('START',c['id'],flush=True); t=time.monotonic()
 trace=RunTrace(trace_id=c['id'],project_id='llm_probe',case_id=c['id'],normalized_request={'capability_ref':'fixed_probe','body':{'user_text':c['question']}},extracted_output={'output_text':c['answer']})
 data={'case':c,'provenance':{'kind':'synthetic_fixed_answer','business_live_called':False,'judge_and_es_real':True},'trace':to_dict(trace),'overlay':PRESET}
 try:
  report=pkg.build_report(load_project('llm_probe'),trace,run_id=c['id']);data['eval_axes']=report
  row={'case_id':c['id'],'elapsed_s':round(time.monotonic()-t,1),'axes':[{'type':r['type_id'],'status':r['status'],'output':r.get('output'),'usage':r.get('usage')} for r in report['results']]}
 except Exception as e:
  data['error']=traceback.format_exc();row={'case_id':c['id'],'error':str(e)}
 data['elapsed_s']=round(time.monotonic()-t,1)
 (OUT/(c['id']+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str))
 summary.append(row);(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
 print('DONE',c['id'],data['elapsed_s'],[(x['type'],x['status']) for x in row.get('axes',[])],flush=True)
