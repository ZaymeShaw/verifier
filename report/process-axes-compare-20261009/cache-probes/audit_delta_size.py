import json,sys
H='/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009'
sys.path.insert(0,H); sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import experiment_io as io, new_arm as N
from cmp_view import normalize
c1t=c2t=dt=0; per={}
for tag in io.CASES:
    frozen,dossier,analysis=N.build_case(tag)
    suspects=list(analysis['structure'].get('suspects') or [])
    for axis in io.AXES:
        extra=list((analysis.get('selections',{}).get(axis) or {}).get('refs') or [])
        for entry in frozen['axes'][axis]:
            body=entry['body']; links=(body.get('links') or {}).get('links') or []
            c1=N.input_only_view(dossier,links); c2=N.full_view(dossier,links,suspects,extra)
            a={ (r['id'],f):json.dumps(i.get('value'),ensure_ascii=False) for r in normalize(c1) for f,i in r['fields'].items()}
            b={ (r['id'],f):json.dumps(i.get('value'),ensure_ascii=False) for r in normalize(c2) for f,i in r['fields'].items()}
            delta=sum(len(v) for k,v in b.items() if a.get(k)!=v)   # 第二次真正新增/不同的字段
            l1=sum(map(len,a.values())); l2=sum(map(len,b.values()))
            c1t+=l1;c2t+=l2;dt+=delta
            p=per.setdefault(axis,[0,0,0]); p[0]+=l1;p[1]+=l2;p[2]+=delta
print(f"总字符  第一次材料 {c1t}  第二次材料 {c2t}  第二次比第一次多出来的字段 {dt}  ({dt/c2t:.0%} of 第二次)")
for k,v in per.items(): print(f"  {k:22s} c1 {v[0]:8d} c2 {v[1]:8d} 增量 {v[2]:8d} ({v[2]/v[1]:.0%})")
