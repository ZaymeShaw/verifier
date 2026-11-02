import json,sys,time,uuid,requests
H='/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009'
sys.path.insert(0,H); sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import experiment_io as io
io.init_secret_guard()
from llm_transport import Transport
t=Transport('primary','gemini-3.8-flash-medium',arm='probe-cache',tag='probe')
M=json.load(open(io.HERE/'frozen/case_main-D01-same-surname-clarify.json'))['axes']['context_memory'][0]['user'][:60000]
S=f"[probe:{uuid.uuid4().hex}]\n你是评测助手，只回答 OK。"
def post(msgs):
    body={'model':t.model,'messages':msgs,'temperature':0,'stream':True,'stream_options':{'include_usage':True},'reasoning_effort':'low'}
    usage={}
    with requests.post(t.url,headers=t.auth,json=body,stream=True,timeout=(300,900)) as r:
        if r.status_code!=200: return None
        for line in r.iter_lines():
            x=line.decode()
            if x.startswith('data:') and x!='data: [DONE]':
                it=json.loads(x[5:]); 
                if it.get('usage'): usage=it['usage']
    return usage.get('prompt_tokens',0),(usage.get('prompt_tokens_details') or {}).get('cached_tokens',0)
# 同一前缀，12 个不同尾部，依次发
res=[]
for i in range(12):
    u=post([{'role':'system','content':S},{'role':'user','content':M+f'\n\n只回复 OK。尾部编号 {i}'}])
    res.append(u); print(i,u,flush=True)
hits=[i for i,u in enumerate(res) if u and u[1]>0]
print('命中的请求序号',hits,'共',len(hits),'/ 12')
# 多轮扩展：第一轮 -> 第二轮=第一轮+assistant+追加，重复 6 次（每次新前缀）
ok=0
for j in range(6):
    s=f"[probe:{uuid.uuid4().hex}]\n你是评测助手，只回答 OK。"
    a=post([{'role':'system','content':s},{'role':'user','content':M+'\n只回复 OK。'}])
    b=post([{'role':'system','content':s},{'role':'user','content':M+'\n只回复 OK。'},{'role':'assistant','content':'OK'},{'role':'user','content':'再追加：只回复 OK。'}])
    print('多轮',j,a,b,flush=True); ok+= 1 if b and b[1]>0 else 0
print('多轮扩展命中',ok,'/ 6')
