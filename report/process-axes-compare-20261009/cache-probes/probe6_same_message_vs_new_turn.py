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

ok1=ok2=0
for j in range(6):
    s=f"[probe:{uuid.uuid4().hex}]\n你是评测助手，只回答 OK。"
    a=post([{'role':'system','content':s},{'role':'user','content':M+'\n只回复 OK。'}])
    b=post([{'role':'system','content':s},{'role':'user','content':M+'\n只回复 OK。'+'\n\n追加说明：仍然只回复 OK。'}])  # 拼进同一条 user
    c=post([{'role':'system','content':s},{'role':'user','content':M+'\n只回复 OK。'},{'role':'assistant','content':'OK'},{'role':'user','content':'追加说明：仍然只回复 OK。'}])  # 新一轮
    print('拼进同一条user',b,' | 新一轮追加',c,flush=True); ok1+=1 if b and b[1]>0 else 0; ok2+=1 if c and c[1]>0 else 0
print('拼进同一条user 命中',ok1,'/6 ; 新一轮追加 命中',ok2,'/6')
