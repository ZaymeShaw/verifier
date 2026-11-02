"""把同一批（job fb5fda…）的导出 trace 拆成实验可用的冻结输入。

只做只读抽取：每个 case 一份冻结文件，含
  - records：六轴 prompt 里 dossier_view 的合并结果（每个编号取最完整的一份，shared# 已还原）
  - expectations / expectation_sources：需求轴冻结的 E 与其原文出处
  - projection / expectations_reply / structure：前置三步已记录的输出（实验里复用）
  - axes：六轴每一批的 system / user / 程序上下文 body / 已记录回答
  - calls：该 case 全部 LLM 调用的元信息（model、status、incomplete、usage），用于"实际用了哪个模型"

用法：python extract_cases.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import experiment_io as io

PROCESS_AXES = ("context_memory", "intent_understanding", "planning_routing",
                "tool_execution", "knowledge_data", "model_capability")
PREFIX = "llm_probe_process_"
SUBMIT_STRUCTURE = "submit_structure"


def resolve(value, shared):
    """只还原 shared_ref；字段正文的 JSON 文本是案卷里的原样值，不在这里解码。"""
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return resolve(shared.get(value["shared_ref"]), shared)
        return {k: resolve(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, shared) for v in value]
    return value


def flatten_record(rec, shared):
    """Keep every recorded field; same_as fields are resolved from their sibling body."""
    out = {k: resolve(v, shared) for k, v in rec.items() if k != "fields"}
    fields = {}
    for name, info in (rec.get("fields") or {}).items():
        if not isinstance(info, dict):
            continue
        row = dict(info)
        if "value" in row:
            row["value"] = resolve(row["value"], shared)
        fields[name] = row
    for name, row in fields.items():
        if "value" not in row and row.get("same_as") in fields and "value" in fields[row["same_as"]]:
            row["value"] = fields[row["same_as"]]["value"]
            row["resolved_from"] = row["same_as"]
    out["fields"] = fields
    return out


def parse_json(text):
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        value, _ = json.JSONDecoder().raw_decode(text.lstrip())
        return value
    except ValueError:
        return None


def split_stage(stage):
    if stage.startswith(PREFIX):
        rest = stage[len(PREFIX):]
        for axis in PROCESS_AXES:
            if rest.startswith(axis + "_batch"):
                return axis, int(rest[len(axis) + len("_batch"):])
    return None, None


def call_meta(cl):
    return {"seq": cl.get("seq"), "stage": (cl.get("raw_request") or {}).get("stage"),
            "model": cl.get("model"), "gateway": cl.get("gateway"),
            "status_code": cl.get("status_code"), "state": cl.get("state"),
            "incomplete": cl.get("incomplete"), "stop_reason": cl.get("stop_reason"),
            "error": cl.get("error"), "response_error": cl.get("response_error"),
            "usage": cl.get("usage"), "latency_ms": cl.get("latency_ms")}


def catalog_ids(prompt: str) -> list[str]:
    """trace_analysis 首轮 prompt 的案卷目录：编号按程序采集顺序排列。"""
    head = prompt.split("\n\n", 1)[0]
    return re.findall(r"^\s{2}(\S+) · ", head, re.M)


def ta_artifacts(case):
    """trace_analysis 子循环的全部可复现材料：目录顺序、目录元信息、取回正文、定稿 payload。"""
    ta = {"record_order": [], "catalog": {}, "collect": {}, "timeline": {}, "reads": {}, "submit": None,
          "prompts": []}
    for cl in case["calls"]:
        stage = (cl.get("raw_request") or {}).get("stage") or ""
        if not stage.startswith("trace_analysis:"):
            continue
        messages = ((cl.get("raw_request") or {}).get("client_request") or {}).get("messages") or []
        user = next((m["content"] for m in messages if m["role"] == "user" and m["content"].startswith("## 案卷目录")), None)
        if user and not ta["record_order"]:
            ta["prompts"].append({"stage": stage, "chars": len(user), "text": user})
            ta["record_order"] = catalog_ids(user)
        for m in messages:
            if m["role"] != "tool":
                continue
            try:
                payload = json.loads(m["content"])
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            if isinstance(payload.get("rows"), list):
                ta["timeline"] = {str(r.get("id")): r for r in payload["rows"]}
            for item in payload.get("items") or []:
                if isinstance(item, dict) and item.get("id"):
                    ta["collect"][str(item["id"])] = item.get("text")
            if payload.get("path") and payload.get("id"):
                ta["reads"][f"{payload['id']}{payload['path']}"] = payload.get("text")
        for tool in cl.get("tool_calls") or []:
            if isinstance(tool, dict) and tool.get("name") == SUBMIT_STRUCTURE:
                ta["submit"] = parse_json(tool.get("arguments"))
    return ta


def build(trace_path: str, out: Path, tags=io.CASES, index_name="index.json"):
    data = json.load(open(trace_path))
    index = {"source": str(trace_path), "job": io.JOB, "cases": {}}
    for tag in tags:
        case = next(c for c in data["cases"] if tag in c["identity"]["case_id"])
        records, expectations, sources, projection, exp_reply = {}, {}, {}, None, None
        structure = None
        axes: dict[str, list[dict]] = {axis: [] for axis in PROCESS_AXES}
        calls = []
        for cl in case["calls"]:
            rr = cl.get("raw_request") or {}
            stage = rr.get("stage") or ""
            calls.append(call_meta(cl))
            if stage == "llm_probe_expectations":
                exp_reply = cl.get("assistant")
            elif stage == "llm_probe_expectations_process_projection":
                projection = parse_json(cl.get("assistant"))
            elif stage.startswith("trace_analysis:"):
                for tool in cl.get("tool_calls") or []:
                    if isinstance(tool, dict) and tool.get("name") == "submit_structure":
                        structure = parse_json(tool.get("arguments"))
                    elif isinstance(tool, dict) and "submit_structure" in json.dumps(tool)[:200]:
                        structure = parse_json(tool.get("arguments"))
            axis, batch = split_stage(stage)
            if axis is None:
                continue
            messages = (rr.get("client_request") or {}).get("messages") or []
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = [m["content"] for m in messages if m["role"] == "user"]
            body = parse_json(user[0]) if user else None
            if body is not None:
                for e in body.get("expectations", []):
                    expectations[e["expectation_id"]] = e
                for s in body.get("expectation_sources", []):
                    sources[s["id"]] = s
                dv = body.get("dossier_view") or {}
                shared = dv.get("shared_contents") or {}
                if isinstance(shared, list):
                    shared = {r["id"]: r.get("body") for r in shared}
                for rec in dv.get("records", []):
                    flat = flatten_record(rec, shared)
                    old = records.get(rec["id"])
                    if old is None or len(json.dumps(flat, ensure_ascii=False)) > len(json.dumps(old, ensure_ascii=False)):
                        records[rec["id"]] = flat
            kind = "correction" if user and "上次输出未通过程序检查" in user[0] else "first"
            axes[axis].append({
                "stage": stage, "batch": batch, "kind": kind, "seq": cl.get("seq"),
                "system": system, "user": user[0] if user else "",
                "body": body,
                "recorded": {"model": cl.get("model"), "content": cl.get("assistant"),
                             "thinking": cl.get("thinking"), "usage": cl.get("usage"),
                             "incomplete": cl.get("incomplete"), "status_code": cl.get("status_code"),
                             "stop_reason": cl.get("stop_reason"), "error": cl.get("error"),
                             "response_error": cl.get("response_error")},
            })
        frozen = {"case_id": case["identity"]["case_id"], "tag": tag, "job": io.JOB,
                  "run_id": case["identity"]["run_id"], "started_at": case["identity"]["started_at"],
                  "records": records, "expectations": list(expectations.values()),
                  "expectation_sources": list(sources.values()),
                  "projection": projection, "structure": structure,
                  "expectations_reply": parse_json(exp_reply),
                  "trace_analysis": ta_artifacts(case),
                  "description": (case.get("identity") or {}).get("description"),
                  "axes": axes, "calls": calls}
        path = out / f"case_{tag}.json"
        io.save_text(path, json.dumps(frozen, ensure_ascii=False, indent=1), exclusive=False)
        index["cases"][tag] = {"case_id": frozen["case_id"], "records": len(records),
                               "expectations": len(expectations),
                               "axes": {a: [{"stage": b["stage"], "kind": b["kind"], "seq": b["seq"],
                                             "body": b["body"] is not None} for b in axes[a]]
                                        for a in PROCESS_AXES if axes[a]},
                               "has_structure": structure is not None, "has_projection": projection is not None,
                               "calls": len(calls)}
        print(f"{tag}: records={len(records)} exp={len(expectations)} calls={len(calls)} "
              f"structure={structure is not None} projection={projection is not None}")
    io.save_json(out / index_name, index, exclusive=False)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(io.HERE / "frozen"))
    ap.add_argument("--unseen", action="store_true", help="抽 io.UNSEEN 里的 case（写进同一目录，索引另存）")
    args = ap.parse_args()
    io.init_secret_guard()
    out = io.target(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.unseen:
        build(str(io.TRACE), out, io.UNSEEN, "index_unseen.json")
        return
    build(str(io.TRACE), out)
    io.progress("阶段2 冻结输入", "已从导出 trace 抽出 8 个 case 的案卷记录、期望 E、前置输出与六轴原始 prompt")


if __name__ == "__main__":
    sys.exit(main())
