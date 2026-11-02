"""说法抽取单步重放：取记录里 claims 提交之前模型看到的那段消息，原样（old）或换成新说明（new）重发 N 次，收说法清单。
用法：replay_claims.py <env_file> <survey.json> <old|new> <reps> <out_dir> <case_index...>
survey.json 每项 {dir, file, answer, claims}：file 是含 claims 提交的那份记录。不打印密钥。"""
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[3]
env_file, survey, variant, reps, out_dir, *idx = sys.argv[1:]
reps, out_dir = int(reps), pathlib.Path(out_dir)
env = dict(l.split("=", 1) for l in open(env_file, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
BASE, MODEL, KEY = env["LLM_BASE_URL"].rstrip("/"), env["LLM_MODEL"], env["DEEPSEEK_API_KEY"]

OLD1 = ("什么算一条说法：回答断言的、能单独为真或为假的一个主张——某对象的某一项是什么、有没有某项、满足什么条件。不限于带数字的：定性的断言（某产品含不含某项责任、某事项要不要某材料、某规定是否存在）也是说法。"
        "一句话里有几个这样的主张就是几条，每条 claim 只说自己那一个。回答断言某对象没有某项、或对象不存在，也是说法：claim 写成\"某对象没有某项\"或\"某对象不存在\"，核的是事实本身，不是回答者那次查到了什么。"
        "不是说法：没有断言的套话、建议、评价、客套；回答者只描述自己做了什么（查了几次、调了什么）；回答自己给内容编的序号、排列、指代。")
NEW1 = ("什么算一条说法：回答断言\"某件事是这样\"的一句话。一句话里断言了几件事就是几条，每条 claim 只说自己那一件。不管它关于什么、能不能核、重不重要都列：带不带数字、定性的、说某对象没有某项或不存在、说回答者自己做了什么，都是说法；"
        "是不是事实、核不核得了由后面判，这里不筛。回答断言某对象没有某项、或对象不存在时，claim 写成\"某对象没有某项\"或\"某对象不存在\"，核的是事实本身，不是回答者那次查到了什么。"
        "不是说法的只有不在断言任何事的话：提问、建议、客套，以及回答给内容编的序号、排列本身。")
OLD2 = "回答和用户问题里都找不到它所指对象的标识，这条才不抽。"
NEW2 = "回答和用户问题里都找不到它所指对象的标识，也照样列。"

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": p}}}
         for n, p in (("submit", {"task_id": {"type": "string"}, "item_id": {"type": "string"}, "payload": {"type": "object"}}),
                      ("search_knowledge", {"items": {"type": "array"}}), ("read_material", {"name": {"type": "string"}}))]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def prefix(record):
    """记录里 claims 提交那条 assistant 消息之前的全部消息（模型当时看到的）。"""
    msgs = json.load(open(ROOT / record, encoding="utf-8"))["messages"]
    for i, m in enumerate(msgs):
        for tc in m.get("tool_calls") or []:
            a = json.loads(tc["function"].get("arguments") or "{}")
            if tc["function"]["name"] == "submit" and a.get("task_id") == "claims" and "claims" in (a.get("payload") or {}):
                return msgs[:i]
    raise ValueError("no claims submit in " + record)


def clean(msgs):
    out = []
    for m in msgs:
        if m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content"), "tool_calls": m["tool_calls"]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    text = json.dumps(out, ensure_ascii=False)
    assert text.count(json.dumps(OLD1, ensure_ascii=False)[1:-1]) == 1 and text.count(OLD2) == 1, "说明原文对不上"
    if variant == "new":
        out = json.loads(text.replace(json.dumps(OLD1, ensure_ascii=False)[1:-1], json.dumps(NEW1, ensure_ascii=False)[1:-1]).replace(OLD2, NEW2))
    return out


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


def job(arg):
    k, row, rep = arg
    try:
        msgs, claims, other = clean(prefix(row["file"])), None, []
        for _ in range(4):  # 别的工具 / 别的任务一律回"只做 claims"，直到交出 claims
            m = call(msgs)["choices"][0]["message"]
            tcs = m.get("tool_calls") or []
            msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": tcs} if tcs else {"role": "assistant", "content": m.get("content") or ""})
            if not tcs:
                msgs.append({"role": "user", "content": "本次重放只做说法抽取：请直接交 claims。"})
                continue
            for tc in tcs:
                a = json.loads(tc["function"].get("arguments") or "{}")
                if a.get("task_id") == "claims" and "claims" in (a.get("payload") or {}):
                    claims = a["payload"]["claims"]
                    res_ = {"accepted": True}
                else:
                    other.append(tc["function"]["name"])
                    res_ = {"error": "本次重放只做说法抽取：请直接交 claims"}
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res_, ensure_ascii=False)})
            if claims is not None:
                break
        res = {"case": k, "dir": row["dir"], "rep": rep, "variant": variant, "claims": claims, "other_calls": other}
        with open(out_dir / "results.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        return f"case{k} rep{rep}: {len(claims) if claims is not None else 'NO-CLAIMS'}"
    except Exception as e:  # noqa: BLE001
        with open(out_dir / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"case": k, "rep": rep, "error": str(e)[:300]}, ensure_ascii=False) + "\n")
        return f"case{k} rep{rep}: ERROR {str(e)[:100]}"


rows = json.load(open(survey, encoding="utf-8"))
out_dir.mkdir(parents=True, exist_ok=True)
todo = [(int(k), rows[int(k)], r) for k in idx for r in range(reps)]
with ThreadPoolExecutor(3) as ex:
    for line in ex.map(job, todo):
        print(line, flush=True)
