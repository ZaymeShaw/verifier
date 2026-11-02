"""Search results whose reported total exceeds rows actually returned (page truncation).
usage: paging.py <data dir>"""
import json, os, re, sys, ast, collections
src = open(os.path.join(os.path.dirname(__file__), "digest.py")).read()
exec("def blocks(m):" + src.split("def blocks(m):")[1].split("def user_texts")[0])
REP = re.compile(r"报告\s*(\d+)\s*(?:位|条|张)[^，,]*?，当前页读取\s*(\d+)")
for h in ["claude", "pi", "insurance_old", "insurance_harness"]:
    d = json.load(open(os.path.join(sys.argv[1], h + ".json")))
    cnt = collections.Counter(); cases = set()
    for c in d["cases"]:
        if c.get("latest") is False: continue
        cid = c["overview"]["case_id"].split("_")[-1]
        seen = set()
        for k in c["calls"]:
            for tid, t in tool_results(k.get("messages") or []):
                if tid in seen: continue
                seen.add(tid)
                tot = got = None
                m = REP.search(t)
                if m: tot, got = int(m.group(1)), int(m.group(2))
                else:
                    try:
                        j = json.loads(t); j = j.get("result", j); dd = j.get("data") or {}
                        if isinstance(dd, dict) and "total" in dd and isinstance(dd.get("records"), list):
                            tot, got = int(dd["total"]), len(dd["records"])
                    except Exception: pass
                if tot is None: continue
                cnt["search_like"] += 1
                if tot > got: cnt["total_gt_returned"] += 1; cases.add(cid)
    print(h, dict(cnt), "cases", len(cases), sorted(cases)[:40])
