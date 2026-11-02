"""同一批数据、同一聚类提示词与标准，只换过程轴送进聚类的记录，对照聚类效果。只读 latest_runs，不写库。
A 现行：过程轴只送问题记录（每条问题一条）。
B 通用：过程轴与其他轴一样，每个 case×轴 一条，reason = 整轴结论文字（含组成）。
C 混合：有问题记录的轴照 A；没有问题记录的轴补一条整轴结论文字；判定失败的轴补一条失败原因（标签 failed）。
D 精简混合：同 C，但判为 sound 且没有问题记录的轴不补（只补无法评估且无问题记录的轴与失败的轴）。
用法：ONLY_MODEL=deepseek-flash python variants.py A|B|C|D   结果写 variant_<X>.json
ONLY_MODEL 设了时，路由只保留这个模型的端点（不降级到别的模型），保证各方案模型一致。
"""
import json, sqlite3, sys, time
ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core import axes_clustering as ac
from impl.server import service
from impl.core import llm_router
import os

ONLY = os.environ.get("ONLY_MODEL")
if ONLY:
    _init = llm_router.LlmRouter.__init__

    def _only(self, endpoints, *args, **kwargs):
        kept = [e for e in endpoints if e.model == ONLY]
        assert kept, f"没有 {ONLY} 端点"
        _init(self, kept, *args, **kwargs)

    llm_router.LlmRouter.__init__ = _only

AX = ["intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability", "context_memory"]
mode = sys.argv[1]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
types = {t["type_id"]: t for t in service.eval_axes_types({"project": "llm_probe"})["types"]}
criteria = db.execute("SELECT criteria FROM axis_clustering WHERE project='llm_probe'").fetchone()[0]
axes, refs = {}, {}


def add(axis_id, value, pos, rk, record, issue_id=None):
    t = types[axis_id]
    axis = axes.setdefault(axis_id, {"axis_id": axis_id, "title": t.get("title") or axis_id,
                                     "description": t.get("summary") or "", "labels": {}})
    desc = {v["value"]: v.get("description") or "" for v in t.get("verdict_enum") or []}
    label = axis["labels"].setdefault(value, {"value": value, "description": desc.get(value, "评测器没有产出结论"), "records": []})
    ref = f"R{len(refs) + 1}"
    label["records"].append({"ref": ref, "case_ref": f"C{pos + 1}", **record})
    refs[ref] = {"pool_index": pos, "request_key": rk, "axis_id": axis_id, "value": value, "issue_id": issue_id}


for pos, rk, raw in db.execute("SELECT position, request_key, json_extract(run_json,'$.table_row.eval_axes_summary') FROM current_cases "
                               "WHERE project='llm_probe' AND request_key IS NOT NULL ORDER BY position"):
    for s in json.loads(raw):
        a = s.get("type_id")
        if a not in AX:
            continue
        if s.get("status") != "succeeded":
            if mode in ("C", "D"):
                add(a, "failed", pos, rk, {"reason": "评测器失败：" + (s.get("error") or s.get("text") or "")})
            continue
        issues = s.get("issues") or []
        if mode == "D" and not issues and s["verdict"] == "sound":
            continue
        if mode == "B" or (mode in ("C", "D") and not issues):
            add(a, str(s["verdict"]), pos, rk, {"reason": s.get("text") or ""})
            continue
        for issue in issues:
            add(a, str(s["verdict"]), pos, rk, {"reason": issue["phenomenon"] + "；预期：" + issue["expected"] + "；实际：" + issue["observed"],
                                                "subject": issue["problem_id"], "issue": issue}, issue["problem_id"])

material = {"axes": [{**x, "labels": list(x["labels"].values())} for x in axes.values()], "refs": refs}
print(mode, "records", len(refs), "chars", len(json.dumps(material["axes"], ensure_ascii=False)), flush=True)
_validate = ac.validate_result


def validate_logged(result, material):
    """校验失败时记下漏了哪些记录，方便看是哪类记录被漏。"""
    given = {(a["axis_id"], l["value"]): {r["ref"] for r in l["records"]} for a in material["axes"] for l in a["labels"]}
    got = {}
    for a in result.get("axes") or []:
        for l in a.get("labels") or []:
            got[(a["axis_id"], l["value"])] = {m for c in l.get("clusters") or [] for m in c.get("member_refs") or []}
    missing = {f"{k[0]}/{k[1]}": sorted(v - got.get(k, set())) for k, v in given.items() if v - got.get(k, set())}
    json.dump({"missing": missing, "result": result}, open(f"{ROOT}/report/clustering-input-20261014/variant_{mode}_raw.json", "w"),
              ensure_ascii=False, indent=1)
    print("missing", {k: len(v) for k, v in missing.items()}, flush=True)
    return _validate(result, material)


ac.validate_result = validate_logged
started = time.monotonic()
result = ac.cluster_with_llm("llm_probe", criteria, material)
result["elapsed_s"] = round(time.monotonic() - started)
result["material_axes"] = material["axes"]
json.dump(result, open(f"{ROOT}/report/clustering-input-20261014/variant_{mode}.json", "w"), ensure_ascii=False, indent=1)
print(mode, "done", result["elapsed_s"], "s model", result.get("model"), flush=True)
