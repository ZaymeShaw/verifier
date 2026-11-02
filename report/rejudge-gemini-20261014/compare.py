"""三方对照：本次 gemini 重判（新代码）/ 同记录原先入库结果（qwen 等，新代码但无编号修复）/ 旧 gemini 汇总（旧代码、旧业务回复）。"""
import json, glob, sqlite3, collections
ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
AX = ["context_memory", "intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability"]
new = {}
for f in glob.glob(f"{ROOT}/report/rejudge-gemini-20261014/cases/*.json"):
    d = json.load(open(f)); new[d["case_id"]] = {r["type_id"]: r for r in d["report"]["results"]}
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
stored = {}
for (rj,) in db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND run_json IS NOT NULL"):
    r = json.loads(rj); stored[r["case_id"]] = {x["type_id"]: x for x in r["eval_axes"]["results"]}
old = {x["case_id"]: x for x in json.load(open(f"{ROOT}/report/multiturn-needs-20261012/fec_batch_axes.json"))}

def stat(res):
    if not res or res.get("status") != "succeeded": return ("failed", 0, 0, 0)
    o = res["output"]; rows = o.get("results") or []
    return (o["assessment"]["verdict"], sum(r["verdict"] == "无法核" for r in rows),
            sum(r["verdict"] == "没达到" for r in rows), len(o.get("issues") or []))
def stat_old(c, ax):
    a = (old.get(c) or {}).get("axes", {}).get(ax)
    if not a: return ("—", 0, 0, 0)
    it = a.get("items") or []
    return (a["verdict"], sum(i["verdict"] == "无法核" for i in it), sum(i["verdict"] == "没达到" for i in it), len(a.get("issues") or []))

for name, get in [("新gemini", lambda c, ax: stat(new[c].get(ax))), ("入库qwen等", lambda c, ax: stat(stored[c].get(ax))),
                  ("旧gemini", stat_old)]:
    print(f"== {name}")
    for ax in AX:
        v = collections.Counter(); unk = miss = iss = 0
        for c in new:
            s = get(c, ax); v[s[0]] += 1; unk += s[1]; miss += s[2]; iss += s[3]
        print(f"  {ax:22s}", dict(v), "无法核", unk, "没达到", miss, "问题", iss)
print("== 判词变化（入库 → 新gemini）")
for ax in AX:
    ch = [(c.split('-main-')[-1].split('-smoke-')[-1][:28], stat(stored[c].get(ax))[0], stat(new[c].get(ax))[0]) for c in sorted(new)]
    ch = [x for x in ch if x[1] != x[2]]
    print(ax, len(ch), ch)
