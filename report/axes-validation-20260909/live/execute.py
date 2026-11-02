import importlib.util,json,sys,time
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
kind=sys.argv[1]
path=root/'tmp/eval_axes_live'/('clause_qa.py' if kind=='clause' else 'run.py')
spec=importlib.util.spec_from_file_location('probe',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.OUT=root/'report/axes-validation-20260909/live'/kind;m.OUT.mkdir(parents=True,exist_ok=True)
results=[]
for case in (m.CASES if kind=='clause' else m.LIVE_IDS):
 try: results.append(m.run_case(case) if kind=='clause' else m.run_live(case))
 except Exception as e: results.append({'case':case,'error':repr(e)});print(repr(e),flush=True)
 (m.OUT/'summary.json').write_text(json.dumps({'cases':results},ensure_ascii=False,indent=2))
