"""实验 7：三项改法，只在本脚本里替换（monkeypatch），不改正式代码。

intent  —— 意图轴材料改为「截至本轮的内部表达」：第 N 轮的批次输出端 = 第 1..N 轮的全部顶层步骤产出、
           Agent 收到的任务、全部模型调用发出的工具调用（现行只取本轮首个步骤产出 + 首次模型调用）。
           输入端 = 第 1..N 轮用户输入。同一份每轮需求，现行 / 累计各判一次。
external —— needs_external（是/否/不确定）换成 external_fact：写出必须到运行记录以外查证的具体事实，不需要留空；
           只有写了的条目锁成无法核。
duties   —— 通用职责从代码（STANDING_DUTIES）挪到场景配置 process_obligations，作为本轴的项目声明子能力。

external / duties 两项一起作为「提议状态」，与实验 6（现行）对照；需求沿用实验 6 写好的每轮需求，排除需求波动。
用法：python exp7_proposals.py <输出目录> intent <case,case...> | proposed <case:axis,axis;...>
"""
import copy, json, os, sqlite3, sys, time
from dataclasses import dataclass, field, replace
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core.project_loader import load_project
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.business_trace import links as L
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.adapters import expectations, process_common
from impl.projects.llm_probe.eval_axes.adapters import process_expected as PE
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

OUT, MODE, ARG = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
project = load_project("llm_probe")
path = f"{OUT}/exp7_results.json"
results = json.load(open(path)) if os.path.exists(path) else []


# ---- intent：截至本轮的内部表达 ---------------------------------------------------------------

def cumulative_intent_links(dossier, rows):
    spans = L._step_spans(rows)
    agent_spans = {r["agent_run_id"]: r for r in L._live(rows.values(), "steps") if r.get("agent_run_id")}
    current = [r for r in rows.values() if r.get("scope") == "current" and not r.get("copy_of")]
    per_turn, inputs, out = [], [], []
    for source in dossier.get("sources") or []:
        turn = source["id"]
        turn_rows = [r for r in current if r.get("turn") == turn]
        runs = [r for r in turn_rows if r["kind"] == "runs" and not r.get("parent_ref")]
        if not runs:
            continue
        top = [r for r in turn_rows if r["kind"] == "steps" and r.get("representation") != "span" and r.get("parent_ref") == runs[0]["id"]]
        tasks = []
        for run in (r for r in turn_rows if r["kind"] == "runs" and r.get("parent_ref")):
            span = agent_spans.get(run.get("run_id"))
            tasks.append((span["id"], "input") if L._value(dossier, run, "input") is None and span
                         and L._value(dossier, span, "input") is not None else (run["id"], "input"))
        calls = [c for c in dossier.get("model_calls") or [] if c.get("turn") == turn and c.get("scope") == "current"]
        inputs.append((runs[0]["id"], "input"))
        out += [L._step_end(dossier, spans, s, "output") for s in top] + tasks
        out += [(c["output_message_ref"], "tool_calls") for c in calls if c.get("output_message_ref") in rows]
        per_turn.append(L._link(f"intent_understanding:{turn}", "intent_understanding", turn, list(inputs), list(out),
                                "第 1 轮到本轮的用户原文 → 截至本轮的系统内部表达（全部步骤产出、Agent 任务、全部工具调用）"))
    return per_turn


def build_links_cumulative(dossier, *, axis_id=None):
    built = L.build_links(dossier, axis_id=axis_id)
    if axis_id in (None, "intent_understanding"):
        rows = {row["id"]: row for row in dossier.get("records") or []}
        built["links"] = [l for l in built["links"] if l["link_type"] != "intent_understanding"] + cumulative_intent_links(dossier, rows)
    return built


def cumulative_intent_spec():
    from impl.projects.llm_probe.eval_axes.adapters.intent_understanding import SPEC
    subs = tuple(replace(s, duty=s.duty.replace("（首个步骤产出、交给 Agent 的任务、首批工具参数）", "（截至本轮的步骤产出、交给 Agent 的任务、工具参数）")
                         .replace("（任务表述、工具调用意图或首次模型输入）", "（任务表述或工具调用意图）")) for s in SPEC.subcapabilities)
    return replace(SPEC, subcapabilities=subs,
                   requires="要判断系统有没有听懂用户：需要看到截至本轮系统内部如何表达用户问题——各步骤的产出、交给 Agent 的任务表述、"
                            "各次工具调用的请求参数。跨轮追问还要看到历史轮里被指代的对象。")


# ---- external：写出要查证的事实 ----------------------------------------------------------------

@dataclass
class ExpectedItem:
    id: str = field(metadata={'description': '本批内唯一的短编号，如 E1'})
    about: str = field(metadata={'description': '针对输入里的哪个对象或环节（记录编号、需求编号、原话里的条件）'})
    subcapability: str = field(metadata={'description': '取给定子能力之一；都不合适写「其他」'})
    statement: str = field(metadata={'description': '做对时必须成立什么；具体到能核对（对象、地点、条件、数量）'})
    basis: str = field(metadata={'description': '依据：输入里的原文片段或记录编号'})
    external_fact: str = field(metadata={'description': '判这条必须到运行记录以外查证的具体事实（例如「知识库里是否收录了某产品的免责条款」）；'
                                                        '运行记录本身能判的留空字符串'})


