"""Re-aggregate with two exclusions: cross-line sums are not errors; old-Insurance delivery concatenation is not an error
(clean/privacy for insurance_old taken from re-labels of the model's own final output).
usage: exclude.py <labels_480.jsonl> <reclean out dir> <out json>"""
import json, re, sys, glob, os, collections
HS = ["claude", "pi", "insurance_old", "insurance_harness"]
AXES = ["intent", "planning", "tool", "knowledge", "model", "context"]
SUM = re.compile(r"跨险种|合计|汇总|相加|求和|加总|心算")
# (case, harness): (answer without the sum, other model problem left in the same/other issues) — judged by hand from issues
SUM_FIX = {
 ("A02","insurance_harness"):("correct",False), ("A06","insurance_harness"):("wrong",True),
 ("A10","insurance_harness"):("partial",True),  ("A11","insurance_harness"):("correct",False),
 ("A13","insurance_harness"):("partial",True),  ("A18","insurance_harness"):("partial",True),  # user said "别混成一条"
 ("A19","insurance_harness"):("correct",False), ("B02","insurance_harness"):("wrong",True),
 ("B17","insurance_harness"):("partial",True),  ("C07","insurance_harness"):("partial",True),
 ("D05","insurance_harness"):("correct",False), ("D19","insurance_harness"):("partial",True),
 ("E04","insurance_harness"):("partial",True),  ("E11","insurance_harness"):("correct",False),
 ("E13","insurance_harness"):("correct",False), ("F02","insurance_harness"):("partial",True),
 ("F04","insurance_harness"):("correct",False), ("F05","insurance_harness"):("correct",False),
 ("F16","insurance_harness"):("partial",False), ("F19","insurance_harness"):("correct",True),
 ("A13","claude"):("wrong",True), ("B10","claude"):("correct",False), ("F04","claude"):("wrong",True),
 ("A13","pi"):("wrong",True), ("B03","pi"):("correct",False), ("F02","pi"):("correct",False),
 ("A06","insurance_old"):("partial",True), ("A10","insurance_old"):("correct",False),
 ("C07","insurance_old"):("correct",False), ("F01","insurance_old"):("wrong",True),
 ("F02","insurance_old"):("correct",False), ("F07","insurance_old"):("correct",False),
 ("F19","insurance_old"):("correct",False),
}
# Rubric corrections after checking each harness's actual prompt (applied after SUM_FIX), (answer or None, model axis):
# - insurance_harness prompt says "已声明的保险金额默认人民币" and "金额必须带数据时点": currency/date additions follow its own rule
# - F12: month filter did apply (March/April pages disjoint, picked customer born 04-20); only /customer/search total=417 is wrong
# - all four tool descriptions say "EMPTY 表示确实无记录": reporting "没有" on EMPTY follows the contract (fault is the tool)
PROMPT_FIX = {
 **{(c, "insurance_harness"): ("correct", "ok") for c in ("D12", "F08", "F14", "F20", "A10", "A13", "F02", "B17")},
 **{("F12", h): ("partial", "ok") for h in ("claude", "pi", "insurance_old", "insurance_harness")},
 ("F11", "claude"): (None, "upstream"), ("F11", "insurance_harness"): (None, "upstream"),
}
KEEP_CTX_OLD ={"B09", "F17", "F20"}  # card shortcut / wrong history object / truncated history: not concatenation
rows = {(r["case"], r["harness"]): r for r in map(json.loads, open(sys.argv[1]))}
rc = {}
for f in sorted(glob.glob(os.path.join(sys.argv[2], "*.jsonl"))):
    for l in open(f):
        if l.strip(): x = json.loads(l); rc[x["case"]] = x
for (c, h), r in rows.items():
    r = dict(r); r["axes"] = dict(r["axes"])
    sv = any(i["axis"] == "model" and SUM.search(i["desc"]) for i in r["issues"])
    if sv:
        ans, other = SUM_FIX[(c, h)]
        r["answer"] = ans
        if not other and not any(i["axis"] == "model" and not SUM.search(i["desc"]) for i in r["issues"]):
            r["axes"]["model"] = "ok"
    if h == "insurance_old":
        if c not in KEEP_CTX_OLD and r["axes"]["context"] == "problem": r["axes"]["context"] = "ok"
        r["clean"] = rc[c]["clean"]; r["privacy"] = bool(r["privacy"]) and rc[c]["privacy"]  # model final is part of the delivered text
        if r["answer"] == "no_answer": r["axes"]["model"] = "problem"
    fix = PROMPT_FIX.get((c, h))
    if fix:
        if fix[0]: r["answer"] = fix[0]
        r["axes"]["model"] = fix[1]
    rows[(c, h)] = r
missing = [c for (c, h) in rows if h == "insurance_old" and c not in rc]
assert not missing, missing
out = {}
for h in HS:
    R = [r for (c, hh), r in rows.items() if hh == h]; o = {"n": len(R)}
    for a in AXES: o[a] = {v: sum(r["axes"].get(a) == v for r in R) for v in ("problem", "unlocated")}
    o["harness_axes_clear"] = sum(all(r["axes"].get(a) != "problem" for a in ("intent", "planning", "model", "context")) for r in R)
    o["answer"] = dict(collections.Counter(r["answer"] for r in R))
    o["usable"] = o["answer"].get("correct", 0) + o["answer"].get("partial", 0)
    o["clean"] = sum(bool(r["clean"]) for r in R)
    o["usable_clean"] = sum(r["answer"] in ("correct", "partial") and r["clean"] for r in R)
    o["privacy"] = sum(bool(r["privacy"]) for r in R)
    out[h] = o
json.dump({"summary": out, "rows": [rows[k] for k in sorted(rows)]}, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
for h in HS: print(h, json.dumps(out[h], ensure_ascii=False))
