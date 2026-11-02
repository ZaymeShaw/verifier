"""Program-checkable signals over all four harnesses (480 cases).

usage: python3 -I scan.py <new-run dir> <out json>
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT, OUT = sys.argv[1], sys.argv[2]
SRC = {
    "claude": "claude/dual_datasetA_full/claude/cases",
    "pi": "pi/triple_datasetA_full/pi/cases",
    "opencode": "opencode/triple_datasetA_full/opencode/cases",
    "insurance": "insurance-rerun/dual_datasetA_full/insurance/cases",
}
BUSINESS = {"customer_search", "customer_detail", "policy_search", "policy_detail", "product_knowledge",
            "benefit_info", "general_qa", "entity_lookup", "ask_clarify", "run_policy_field_lookup"}
GARBLE = re.compile(r"\b(voluptatem|lorem|ipsum|información|también|según|además)\b", re.I)
LEAK = re.compile(r"(Let me |I now have|I'll |I have all|</think>|I need to |I should )")


def base_name(n):
    n = n.split("__")[-1]
    for p in ("insurance-tools_", "insurance_"):
        if n.startswith(p):
            n = n[len(p):]
    return n


def case_dirs(h):
    b = os.path.join(ROOT, SRC[h])
    for d in sorted(os.listdir(b)):
        p = os.path.join(b, d)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "llm_calls.jsonl")):
            if h == "opencode":
                cid = json.load(open(os.path.join(p, "identity.json")))["case_id"]
            else:
                cid = d.split("_", 1)[1] if h in ("pi", "insurance") else d
            yield cid, p


def tool_msgs(msgs):
    for m in msgs:
        if m.get("role") == "tool":
            c = m.get("content")
            yield m.get("tool_call_id"), c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    cc = b.get("content")
                    if isinstance(cc, list):
                        cc = "\n".join(x.get("text", "") for x in cc if isinstance(x, dict))
                    yield b.get("tool_use_id"), cc or ""


def status_of(t):
    try:
        j = json.loads(t)
    except Exception:
        if "truncated" in t and "Full output saved" in t:
            return "HARNESS_TRUNCATED"
        if "persisted-output" in t:
            return "HARNESS_PERSISTED"
        if "not found" in t.lower():
            return "TOOL_NOT_FOUND"
        return "NON_JSON"
    if isinstance(j, list) and j and isinstance(j[0], dict) and "text" in j[0]:
        try:
            j = json.loads(j[0]["text"])
        except Exception:
            return "NON_JSON"
    if not isinstance(j, dict):
        return "NON_JSON"
    if isinstance(j.get("result"), dict):
        ex = j["result"].get("execution") or {}
        st = ex.get("status")
        code = ex.get("code")
        return f"{st}:{code}" if code else str(st)
    st = j.get("status")
    err = j.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else None
    return f"{st}:{code}" if code else str(st)


def analyze(h, cid, p):
    calls = [json.loads(l) for l in open(os.path.join(p, "llm_calls.jsonl"))]
    calls.sort(key=lambda r: (r.get("ts") or "", r.get("seq") or 0))
    main = [c for c in calls if (c.get("request") or {}).get("tools")]
    names = {}
    tool_calls = []
    finals = []
    failed_llm = sum(1 for c in calls if c.get("state") not in (None, "succeeded"))
    for c in main:
        resp = (c.get("response") or {}).get("response") or {}
        msg = ((resp.get("choices") or [{}])[0]).get("message") or {}
        tcs = msg.get("tool_calls") or []
        for tc in tcs:
            fn = tc.get("function") or {}
            names[tc.get("id")] = base_name(fn.get("name", ""))
            tool_calls.append(base_name(fn.get("name", "")))
        if not tcs and msg.get("content"):
            finals.append(msg["content"])
    seen = {}
    for c in main:
        for tid, t in tool_msgs((c.get("request") or {}).get("messages") or []):
            if tid not in seen:
                seen[tid] = (names.get(tid, "?"), status_of(t or ""))
    statuses = Counter(f"{n}={s}" for n, s in seen.values())
    biz = [n for n in tool_calls if n in BUSINESS]
    nonbiz = [n for n in tool_calls if n not in BUSINESS]
    final = finals[-1] if finals else ""
    rec = {
        "harness": h, "case": cid, "llm_calls": len(calls), "main_calls": len(main), "failed_llm": failed_llm,
        "tool_calls": len(tool_calls), "biz_calls": Counter(biz), "nonbiz_calls": Counter(nonbiz),
        "statuses": statuses, "finals": len(finals),
        "garble": sorted(set(m.group(0) for f in finals for m in GARBLE.finditer(f))),
        "leak": bool(LEAK.search(final)) if h != "insurance" else None,
        "ends_with_offer": bool(re.search(r"(是否需要我|需要的话|要不要我|如需|请告诉我|请回复)", final[-200:])),
    }
    if h == "insurance":
        cj = json.load(open(os.path.join(os.path.dirname(p), f"INS_{cid}.json")))
        turns = cj.get("turns", [])
        delivered = [t.get("final_text") or t.get("answer") or "" for t in turns]
        drafts = []
        for f in finals:
            m = re.search(r'"answer_draft"\s*:\s*"((?:[^"\\]|\\.)*)"', f)
            drafts.append(json.loads('"' + m.group(1) + '"', strict=False) if m else None)
        rec["turns"] = len(turns)
        rec["delivered_dump_lines"] = sum(d.count("· 查询信息:") for d in delivered)
        rec["delivered_has_draft"] = []
        for i, d in enumerate(delivered):
            dr = drafts[i] if i < len(drafts) else None
            rec["delivered_has_draft"].append(None if dr is None else (dr[:20] in d))
        rec["delivered_render_style"] = sum(1 for d in delivered if re.search(r"^(保单|客户|产品) .*:\n·", d, re.M))
        rec["completeness"] = cj["response"].get("completeness")
        rec["model_finals_without_json"] = sum(1 for x in drafts if x is None)
    return rec


def main():
    recs = []
    for h in SRC:
        for cid, p in case_dirs(h):
            recs.append(analyze(h, cid, p))
    json.dump(recs, open(OUT, "w"), ensure_ascii=False, indent=0, default=dict)
    by = defaultdict(list)
    for r in recs:
        by[r["harness"]].append(r)
    for h, rs in by.items():
        st = Counter()
        nb = Counter()
        bz = Counter()
        for r in rs:
            st.update(r["statuses"])
            nb.update(r["nonbiz_calls"])
            bz.update(r["biz_calls"])
        print(f"\n===== {h}: cases={len(rs)}")
        print(" llm_calls", sum(r["llm_calls"] for r in rs), "failed_llm", sum(r["failed_llm"] for r in rs),
              "tool_calls", sum(r["tool_calls"] for r in rs), "zero_tool_cases", sum(1 for r in rs if r["tool_calls"] == 0))
        print(" biz", dict(bz.most_common()))
        print(" nonbiz", dict(nb.most_common()))
        nonok = Counter({k: v for k, v in st.items() if not k.endswith("=SUCCESS") and not k.endswith("=True")})
        print(" non-success results", dict(nonok.most_common(40)))
        print(" garble cases", [(r["case"], r["garble"]) for r in rs if r["garble"]])
        if h != "insurance":
            print(" leak-in-final cases", sum(1 for r in rs if r["leak"]))
        print(" ends_with_offer", sum(1 for r in rs if r["ends_with_offer"]))
        if h == "insurance":
            print(" turns", sum(r["turns"] for r in rs))
            print(" dump cases", sum(1 for r in rs if r["delivered_dump_lines"]), "dump lines", sum(r["delivered_dump_lines"] for r in rs))
            flat = [x for r in rs for x in r["delivered_has_draft"]]
            print(" delivered contains model draft prefix", Counter(flat))
            print(" render-style turns", sum(r["delivered_render_style"] for r in rs))
            print(" completeness", Counter(r["completeness"] for r in rs))


main()
