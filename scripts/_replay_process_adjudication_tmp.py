"""Replay the 2026-09-24 adjudicated cases from local SQLite, without business calls.

The workbook supplies the captured final caller output. Agno runs and spans are read
from SQLite; the HTTP trace API was unavailable, so its trace tree is reconstructed
from persisted parent span IDs and explicitly marked partial. Only build_report
contacts the configured LLM. This script does not contact the insurance backend.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import openpyxl

from impl.core.project_loader import load_project
from impl.core.config import get_runtime_config
from impl.core.schema import RunTrace
from impl.projects.llm_probe.eval_axes import build_report
from impl.projects.llm_probe.eval_axes.runner import new_run_id, run_axes
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "report/process-axes-optimization-20260926/adjudication-oracle.json"
WORKBOOK = Path("/Users/xiaozijian/Downloads/verifier-llm_probe-cases-20260924-212317.xlsx")
DATABASE = Path("/Users/xiaozijian/.insurance-qa-agent-real/runtime-real.db")
OUTPUT = ROOT / "report/process-axes-optimization-20260926/live-adjudicated"
DATE_START, DATE_END = 1790250000, 1790260000


def _answer(value: str) -> str:
    try:
        return str(json.loads(value).get("answer") or "")
    except (TypeError, ValueError, AttributeError):
        return ""


def _cases() -> dict[str, dict]:
    codes = {case for item in json.loads(ORACLE.read_text())["assertions"] for case in item["cases"]}
    sheet = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)["用例池候选区"]
    found: dict[str, dict] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        case_id = str(row[0] or "")
        code = next((item for item in codes if f"-{item}-" in case_id), None)
        if code:
            found[code] = {"case_id": case_id, "request": json.loads(row[4]),
                           "output": json.loads(row[5])}
    if set(found) != codes:
        raise ValueError(f"裁定用例未完整对应到工作簿：{sorted(codes - set(found))}")
    return found


def _spans(connection: sqlite3.Connection, run_id: str) -> tuple[list[dict], list[dict]]:
    traces, raw_spans = [], []
    for trace in connection.execute("SELECT * FROM agno_traces WHERE run_id=?", (run_id,)):
        nodes: dict[str, dict] = {}
        roots: list[dict] = []
        for row in connection.execute("SELECT * FROM agno_spans WHERE trace_id=? ORDER BY start_time,span_id",
                                      (trace["trace_id"],)):
            span = dict(row)
            attributes = json.loads(span["attributes"] or "{}")
            raw_spans.append(span | {"attributes": attributes})
            kind = str(attributes.get("openinference.span.kind") or span["span_kind"] or "").upper()
            metadata: dict = {}
            if kind == "AGENT":
                metadata["run_id"] = attributes.get("agno.run.id")
            elif kind == "LLM":
                metadata = {"model": attributes.get("llm.model_name"),
                            "input_tokens": attributes.get("llm.token_count.prompt"),
                            "output_tokens": attributes.get("llm.token_count.completion")}
            elif kind == "TOOL":
                metadata["parameters"] = attributes.get("tool.parameters")
            nodes[span["span_id"]] = {
                "id": span["span_id"], "name": span["name"], "type": kind,
                "status": span["status_code"], "start_time": span["start_time"],
                "end_time": span["end_time"], "input": attributes.get("input.value"),
                "output": attributes.get("output.value"), "metadata": metadata,
                "spans": [], "_parent": span["parent_span_id"],
            }
        for node in nodes.values():
            parent = node.pop("_parent")
            (nodes[parent]["spans"] if parent in nodes else roots).append(node)
        traces.append({"trace_id": trace["trace_id"], "run_id": run_id,
                       "session_id": trace["session_id"], "tree": roots})
    return traces, raw_spans


def _snapshot(connection: sqlite3.Connection, row: sqlite3.Row, history: list[dict]) -> dict:
    run = json.loads(row["run_data"])
    traces, raw_spans = _spans(connection, row["run_id"])
    records = {"run": run, "history_runs": history, "traces": traces, "raw_spans": raw_spans}
    return {
        "schema_version": 1, "provider": "agno", "status": "partial",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "association": {"method": "workbook answer + sqlite session/run IDs", "run_id": row["run_id"],
                        "session_id": row["session_id"], "user_id": row["user_id"]},
        "history_coverage": {"status": "partial", "reason": "同一会话此前的 SQLite run 已采集；AgentOS HTTP 的会话快照未采集"},
        "records": records, "errors": ["AgentOS HTTP Trace API unavailable; tree reconstructed from SQLite spans"],
        "fingerprint": hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }


def _trace(connection: sqlite3.Connection, case: dict) -> tuple[RunTrace, list[str]]:
    target = _answer(case["output"]["output_text"])
    if not target:
        raise ValueError("工作簿最终 answer 为空")
    matches = []
    for row in connection.execute("SELECT * FROM agno_runs WHERE created_at BETWEEN ? AND ? AND run_type='workflow'",
                                  (DATE_START, DATE_END)):
        if _answer(json.loads(row["run_data"]).get("content")) == target:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"最终答复在冻结时间窗中匹配 {len(matches)} 条 run，要求恰好一条")
    final = matches[0]
    rows = list(connection.execute("SELECT * FROM agno_runs WHERE session_id=? AND created_at<=? "
                                   "AND run_type='workflow' ORDER BY created_at,run_index",
                                   (final["session_id"], final["created_at"])))
    if not rows or rows[-1]["run_id"] != final["run_id"]:
        raise ValueError("会话最后一轮与工作簿输出不一致")
    turns = []
    history: list[dict] = []
    for index, row in enumerate(rows):
        run = json.loads(row["run_data"])
        delivered = case["output"] if index == len(rows) - 1 else {}
        turns.append({"turn_index": index + 1,
                      "request": {"capability_ref": "insurance-agno-e2e", "body": {
                          "messages": [{"role": "user", "content": run.get("input") or ""}]}},
                      "extracted_output": delivered, "call_status": "succeeded",
                      "project_fields": {"business_trace": _snapshot(connection, row, history)}})
        history.append(run)
    trace = RunTrace(
        trace_id=f"adjudication-replay:{case['case_id']}", project_id="llm_probe", case_id=case["case_id"],
        normalized_request=case["request"], extracted_output=case["output"],
        project_fields={"business_trace": turns[-1]["project_fields"]["business_trace"]},
        turn_records=turns, session_id=final["session_id"], final_output_turn=len(turns),
        interaction_mode="multi_turn" if len(turns) > 1 else "single_turn",
    )
    return trace, [row["run_id"] for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="", help="逗号分隔的裁定用例编号；默认全部九例")
    parser.add_argument("--axis", default="", help="只实测指定过程轴及其上游整理轴")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    if args.axis and args.axis not in {"intent_understanding", "planning_routing", "tool_execution",
                                     "context_memory", "knowledge_data", "model_capability"}:
        raise ValueError(f"未知过程轴：{args.axis}")
    cases = _cases()
    if selected - set(cases):
        raise ValueError(f"未知用例：{sorted(selected - set(cases))}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = get_runtime_config()
    if config.eval_axes.model_policy != "same_model":
        raise ValueError("本次获批端点回放必须设置 EVAL_AXES_MODEL_POLICY=same_model")
    same_model_endpoints = [config.llm, *(item for item in config.llm.fallbacks
                                         if item.model == config.llm.model)]
    if any(urlsplit(item.base_url).hostname != "8.148.158.241" for item in same_model_endpoints):
        raise ValueError("同模型候选包含未获批目的地，拒绝发送 Trace")
    spec = load_project("llm_probe")
    configured_axes, _warnings = load_scenario_axes("llm_probe", "insurance-agno-e2e")
    descriptions = {item.type_id: item.description for item in configured_axes}
    with sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for code, case in cases.items():
            if selected and code not in selected:
                continue
            path = OUTPUT / f"{code}{'--' + args.axis if args.axis else ''}.json"
            if path.exists() and not args.force:
                print(json.dumps({"case": code, "status": "skipped"}), flush=True)
                continue
            start = time.monotonic()
            try:
                trace, run_ids = _trace(connection, case)
                if args.axis:
                    axes = [ScenarioAxis("trace_analysis", True, "完整整理过程案卷"),
                            ScenarioAxis(args.axis, True, descriptions.get(args.axis, ""))]
                    run_id = new_run_id()
                    results = run_axes(spec, trace, axes, scenario_id="insurance-agno-e2e", run_id=run_id)
                    report = {"run_id": run_id, "scenario_id": "insurance-agno-e2e",
                              "trace_id": trace.trace_id, "case_id": trace.case_id,
                              "axes": [item.as_dict() for item in axes],
                              "results": [item.as_dict() for item in results], "warnings": []}
                else:
                    report = build_report(spec, trace)
                # The source remains in SQLite; omit the large duplicated dossier from the saved verdicts.
                for item in report["results"]:
                    if item.get("type_id") == "trace_analysis" and isinstance(item.get("output"), dict):
                        item["output"].pop("dossier", None)
                result = {"case": code, "case_id": case["case_id"], "source_run_ids": run_ids,
                          "source_workbook_sha256": hashlib.sha256(WORKBOOK.read_bytes()).hexdigest(),
                          "capture": "sqlite_only_partial; final delivered output from workbook",
                          "seconds": round(time.monotonic() - start, 1), "axes": report}
            except Exception as exc:
                result = {"case": code, "case_id": case["case_id"], "source_run_ids": [],
                          "seconds": round(time.monotonic() - start, 1),
                          "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            axes = {row["type_id"]: row.get("verdict") or row.get("status")
                    for row in result.get("axes", {}).get("results", [])}
            print(json.dumps({"case": code, "seconds": result["seconds"],
                              "axes": axes, "error": result.get("error")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
