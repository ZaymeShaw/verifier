"""实验 3：同一份分析轴产物，分别用「已存的整份需求」与「每轮需求」重判几个轴，对照冤判是否消失、原判有没有被改坏。

每轮需求取实验 1 的第 0 遍；判第几轮的批次就给第几轮的需求，「需求出处」也只给那一轮的 sources。
批次属于第几轮 = 批次材料里记录编号 turnN/ 的最大 N（跨轮环节按较晚一轮）。
除需求外，提示词、材料、模型、程序处理与线上一致（直接调用 judge_batch / outcome_of）。
用法：python exp3_rejudge.py <输出目录> <case:axis,axis;case:axis...>
"""
import copy, json, re, sqlite3, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from dataclasses import replace
from impl.core.project_loader import load_project
from impl.projects.llm_probe.business_trace.links import LIMITS
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.llm import axis_llm
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS, _scenario_entry, project_subcapabilities
from impl.projects.llm_probe.eval_axes.adapters.process_expected import judge_batch, outcome_of
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

OUT = sys.argv[1]
PLAN = [(c, a.split(",")) for c, a in (p.split(":") for p in sys.argv[2].split(";"))]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")
exp1 = {r["case"]: r for r in json.load(open(f"{OUT}/exp1_results.json"))}


def batch_turn(batch):
    ids = [r.get("id", "") for r in batch["view"].get("records") or []]
    ids += [l["link_id"] for l in batch["links"]]
    turns = [int(m) for s in ids for m in re.findall(r"turn(\d+)", s)]
    if not turns:
        raise ValueError(f"批次算不出轮次：{[l['link_id'] for l in batch['links']]}")
    return max(turns)


def run_axis(axis_id, analysis, runtime, expectations_for):
    spec = PROCESS_SPECS[axis_id]
    spec = replace(spec, subcapabilities=spec.subcapabilities + project_subcapabilities(_scenario_entry(runtime), axis_id))
    client = axis_llm(runtime.spec, role="judge")
    batches = analysis["selections"][axis_id]["materials"]
    judged, failures = [], []
    for number, batch in enumerate(batches, 1):
        try:
            judged.append(judge_batch(client, runtime, axis_id, spec, number, analysis["dossier"], batch["links"],
                                      batch["view"], expectations_for(batch), LIMITS,
                                      [p for b in judged for p in b["actual"]["problems"] if not p.get("same_as")]))
        except ValueError as exc:
            failures.append(f"批次{number}：{exc}")
    out = outcome_of(axis_id, judged, failures, {**client.usage(), "tool_calls": 0}, {"refs": [], "why": []})
    return {"verdict": out.output["assessment"]["verdict"], "failures": failures,
            "batches": [{"number": b["number"], "turn": batch_turn(batches[b["number"] - 1]), "links": b["links"],
                         "problems": [p["phenomenon"] for p in b["actual"]["problems"]]} for b in judged],
            "rows": [(r["batch"], r["id"], r["verdict"], r["statement"], r.get("observed", "")) for r in out.output["results"]],
            "issues": [i["phenomenon"] for i in out.output["issues"]], "usage": out.usage}


results = []
for case, axes in PLAN:
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%main-{case}",)).fetchone()
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    analysis = copy.deepcopy(res["trace_analysis"]["output"])
    prepare_selections(analysis["dossier"], analysis["structure"], analysis["selections"])
    stored = res["expectations"]["output"]
    per_turn = exp1[case]["per_turn"]

    def by_turn(batch):
        t = f"t{batch_turn(batch)}"
        return {**stored, "expectations": per_turn[t][0]["expectations"],
                "sources": [s for s in stored["sources"] if s["turn"] in (t, "case")]}

    for axis_id in axes:
        rec = {"case": case, "axis": axis_id, "stored_verdict": res[axis_id]["output"]["assessment"]["verdict"],
               "stored_issues": [i["phenomenon"] for i in res[axis_id]["output"]["issues"]]}
        for mode, fn in (("whole", lambda b: stored), ("per_turn", by_turn)):
            runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                                      trace_id=f"exp3:{case}:{axis_id}:{mode}:{time.time():.0f}", ensure_time_left=lambda *_: None)
            started = time.monotonic()
            rec[mode] = run_axis(axis_id, analysis, runtime, fn)
            rec[mode]["elapsed"] = round(time.monotonic() - started)
            print(case, axis_id, mode, rec["stored_verdict"], "->", rec[mode]["verdict"], len(rec[mode]["issues"]), "issues",
                  rec[mode]["failures"] or "", flush=True)
        results.append(rec)
        json.dump(results, open(f"{OUT}/exp3_results.json", "w"), ensure_ascii=False, indent=1)
print("done")
