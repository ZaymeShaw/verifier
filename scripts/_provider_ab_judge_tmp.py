"""临时：同一次业务执行分别用 Agno / llmtracing 快照跑评判，只调评判模型。"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace, to_dict
from impl.projects.llm_probe.judge import LlmProbeJudge
OUT = ROOT / "report/business-trace-provider-ab-20261001"
traces = json.loads((OUT / "traces.json").read_text())

def run(name, rep):
    target = OUT / f"{name}-r{rep}.json"
    if target.exists(): return
    started = time.time(); trace = normalize_run_trace(traces[name])
    result = LlmProbeJudge(load_project("llm_probe")).judge_trace(trace)
    target.write_text(json.dumps({"judge": to_dict(result), "axes": getattr(trace, "_pending_process_report", None),
                                  "elapsed_seconds": round(time.time() - started, 1)}, ensure_ascii=False, indent=2))
    print(name, rep, "done", round(time.time() - started), flush=True)

with ThreadPoolExecutor(max_workers=int(sys.argv[1]) if sys.argv[1:] else 2) as pool:
    for f in [pool.submit(run, n, r) for r in (1, 2) for n in ("agno", "llmtracing")]: f.result()
