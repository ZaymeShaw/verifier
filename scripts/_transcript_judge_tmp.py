"""临时：llmtracing 对话稿评测路线的只评判重放（4 次既有执行 + 同执行 A/B 的 llmtracing 侧两次）。不调业务。"""
import json, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace, to_dict
from impl.projects.llm_probe.judge import LlmProbeJudge

OUT = ROOT / "report/business-trace-llmtracing-transcript-20261001"
OUT.mkdir(parents=True, exist_ok=True)
src = (ROOT / "scripts/_replay_llmtracing_judge_tmp.py").read_text().split("\ndef main")[0]
ns = {"__file__": str(ROOT / "scripts/_replay_llmtracing_judge_tmp.py")}
exec(compile(src, "replay", "exec"), ns)
ab = json.loads((ROOT / "report/business-trace-provider-ab-20261001/traces.json").read_text())

JOBS = {cid.split("-real-")[1]: (lambda c=cid, p=pre: ns["llmtracing_trace"](c, p)) for cid, pre in ns["CASES"].items()}
JOBS["customer-profile-0829e857"] = lambda: ns["llmtracing_trace"](
    "llm-probe-insurance-real-smoke-customer-profile-fuyunping-llmtracing", ["0829e857"])
JOBS["ab-llmtracing-r1"] = lambda: normalize_run_trace(ab["llmtracing"])
JOBS["ab-llmtracing-r2"] = lambda: normalize_run_trace(ab["llmtracing"])


def run(name):
    target = OUT / f"{name}.json"
    if target.exists():
        return
    started = time.time()
    try:
        trace = JOBS[name]()
        result = LlmProbeJudge(load_project("llm_probe")).judge_trace(trace)
        body = {"name": name, "judge": to_dict(result), "axes": getattr(trace, "_pending_process_report", None)}
    except Exception:
        body = {"name": name, "error": traceback.format_exc()}
    body["elapsed_seconds"] = round(time.time() - started, 1)
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2))
    print(name, "done", body["elapsed_seconds"], flush=True)


with ThreadPoolExecutor(max_workers=int(sys.argv[1]) if sys.argv[1:] else 2) as pool:
    list(pool.map(run, JOBS))
