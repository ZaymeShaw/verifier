"""Check status of 10-08 findings in 10-12 traces. usage: followup.py <data dir>"""
import json, os, re, sys, ast, collections
src = open(os.path.join(os.path.dirname(__file__), "digest.py")).read()
exec("def blocks(m):" + src.split("def blocks(m):")[1].split("def user_texts")[0])
def base(n): return n.split("__")[-1].replace("insurance-tools_", "")
for h in ["claude", "pi", "insurance_old", "insurance_harness"]:
    d = json.load(open(os.path.join(sys.argv[1], h + ".json")))
    c = collections.Counter(); ex = collections.defaultdict(list)
    for case in d["cases"]:
        if case.get("latest") is False: continue
        cid = case["overview"]["case_id"].split("_")[-1]
        names = {}; seen = set(); per_turn_tool = collections.Counter(); max_same = 0
        got_fact = False
        for k in case["calls"]:
            for tc in k.get("tool_calls") or []:
                names[tc.get("id")] = base(tc.get("name", ""))
            for tid, t in tool_results(k.get("messages") or []):
                if tid in seen: continue
                seen.add(tid); n = names.get(tid, "?")
                if re.search(r"same_tool_limit|同一工具.{0,10}上限|已达.{0,6}上限|rag_limit|额度耗尽|调用上限", t[:1500]):
                    c["limit_hit"] += 1; ex["limit_hit"].append(f"{cid}:{n}")
                if n in ("product_knowledge", "benefit_info", "general_qa"):
                    c["rag_results"] += 1
                    m = re.findall(r'"typed_value":"(.*?)(?<!\\)"', t)
                    body = sum(len(x) for x in m)
                    if re.search(r'"incomplete":\s*true|omitted_items":\s*[1-9]', t): c["rag_projection_incomplete"] += 1
                    if '"PARTIAL"' in t[:300] or '"SUCCESS"' in t[:300]:
                        c["rag_nonempty_status"] += 1
                        if body < 200: c["rag_status_ok_but_body_lt200"] += 1; ex["thin"].append(f"{cid}:{n}")
                if n in ("ask_user", "ask_clarify"):
                    pass
            for tc in k.get("tool_calls") or []:
                if base(tc.get("name", "")) in ("ask_user", "ask_clarify"):
                    c["clarify_calls"] += 1
                    if got_fact: c["clarify_after_facts"] += 1; ex["clarify_after_facts"].append(cid)
            # facts acquired so far in this call's context?
            for tid, t in tool_results(k.get("messages") or []):
                if names.get(tid) in ("customer_search","customer_detail","policy_search","policy_detail") and re.search(r'"(records|facts)":\s*\[\s*\{', t[:4000]):
                    got_fact = True
        # same-tool calls per case
        cnt = collections.Counter(names.values())
        if cnt and max(cnt.values()) > 4: c["cases_same_tool_gt4"] += 1
        # nonexistent tool calls
        for k in case["calls"]:
            allowed = set(base(x) for x in (k.get("tool_names") or []))
            for tc in k.get("tool_calls") or []:
                if allowed and base(tc.get("name", "")) not in allowed: c["unknown_tool"] += 1; ex["unknown_tool"].append(f"{cid}:{tc.get('name')}")
        c["max_calls"] = max(c["max_calls"], len(case["calls"]))
    print(h, dict(c))
    for k, v in ex.items(): print("   ", k, v[:15])
