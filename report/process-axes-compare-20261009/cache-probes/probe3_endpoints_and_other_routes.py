import json,sys,time,uuid,glob,requests
H='/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-compare-20261009'
sys.path.insert(0,H); sys.path.insert(0,'/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
import experiment_io as io
io.init_secret_guard()
from llm_transport import Transport
import re
# 1) 原生 Gemini / 显式缓存端点是否存在（只看状态码）
t=Transport('primary','gemini-3.8-flash-medium',arm='probe-cache',tag='probe')
root=re.sub(r'/v1/?$','',t.url.rsplit('/chat/completions',1)[0])
for path,method in [('/v1/models','GET'),('/v1beta/models','GET'),('/v1beta/cachedContents','GET'),('/v1/responses','OPTIONS')]:
    try:
        r=requests.request(method,root+path,headers=t.auth,timeout=20); print(f'{method} {path:26s} -> {r.status_code} {r.text[:80]!r}')
    except Exception as e: print(path,'ERR',type(e).__name__)
# 2) 其他线路的前缀缓存行为
fr=json.load(open(io.HERE/'frozen/case_main-D01-same-surname-clarify.json'))
M=fr['axes']['context_memory'][0]['user']
def run(provider,model):
    tt=Transport(provider,model,arm='probe-cache',tag='probe')
    S=f"[probe:{uuid.uuid4().hex}]\n你是评测助手，只回答 OK。"
    def post(q,label):
        body={'model':model,'messages':[{'role':'system','content':S},{'role':'user','content':M+'\n\n'+q}],'temperature':0,'stream':True,'stream_options':{'include_usage':True}}
        usage={}
        try:
            with requests.post(tt.url,headers=tt.auth,json=body,stream=True,timeout=(60,600)) as r:
                if r.status_code!=200: print(provider,model,label,'HTTP',r.status_code,r.text[:100]);return
                for line in r.iter_lines():
                    x=line.decode()
                    if x.startswith('data:') and x!='data: [DONE]':
                        it=json.loads(x[5:])
                        if it.get('usage'): usage=it['usage']
        except Exception as e: print(provider,model,label,'ERR',type(e).__name__);return
        p=usage.get('prompt_tokens',0); d=usage.get('prompt_tokens_details') or {}
        c=d.get('cached_tokens',0) or usage.get('prompt_cache_hit_tokens',0) or 0
        print(f"{provider}/{model:24s} {label:14s} 输入{p:6d} 命中{c:6d} ({c/max(p,1):4.0%})")
    post('Q1 只回复OK','冷启动'); post('Q1 只回复OK','完全相同'); post('Q2 只回复OK 另一个尾部','仅尾部不同')
for prov,model in [('fallback1','qwen3.8-flash'),('fallback2','deepseek-flash')]:
    try: run(prov,model)
    except Exception as e: print(prov,'ERR',type(e).__name__,str(e)[:100])
