"""临时：把网关日志里已有的 llmtracing 执行切成快照，套进 RunTrace，跑一遍过程评估（只调评判模型，不调业务）。"""
from __future__ import annotations

import copy, json, os, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier")
sys.path.insert(0, str(ROOT))
from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace, to_dict
from impl.projects.llm_probe.business_trace import collect
from impl.projects.llm_probe.capability import capability_business_trace
from impl.projects.llm_probe.judge import LlmProbeJudge

OUT = ROOT / "report/business-trace-llmtracing-judge-20261001"
TEMPLATE = sorted((ROOT / "report/process-dossier-20260920/clean-traces").glob("*.json"))[0]
FROZEN = ROOT / "report/business-trace-agno-20260913/snapshots"
CASES = {  # case_id -> executions in turn order
    "llm-probe-insurance-real-smoke-policy-list-fuyunping-llmtracing": ["9adecc64"],
    "llm-probe-insurance-real-smoke-customer-profile-fuyunping-llmtracing": ["029a92bd"],
    "llm-probe-insurance-real-main-E04-carry-second-status-llmtracing": ["9f2c1689", "64fa5cb4"],
}


def _executions(log: str, start: int) -> dict[str, str]:
    found = {}
    with open(log, "rb") as f:
        f.seek(start); f.readline()
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("execution_id"):
                found.setdefault(e["execution_id"][:8], e["execution_id"])
    return found


def _last_user(snap: dict) -> str:
    msgs = (snap["records"]["calls"][0].get("pre") or {}).get("messages") or []
    return next(str(m.get("content")) for m in reversed(msgs) if m.get("role") == "user")


def _final_text(snap: dict) -> str:
    out = snap["records"]["calls"][-1].get("outcome") or {}
    return str((((out.get("response") or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def llmtracing_trace(case_id: str, prefixes: list[str]):
    cfg = capability_business_trace("insurance-llmtracing"); log = cfg["config"]["log_path"]
    start = max(0, os.path.getsize(log) - 60_000_000)
    full = _executions(log, start)
    base = json.loads(TEMPLATE.read_text())
    turn_tpl = base["turn_records"][0]
    turns = []
    for i, prefix in enumerate(prefixes):
        snap = collect(cfg, request={}, response={}, association={
            "method": "explicit_headers", "run_id": "replay", "case_id": case_id,
            "execution_id": full[prefix], "log_path": log, "log_offset": start})
        assert snap["status"] == "succeeded" and snap["records"]["calls"], (case_id, prefix, snap["status"])
        request = copy.deepcopy(turn_tpl["request"])
        request["capability_ref"] = "insurance-llmtracing"
        request["body"]["messages"] = [{"role": "user", "content": _last_user(snap)}]
        turn = copy.deepcopy(turn_tpl) | {
            "turn_index": i + 1, "mock_message": request["body"]["messages"][0]["content"], "request": request,
            "extracted_output": {"output_text": _final_text(snap)}, "project_fields": {"business_trace": snap}}
        turn.pop("live_exchanges", None); turn.pop("raw_response", None)
        turns.append(turn)
    trace = base | {"trace_id": f"replay-{case_id}", "case_id": case_id, "normalized_request": turns[0]["request"],
                    "input": turns[0]["request"], "extracted_output": turns[-1]["extracted_output"],
                    "project_fields": turns[-1]["project_fields"], "turn_records": turns,
                    "conversation_transcript": [], "conversation_summary": None, "final_output_turn": len(turns),
                    "scenario": "insurance-llmtracing", "mock_intent": None}
    return normalize_run_trace(trace)


def agno_trace(path: Path):
    snapshot = json.loads(path.read_text())
    run = snapshot["records"]["run"]
    request = run.get("run_input") if isinstance(run.get("run_input"), dict) else {}
    from impl.core.schema import RunTrace
    return RunTrace(trace_id=f"replay-{path.stem}", project_id="llm_probe", case_id=f"frozen-{path.stem[5:]}",
                    normalized_request={"capability_ref": "insurance-agno-e2e",
                                        "body": request.get("body") or {"messages": [{"role": "user", "content": str(run.get("run_input") or "")}]}},
                    extracted_output={"output_text": run.get("content")}, project_fields={"business_trace": snapshot})


def run(name: str, build) -> dict:
    target = OUT / f"{name}.json"
    if target.exists():
        return {"name": name, "status": "skipped"}
    started = time.time()
    try:
        trace = build()
        result = LlmProbeJudge(load_project("llm_probe")).judge_trace(trace)
        report = getattr(trace, "_pending_process_report", None)
        payload = {"name": name, "judge": to_dict(result), "axes": report, "elapsed_seconds": round(time.time() - started, 1)}
        status = {"name": name, "status": "done", "seconds": payload["elapsed_seconds"],
                  "axes": {r["type_id"]: (r.get("verdict") or r.get("status")) for r in (report or {}).get("results", [])}}
    except Exception as exc:
        payload = {"name": name, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
        status = {"name": name, "status": "error", "error": payload["error"]}
    OUT.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    jobs = [(f"llmtracing--{c.split('real-')[1]}", lambda c=c, p=p: llmtracing_trace(c, p)) for c, p in CASES.items()]
    jobs += [(f"agno--{n}", lambda n=n: agno_trace(FROZEN / f"{n}.json")) for n in ("snap-policy-with-data", "snap-multi-turn")]
    if sys.argv[1:] == ["--build-only"]:
        for name, build in jobs:
            t = build(); print(name, len(t.turn_records or []), (t.normalized_request or {}).get("capability_ref"))
        sys.exit(0)
    print(f"{len(jobs)} samples", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(run, n, b) for n, b in jobs]):
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)
