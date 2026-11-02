"""实验 1：对 fec 批 8 道多轮题，按「整 case 一份」（现行）与「每轮一份」各写需求两遍，只写需求、不判业务。

每轮一份的材料 = 该轮的 sources（本轮用户原话 want + 本轮请求里的历史 history）+ 场景字段，
不含后面轮次的任何内容。调用的是现行 expectations.run，提示词与校验不变。
用法：python exp1_per_turn.py <输出目录>
"""
import copy, hashlib, json, sqlite3, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.adapters import expectations

OUT = sys.argv[1]
REPEAT = 2
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")


def material(sources, missing):
    body = {"sources": sources, "missing": missing}
    body["sha256"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return body


def write(req, tag):
    runtime = SimpleNamespace(spec=project, trace_id=f"exp1:{tag}:{time.time():.0f}", ensure_time_left=lambda *_: None)
    started = time.monotonic()
    try:
        out = expectations.run({"requirements": copy.deepcopy(req)}, None, runtime)
        return {"expectations": out.output["expectations"], "elapsed": round(time.monotonic() - started)}
    except Exception as exc:  # 评测器失败如实记录
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed": round(time.monotonic() - started)}


results = []
for (rj,) in db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' ORDER BY position"):
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    exo = res["expectations"]["output"]
    turns = sorted({s["turn"] for s in exo["sources"] if s["turn"].startswith("t")})
    if len(turns) < 2:
        continue
    case = rj["case_id"].split("main-")[-1]
    rec = {"case": case, "turns": turns, "sources": exo["sources"], "stored_global": exo["expectations"],
           "global": [], "per_turn": {t: [] for t in turns}}
    full = material(exo["sources"], exo["missing"])
    for k in range(REPEAT):
        rec["global"].append(write(full, f"{case}:global:{k}"))
        print(case, "global", k, len(rec["global"][-1].get("expectations", [])), flush=True)
        for t in turns:
            part = material([s for s in exo["sources"] if s["turn"] in (t, "case")], exo["missing"])
            rec["per_turn"][t].append(write(part, f"{case}:{t}:{k}"))
            print(case, t, k, len(rec["per_turn"][t][-1].get("expectations", [])), flush=True)
    results.append(rec)
    json.dump(results, open(f"{OUT}/exp1_results.json", "w"), ensure_ascii=False, indent=1)
print("done")
