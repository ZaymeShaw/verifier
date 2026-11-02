import json,sys,re
H='/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009'
sys.path.insert(0,H); sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import new_arm as N
for tag,axis in [('main-D01-same-surname-clarify','planning_routing'),('main-B01-meeting-prep-fuyunping','planning_routing'),('main-B01-meeting-prep-fuyunping','context_memory')]:
    frozen,dossier,analysis=N.build_case(tag)
    body=frozen['axes'][axis][0]['body']; links=(body.get('links') or {}).get('links') or []
    c2=N.full_view(dossier,links,list(analysis['structure'].get('suspects') or []),list((analysis.get('selections',{}).get(axis) or {}).get('refs') or []))
    user=N.actual_prompt(axis,body,c2,{'expected':[]},links,[])
    print(tag[:20],axis,'user chars',len(user),'material 顶层键',list(c2)[:8], 'shared_contents' in c2 and len(c2['shared_contents']))
    # 在 user 文本里找重复出现的长片段：取 300 字窗口，统计出现>1 次的窗口占比
    step=300; wins={}
    for i in range(0,len(user)-step,step//2):
        w=user[i:i+step]; wins.setdefault(w,[]).append(i)
    dup=sum(1 for v in wins.values() if len(v)>1); print('   重复的300字窗口 ',dup,'/',len(wins))
    # 更准确：统计 user 中每个 >=200 字的 JSON 字符串字面量重复次数
    lits=re.findall(r'"((?:[^"\\\\]|\\\\.){200,})"',user)
    from collections import Counter
    cnt=Counter(lits); extra=sum(len(s)*(n-1) for s,n in cnt.items() if n>1)
    print('   长字符串字面量',len(lits),'去重后',len(cnt),'重复多占',extra,'字符 =',f'{extra/len(user):.0%} of user')
