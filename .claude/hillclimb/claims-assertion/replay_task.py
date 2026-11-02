"""从一次"看到某任务"的模型调用记录取前缀（system、开场、任务消息），把该轴的说明与提交格式从旧定义换成新定义，重发 N 次收提交。
用法：replay_task.py <env> <record.json> <old_defs.json> <new_defs.json> <axis> <old|new> <reps> <out_dir>。不打印密钥。"""
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

env_file, record, old_defs, new_defs, axis, variant, reps, out_dir = sys.argv[1:]
reps, out_dir = int(reps), pathlib.Path(out_dir)
env = dict(l.split("=", 1) for l in open(env_file, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
BASE, MODEL, KEY = env["LLM_BASE_URL"].rstrip("/"), env["LLM_MODEL"], env["DEEPSEEK_API_KEY"]
TOOLS = [{"type": "function", "function": {"name": "submit", "parameters": {"type": "object", "properties": {
    "task_id": {"type": "string"}, "item_id": {"type": "string"}, "payload": {"type": "object"}}}}}]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def model_schema(axis_def):
    """提交格式里给模型看的那部分：去掉程序填的字段（与任务消息里的写法一致：sort_keys）。"""
    out = json.loads(json.dumps(axis_def["output"]))
    props = out["properties"]
    for k in [k for k, v in props.items() if isinstance(v, dict) and v.get("x-fill") == "program"]:
        props.pop(k)
        out["required"] = [r for r in out["required"] if r != k]
    return out


def prefix():
    msgs = json.load(open(record, encoding="utf-8"))["messages"]
    head = []
    for m in msgs:
        head.append({"role": m["role"], "content": m.get("content") or ""})
        if f"【任务 {axis}" in (m.get("content") or ""):
            break
    if variant == "new":
        o, n = json.load(open(old_defs, encoding="utf-8"))["axes"][axis], json.load(open(new_defs, encoding="utf-8"))["axes"][axis]
        t = head[-1]["content"]
        assert t.count(o["instruction"]) == 1, "旧说明对不上"
        t = t.replace(o["instruction"], n["instruction"])
        so, sn = (json.dumps(model_schema(x)["properties"]["claims"]["items"], ensure_ascii=False, sort_keys=True) for x in (o, n))
        assert t.count(so) == 1, "旧格式对不上"
        head[-1]["content"] = t.replace(so, sn)
    return head


def call(msgs):
    body = json.dumps({"model": MODEL, "messages": msgs, "tools": TOOLS}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", body, {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    for _ in range(8):
        try:
            return json.load(op.open(req, timeout=600))
        except urllib.error.HTTPError as e:
            msg = e.read()[:200].decode(errors="ignore")
            if e.code in (429, 500, 502, 503) or (e.code == 400 and "location" in msg):
                time.sleep(10 + random.random() * 10)
                continue
            raise RuntimeError(f"{e.code} {msg}")
    raise RuntimeError("retries exhausted")


def job(rep):
    msgs, got = prefix(), None
    for _ in range(4):
        m = call(msgs)["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": tcs} if tcs else {"role": "assistant", "content": m.get("content") or ""})
        if not tcs:
            msgs.append({"role": "user", "content": f"本次重放只做 {axis}：请直接交。"})
            continue
        for tc in tcs:
            a = json.loads(tc["function"].get("arguments") or "{}")
            if a.get("task_id") == axis and "claims" in (a.get("payload") or {}):
                got = a["payload"]["claims"]
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps({"accepted": True} if got is not None else {"error": f"本次重放只做 {axis}"}, ensure_ascii=False)})
        if got is not None:
            break
    with open(out_dir / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"rep": rep, "variant": variant, "claims": got}, ensure_ascii=False) + "\n")
    return f"rep{rep}: {len(got) if got is not None else 'NO-CLAIMS'}"


out_dir.mkdir(parents=True, exist_ok=True)
prefix()
with ThreadPoolExecutor(3) as ex:
    for line in ex.map(job, range(reps)):
        print(line, flush=True)
