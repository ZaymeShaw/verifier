"""从导出 trace 还原现行六轴的上游状态（案卷、结构输出、视图）。

导出 trace 里没有落盘业务 RunTrace，能拿到的只有 trace_analysis 子循环读到的
东西：案卷目录（记录顺序 + 每条摘要）、按编号取回的正文、时间线元信息、定稿 payload。
三处拼起来就是 `build_dossier` 的产物：目录给出记录集合与顺序，取回正文给出字段正文，
六轴视图给出 `ref` 与交付后的值。这是还原，不是重采；充分性由下游视图与 prompt 的
逐字比对来判定（`replay.py --check`）。
"""
from __future__ import annotations

import copy
import json
from typing import Any, Mapping

AXES = ("context_memory", "intent_understanding", "planning_routing",
        "tool_execution", "knowledge_data", "model_capability")


def parse_json(text: Any) -> Any:
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


def resolve(value: Any, shared: Mapping[str, Any]) -> Any:
    """只还原 shared_ref；JSON 文本形式的字段正文是案卷原样值。"""
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return resolve(shared.get(value["shared_ref"]), shared)
        return {k: resolve(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, shared) for v in value]
    return value


def flatten_view(view: Mapping[str, Any]) -> dict[str, Any]:
    """把一个轴的视图压成可与重建结果直接比对的形态：shared# 还原、字段取全。"""
    shared = view.get("shared_contents") or {}
    if isinstance(shared, list):
        shared = {row["id"]: row.get("body") for row in shared}
    rows = {}
    for rec in view.get("records") or []:
        body = {k: v for k, v in rec.items() if k != "fields"}
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
        body["fields"] = fields
        rows[rec["id"]] = body
    contents = {}
    for ref, holder in (view.get("contents") or {}).items():
        if isinstance(holder, dict) and "shared_ref" in holder:
            contents[ref] = resolve(holder, shared)
        elif isinstance(holder, dict) and "same_as" in holder:
            contents[ref] = {"same_as": holder["same_as"]}
        else:
            contents[ref] = holder
    return {"records": rows, "contents": contents, "gaps": view.get("gaps") or [],
            "missing_endpoints": view.get("missing_endpoints") or [],
            "input_limitations": view.get("input_limitations") or [],
            "excluded": view.get("excluded") or []}


_PATH_KINDS = (
    ("records/session", "sessions"),
    ("records/memories/", "memories"),
    ("records/checkpoints/", "checkpoints"),
    ("records/definitions/", "definitions"),
    ("records/raw_runs/", "runs"),
    ("records/run/step_executor_runs/", "steps"),
    ("records/run/step_results/", "steps"),
    ("records/run", "runs"),
    ("/tools/", "tool_calls"),
    ("/messages/", "messages"),
    ("/states/", "states"),
    ("/references/", "references"),
    ("/events/", "events"),
    ("/artifacts/", "artifacts"),
    ("/requirements/", "requirements"),
    ("/attributes/", "reasoning"),
    ("records/traces", "model_calls"),
    (".delivered_output", "delivered_output"),
    (".final_output", "final_output"),
)


def kind_from_path(path: str) -> str | None:
    """目录里没有时间线的记录（session/definitions 等）也带 kind：按 ref 结构还原 reader 的分类。"""
    for needle, kind in _PATH_KINDS:
        if needle in path:
            return kind
    return None


def _merge_row(path: str, view_row: Mapping[str, Any] | None, body: Mapping[str, Any] | None,
               meta: Mapping[str, Any] | None) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for source in (body, view_row):
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if key == "fields":
                continue
            row[key] = copy.deepcopy(value)
    if isinstance(meta, Mapping):
        for key in ("kind", "scope", "turn", "parent_ref", "copy_of", "ordinal"):
            if meta.get(key) is not None and not row.get(key):
                row[key] = meta[key]
    if not row.get("kind"):
        derived = kind_from_path(path)
        if derived:
            row["kind"] = derived
    row.setdefault("id", path)
    fields: dict[str, Any] = {}
    if isinstance(view_row, Mapping) and isinstance(view_row.get("fields"), Mapping):
        for name, info in view_row["fields"].items():
            if isinstance(info, Mapping):
                fields[name] = {k: v for k, v in info.items() if k != "resolved_from"}
    if isinstance(body, Mapping) and isinstance(body.get("fields"), Mapping):
        for name, info in body["fields"].items():
            if not isinstance(info, Mapping):
                continue
            if name in fields:
                for key, value in info.items():
                    fields[name].setdefault(key, copy.deepcopy(value))
            else:
                fields[name] = copy.deepcopy(info)
    for name, info in fields.items():
        if isinstance(info, Mapping):
            info.pop("chars", None)
            info.pop("captured_tool_definitions", None)
    row["fields"] = fields
    _restore_raw_attributes(row, fields, view_row)
    row.pop("captured_tool_definitions", None)
    return row


