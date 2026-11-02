import json,sys,uuid,re,requests
H='/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009'
sys.path.insert(0,H); sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import experiment_io as io
io.init_secret_guard()
from llm_transport import Transport
t=Transport('primary','gemini-3.8-flash-medium',arm='probe-cache',tag='probe')
root=re.sub(r'/v1/?$','',t.url.rsplit('/chat/completions',1)[0])
M=json.load(open(io.HERE/'frozen/case_main-D01-same-surname-clarify.json'))['axes']['context_memory'][0]['user']
S=f"[probe:{uuid.uuid4().hex}]\n你是评测助手，只回答 OK。"
def post(q,label,model='gemini-3.8-flash-medium'):
    body={'systemInstruction':{'parts':[{'text':S}]},'contents':[{'role':'user','parts':[{'text':M+'\n\n'+q}]}],'generationConfig':{'temperature':0}}
    r=requests.post(f"{root}/v1beta/models/{model}:generateContent",headers=t.auth,json=body,timeout=600)
    if r.status_code!=200: print(label,'HTTP',r.status_code,r.text[:200]);return
    u=r.json().get('usageMetadata') or {}
    p=u.get('promptTokenCount',0);c=u.get('cachedContentTokenCount',0)
    print(f"原生接口 {label:10s} 输入{p:6d} 命中{c:6d} ({c/max(p,1):4.0%})  keys={sorted(u)[:6]}")
post('Q1 只回复OK','冷启动'); post('Q1 只回复OK','完全相同'); post('Q2 只回复OK 另一个尾部','仅尾部不同'); post('Q3 再一个不同尾部','仅尾部不同2')
