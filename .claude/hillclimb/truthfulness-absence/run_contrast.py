"""B02 对照组：重放真实轴判定这一步，只判"购买"那一条。
用法：run_contrast.py <env_file> <variants_dir> <reps> <out_dir>
每个变体 × reps 次；判官的 submit 一律回"已收下"（不做验收打回），想再取证则回"本次只判定，不再取证"，最多 4 轮。
结果写 <out_dir>/results.jsonl（逐次落盘、按 (case, rep) 续跑）、traces/、errors.jsonl。不打印密钥。"""
import json
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

env_file, vdir, reps, out_dir = sys.argv[1], pathlib.Path(sys.argv[2]), int(sys.argv[3]), pathlib.Path(sys.argv[4])
env = dict(l.split("=", 1) for l in open(env_file, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
BASE, MODEL, KEY = env["LLM_BASE_URL"].rstrip("/"), env["LLM_MODEL"], env["DEEPSEEK_API_KEY"]
GOLD = {"V0": "unverifiable", "V1": "refuted", "V2": "unverifiable", "V3": "verified"}
TARGET = re.compile(r"余昕雅(已购买|购买了)平安安佑福")
FULLSET = "去重为 2 张保单"
CEILING_S = 900


def tool(name, props):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {"type": t} for p, t in props.items()}}}}


TOOLS = [tool("submit", {"task_id": "string", "item_id": "string", "payload": "object"}),
         tool("search_knowledge", {"items": "array"}), tool("read_material", {"name": "string"})]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "traces").mkdir(exist_ok=True)
results = out_dir / "results.jsonl"
done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results.read_text().splitlines())} if results.exists() else set()


def call(msgs):
    body = json.dumps({"model": MODEL, "messages": msgs, "tools": TOOLS}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", body, {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    for attempt in range(8):
        try:
            return json.load(op.open(req, timeout=300)), attempt
        except urllib.error.HTTPError as e:
            msg = e.read()[:200].decode(errors="ignore")
            if e.code in (400, 429, 500, 502, 503) and ("location" in msg or e.code != 400):
                time.sleep(10 + random.random() * 10)
                continue
            raise RuntimeError(f"{e.code} {msg}")
    raise RuntimeError("retries exhausted")


def target_id(msgs):
    for m in msgs:
        for c in re.findall(r'\{[^{}]*"claim_id"[^{}]*\}', str(m.get("content", ""))):
            try:
                c = json.loads(c)
            except json.JSONDecodeError:
                continue
            if TARGET.search(c.get("claim") or c.get("text") or ""):
                return c["claim_id"]
    raise ValueError("target claim not found")


def run(case, rep):
    variant = case.stem.split("_")[1]
    msgs = json.load(open(case, encoding="utf-8"))
    tid = target_id(msgs)
    t0, usage, retries, extra_search, payload = time.time(), [], 0, 0, None
    for _ in range(4):
        r, a = call(msgs)
        retries += a
        usage.append(r.get("usage"))
        m = r["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": tcs} if tcs else {"role": "assistant", "content": m.get("content")})
        if not tcs:
            break
        for tc in tcs:
            a = json.loads(tc["function"]["arguments"] or "{}")
            if tc["function"]["name"] == "submit":
                if a.get("item_id") == tid:
                    payload = a.get("payload") or {}
                res = {"accepted": True}
            else:
                extra_search += 1
                res = {"error": "本次只判定，不再取证；请依据已有结果判定"}
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, ensure_ascii=False)})
        if payload is not None or time.time() - t0 > CEILING_S:
            break
    verdict = (payload or {}).get("verdict")
    basis = " ".join(b.get("quote", "") for b in (payload or {}).get("basis") or [])
    grade = {"verdict_ok": float(verdict == GOLD[variant]),
             "fullset_cited": float(FULLSET in basis) if GOLD[variant] == "refuted" else None}
    row = {"prompt_id": case.stem, "rep": rep, "tags": [variant, case.stem.split("_")[0]], "status": "ok" if payload else "no_judgment",
           "gold": GOLD[variant], "verdict": verdict, "reason": (payload or {}).get("reason"), "basis": basis[:600], "grade": grade,
           "extra_search": extra_search, "retries": retries, "latency_s": round(time.time() - t0, 1), "model": MODEL, "usage": usage}
    json.dump([{"role": x["role"], "content": x.get("content") if x.get("content") is not None else json.dumps(x.get("tool_calls"), ensure_ascii=False)} for x in msgs],
              open(out_dir / "traces" / f"{case.stem}_rep{rep}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return row


def job(arg):
    case, rep = arg
    try:
        row = run(case, rep)
        with open(results, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return f"{case.stem} rep{rep}: {row['verdict']} (gold {row['gold']}) fullset={row['grade']['fullset_cited']}"
    except Exception as e:  # noqa: BLE001
        with open(out_dir / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"prompt_id": case.stem, "rep": rep, "class": "harness", "error": str(e)[:300]}, ensure_ascii=False) + "\n")
        return f"{case.stem} rep{rep}: ERROR {str(e)[:100]}"


todo = [(c, k) for c in sorted(vdir.glob("*.json")) for k in range(reps) if (c.stem, k) not in done]
with ThreadPoolExecutor(3) as ex:
    for line in ex.map(job, todo):
        print(line, flush=True)