def _strings(value: Any) -> list[str]:
    """与 materials._strings 同义：取 >=40 字的字符串叶子，用于判重复正文。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _restore_raw_attributes(row: Mapping[str, Any], fields: dict[str, Any],
                            view_row: Mapping[str, Any] | None) -> None:
    """把 raw_attributes 补回完整形态：material_view 会把已由其他字段交付的键从渲染值里剔掉
    （omitted_keys_delivered_elsewhere），记录行本身持有的是完整字典。交付时会因与其他字段
    正文重复而再被剔掉的键，只补回占位值：它们不进正文，只决定剔除名单本身。"""
    raw_ref = row.get("raw_ref")
    info = fields.get("raw_attributes")
    if not raw_ref or not isinstance(info, Mapping) or "value" not in info:
        return
    value = info["value"]
    if not isinstance(value, dict):
        return
    restored = dict(value)
    prefix = f"{raw_ref}/attributes/"
    for entry in fields.values():
        if not isinstance(entry, Mapping):
            continue
        ref, inner = entry.get("ref") or "", entry.get("value")
        if ref.startswith(prefix) and inner is not None:
            restored.setdefault(ref[len(prefix):], inner)
    defs = (view_row or {}).get("captured_tool_definitions")
    if isinstance(defs, Mapping):
        restored.update(defs)
    omitted = info.get("omitted_keys_delivered_elsewhere") or []
    texts = sorted((s for name, entry in fields.items() if name != "raw_attributes" and isinstance(entry, Mapping)
                    for s in _strings(entry.get("value")) if len(s) >= 40), key=len)
    for key in omitted:
        if key not in restored and texts:
            restored[key] = texts[-1]
    fields["raw_attributes"] = {"status": info.get("status"), "ref": info.get("ref") or f"{raw_ref}/attributes",
                                "value": restored}


def build(frozen: Mapping[str, Any]) -> dict[str, Any]:
    """还原 `build_dossier` 的内部案卷。"""
    ta = frozen.get("trace_analysis") or {}
    order = ta.get("record_order") or []
    collect = ta.get("collect") or {}
    timeline = ta.get("timeline") or {}
    view_rows = frozen.get("records") or {}
    gaps = {}
    for axis, batches in (frozen.get("axes") or {}).items():
        for batch in batches:
            for gap in ((batch.get("body") or {}).get("dossier_view") or {}).get("gaps") or []:
                key = str(gap.get("id"))
                old = gaps.get(key)
                if old is None or len(json.dumps(gap, ensure_ascii=False)) > len(json.dumps(old, ensure_ascii=False)):
                    gaps[key] = gap
    records, contents, sources, out_gaps = [], {}, [], []
    for path in order:
        if path.startswith("content#"):
            body = collect.get(path)
            if body is not None:
                parsed = parse_json(body)
                contents[path] = parsed if parsed is not None else body
            continue
        if ".gap." in path:
            gap = gaps.get(path) or {"id": path}
            out_gaps.append(copy.deepcopy(dict(gap, id=path)))
            continue
        if "/records/" not in path and "." not in path:
            sources.append({"id": path, "turn": path, "kind": "sources", "scope": "current"})
            continue
        raw = collect.get(path)
        body = parse_json(raw) if raw is not None else None
        row = _merge_row(path, view_rows.get(path), body, timeline.get(path))
        records.append(row)
    coverage = _coverage(frozen)
    calls = []
    for row in records:
        if row.get("kind") != "model_calls":
            continue
        # dossier.py 在 model_calls 条目上另提一份 exact_request/input/output（记录行本身没有）。
        entry = {k: v for k, v in row.items()}
        for name in ("exact_request", "input", "output"):
            entry[name] = row.get("fields", {}).get(name)
        entry["input_limit"] = None
        calls.append(entry)
    return {"records": records, "contents": contents, "sources": sources, "gaps": out_gaps,
            "coverage": coverage, "model_calls": calls,
            "external_contents": len(contents)}


def _coverage(frozen: Mapping[str, Any]) -> list[dict[str, Any]]:
    """采集情况：目录首行记录了一轮成功与否与受限项。"""
    text = ((frozen.get("trace_analysis") or {}).get("prompts") or [{}])[0].get("text") or ""
    for line in text.splitlines():
        if line.startswith("采集："):
            out = []
            for part in line[len("采集："):].split("；"):
                turn = part.split(" ")[0]
                status = "succeeded" if "succeeded" in part else ("failed" if "failed" in part else "?")
                limited = []
                if "（受限：" in part:
                    limited = part.split("（受限：", 1)[1].rstrip("）").split(",")
                out.append({"turn": turn, "status": status, "limited": limited, "errors": []})
            return out
    return []


def analysis_output(frozen: Mapping[str, Any], dossier: Mapping[str, Any], enabled: tuple[str, ...] = AXES) -> dict[str, Any]:
    """用真实流程装配 trace_analysis 的输出：程序环节表 → 可疑环节 → 每轴视图。"""
    from impl.projects.llm_probe.process_loop.analysis import Analysis, SUBMIT

    analysis = Analysis(dossier, None, enabled)
    analysis._end(_AcceptedStructure(frozen.get("structure") or {}))
    output = {**analysis.output, "dossier": dossier}
    output.pop("usage", None)
    return output


class _FakeCall:
    def __init__(self, args: Mapping[str, Any]):
        self.tool = "submit_structure"
        self.ok = True
        self.denied = None
        self.error = None
        self.result = {"accepted": True}
        self.args = dict(args)


class _AcceptedStructure:
    """把已记录的定稿 payload 当作唯一一次被接受的提交交给同一个 `_end`。"""

    def __init__(self, args: Mapping[str, Any]):
        self.call = _FakeCall(args)
        self.llm_calls = 1
        self.calls = [self.call]

    def of(self, tool: str) -> list[Any]:
        from impl.projects.llm_probe.process_loop.analysis import SUBMIT
        return [self.call] if tool == SUBMIT else []
