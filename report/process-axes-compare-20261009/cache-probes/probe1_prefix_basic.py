import json,sys,time,uuid,glob,requests
sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009')
sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import experiment_io as io
io.init_secret_guard()
from llm_transport import Transport
t=Transport('primary','gemini-3.8-flash-medium',arm='probe-cache',tag='probe')
H=io.HERE
sysf=sorted(glob.glob(str(H/'runs/new3/prompt/pass1/*actual_context_memory_b1__system.txt')))[0]
S=open(sysf).read()
fr=json.load(open(H/'frozen/case_main-D01-same-surname-clarify.json'))
M=fr['axes']['context_memory'][0]['user']
def post(messages,label):
    body={'model':t.model,'messages':messages,'temperature':0,'stream':True,'stream_options':{'include_usage':True},'reasoning_effort':'low'}
    usage={};n=0;t0=time.time()
    with requests.post(t.url,headers=t.auth,json=body,stream=True,timeout=(300,900)) as r:
        if r.status_code!=200: print(label,'HTTP',r.status_code,r.text[:200]);return
        for line in r.iter_lines():
            x=line.decode()
            if x.startswith('data:') and x!='data: [DONE]':
                it=json.loads(x[5:]); 
                if it.get('usage'): usage=it['usage']
    p=usage.get('prompt_tokens',0); c=(usage.get('prompt_tokens_details') or {}).get('cached_tokens',0)
    print(f"{label:46s} 输入{p:6d} 命中{c:6d} ({c/max(p,1):4.0%}) {time.time()-t0:5.1f}s")
def sys_(tag): return f"[probe:{tag}:{uuid.uuid4().hex}]\n"+S
print('system chars',len(S),'material chars',len(M))
# A: 只有 system 相同，user 不同
sa=sys_('A'); 
post([{'role':'system','content':sa},{'role':'user','content':'只回复 OK。1'}],'A1 冷启动 system+短user')
post([{'role':'system','content':sa},{'role':'user','content':'只回复 OK。2 另一个问题'}],'A2 同 system、不同短user')
# B: system+长材料 相同，尾部不同
sb=sys_('B')
post([{'role':'system','content':sb},{'role':'user','content':M+'\n\n只回复 OK。Q1'}],'B1 冷启动 system+长材料')
post([{'role':'system','content':sb},{'role':'user','content':M+'\n\n只回复 OK。Q2 不同尾部'}],'B2 同前缀、不同尾部')
post([{'role':'system','content':sb},{'role':'user','content':'改动开头。'+M+'\n\n只回复 OK。Q1'}],'B3 材料开头改了几个字')
# C: 多轮：第一轮 [system, user M]，第二轮 [system, user M, assistant, user 追加]
sc=sys_('C')
post([{'role':'system','content':sc},{'role':'user','content':M[:len(M)//2]+'\n只回复 OK。'}],'C1 冷启动 第一轮(材料前半)')
post([{'role':'system','content':sc},{'role':'user','content':M[:len(M)//2]+'\n只回复 OK。'},{'role':'assistant','content':'OK'},{'role':'user','content':M[len(M)//2:]+'\n只回复 OK。'}],'C2 第二轮=第一轮+assistant+追加材料')
# D: 紧接着重复 C2 全文
post([{'role':'system','content':sc},{'role':'user','content':M[:len(M)//2]+'\n只回复 OK。'},{'role':'assistant','content':'OK'},{'role':'user','content':M[len(M)//2:]+'\n只回复 OK。'}],'D 完全相同请求再发一次')
