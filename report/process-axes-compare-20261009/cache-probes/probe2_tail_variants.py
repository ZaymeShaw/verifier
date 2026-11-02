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

sysE=sys_('E')
def mk(q,extra=''): return [{'role':'system','content':sysE},{'role':'user','content':M+extra+'\n\n只回复 OK。'+q}]
post(mk('Q1'),'E1 冷启动')
post(mk('Q1'),'E2 完全相同重发')
post(mk('Q2'),'E3 仅尾部不同(Q2)')
post(mk('Q2'),'E4 E3 重发')
post(mk('Q1'),'E5 回到 Q1')
post(mk('Q3 稍长一点的不同尾部，多写几个字'),'E6 尾部不同且更长')
# 短尾部差异放在 system 末尾 vs 放在 user 开头
sysF=sys_('F')
mk2=lambda q:[{'role':'system','content':sysF},{'role':'user','content':q+'\n'+M}]
post(mk2('先说明任务一'),'F1 冷启动(差异在user开头)')
post(mk2('先说明任务二'),'F2 仅user开头不同')
