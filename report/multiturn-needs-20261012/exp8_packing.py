"""实验 8（离线，不调模型）：同一轮的环节怎么装批更省。

seq —— 现行：按环节顺序往一批里装，装不下就另起一批（prepare_axis_materials）。
ffd —— 先装大的：按单个环节材料大小从大到小，放进第一个还装得下的批（装得下 = 合起来的实际材料不超过预算，
       同批共享的正文只算一次）；批内环节恢复原顺序。
all —— 下界参考：整轮所有环节放一批时的材料字数（同一正文只算一次）；ceil(all / 预算) 是不可能再少的批数。
重复 = 各批材料字数之和 / all：>1 的部分就是同一正文在不同批里重复发送。

范围：fec 批 32 道题 × 6 轴，按轮分组（与 turn_batches 相同）。结果写 exp8_results.json。
"""
import copy, json, math, sqlite3, sys
from collections import defaultdict

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.projects.llm_probe.business_trace.dossier import VIEW_BUDGET_CHARS
from impl.projects.llm_probe.business_trace.materials import material_view, model_material, prepare_axis_materials
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as TA
from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links

AXES = ["intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability", "context_memory"]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)


def size_fn(dossier, suspects):
    shared = len(json.dumps(model_material(material_view(dossier, [], suspects)), ensure_ascii=False))
    return lambda links: len(json.dumps(model_material(material_view(dossier, links, suspects)), ensure_ascii=False)) - shared


def ffd(links, size, budget=VIEW_BUDGET_CHARS):
    order = {l["link_id"]: k for k, l in enumerate(links)}
    bins = []
    for link in sorted(links, key=lambda l: -size([l])):
        for b in bins:
            if size(b + [link]) <= budget:
                b.append(link)
                break
        else:
            bins.append([link])
    return [sorted(b, key=lambda l: order[l["link_id"]]) for b in bins]


def turn_groups(axis_id, dossier, structure):
    """与 trace_analysis.turn_batches 相同的按轮分组。"""
    records = dossier.get("records") or []
    turns = sorted({TA._turn_no(r.get("id", "")) for r in records} - {None}) or [1]
    owners = {}
    for record in records:
        turn = TA._turn_no(record.get("id", ""))
        for token in set(TA.re.findall(r"content#\d+", json.dumps(record.get("fields") or {}, ensure_ascii=False))):
            if turn:
                owners.setdefault(token, set()).add(turn)
    groups = defaultdict(list)
    for link in _axis_links(axis_id, dossier, structure):
        groups[TA._link_turn(link, owners, turns)].append(link)
    return groups


rows = []
for (rj,) in db.execute("SELECT run_json FROM current_cases WHERE project='llm_probe' AND request_key LIKE 'fec27623%'"):
    rj = json.loads(rj)
    res = {r["type_id"]: r for r in rj["eval_axes"]["results"]}
    if not (res.get("trace_analysis") or {}).get("output"):
        continue
    a = copy.deepcopy(res["trace_analysis"]["output"])
    dossier, structure = a["dossier"], a["structure"]
    multi = len(dossier.get("sources") or []) > 1
    suspects = list(structure.get("suspects") or [])
    size = size_fn(dossier, suspects)
    for axis_id in AXES:
        for turn, links in turn_groups(axis_id, dossier, structure).items():
            seq = [b["links"] for b in prepare_axis_materials(dossier, links, suspects)]
            packed = ffd(links, size)
            whole = size(links)
            rows.append({"case": rj["case_id"].split("main-")[-1], "multi": multi, "axis": axis_id, "turn": turn,
                         "links": len(links), "whole": whole, "lower": max(1, math.ceil(whole / VIEW_BUDGET_CHARS)),
                         "seq": [size(b) for b in seq], "ffd": [size(b) for b in packed]})
    print(rj["case_id"].split("main-")[-1], flush=True)

json.dump(rows, open(f"{ROOT}/report/multiturn-needs-20261012/exp8_results.json", "w"), ensure_ascii=False, indent=1)
for multi in (False, True):
    for axis_id in AXES + ["合计"]:
        rs = [r for r in rows if r["multi"] == multi and (axis_id == "合计" or r["axis"] == axis_id)]
        print("多轮" if multi else "单轮", axis_id.ljust(20),
              "批 seq", sum(len(r["seq"]) for r in rs), "ffd", sum(len(r["ffd"]) for r in rs), "下界", sum(r["lower"] for r in rs),
              "| 千字 seq", sum(sum(r["seq"]) for r in rs) // 1000, "ffd", sum(sum(r["ffd"]) for r in rs) // 1000,
              "不重复", sum(r["whole"] for r in rs) // 1000)