@dataclass
class ExpectedList:
    expected: list[ExpectedItem] = field(metadata={'nonempty': True})
    not_covered: list[str] = field(metadata={'description': '写不全、拿不准、本次看不到的范围；本次不需要的子能力也写在这里并说明'})


def settle_external(actual, expected, texts):
    for item in expected["expected"]:
        item["needs_external"] = "是" if (item.get("external_fact") or "").strip() else "否"
    return ORIGINAL_SETTLE(actual, expected, texts)


ORIGINAL_SETTLE = PE.settle
ORIGINAL_JUDGE = PE.judge_batch
SAVED = {k: getattr(PE, k) for k in ("EXPECTED_SPEC", "EXPECTED_TASK", "ACTUAL_TASK", "STANDING_DUTIES", "settle", "judge_batch")}
SAVED_ENTRY = process_common._scenario_entry
OBLIGATIONS = [
    {"id": "gaps_from_upstream", "link_type": "context_memory", "label": "交付不凭空加缺口",
     "situation": "交付里带缺口说明（gaps / limitations）或完整度状态",
     "duty": "缺口说明与完整度状态必须来自上游步骤或模型产出，包裹、交付步骤不得凭空新增缺口或改成 PARTIAL", "confirmed": "实验"},
    {"id": "budget_hint_updates", "link_type": "context_memory", "label": "执行余量提示随用量更新",
     "situation": "同一轮内有多次模型请求，且请求里带「执行余量」提示",
     "duty": "「执行余量」提示必须随已用的调用、工具次数更新，不得逐字不变", "confirmed": "实验"},
]


def apply_proposed():
    PE.EXPECTED_SPEC = StructuredOutputSpec.from_dataclass(ExpectedList, description="做对时必须成立的条目清单（本应清单）。")
    PE.EXPECTED_TASK = (PE.EXPECTED_TASK.replace("，不写通用职责原文；", "；")
                        .replace("- 「通用职责」逐条看：本批材料涉及它说的环节时写成一条（about 点出本 case 对应的环节，basis 写「通用职责 D1」这样带编号）；"
                                 "本批材料不涉及时不写，在 not_covered 里写「通用职责 D1：本批不涉及」；\n", "")
                        .replace("- needs_external：这条是否必须独立查证（例如库里到底有没有、数据源是否真缺失）才判得了；",
                                 "- external_fact：只有当这条的对错取决于运行记录以外的事实（例如知识库里到底有没有、数据源是否真缺失）时，"
                                 "写出那件具体要查的事实；运行记录本身就能判的（调用有没有报错、返回的是不是所请求的对象、参数和原文是否一致）留空；"
                                 "运行记录里的任何内容（包括本批没给出的步骤、调用、交付记录）都不算外部事实，本批看不到的写进 not_covered；"
                                 "「若不存在则返回空才算对」这类条件句不写：只有这条无论记录里显示什么，都得靠外部事实才能判对错时才写"))
    PE.ACTUAL_TASK = PE.ACTUAL_TASK.replace("- needs_external=是 的条目由程序锁成无法核；", "- 写了 external_fact 的条目由程序锁成无法核；")
    PE.STANDING_DUTIES = {}
    PE.settle = settle_external
    original_entry = process_common._scenario_entry

    def entry(runtime):
        e = dict(original_entry(runtime) or {})
        e["process_obligations"] = list(e.get("process_obligations") or []) + OBLIGATIONS
        return e
    process_common._scenario_entry = entry

    def judge_batch(*args, **kwargs):  # 项目声明子能力按（轮，子能力）取值，替代 D 编号的通用职责
        batch = ORIGINAL_JUDGE(*args, **kwargs)
        batch["duties"] = {item["id"]: item["subcapability"] for item in batch["expected"]["expected"]
                           if item["subcapability"].startswith("项目声明")}
        return batch
    PE.judge_batch = judge_batch
    assert "通用职责" not in PE.EXPECTED_TASK and "external_fact" in PE.EXPECTED_TASK and "external_fact" in PE.ACTUAL_TASK


def restore():
    for k, v in SAVED.items():
        setattr(PE, k, v)
    process_common._scenario_entry = SAVED_ENTRY
    process_common.build_links = L.build_links


# ---- 运行 ------------------------------------------------------------------------------------

def load(case):
    (rj,) = db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%' "
                       "AND json_extract(run_json,'$.case_id') LIKE ?", (f"%{case}%",)).fetchone()
    rj = json.loads(rj)
    return rj, {r["type_id"]: r for r in rj["eval_axes"]["results"]}


