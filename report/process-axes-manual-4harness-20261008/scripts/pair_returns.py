"""Pair identical (case, tool, args) calls between MCP harnesses and Insurance; compare returns.

usage: python3 -I pair_returns.py <new-run dir>
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = sys.argv[1]
SRC = {
    "claude": "claude/dual_datasetA_full/claude/cases",
    "pi": "pi/triple_datasetA_full/pi/cases",
    "opencode": "opencode/triple_datasetA_full/opencode/cases",
    "insurance": "insurance-rerun/dual_datasetA_full/insurance/cases",
}


def norm_name(n):
    n = n.split("__")[-1]
    for p in ("insurance-tools_", "insurance_"):
        if n.startswith(p):
            n = n[len(p):]
    return n


def norm_args(a):
    a = {k: v for k, v in a.items() if v is not None}
    a.setdefault("compact", True)
    return json.dumps(a, ensure_ascii=False, sort_keys=True)


def parse_result(t):
    try:
        j = json.loads(t)
    except Exception:
        return None
    if isinstance(j, list) and j and isinstance(j[0], dict) and "text" in j[0]:
        try:
            j = json.loads(j[0]["text"])
        except Exception:
            return None
    if not isinstance(j, dict):
        return None
    if isinstance(j.get("result"), dict):
        r = j["result"]
        ex = r.get("execution") or {}
        return {"status": ex.get("status") or r.get("status"), "data": r.get("data"),
                "facts": r.get("facts") or [], "projection": j.get("projection"), "fmt": "insurance"}
    return {"status": j.get("status"), "data": j.get("data"), "facts": j.get("facts") or [],
            "projection": None, "fmt": "mcp"}


def case_id(h, d, p):
    if h == "opencode":
        return json.load(open(os.path.join(p, "identity.json")))["case_id"]
    return d.split("_", 1)[1] if h in ("pi", "insurance") else d


def collect(h):
    out = defaultdict(list)
    base = os.path.join(ROOT, SRC[h])
    for d in os.listdir(base):
        p = os.path.join(base, d)
        f = os.path.join(p, "llm_calls.jsonl")
        if not os.path.exists(f):
            continue
        cid = case_id(h, d, p)
        calls = {}
        results = {}
        for line in open(f):
            r = json.loads(line)
            msg = ((((r.get("response") or {}).get("response") or {}).get("choices") or [{}])[0]).get("message") or {}
            for tc in msg.get("tool_calls") or []:
                try:
                    a = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    continue
                calls[tc["id"]] = (norm_name(tc["function"]["name"]), norm_args(a))
            for m in (r.get("request") or {}).get("messages") or []:
                if m.get("role") == "tool":
                    c = m.get("content")
                    results[m.get("tool_call_id")] = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                elif isinstance(m.get("content"), list):
                    for b in m["content"]:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            cc = b.get("content")
                            cc = cc if isinstance(cc, str) else json.dumps(cc, ensure_ascii=False)
                            results[b.get("tool_use_id")] = cc
        for tid, key in calls.items():
            if tid in results:
                out[(cid,) + key].append(parse_result(results[tid]))
    return out


def records(data):
    if isinstance(data, dict):
        return data.get("records") or []
    return []


def main():
    ins = collect("insurance")
    for h in ("claude", "pi", "opencode"):
        mcp = collect(h)
        keys = set(mcp) & set(ins)
        stat = Counter()
        examples = []
        for k in sorted(keys):
            a = next((x for x in mcp[k] if x), None)
            b = next((x for x in ins[k] if x), None)
            if not a or not b:
                stat["unparsed"] += 1
                continue
            stat["pairs"] += 1
            stat[f"tool:{k[1]}"] += 1
            if a["status"] != b["status"]:
                stat["status_diff"] += 1
                examples.append(("status", k, a["status"], b["status"]))
            ra, rb = records(a["data"]), records(b["data"])
            ka = set().union(*[set(x) for x in ra if isinstance(x, dict)]) if ra else set()
            kb = set().union(*[set(x) for x in rb if isinstance(x, dict)]) if rb else set()
            if len(ra) != len(rb):
                stat["record_count_diff"] += 1
                examples.append(("records", k, len(ra), len(rb)))
            if ka - kb:
                stat["ins_drops_fields"] += 1
            if a["data"] is not None and b["data"] is None:
                stat["ins_no_data"] += 1
            if len(a["facts"]) != len(b["facts"]):
                stat["facts_count_diff"] += 1
            if b["projection"] and b["projection"].get("omitted_items"):
                stat["ins_omitted_items>0"] += 1
            if len(a["facts"]) > 0 and len(b["facts"]) == 0:
                stat["ins_zero_facts_mcp_has"] += 1
                examples.append(("facts", k, len(a["facts"]), 0))
        print(f"\n== {h} vs insurance: identical (case,tool,args) keys={len(keys)}")
        print(" ", dict(stat))
        for e in examples[:8]:
            print("   ", e[0], e[1][0], e[1][1], e[1][2][:90], "|", e[2], "vs", e[3])


main()
