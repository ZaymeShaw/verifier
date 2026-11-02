"""Whole-set program statistics for share_20261012 traces.
usage: python3 -I scan.py <data dir> <out json>
"""
import json, os, re, sys, statistics as st, collections

DATA, OUT = sys.argv[1], sys.argv[2]
HS = ["claude", "pi", "insurance_old", "insurance_harness"]
BUSINESS = {"customer_search", "customer_detail", "policy_search", "policy_detail", "product_knowledge", "benefit_info", "general_qa"}
QUESTION_END = re.compile(r"(吗|呢|？|\?)\s*$")
OFFER_END = re.compile(r"(需要|要不要|是否需要|如需|如果需要|要我)[^。\n]{0,60}(吗|？|\?)\s*$")


import ast
def blocks(m):
    c = m.get("content")
    if isinstance(c, list):
        return c
    if isinstance(c, str) and c.startswith("[{"):
        try:
            import ast
            return ast.literal_eval(c)
        except Exception:
            return None
    return None


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return text_of(c.get("content") if "content" in c else c.get("text", ""))
    if isinstance(c, list):
        return "\n".join(text_of(b.get("text") if b.get("type") == "text" else b.get("content")) for b in c if isinstance(b, dict))
    return ""


def tool_results(msgs):
    for m in msgs:
        if m.get("role") == "tool":
            yield m.get("tool_call_id"), m.get("text") or text_of(m.get("content"))
        bl = blocks(m) if m.get("role") == "user" else None
        for b in bl or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                yield b.get("tool_use_id"), text_of(b.get("content"))



def base(n):
    return n.split("__")[-1].replace("insurance-tools_", "")


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None


def tool_status(text):
    m = re.search(r'"status"\s*:\s*"([A-Z_]+)"', text[:3000])
    if m: return m.group(1)
    if text.lstrip().startswith('{"data"') or text.lstrip().startswith('{"result":{"data"'): return "DATA"
    return "OTHER"


res = {}
for h in HS:
    d = json.load(open(os.path.join(DATA, h + ".json")))
    cases = [c for c in d["cases"] if c.get("latest") is not False]
    r = collections.defaultdict(list)
    cnt = collections.Counter()
    status = collections.Counter()
    tool_counter = collections.Counter()
    for c in cases:
        ov = c["overview"]; m = ov.get("metrics") or {}
        cid = ov["case_id"].split("_")[-1]
        if m.get("wall_ms"): r["wall_s"].append(m["wall_ms"] / 1000)
        r["llm_calls"].append(len(c["calls"]))
        inp = out = cached = 0
        ntool = nbiz = 0
        seen_tc = set(); seen_tr = set(); sigs = collections.Counter()
        last_tr_len = 0
        for k in c["calls"]:
            if k["state"] != "succeeded": cnt["failed_calls"] += 1
            u = k.get("usage") or {}
            inp += u.get("prompt_tokens") or 0; out += u.get("completion_tokens") or 0
            cached += ((u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("cached_tokens") or 0)
            cs = k.get("context_stats") or {}
            if k.get("tool_names"):
                r["per_call_input"].append(u.get("prompt_tokens") or 0)
                r["fixed_overhead_tokens_est"].append((cs.get("system_tokens_est") or 0) + (cs.get("tools_tokens_est") or 0))
            for tc in k.get("tool_calls") or []:
                if tc.get("id") in seen_tc: continue
                seen_tc.add(tc.get("id"))
                n = base(tc.get("name", "")); ntool += 1; tool_counter[n] += 1
                if n in BUSINESS: nbiz += 1
                sigs[(n, json.dumps(tc.get("arguments"), ensure_ascii=False, sort_keys=True))] += 1
            for tid, txt in tool_results(k.get("messages") or []):
                if tid in seen_tr: continue
                seen_tr.add(tid)
                r["tool_result_chars"].append(len(txt))
                status[tool_status(txt)] += 1
                if "<persisted-output>" in txt or "[MCP text output truncated" in txt or "Output too large" in txt:
                    cnt["truncated_results"] += 1
                    r["_trunc_case"].append(cid)
        r["input_tokens"].append(inp); r["output_tokens"].append(out); r["cached_tokens"].append(cached)
        r["tool_calls"].append(ntool); r["biz_tool_calls"].append(nbiz)
        cnt["duplicate_tool_calls"] += sum(v - 1 for v in sigs.values() if v > 1)
        for t in ov.get("turns", []):
            ft = (t.get("final_text") or "").strip()
            cnt["turns"] += 1
            if OFFER_END.search(ft[-120:]): cnt["ends_with_offer_question"] += 1
    agg = {}
    for k, v in r.items():
        if k.startswith("_"): continue
        agg[k] = {"median": st.median(v) if v else None, "p90": pct(v, 0.9), "max": max(v) if v else None, "sum": sum(v), "mean": round(st.mean(v), 2) if v else None}
    agg["cache_hit"] = round(sum(r["cached_tokens"]) / max(1, sum(r["input_tokens"])), 3)
    agg["counts"] = dict(cnt)
    agg["truncated_cases"] = len(set(r["_trunc_case"]))
    agg["tool_status"] = dict(status)
    agg["tools"] = dict(tool_counter.most_common())
    res[h] = agg
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
for h in HS:
    a = res[h]
    print(f"== {h}")
    for k in ["wall_s", "llm_calls", "tool_calls", "biz_tool_calls", "input_tokens", "output_tokens", "per_call_input", "fixed_overhead_tokens_est", "tool_result_chars"]:
        print(f"  {k}: {a[k]}")
    print("  cache_hit", a["cache_hit"], "counts", a["counts"], "truncated_cases", a["truncated_cases"])
    print("  status", a["tool_status"])
    print("  tools", a["tools"])
