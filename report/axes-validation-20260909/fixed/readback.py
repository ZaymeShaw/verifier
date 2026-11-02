import json
from pathlib import Path
from impl.projects.llm_probe.eval_axes.sources.es_tools import EsTools
from impl.projects.llm_probe.material_tools import quote_in_text
out=Path('report/axes-validation-20260909/fixed'); receipts=[]
tools=EsTools([{'source':'es','uri':'es://clause_kb'}],receipts)
rows=[]
for p in sorted(out.glob('fixed-*.json')):
 d=json.loads(p.read_text()); answer=d['case']['answer']
 for ax in d.get('eval_axes',{}).get('results',[]):
  if ax['type_id']!='truthfulness':continue
  for c in (ax.get('output') or {}).get('claims',[]):
   row={'case':d['case']['id'],'claim':c,'exact_in_answer':c['text'] in answer,'citations':[]}
   for cit in c['citations']:
    r=tools.es_read(cit['source'][5:],cit['ref']);doc=tools.es_read(cit['source'][5:],cit['ref'].split('#')[0])
    row['citations'].append({'citation':cit,'readback':r,'whole_doc':doc,'quote_matches':quote_in_text(cit['note'],r.get('text',''))})
   rows.append(row)
(out/'readback.json').write_text(json.dumps({'rows':rows,'receipts':receipts},ensure_ascii=False,indent=2))
print('claims',len(rows),'citations',sum(len(r['citations']) for r in rows))
from impl.core.context_store import _record_paths_for_trace
import shutil
for case_id in ['fixed-kn-correct','fixed-kn-wrong','fixed-opinion','fixed-mixed','fixed-cashvalue-context','fixed-kn-wrong-no-truth']:
 paths=_record_paths_for_trace('llm_probe',case_id)
 target=out/'contexts'/case_id;target.mkdir(parents=True,exist_ok=True)
 for p in paths:shutil.copy2(p,target/p.name)
 print(case_id,'contexts',len(paths))
