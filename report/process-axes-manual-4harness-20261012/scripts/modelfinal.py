"""Per case/turn: model's own last text (vs delivered). usage: modelfinal.py <data dir> <harness> <out json>"""
import json, sys, os, collections
d = json.load(open(os.path.join(sys.argv[1], sys.argv[2] + ".json")))
norm = lambda x: "".join((x or "").split())
out = {}
for case in d["cases"]:
    if case.get("latest") is False: continue
    cid = case["overview"]["case_id"].split("_")[-1]
    turns = case["overview"]["turns"]
    tb = collections.defaultdict(list); ti = 0
    for c in case["calls"]:
        msgs = c.get("messages") or []
        allu = "".join(norm(m.get("text")) for m in msgs if m.get("role") == "user")
        for j, t in enumerate(turns):
            if norm(t["prompt"])[:30] in allu: ti = j
        tb[ti].append(((c.get("assistant") or "").strip(), bool(c.get("tool_calls"))))
    out[cid] = [{"delivered": t.get("final_text") or "",
                 "last_text": (tb[j][-1][0] if tb.get(j) else ""),
                 "last_is_tool": (tb[j][-1][1] if tb.get(j) else None)} for j, t in enumerate(turns)]
json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False)
