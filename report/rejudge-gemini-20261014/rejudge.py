"""用工作区现行代码、只用一个模型，对库里已存的业务记录离线重判（不写回库）。

业务记录 = 当前实例 current_cases 里的 32 条（批次 c7a504df + f763d7da，原先由 qwen/deepseek 判）。
每条走正式入口 eval_axes.build_report（过程案卷 → 需求 → 六轴），业务 Trace 用记录里固化的快照。
用法：ONLY_MODEL=gemini-3.8-flash-medium python rejudge.py   结果写 cases/<pos>.json，已有的跳过（可续跑）。
"""
import json, os, sqlite3, sys, time

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core import llm_router

ONLY = os.environ["ONLY_MODEL"]
_init = llm_router.LlmRouter.__init__


def _only(self, endpoints, *args, **kwargs):
    kept = [e for e in endpoints if e.model == ONLY]
    assert kept, f"没有 {ONLY} 端点"
    _init(self, kept, *args, **kwargs)


llm_router.LlmRouter.__init__ = _only

from impl.core.project_loader import load_project
from impl.server.service import normalize_run_trace
from impl.projects.llm_probe.eval_axes import build_report

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")
db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
rows = db.execute("SELECT position, run_json FROM current_cases WHERE project='llm_probe' AND run_json IS NOT NULL "
                  "ORDER BY position").fetchall()
spec = load_project("llm_probe")
for pos, rj in rows:
    path = f"{OUT}/{pos}.json"
    if os.path.exists(path):
        continue
    run = json.loads(rj)
    started = time.monotonic()
    try:
        report = build_report(spec, normalize_run_trace(run["trace"]))
        error = ""
    except Exception as exc:  # 整条没跑成也记下来，不中断其余
        report, error = None, f"{type(exc).__name__}: {exc}"
    elapsed = round(time.monotonic() - started)
    json.dump({"pos": pos, "case_id": run["case_id"], "request_key": run["request_key"], "model": ONLY,
               "elapsed": elapsed, "error": error, "report": report}, open(path, "w"), ensure_ascii=False)
    status = {r["type_id"]: (r.get("verdict") or r["status"]) for r in (report or {}).get("results", [])}
    print(pos, run["case_id"], elapsed, "s", error or status, flush=True)
print("done")