def judge(case, axis_id, rj, res, e, tag, spec):
    analysis = copy.deepcopy(res["trace_analysis"]["output"])
    prepare_selections(analysis["dossier"], analysis["structure"], analysis["selections"])
    runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                              trace_id=f"exp7:{tag}:{case}:{axis_id}:{time.time():.0f}", ensure_time_left=lambda *_: None)
    started = time.monotonic()
    try:
        o = PE.run_expected_axis(axis_id, {"trace_analysis": analysis, "expectations": e}, None, runtime, spec).output
    except Exception as exc:  # 评测器错误照实记下，不中断其余组
        return {"verdict": "evaluator_error", "error": f"{type(exc).__name__}: {exc}", "counts": {}, "issues": [], "rows": [],
                "elapsed": round(time.monotonic() - started)}
    comp = o["assessment"]["composition"]
    return {"verdict": o["assessment"]["verdict"], "counts": comp["counts"], "demoted": comp["demoted"], "standing_duties": comp["standing_duties"],
            "batches": o["view"]["batches"], "failed": o["view"]["failed_batches"],
            "issues": [i["phenomenon"] for i in o["issues"]], "not_covered": comp["not_covered"],
            "rows": [(r["batch"], r["turn"], r["id"], r["verdict"], r["statement"], r.get("observed", "")) for r in o["results"]],
            "elapsed": round(time.monotonic() - started)}


def save(rec):
    global results
    results = [r for r in results if (r["exp"], r["case"], r["axis"]) != (rec["exp"], rec["case"], rec["axis"])] + [rec]
    json.dump(results, open(path, "w"), ensure_ascii=False, indent=1)


def needs_for(case, rj, res):
    """同一 case 两种做法共用一份每轮需求：实验 6 写过的直接用，否则写一次并存档。"""
    stored_e = res["expectations"]["output"]
    old = next((r["expectations"] for r in json.load(open(f"{OUT}/exp6_results.json")) if r["case"] == case), None) \
        or next((r["expectations"] for r in results if r["case"] == case and r.get("expectations")), None)
    if old is None:
        runtime = SimpleNamespace(spec=project, scenario_id=rj["eval_axes"].get("scenario_id"),
                                  trace_id=f"exp7:needs:{case}:{time.time():.0f}", ensure_time_left=lambda *_: None)
        old = expectations.run({"requirements": {"sources": stored_e["sources"], "missing": stored_e["missing"],
                                                 "sha256": stored_e["material_sha256"]}}, None, runtime).output["expectations"]
    return {**stored_e, "expectations": old}


def proposed_spec(axis_id):
    return cumulative_intent_spec() if axis_id == "intent_understanding" else PROCESS_SPECS[axis_id]


def show(case, axis_id, tag, r):
    print(case, axis_id, tag, r["verdict"], r["counts"], r.get("standing_duties") or "", r.get("error") or "", flush=True)


if MODE == "intent":
    for case in ARG.split(","):
        rj, res = load(case)
        e = needs_for(case, rj, res)
        rec = {"exp": "intent", "case": case, "axis": "intent_understanding", "expectations": e["expectations"],
               "stored": res["intent_understanding"]["output"]["assessment"]["verdict"]}
        restore()
        rec["now"] = judge(case, "intent_understanding", rj, res, e, "intent-now", PROCESS_SPECS["intent_understanding"])
        process_common.build_links = build_links_cumulative
        rec["cumulative"] = judge(case, "intent_understanding", rj, res, e, "intent-cum", cumulative_intent_spec())
        save(rec)
        for k in ("now", "cumulative"):
            show(case, "intent_understanding", k, rec[k])
elif MODE == "compare":
    # 现行 vs 提议（7a 累计意图材料 + 7b 收紧的 external_fact + 7c 项目声明按轮取值），同一份需求；
    # 实验 6 已有的（case, 轴）现行结果直接复用（需求与代码都相同）。
    exp6 = {(r["case"], r["axis"]): r["new"] for r in json.load(open(f"{OUT}/exp6_results.json"))}
    for case, axes in (p.split(":") for p in ARG.split(";")):
        rj, res = load(case)
        e = needs_for(case, rj, res)
        for axis_id in axes.split(","):
            prev = next((r for r in results if (r["exp"], r["case"], r["axis"]) == ("compare", case, axis_id)), {})
            rec = {"exp": "compare", "case": case, "axis": axis_id, "expectations": e["expectations"],
                   "stored": res[axis_id]["output"]["assessment"]["verdict"]}
            restore()
            rec["current"] = prev.get("current") or exp6.get((case, axis_id)) or judge(case, axis_id, rj, res, e, "cur", PROCESS_SPECS[axis_id])
            show(case, axis_id, "current", rec["current"])
            apply_proposed()
            process_common.build_links = build_links_cumulative
            rec["proposed"] = judge(case, axis_id, rj, res, e, "prop", proposed_spec(axis_id))
            show(case, axis_id, "proposed", rec["proposed"])
            restore()
            save(rec)
print("done")
