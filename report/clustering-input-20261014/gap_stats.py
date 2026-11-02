"""现行聚类输入（过程轴只送问题记录）漏掉了什么：逐 case×轴 统计。只读 latest_runs。"""
import json, sqlite3, collections
ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
AX = ["intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability", "context_memory"]
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
cells = collections.Counter(); rows_lost = collections.Counter(); examples = collections.defaultdict(list)
for pos, axes in db.execute("SELECT position, json_extract(run_json,'$.table_row.eval_axes_summary') FROM current_cases "
                            "WHERE project='llm_probe' AND request_key IS NOT NULL ORDER BY position"):
    for s in json.loads(axes):
        a = s.get("type_id")
        if a not in AX:
            continue
        if s.get("status") != "succeeded":
            cells["失败（整轴不进聚类）"] += 1; examples["失败"].append((pos, a, (s.get("error") or s.get("text") or "")[:80])); continue
        items = s["items"] if isinstance(s["items"], list) else json.loads(s["items"])
        c = collections.Counter(i["value"] for i in items)
        n = len(s.get("issues") or [])
        key = f"{s['verdict']} / {'有问题记录' if n else '无问题记录'}"
        cells[key] += 1
        rows_lost["无法核条目（任何情况都不进）"] += c["无法核"]
        rows_lost["没达到条目（经问题记录进）"] += c["没达到"]
        if not n:
            rows_lost["整轴结论文字未进（无问题记录的轴）"] += 1
            if s["verdict"] == "not_evaluable" and len(examples["无法评估且无问题"]) < 6:
                examples["无法评估且无问题"].append((pos, a, s.get("text", "")[:160]))
        if n and s["verdict"] == "not_evaluable" and len(examples["无法评估且有问题"]) < 3:
            examples["无法评估且有问题"].append((pos, a, s.get("text", "")[:160]))
print("case×过程轴 共", sum(cells.values()))
for k, v in sorted(cells.items()): print(" ", k, v)
for k, v in rows_lost.items(): print(" ", k, v)
for k, v in examples.items():
    print("##", k)
    for e in v: print("   ", e)
