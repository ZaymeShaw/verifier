"""实验 5：步骤端点改用 span 记录的内容（links.py 修 bug）前后，同一份分析轴产物、同一份需求，各重判一次。

旧 = HEAD 的 links.py（old_links_HEAD.py），新 = 工作区 links.py。其余与线上一致（prepare_selections → judge_batch → outcome_of）。
已有结果按（case, 轴）合并，重跑某组只替换该组。
用法：python exp5_step_ends.py <输出目录> <case:axis;case:axis...>
"""
import copy, importlib.util, json, os, re, sqlite3, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from dataclasses import replace
from impl.core.project_loader import load_project
from impl.projects.llm_probe.business_trace.links import LIMITS, build_links
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.llm import axis_llm
from impl.projects.llm_probe.eval_axes.adapters import process_common
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS, _scenario_entry, project_subcapabilities
from impl.projects.llm_probe.eval_axes.adapters.process_expected import judge_batch, outcome_of
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

OUT = sys.argv[1]
PLAN = [p.split(":") for p in sys.argv[2].split(";")]
spec = importlib.util.spec_from_file_location("old_links", f"{OUT}/old_links_HEAD.py")
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
UNRECORDED = re.compile(r"未记录|没有记录|未保存|缺失|missing|未提供|看不到|无法看到|不可见")
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")

results = json.load(open(f"{OUT}/exp5_results.json")) if os.path.exists(f"{OUT}/exp5_results.json") else []
for case, axis_id in PLAN:
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%main-{case}%" if not case.startswith("smoke") else f"%{case}%",)).fetchone()
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    rec = {"case": case, "axis": axis_id, "stored_verdict": res[axis_id]["output"]["assessment"]["verdict"]}
    for mode, builder in (("old", old.build_links), ("new", build_links)):
        process_common.build_links = builder
        analysis = copy.deepcopy(res["trace_analysis"]["output"])
        prepare_selections(analysis["dossier"], analysis["structure"], analysis["selections"])
        runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                                  trace_id=f"exp5:{case}:{axis_id}:{mode}:{time.time():.0f}", ensure_time_left=lambda *_: None)
        axis_spec = PROCESS_SPECS[axis_id]
        axis_spec = replace(axis_spec, subcapabilities=axis_spec.subcapabilities + project_subcapabilities(_scenario_entry(runtime), axis_id))
        client = axis_llm(project, role="judge")
        judged, failures = [], []
        for number, batch in enumerate(analysis["selections"][axis_id]["materials"], 1):
            try:
                judged.append(judge_batch(client, runtime, axis_id, axis_spec, number, analysis["dossier"], batch["links"],
                                          batch["view"], res["expectations"]["output"], LIMITS,
                                          [p for b in judged for p in b["actual"]["problems"] if not p.get("same_as")]))
            except ValueError as exc:
                failures.append(f"批次{number}：{exc}")
        out = outcome_of(axis_id, judged, failures, {**client.usage(), "tool_calls": 0}, {"refs": [], "why": []})
        rows = [(r["batch"], r["id"], r["verdict"], r["statement"], r.get("observed", "")) for r in out.output["results"]]
        unc = [r for r in rows if r[2] not in ("达到", "没达到")]
        rec[mode] = {"verdict": out.output["assessment"]["verdict"], "failures": failures, "batches": len(judged),
                     "counts": {v: sum(r[2] == v for r in rows) for v in sorted({r[2] for r in rows})},
                     "uncheckable": unc, "unrecorded": [r for r in unc if UNRECORDED.search(r[4] or "")],
                     "issues": [i["phenomenon"] for i in out.output["issues"]]}
        print(case, axis_id, mode, rec["stored_verdict"], "->", rec[mode]["verdict"], rec[mode]["counts"],
              "未记录类", len(rec[mode]["unrecorded"]), failures or "", flush=True)
    results = [r for r in results if (r["case"], r["axis"]) != (case, axis_id)] + [rec]
    json.dump(results, open(f"{OUT}/exp5_results.json", "w"), ensure_ascii=False, indent=1)
print("done")
