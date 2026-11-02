"""Run the installed pi harness in a fresh evidence-only working directory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

OUT=Path(__file__).resolve().parent


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def decode_json(text):
    decoder=json.JSONDecoder()
    for start,ch in enumerate(text):
        if ch!='{':continue
        try:obj,_=decoder.raw_decode(text[start:])
        except ValueError:continue
        if isinstance(obj,dict) and {'spawn_id','cases','findings'}.issubset(obj):return obj
    return None


def run(label, model=None, provider_adapter=False, agent_dir=None):
    dataset='historical' if label.startswith('historical') else 'controlled'
    dest=OUT/'runs'/label
    dest.mkdir(parents=True,exist_ok=False)
    work=Path(tempfile.mkdtemp(prefix='verifier-review-'))
    shutil.copytree(OUT/'corpus'/dataset, work/'evidence')
    shutil.copyfile(OUT/'reviewer-system.txt',work/'system.txt')
    sid=uuid.uuid4().hex
    if dataset=='controlled':
        task=f'''spawn_id: {sid}
这是一个有限范围的独立审阅任务。请只读当前目录 evidence/ 中的12个case文件，对每个case提供的请求与响应审阅。每个文件是独立case。
这些是边界明确的微型审阅材料，不要求补成整个verifier输出协议，不因未提供完整业务案卷而自动判错。
逐个阅读并按角色清单判断；不得预设有问题或没有问题，不知道正负样本比例。不要对case之间作配对推断。
只能读取当前任务目录，不得搜索其他目录、仓库或历史报告。不能写文件或调用其他代理。
最终输出角色要求的JSON。'''
    else:
        task=f'''spawn_id: {sid}
这是一个有限范围的历史原文审阅。evidence/ledger.json 给出5次真实网关调用，evidence/axis-status.json 给出相关case的轴终态。
所有5个 evidence/<call_id>.txt 都是必读原文，需核对请求与响应、相邻调用的材料及任务差异。它们未经删节。
本任务只提供这些调用，不提供完整业务案卷解引用，不要求猜测未提供的调用或源码。每条finding只落在一个case和一个call/axis。
大文件含很长的单行，read/grep输出可能被截断；可用只读python按字符块提取并阅读，明确不能确认的内容。
请按角色清单审阅实际上下文和输出，不得搜索其他目录、历史诊断、源码或参考答案。不要写文件或调用其他代理。
硬性事实仅供定位：axis-status.json。最终输出角色要求的JSON。'''
    (work/'task.txt').write_text(task)
    argv=['pi','-p','--mode','json','--no-session','--no-skills','--no-context-files',
          '--no-prompt-templates','--no-extensions','--tools','read,bash,grep,find,ls',
          '--append-system-prompt',str(work/'system.txt'),task]
    if model:
        argv[1:1]=['--model',model]
    adapter=Path('/Users/xiaozijian/.pi/agent/extensions/anyrouter-claude-code.ts')
    if provider_adapter:
        argv[1:1]=['-e',str(adapter)]
    before=hashes(work)
    meta={'label':label,'dataset':dataset,'spawn_id':sid,'command':argv,'cwd':str(work),
          'started_at':datetime.now(timezone.utc).isoformat(),
          'isolation':'fresh cwd, no conversation, no context files/skills/extensions; same installed pi default provider/model; no OS sandbox',
          'input_hashes':before}
    if provider_adapter:
        meta['provider_adapter']={'path':str(adapter),'sha256':hashlib.sha256(adapter.read_bytes()).hexdigest()}
    env=os.environ.copy()
    if agent_dir:
        env['PI_CODING_AGENT_DIR']=str(agent_dir)
        meta['isolated_agent_dir']=str(agent_dir)
    (dest/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    start=time.monotonic()
    with (dest/'stdout.jsonl').open('w') as stdout,(dest/'stderr.txt').open('w') as stderr:
        proc=subprocess.Popen(argv,cwd=work,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        meta['reviewer_pid']=proc.pid
        meta['runner_pid']=os.getpid()
        (dest/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
        try:code=proc.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            code=-1
    meta.update(exit_code=code,elapsed_s=round(time.monotonic()-start,2),ended_at=datetime.now(timezone.utc).isoformat(),scope_valid=before==hashes(work))
    texts=[];messages=[];reads=[]
    for line in (dest/'stdout.jsonl').read_text().splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get('type')=='message_end' and event.get('message',{}).get('role')=='assistant':
            m=event['message'];messages.append({k:m.get(k) for k in ('model','provider','usage','stopReason','errorMessage')})
            text=''.join(c.get('text','') for c in m.get('content',[]) if c.get('type')=='text')
            if text:texts.append(text)
        if event.get('type')=='tool_execution_start':reads.append({k:event.get(k) for k in ('toolName','args')})
    review=next((obj for text in reversed(texts) if (obj:=decode_json(text)) is not None),None)
    meta['review_valid']=review is not None and review.get('spawn_id')==sid
    if review is not None:
        (dest/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2))
        meta['review_sha256']=hashlib.sha256((dest/'review.json').read_bytes()).hexdigest()
    (dest/'messages.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2))
    (dest/'tool-calls.json').write_text(json.dumps(reads,ensure_ascii=False,indent=2))
    (dest/'final.txt').write_text(texts[-1] if texts else '')
    (dest/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    print(json.dumps({k:meta[k] for k in ('label','exit_code','elapsed_s','scope_valid','review_valid')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--provider-adapter',action='store_true');p.add_argument('--agent-dir');p.add_argument('labels',nargs='+');args=p.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda label:run(label,args.model,args.provider_adapter,args.agent_dir),args.labels))
