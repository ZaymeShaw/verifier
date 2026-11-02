"""Descriptive results only; target correctness needs explicit adjudication."""
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
gold={r['case_id']:r for r in json.loads((OUT/'private-gold.json').read_text())}
rows=[]
for directory in sorted((OUT/'runs').iterdir()):
    meta=json.loads((directory/'meta.json').read_text())
    if 'exit_code' not in meta:continue
    messages=json.loads((directory/'messages.json').read_text())
    row={k:meta.get(k) for k in ('label','dataset','exit_code','elapsed_s','review_valid','scope_valid')}
    row['models']=sorted({m['model'] for m in messages if m.get('model')})
    row['errors']=[m['errorMessage'] for m in messages if m.get('errorMessage')]
    row['usage_totals']={k:sum((m.get('usage') or {}).get(k,0) or 0 for m in messages) for k in ('input','output','cacheRead','cacheWrite','totalTokens')}
    row['tool_calls']=len(json.loads((directory/'tool-calls.json').read_text()))
    if meta.get('review_valid'):
        review=json.loads((directory/'review.json').read_text())
        row['case_coverage']=sorted(review.get('cases',{}))
        row['findings']=[{k:f.get(k) for k in ('id','case_id','severity','what','why','quote')} for f in review['findings']]
        if meta['dataset']=='controlled':
            row['per_case']=[{'case_id':cid,'family':g['family'],'variant':g['variant'],
                             'findings':[{k:f.get(k) for k in ('id','severity','what')} for f in review['findings'] if f['case_id']==cid]} for cid,g in gold.items()]
    rows.append(row)
(OUT/'run-summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
for row in rows:
    print({k:row.get(k) for k in ('label','elapsed_s','review_valid','tool_calls','models')})
    for c in row.get('per_case',[]):print(c)
