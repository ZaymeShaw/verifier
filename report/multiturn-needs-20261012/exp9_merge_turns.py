"""实验 9：多轮题允许几轮合成一批，需求按轮分开标注（方案 A），看调用省多少、串轮冤判回不回来。

只在本脚本里替换，正式代码不改；其余与现行（实验 6 的代码）相同，便于直接与现行一批一轮的结果对照：
- 装批：同一轴所有轮的环节按轮次顺序排好，按现行预算顺序装批（不再按轮切开）；批次 turn 记作 "t1+t2"。
- 需求：批里含哪几轮，就给哪几轮的需求与出处（每条需求本来就带 turn）。
- 本应清单每条加 turn 字段（必须是本批含有的轮），提示词要求每条只依据同一轮的需求和该轮材料写，不得拿一轮的需求去对另一轮的材料。
- 通用职责按条目自己的 turn 归到（轮，职责）。
对照：F01 用实验 6 的现行结果与需求；E01 用实验 7d 的现行结果与需求。
用法：python exp9_merge_turns.py <输出目录> <case:axis,axis;...>
"""
import copy, json, os, sqlite3, sys, time
from dataclasses import dataclass, field, fields as dc_fields
from typing import Literal
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core.project_loader import load_project
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.business_trace.materials import prepare_axis_materials
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.adapters import process_expected as PE
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as TA
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS, _axis_links

OUT = sys.argv[1]
PLAN = [(c, a.split(",")) for c, a in (p.split(":") for p in sys.argv[2].split(";"))]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")
path = f"{OUT}/exp9_results.json"
results = json.load(open(path)) if os.path.exists(path) else []


# ---- 装批：几轮合批 -------------------------------------------------------------------------

def merged_batches(axis_id, dossier, structure, selection):
    records = dossier.get("records") or []
    turns = sorted({TA._turn_no(r.get("id", "")) for r in records} - {None}) or [1]
    links = _axis_links(axis_id, dossier, structure)
    if not links:
        return TA.turn_batches(axis_id, dossier, structure, selection)
    owners = {}
    for record in records:
        turn = TA._turn_no(record.get("id", ""))
        for token in set(TA.re.findall(r"content#\d+", json.dumps(record.get("fields") or {}, ensure_ascii=False))):
            if turn:
                owners.setdefault(token, set()).add(turn)
    turn_of = {l["link_id"]: TA._link_turn(l, owners, turns) for l in links}
    ordered = sorted(links, key=lambda l: turn_of[l["link_id"]])
    batches = prepare_axis_materials(dossier, ordered, list(structure.get("suspects") or []))
    return [{**b, "turn": "+".join(f"t{t}" for t in sorted({turn_of[l['link_id']] for l in b["links"]}))} for b in batches]


TA.turn_batches_original = TA.turn_batches
TA.turn_batches = merged_batches


# ---- 需求：批里有哪几轮给哪几轮 -----------------------------------------------------------------

def turn_expectations(expectations, turn):
    ts = set(turn.split("+"))
    return {**expectations, "expectations": [e for e in expectations.get("expectations") or [] if e.get("turn") in ts],
            "sources": [s for s in expectations.get("sources") or [] if s.get("turn") in ts | {"case"}]}


PE.turn_expectations = turn_expectations

# ---- 本应清单每条带 turn --------------------------------------------------------------------------

@dataclass
class ExpectedItem:
    id: str = field(metadata={'description': '本批内唯一的短编号，如 E1'})
    about: str = field(metadata={'description': '针对输入里的哪个对象或环节（记录编号、需求编号、原话里的条件）'})
    subcapability: str = field(metadata={'description': '取给定子能力之一；都不合适写「其他」'})
    statement: str = field(metadata={'description': '做对时必须成立什么；具体到能核对（对象、地点、条件、数量）'})
    basis: str = field(metadata={'description': '依据：输入里的原文片段或记录编号；通用职责写「通用职责 D1」这样带编号'})
    needs_external: Literal['是', '否', '不确定'] = field(metadata={'description': '是否必须独立查证（例如库里到底有没有）才判得了'})
    turn: str = field(metadata={'description': '这条属于哪一轮（tN，必须是本批材料含有的轮）；只依据同一轮的需求和该轮材料写'})


