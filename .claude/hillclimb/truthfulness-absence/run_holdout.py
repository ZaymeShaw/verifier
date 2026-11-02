"""留空集：原始记录原样重放真实轴判定，收齐每条说法的结论。用法：run_holdout.py <env> <points.json> <prompt_from.txt> <prompt_to.txt> <reps> <out_dir> <case_substr...>
prompt_from == prompt_to 即原样（P0）；否则把任务说明里的 from 整段换成 to。submit 一律回"已收下"，再取证回"本次只判定"，最多 6 轮。"""
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

env_file, points_path, p_from, p_to, reps, out_dir, *cases = sys.argv[1:]
reps, out_dir = int(reps), pathlib.Path(out_dir)
env = dict(l.split("=", 1) for l in open(env_file, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
BASE, MODEL, KEY = env["LLM_BASE_URL"].rstrip("/"), env["LLM_MODEL"], env["DEEPSEEK_API_KEY"]
FROM, TO = open(p_from, encoding="utf-8").read(), open(p_to, encoding="utf-8").read()
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
out_dir.mkdir(parents=True, exist_ok=True)
results = out_dir / "results.jsonl"
done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results.read_text().splitlines())} if results.exists() else set()


def tool(name, props):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {"type": t} for p, t in props.items()}}}}


TOOLS = [tool("submit", {"task_id": "string", "item_id": "string", "payload": "object"}),
         tool("search_knowledge", {"items": "array"}), tool("read_material", {"name": "string"})]


def call(msgs):
    body = json.dumps({"model": MODEL, "messages": msgs, "tools": TOOLS}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", body, {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    for _ in range(8):
        try:
            return json.load(op.open(req, timeout=600))
        except urllib.error.HTTPError as e:
            msg = e.read()[:200].decode(errors="ignore")
            if e.code != 400 or "location" in msg:
                time.sleep(10 + random.random() * 10)
                continue
            raise RuntimeError(f"{e.code} {msg}")
    raise RuntimeError("retries exhausted")


def load(record):
    msgs = []
    for m in json.load(open(record, encoding="utf-8"))["messages"]:
        if m.get("tool_calls"):
            msgs.append({"role": "assistant", "content": None, "tool_calls": m["tool_calls"]})
        elif m["role"] == "tool":
            msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            msgs.append({"role": m["role"], "content": m["content"]})
    assert FROM in msgs[2]["content"]
    msgs[2]["content"] = msgs[2]["content"].replace(FROM, TO)
    return msgs


def run(point, rep):
    msgs, verdicts, t0 = load(point["record"]), {}, time.time()
    want = {c["claim_id"] for c in point["claims"]}
    for _ in range(6):
        m = call(msgs)["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": tcs} if tcs else {"role": "assistant", "content": m.get("content")})
        if not tcs:
            msgs.append({"role": "user", "content": "还有说法没交判定，请继续逐条交。"})
            continue
        for tc in tcs:
            a = json.loads(tc["function"]["arguments"] or "{}")
            if tc["function"]["name"] == "submit" and a.get("item_id"):
                p = a.get("payload") or {}
                verdicts[a["item_id"]] = {"verdict": p.get("verdict"), "gap": p.get("gap"), "reason": (p.get("reason") or "")[:400]}
            res = {"accepted": True} if tc["function"]["name"] == "submit" else {"error": "本次只判定，不再取证；请依据已有结果判定"}
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, ensure_ascii=False)})
        if want <= set(verdicts):
            break
    return {"prompt_id": point["case"], "rep": rep, "verdicts": verdicts, "missing": sorted(want - set(verdicts)),
            "latency_s": round(time.time() - t0, 1), "model": MODEL}


def job(arg):
    point, rep = arg
    try:
        row = run(point, rep)
        with open(results, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return f"{point['case']} rep{rep}: {len(row['verdicts'])} judged, missing {len(row['missing'])}"
    except Exception as e:  # noqa: BLE001
        with open(out_dir / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"prompt_id": point["case"], "rep": rep, "class": "harness", "error": str(e)[:300]}, ensure_ascii=False) + "\n")
        return f"{point['case']} rep{rep}: ERROR {str(e)[:100]}"


points = [p for p in json.load(open(points_path, encoding="utf-8")) if any(s in p["case"] for s in cases) and "replay" not in p["case"]]
todo = [(p, k) for p in points for k in range(reps) if (p["case"], k) not in done]
with ThreadPoolExecutor(3) as ex:
    for line in ex.map(job, todo):
        print(line, flush=True)
