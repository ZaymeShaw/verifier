"""B02 拆说法验证：说法清单里补上"惠享版就是用户所指那款"（B），只重放真实轴判定，收 c1 和 B 两条的结论。
用法：run_split.py <env_file> <variants_dir> <reps> <out_dir>
submit 一律回"已收下"；再取证回"本次只判定"；没调工具就催一次；最多 8 轮。"""
import json, pathlib, random, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

env_file, vdir, reps, out_dir = sys.argv[1], pathlib.Path(sys.argv[2]), int(sys.argv[3]), pathlib.Path(sys.argv[4])
env = dict(l.split("=", 1) for l in open(env_file, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
BASE, MODEL, KEY = env["LLM_BASE_URL"].rstrip("/"), env["LLM_MODEL"], env["DEEPSEEK_API_KEY"]
GOLD = {"V0": {"A": "unverifiable", "B": "unverifiable"},
        "V1": {"A": "refuted", "B": "refuted"},
        "V2": {"A": "unverifiable", "B": "refuted"}}
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
out_dir.mkdir(parents=True, exist_ok=True); (out_dir / "traces").mkdir(exist_ok=True)
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
            return json.load(op.open(req, timeout=300))
        except urllib.error.HTTPError as e:
            msg = e.read()[:200].decode(errors="ignore")
            if e.code in (400, 429, 500, 502, 503) and ("location" in msg or e.code != 400):
                time.sleep(10 + random.random() * 10); continue
            raise RuntimeError(f"{e.code} {msg}")
    raise RuntimeError("retries exhausted")


def run(case, rep):
    variant = case.stem.split("_")[1]
    msgs = json.load(open(case, encoding="utf-8"))
    bid = "c%d" % max(int(x) for x in re.findall(r'"claim_id": "c(\d+)"', msgs[2]["content"]))
    want, got, t0 = {"A": "c1", "B": bid}, {}, time.time()
    for _ in range(8):
        m = call(msgs)["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": tcs} if tcs else {"role": "assistant", "content": m.get("content")})
        if not tcs:
            msgs.append({"role": "user", "content": "还有说法没交判定，请继续逐条交。"}); continue
        for tc in tcs:
            a = json.loads(tc["function"]["arguments"] or "{}")
            if tc["function"]["name"] == "submit":
                for k, cid in want.items():
                    if a.get("item_id") == cid:
                        got[k] = a.get("payload") or {}
                res = {"accepted": True}
            else:
                res = {"error": "本次只判定，不再取证；请依据已有结果判定"}
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, ensure_ascii=False)})
        if len(got) == 2:
            break
    row = {"prompt_id": case.stem, "rep": rep, "variant": variant, "model": MODEL, "latency_s": round(time.time() - t0, 1)}
    for k in "AB":
        p = got.get(k) or {}
        row[k] = {"verdict": p.get("verdict"), "gold": GOLD[variant][k], "ok": p.get("verdict") == GOLD[variant][k],
                  "gap": p.get("gap"), "reason": p.get("reason")}
    json.dump([{"role": x["role"], "content": x.get("content") if x.get("content") is not None else json.dumps(x.get("tool_calls"), ensure_ascii=False)} for x in msgs[3:]],
              open(out_dir / "traces" / f"{case.stem}_rep{rep}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return row


def job(arg):
    case, rep = arg
    try:
        row = run(case, rep)
        with open(results, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return f"{case.stem} rep{rep}: A={row['A']['verdict']}(gold {row['A']['gold']}) B={row['B']['verdict']}(gold {row['B']['gold']})"
    except Exception as e:  # noqa: BLE001
        with open(out_dir / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"prompt_id": case.stem, "rep": rep, "error": str(e)[:300]}, ensure_ascii=False) + "\n")
        return f"{case.stem} rep{rep}: ERROR {str(e)[:100]}"


todo = [(c, k) for c in sorted(vdir.glob("*.json")) for k in range(reps) if (c.stem, k) not in done]
with ThreadPoolExecutor(3) as ex:
    for line in ex.map(job, todo):
        print(line, flush=True)
