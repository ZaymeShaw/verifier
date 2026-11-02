"""实验 6：正式实现（每轮需求 + 一批一轮 + 通用职责按轴取值 + 步骤端点修复）端到端重判。

复用已存的分析轴产物（dossier / structure / selections），其余全走正式代码：
expectations.run（按轮写需求）→ prepare_selections（按轮分批）→ run_expected_axis（每批本轮需求、汇总）。
结果按（case, 轴）合并进 exp6_results.json。用法：python exp6_pipeline.py <输出目录> <case:axis,axis;...>
"""
import copy, json, os, re, sqlite3, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.adapters import expectations
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS
from impl.projects.llm_probe.eval_axes.adapters.process_expected import run_expected_axis
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

OUT = sys.argv[1]
PLAN = [(c, a.split(",")) for c, a in (p.split(":") for p in sys.argv[2].split(";"))]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")
path = f"{OUT}/exp6_results.json"
results = json.load(open(path)) if os.path.exists(path) else []

for case, axes in PLAN:
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%{case}%",)).fetchone()
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    stored_e = res["expectations"]["output"]
    runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                              trace_id=f"exp6:{case}:{time.time():.0f}", ensure_time_left=lambda *_: None)
    material = {"sources": stored_e["sources"], "missing": stored_e["missing"], "sha256": stored_e["material_sha256"]}
    e = expectations.run({"requirements": material}, None, runtime).output
    print(case, "需求", [(x["expectation_id"], x["statement"][:30]) for x in e["expectations"]], flush=True)
    analysis = copy.deepcopy(res["trace_analysis"]["output"])
    prepare_selections(analysis["dossier"], analysis["structure"], analysis["selections"])
    for axis_id in axes:
        started = time.monotonic()
        out = run_expected_axis(axis_id, {"trace_analysis": analysis, "expectations": e}, None, runtime, PROCESS_SPECS[axis_id])
        o = out.output
        stored = res[axis_id]["output"]
        rows = [(r["batch"], r["turn"], r["id"], r["standing_duty"], r["verdict"], r["statement"], r.get("observed", "")) for r in o["results"]]
        rec = {"case": case, "axis": axis_id, "expectations": e["expectations"],
               "stored": {"verdict": stored["assessment"]["verdict"],
                          "counts": stored["assessment"].get("composition", {}).get("counts"),
                          "issues": [i["phenomenon"] for i in stored["issues"]]},
               "new": {"verdict": o["assessment"]["verdict"], "counts": o["assessment"]["composition"]["counts"],
                       "standing_duties": o["assessment"]["composition"]["standing_duties"],
                       "batches": o["view"]["batches"], "failed": o["view"]["failed_batches"],
                       "issues": [i["phenomenon"] for i in o["issues"]], "rows": rows,
                       "not_covered": o["assessment"]["composition"]["not_covered"]},
               "elapsed": round(time.monotonic() - started)}
        results = [r for r in results if (r["case"], r["axis"]) != (case, axis_id)] + [rec]
        json.dump(results, open(path, "w"), ensure_ascii=False, indent=1)
        print(case, axis_id, rec["stored"]["verdict"], "->", rec["new"]["verdict"], rec["new"]["counts"],
              rec["new"]["standing_duties"], rec["new"]["failed"] or "", flush=True)
print("done")
