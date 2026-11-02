"""One-off replay of the frozen process-eval samples through the current Judge.

Samples: report/business-trace-agno-20260913/snapshots (5) + report/process-dossier-20260920/clean-traces (25 sessions).
Frozen traces only: no business backend call. Resumable, so a later Judge change can be re-run on the same batch.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from impl.core.project_loader import load_project
from impl.core.schema import RunTrace, normalize_run_trace, to_dict
from impl.projects.llm_probe.judge import LlmProbeJudge

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "report/business-trace-agno-20260913/snapshots"
CLEAN = ROOT / "report/process-dossier-20260920/clean-traces"
OUT = ROOT / "report/process-dossier-20260920/results"


def _frozen_trace(path: Path) -> RunTrace:
    snapshot = json.loads(path.read_text())
    run = snapshot["records"]["run"]
    request = run.get("run_input") if isinstance(run.get("run_input"), dict) else {}
    return RunTrace(
        trace_id=f"replay-{path.stem}", project_id="llm_probe", case_id=f"frozen-{path.stem[5:]}",
        normalized_request={"capability_ref": "insurance-agno-e2e",
                            "body": request.get("body") or {"messages": [{"role": "user", "content": str(run.get("run_input") or "")}]}},
        extracted_output={"output_text": run.get("content")},
        project_fields={"business_trace": snapshot},
    )


def samples(kind: str) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    if kind in {"all", "frozen"}:
        found += [("frozen", path) for path in sorted(FROZEN.glob("snap-*.json"))]
    if kind in {"all", "clean"}:
        found += [("clean", path) for path in sorted(CLEAN.glob("*.json"))]
    return found


def replay(name: str, path: Path, force: bool) -> dict:
    target = OUT / f"{name}.json"
    if target.exists() and not force:
        return {"name": name, "status": "skipped"}
    started = time.time()
    try:
        spec = load_project("llm_probe")
        trace = _frozen_trace(path) if path.parent == FROZEN else normalize_run_trace(json.loads(path.read_text()))
        result = LlmProbeJudge(spec).judge_trace(trace)
        report = getattr(trace, "_pending_process_report", None)
        OUT.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"name": name, "sample": str(path), "judge": to_dict(result),
                                      "axes": report, "elapsed_seconds": round(time.time() - started, 1)},
                                     ensure_ascii=False, indent=2))
        axes = {r["type_id"]: (r.get("verdict") or r.get("status")) for r in (report or {}).get("results", [])}
        return {"name": name, "status": "done", "seconds": round(time.time() - started, 1),
                "fulfillment": (result.overall_fulfillment or {}).get("status"), "axes": axes}
    except Exception as exc:  # keep going: one sample must not stop the batch
        OUT.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"name": name, "sample": str(path), "error": f"{type(exc).__name__}: {exc}",
                                      "traceback": traceback.format_exc(),
                                      "elapsed_seconds": round(time.time() - started, 1)}, ensure_ascii=False, indent=2))
        return {"name": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("all", "frozen", "clean"), default="all")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--only", default="", help="逗号分隔的样本名子串过滤")
    parser.add_argument("--out", default="", help="输出目录（默认 report/process-dossier-20260920/results）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    global OUT
    if args.out:
        OUT = Path(args.out).resolve()
    wanted = samples(args.kind)
    if args.only:
        needles = [x.strip() for x in args.only.split(",") if x.strip()]
        wanted = [(kind, path) for kind, path in wanted if any(n in path.stem for n in needles)]
    jobs = [(f"{kind}--{path.stem}", path) for kind, path in wanted]
    print(f"{len(jobs)} samples, workers={args.workers}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(replay, name, path, args.force): name for name, path in jobs}
        for future in as_completed(futures):
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
