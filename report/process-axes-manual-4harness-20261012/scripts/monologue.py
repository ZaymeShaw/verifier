"""Share of delivered turns containing internal monologue phrases. usage: monologue.py <data dir>"""
import json, os, re, sys, collections
MONO = re.compile(r"(让我|我需要(先|再|查|确认|用)|我应该|我应|Let me|I need to|I should|I now have|I'll |</think>|现在整理|现在组织|让me)", re.I)
HEAVY = re.compile(r"(</think>|Let me|I should|I need to|I now have)", re.I)
for h in ["claude", "pi", "insurance_old", "insurance_harness"]:
    d = json.load(open(os.path.join(sys.argv[1], h + ".json")))
    c = collections.Counter(); ex = []
    for case in d["cases"]:
        if case.get("latest") is False: continue
        for t in case["overview"]["turns"]:
            ft = t.get("final_text") or ""
            c["turns"] += 1
            n = len(MONO.findall(ft))
            if n: c["any_monologue"] += 1
            if n >= 3: c["monologue_3plus"] += 1
            if HEAVY.search(ft): c["english_monologue"] += 1
            c["chars"] += len(ft)
    print(h, dict(c), "avg_chars", c["chars"] // c["turns"])