assert [f.name for f in dc_fields(PE.ExpectedItem)] == [f.name for f in dc_fields(ExpectedItem)][:-1]  # 除 turn 外与现行一致


@dataclass
class ExpectedList:
    expected: list[ExpectedItem] = field(metadata={'nonempty': True})
    not_covered: list[str] = field(metadata={'description': '写不全、拿不准、本次看不到的范围；本次不需要的子能力也写在这里并说明'})


PE.EXPECTED_SPEC = StructuredOutputSpec.from_dataclass(ExpectedList, description="做对时必须成立的条目清单（本应清单）。")
MULTI = ("- 本批可能含几轮的材料（记录编号里的 turnN 表示第 N 轮），需求清单每条也标了 turn："
         "每条本应只依据同一轮的需求和该轮的材料写，turn 填那一轮；不得拿一轮的需求去要求另一轮的材料"
         "（例如用户在后一轮更正了对象，前一轮按原对象处理不算错）；「通用职责」按轮分别写；\n")
anchor = "- basis 引输入里的原文片段或记录编号；\n"
assert anchor in PE.EXPECTED_TASK
PE.EXPECTED_TASK = PE.EXPECTED_TASK.replace(anchor, anchor + MULTI)


def standing_duties(batches):
    found = {}
    for b in batches:
        turn_of = {item["id"]: item.get("turn") or b["turn"] for item in b["expected"]["expected"]}
        for row in b["actual"]["actual"]:
            duty = b["duties"].get(row["id"])
            if duty:
                found.setdefault(f"{turn_of[row['id']]} {duty}", set()).add(row["verdict"])
    return {k: next(v for v in (PE.NOT_MET, PE.MET, PE.UNCHECKABLE) if v in vs) for k, vs in found.items()}


PE.standing_duties = standing_duties


# ---- 运行 ------------------------------------------------------------------------------------

def baseline(case, axis_id):
    for r in json.load(open(f"{OUT}/exp6_results.json")):
        if (r["case"], r["axis"]) == (case, axis_id):
            return r["new"], r["expectations"]
    for r in json.load(open(f"{OUT}/exp7_results.json")):
        if (r["exp"], r["case"], r["axis"]) == ("compare", case, axis_id):
            return r["current"], r["expectations"]
    raise KeyError((case, axis_id))


for case, axes in PLAN:
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%{case}%",)).fetchone()
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    for axis_id in axes:
        base, needs = baseline(case, axis_id)
        e = {**res["expectations"]["output"], "expectations": needs}
        analysis = copy.deepcopy(res["trace_analysis"]["output"])
        TA.prepare_selections(analysis["dossier"], analysis["structure"], analysis["selections"])
        runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                                  trace_id=f"exp9:{case}:{axis_id}:{time.time():.0f}", ensure_time_left=lambda *_: None)
        started = time.monotonic()
        try:
            o = PE.run_expected_axis(axis_id, {"trace_analysis": analysis, "expectations": e}, None, runtime, PROCESS_SPECS[axis_id]).output
            comp = o["assessment"]["composition"]
            new = {"verdict": o["assessment"]["verdict"], "counts": comp["counts"], "standing_duties": comp["standing_duties"],
                   "batches": o["view"]["batches"], "failed": o["view"]["failed_batches"],
                   "issues": [i["phenomenon"] for i in o["issues"]],
                   "rows": [(r["batch"], r["turn"], r["id"], r["verdict"], r["statement"], r.get("observed", "")) for r in o["results"]]}
        except Exception as exc:
            new = {"verdict": "evaluator_error", "error": f"{type(exc).__name__}: {exc}", "batches": [], "issues": [], "rows": []}
        new["elapsed"] = round(time.monotonic() - started)
        rec = {"case": case, "axis": axis_id, "per_turn": base, "merged": new}
        results = [r for r in results if (r["case"], r["axis"]) != (case, axis_id)] + [rec]
        json.dump(results, open(path, "w"), ensure_ascii=False, indent=1)
        print(case, axis_id, "一批一轮", len(base.get("batches") or []), "批", base["verdict"], base["counts"].get("无法核"),
              "| 合批", len(new["batches"]), "批", new["verdict"], new.get("counts", {}).get("无法核"), new["elapsed"], "s",
              new.get("error") or "", flush=True)
print("done")
