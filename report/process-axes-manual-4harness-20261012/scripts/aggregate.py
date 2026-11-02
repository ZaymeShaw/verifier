"""Aggregate annotation jsonl (120 cases x 4 harnesses) into the comparison table.
Normalizes cross-line sums: strict = any sum violation -> wrong; lenient = wrong only because of sums -> partial.
usage: aggregate.py <annot out dir> <out json>"""
import json, sys, os, glob, re, collections
HS = ["claude", "pi", "insurance_old", "insurance_harness"]
AXES = ["intent", "planning", "tool", "knowledge", "model", "context"]
SUM = re.compile(r"跨险种|合计|汇总|相加|求和|加总|心算")
MINOR = re.compile(r"跨险种|合计|汇总|相加|求和|加总|心算|人民币|币种|补.?元|单位")
# verified by hand: wrong for reasons beyond the sum
KEEP_WRONG = {("B02", "insurance_harness"), ("A06", "insurance_harness")}
rows = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.jsonl"))):
    for l in open(f):
        if l.strip():
            r = json.loads(l); rows[(r["case"], r["harness"])] = r
for r in rows.values():
    iss = r.get("issues", [])
    r["sum_violation"] = any(i.get("axis") == "model" and SUM.search(i.get("desc", "")) for i in iss)
    a = r["answer"]
    r["answer_strict"] = "wrong" if r["sum_violation"] and a in ("correct", "partial") else a
    only_minor = iss and all(MINOR.search(i.get("desc", "")) or i.get("axis") in ("tool", "knowledge", "context") for i in iss)
    r["answer_lenient"] = "partial" if a == "wrong" and r["sum_violation"] and only_minor and (r["case"], r["harness"]) not in KEEP_WRONG else a
by = collections.defaultdict(list)
for r in rows.values(): by[r["harness"]].append(r)
out = {}
for h in HS:
    R = by[h]; n = len(R); o = {"n": n}
    for a in AXES:
        o[a] = {v: sum(r["axes"].get(a) == v for r in R) for v in ("problem", "unlocated", "upstream")}
    o["axes_all_clear"] = sum(all(r["axes"].get(a) in ("ok", "na", "upstream") for a in AXES) for r in R)
    o["harness_axes_clear"] = sum(all(r["axes"].get(a) in ("ok", "na", "upstream", "unlocated") for a in ("intent", "planning", "model", "context")) for r in R)
    for key in ("answer", "answer_strict", "answer_lenient"):
        o[key] = dict(collections.Counter(r[key] for r in R))
    o["clean"] = sum(bool(r.get("clean")) for r in R)
    o["correct_clean_strict"] = sum(r["answer_strict"] == "correct" and r.get("clean") for r in R)
    o["usable_clean_strict"] = sum(r["answer_strict"] in ("correct", "partial") and r.get("clean") for r in R)
    o["privacy"] = sum(bool(r.get("privacy")) for r in R)
    o["sum_violation"] = sum(r["sum_violation"] for r in R)
    out[h] = o
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for h in HS: print(h, json.dumps(out[h], ensure_ascii=False))
