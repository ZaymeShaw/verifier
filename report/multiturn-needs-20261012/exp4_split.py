"""实验 4：一批只放一轮。分批逻辑见 turn_batches.py（与线上 prepare_selections 一致，只多一步按轮分组）；每批给本轮需求。
其余同实验 3（judge_batch / outcome_of 原样调用）。用法：python exp4_split.py <输出目录> <case:axis,...;...>
"""
import copy, json, re, sqlite3, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from dataclasses import replace
from impl.core.project_loader import load_project
from impl.projects.llm_probe.business_trace.links import LIMITS
from impl.projects.llm_probe.business_trace.materials import prepare_axis_materials
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.llm import axis_llm
from impl.projects.llm_probe.eval_axes.adapters.process_common import (PROCESS_SPECS, _axis_links, _scenario_entry,
                                                                     project_subcapabilities)
from impl.projects.llm_probe.eval_axes.adapters.process_expected import judge_batch, outcome_of

OUT = sys.argv[1]
PLAN = [(c, a.split(",")) for c, a in (p.split(":") for p in sys.argv[2].split(";"))]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")
exp1 = {r["case"]: r for r in json.load(open(f"{OUT}/exp1_results.json"))}


sys.path.insert(0, OUT)
from turn_batches import turn_materials


def split_batches(axis_id, analysis):
    return turn_materials(axis_id, analysis["dossier"], analysis.get("structure") or {}, analysis["selections"][axis_id])


results = []
for case, axes in PLAN:
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%main-{case}",)).fetchone()
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    analysis = copy.deepcopy(res["trace_analysis"]["output"])
    stored = res["expectations"]["output"]
    per_turn = exp1[case]["per_turn"]
    for axis_id in axes:
        runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                                  trace_id=f"exp4:{case}:{axis_id}:{time.time():.0f}", ensure_time_left=lambda *_: None)
        spec = PROCESS_SPECS[axis_id]
        spec = replace(spec, subcapabilities=spec.subcapabilities + project_subcapabilities(_scenario_entry(runtime), axis_id))
        client = axis_llm(runtime.spec, role="judge")
        batches = split_batches(axis_id, analysis)
        judged, failures = [], []
        for number, batch in enumerate(batches, 1):
            t = f"t{batch['turn']}"
            need = {**stored, "expectations": per_turn[t][0]["expectations"],
                    "sources": [s for s in stored["sources"] if s["turn"] in (t, "case")]}
            try:
                judged.append(judge_batch(client, runtime, axis_id, spec, number, analysis["dossier"], batch["links"],
                                          batch["view"], need, LIMITS,
                                          [p for b in judged for p in b["actual"]["problems"] if not p.get("same_as")]))
            except ValueError as exc:
                failures.append(f"批次{number}：{exc}")
        out = outcome_of(axis_id, judged, failures, {**client.usage(), "tool_calls": 0}, {"refs": [], "why": []})
        rec = {"case": case, "axis": axis_id, "stored_verdict": res[axis_id]["output"]["assessment"]["verdict"],
               "stored_issues": [i["phenomenon"] for i in res[axis_id]["output"]["issues"]],
               "verdict": out.output["assessment"]["verdict"], "failures": failures,
               "batches": [{"number": i + 1, "turn": b["turn"], "links": [l["link_id"] for l in b["links"]]} for i, b in enumerate(batches)],
               "rows": [(r["batch"], r["id"], r["verdict"], r["statement"], r.get("observed", "")) for r in out.output["results"]],
               "issues": [i["phenomenon"] for i in out.output["issues"]], "usage": out.usage}
        results.append(rec)
        json.dump(results, open(f"{OUT}/exp4_results.json", "w"), ensure_ascii=False, indent=1)
        print(case, axis_id, rec["stored_verdict"], "->", rec["verdict"], len(rec["issues"]), "issues",
              [(b["number"], b["turn"]) for b in rec["batches"]], failures or "", flush=True)
print("done")
