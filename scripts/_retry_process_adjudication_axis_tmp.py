"""Retry one failed process axis using an already completed organizer selection."""
from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from impl.core.config import get_runtime_config
from impl.core.project_loader import load_project
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from impl.projects.llm_probe.eval_axes.adapters.process_common import run_process_axis
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from scripts._replay_process_adjudication_tmp import DATABASE, OUTPUT, _cases, _trace

AXES = {"intent_understanding", "planning_routing", "tool_execution", "context_memory",
        "knowledge_data", "model_capability"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case")
    parser.add_argument("axis", choices=sorted(AXES))
    args = parser.parse_args()
    config = get_runtime_config()
    same_model = [config.llm, *(item for item in config.llm.fallbacks if item.model == config.llm.model)]
    if config.eval_axes.model_policy != "same_model" or any(
        urlsplit(item.base_url).hostname != "8.148.158.241" for item in same_model
    ):
        raise ValueError("本次回放仅获批 8.148.158.241，且必须设置 EVAL_AXES_MODEL_POLICY=same_model")
    source_path = OUTPUT / f"{args.case}--{args.axis}.json"
    if not source_path.exists():
        source_path = OUTPUT / f"{args.case}.json"
    saved = json.loads(source_path.read_text())
    analysis = next(item for item in saved["axes"]["results"] if item["type_id"] == "trace_analysis")
    if analysis.get("status") != "succeeded" or analysis.get("verdict") != "complete":
        raise ValueError("整理轴未成功，不可复用其选材")
    case = _cases()[args.case]
    with sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        trace, run_ids = _trace(connection, case)
        if run_ids != saved["source_run_ids"]:
            raise ValueError("本地原始运行与整理时不同")
        dossier = build_dossier(trace, trace.project_fields["business_trace"])
    spec = importlib.import_module(f"impl.projects.llm_probe.eval_axes.adapters.{args.axis}").SPEC
    axis_description = next((item.get("description") or "" for item in saved["axes"]["axes"]
                             if item.get("type_id") == args.axis), "")
    source = dict(analysis["output"], dossier=dossier)
    started = time.monotonic()
    try:
        outcome = run_process_axis(args.axis, {"trace_analysis": source},
                                   ScenarioAxis(args.axis, True, axis_description),
                                   SimpleNamespace(spec=load_project("llm_probe"), trace_id=trace.trace_id,
                                                   ensure_time_left=lambda _axis: None), spec)
        result = {"case": args.case, "axis": args.axis, "source_run_ids": run_ids,
                  "organizer_run_id": saved["axes"]["run_id"],
                  "seconds": round(time.monotonic() - started, 1),
                  "verdict": outcome.output["assessment"]["verdict"],
                  "output": outcome.output, "usage": outcome.usage}
    except Exception as exc:
        result = {"case": args.case, "axis": args.axis, "source_run_ids": run_ids,
                  "organizer_run_id": saved["axes"]["run_id"],
                  "seconds": round(time.monotonic() - started, 1),
                  "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    path = OUTPUT / f"retry-{args.case}-{args.axis}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result.get(key) for key in ("case", "axis", "seconds", "verdict", "error")},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
