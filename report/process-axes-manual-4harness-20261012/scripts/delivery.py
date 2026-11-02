"""Classify delivered final_text vs model texts per turn. usage: delivery.py <data dir> <harness>"""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
d = json.load(open(os.path.join(sys.argv[1], sys.argv[2] + ".json")))
norm = lambda x: "".join((x or "").split())
cnt = collections.Counter(); ex = collections.defaultdict(list)
for case in d["cases"]:
    if case.get("latest") is False: continue
    cid = case["overview"]["case_id"].split("_")[-1]
    turns = case["overview"]["turns"]
    # group calls into turns by user prompt appearance in the last user msg
    texts_by_turn = collections.defaultdict(list)
    ti = 0
    for c in case["calls"]:
        if not c.get("tool_names"): continue
        msgs = c.get("messages") or []
        users = [m for m in msgs if m.get("role") == "user" and not m.get("tool_call_id")]
        # find which turn prompt is latest present
        allu = "".join(norm(m.get("text")) for m in msgs if m.get("role") == "user")
        for j, t in enumerate(turns):
            if norm(t["prompt"])[:30] in allu: ti = j
        if (c.get("assistant") or "").strip():
            texts_by_turn[ti].append(((c.get("assistant") or "").strip(), bool(c.get("tool_calls"))))
    for j, t in enumerate(turns):
        ft = norm(t.get("final_text"))
        tx = texts_by_turn.get(j, [])
        finals = [norm(a) for a, tc in tx if not tc]
        last = finals[-1] if finals else ""
        if finals and ft == last: k = "same"
        elif not ft: k = "empty_delivery"
        elif ft == norm("".join(a for a, _ in tx)) or ft == norm("\n\n".join(a for a, _ in tx)): k = "concat_all_texts"
        elif last and last in ft: k = "contains_final_plus_extra"
        elif not finals: k = "no_text_only_final(model ended with tool call?)"
        else: k = "different"
        cnt[k] += 1
        if k != "same" and len(ex[k]) < 6: ex[k].append(f"{cid}#t{t['index']}")
print(sys.argv[2], dict(cnt)); [print("  ", k, v) for k, v in ex.items()]
