"""登记的资源类型 case_trace（spec/alg/resources.md §10.2）：评测 case 的 trace 案卷，每条记录一个资源。

组织：这个 case 各轮的原样快照 → 信息源自带的翻译器（``open_reader``）读成统一记录 → 按 case 合成案卷
（多轮合并、编号带 ``turnN/`` 前缀、相同内容去重）。资源：案卷里每条记录（含每轮的原始请求响应）挂一个
记录集直接资源 ``trace://<记录编号>``，正文 = ``record_body``，出处（在原样快照里的位置）记在 ``_meta``。

Content interning removes identical copies, never executions. Expanding content_ref
recovers the redacted source exactly; neither the organizer nor judges write evidence.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from impl.core.resources import META_PREFIX
from impl.projects.llm_probe_loop.business_trace import open_reader
from impl.projects.llm_probe_loop.business_trace.reader import _epoch_sort, redact, resolve

SCHEME = "trace"
TYPE = "record_set"
SOURCE_KEY = META_PREFIX + "source"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _Contents:
    def __init__(self):
        self.values: dict[str, Any] = {}
        self.index: dict[str, str] = {}

    def add(self, value: Any) -> Any:
        key = _json(value)
        if len(key) < 160:
            return value
        if key in self.index:
            return {"content_ref": self.index[key]}
        if isinstance(value, dict):
            body = {k: self.add(v) for k, v in value.items()}
        elif isinstance(value, list):
            body = [self.add(v) for v in value]
        else:
            body = value
        ident = f"content#{len(self.values) + 1}"
        self.index[key] = ident
        self.values[ident] = body
        return {"content_ref": ident}


def expand_content(value: Any, contents: Mapping[str, Any]) -> Any:
    """Used by offline inspection/tests to recover full original material."""
    if isinstance(value, dict):
        if set(value) == {"content_ref"} and value["content_ref"] in contents:
            return expand_content(contents[value["content_ref"]], contents)
        return {k: expand_content(v, contents) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_content(v, contents) for v in value]
    return value


def record_body(dossier: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """一条记录的正文。取证件读到的与下游轴看到的必须是同一个东西，所以两边共用这一个函数。"""
    fields: dict[str, Any] = {}
    for name, info in (row.get("fields") or {}).items():
        item: dict[str, Any] = {"status": info.get("status")}
        if info.get("note"):
            item["note"] = info["note"]
        if "value" in info:
            value = render_value(dossier, info["value"])
            item["chars"] = len(_text(value))
            item["value"] = value
        fields[name] = item
    body = {key: value for key, value in row.items() if key != "fields"}
    body["fields"] = fields
    return body


def render_value(dossier: Mapping[str, Any], value: Any, *, max_depth: int = 16) -> Any:
    """Recover the exact original for content_refs so downstream prompts carry raw text."""
    contents = dossier.get("contents") or {}

    def walk(item: Any, depth: int) -> Any:
        if isinstance(item, dict):
            if set(item) == {"content_ref"} and depth < max_depth:
                body = contents.get(item["content_ref"])
                if body is None:
                    return item
                return walk(body, depth + 1)
            return {key: walk(child, depth + 1) for key, child in item.items()}
        if isinstance(item, list):
            return [walk(child, depth + 1) for child in item]
        return item

    return walk(value, 0)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _snapshots(trace: Any, snapshot: Any) -> list[tuple[str, Any, Any]]:
    turns = getattr(trace, "turn_records", None) or []
    if turns:
        return [(f"turn{i + 1}", (t.get("project_fields") or {}).get("business_trace"),
                 {k: t.get(k) for k in ("turn_index", "mock_message", "request", "extracted_output", "call_status")})
                for i, t in enumerate(turns)]
    return [("turn1", snapshot, {"request": getattr(trace, "normalized_request", {}),
                                "extracted_output": getattr(trace, "extracted_output", {})})]


def build_dossier(trace: Any, snapshot: Any) -> dict[str, Any]:
    contents = _Contents()
    records, calls, sources, coverage, gaps = [], [], [], [], []
    timelines: dict[str, list[dict]] = {"current": [], "history": [], "observed_at_collection": []}
    evidence_ids: set[str] = set()
    taken: dict[str, int] = {}

    def unique_id(base: str, kind: str) -> str:
        """One source path may be listed under two categories (e.g. messages and reasoning).

        Numbers must stay unique or a selection would silently drop one representation.
        """
        count = taken.get(base, 0)
        taken[base] = count + 1
        return base if count == 0 else f"{base}#{kind}"
    for turn, snap, request in _snapshots(trace, snapshot):
        evidence_ids.add(turn)
        source = {"id": turn, "request_and_response": contents.add(redact(request))}
        sources.append(source)
        if not isinstance(snap, Mapping) or snap.get("status") == "failed":
            gaps.append({"id": f"{turn}.collection", "reason": "本轮业务 Trace 缺失或采集失败；不能据此断言本轮没有调用", "errors": (snap or {}).get("errors", []) if isinstance(snap, Mapping) else []})
            coverage.append({"turn": turn, "status": "failed"})
            continue
        reader = open_reader(snap)
        source["original_records"] = contents.add(reader.source["records"])
        if getattr(reader, "link_limits", None):
            source["link_limits"] = reader.link_limits
        if getattr(reader, "recorder", None):
            source["recorder"] = reader.recorder
        overview = reader.overview()
        coverage.append({"turn": turn, "status": snap.get("status"), "coverage": snap.get("coverage"),
                         "association": overview["association"], "errors": overview["collection_errors"],
                         "limitations": reader.limitations})
        for name, limitation in reader.limitations.items():
            if limitation.get("status") not in {"complete", "available", "supported"}:
                gap = {"id": f"{turn}.gap.{name}", **limitation}
                if isinstance(limitation.get("items"), list):
                    # 逐条缺口的 ref 与案卷编号同一命名空间，下游可直接对号。
                    gap["items"] = [dict(item, ref=turn + item["ref"]) if str(item.get("ref", "")).startswith("/records/") else item
                                    for item in limitation["items"]]
                gaps.append(gap)
        # Namespace every source pointer so historical snapshots cannot be confused with this turn.
        def qualified(value: Any) -> Any:
            if isinstance(value, str) and value.startswith("/records/"):
                return turn + value
            if isinstance(value, dict):
                return {k: qualified(v) for k, v in value.items()}
            if isinstance(value, list):
                return [qualified(v) for v in value]
            return value
        for entry in reader.entries:
            ident = unique_id(turn + entry["ref"], str(entry["kind"]))
            evidence_ids.add(ident)
            fields = {}
            for name, info in entry["fields"].items():
                fields[name] = qualified(dict(info))
                if "ref" in info:
                    evidence_ids.add(turn + info["ref"])
                    fields[name]["value"] = contents.add(resolve(reader.source, info["ref"]))
            row = {**qualified({k: v for k, v in entry.items() if k not in {"fields", "id"}}),
                   "id": ident, "source_id": entry.get("id"), "turn": turn, "fields": fields}
            records.append(row)
            if entry["kind"] == "model_calls" and not entry.get("copy_of"):
                reconstructed = qualified(entry.get("reconstructed_input") or {})
                calls.append({"id": ident, "scope": entry.get("scope"), "turn": turn,
                              "input": fields.get("input"), "output": fields.get("output"),
                              "exact_request": fields.get("exact_request"),
                              "reconstructed_input": reconstructed,
                              "output_message_ref": qualified(entry.get("output_message_ref")),
                              "input_limit": reader.model_call_note(entry)})
                for key in ("recorded_request", "task_ref"):
                    if key in entry:
                        calls[-1][key] = qualified(entry[key])
            if entry["kind"] in {"runs", "steps", "messages", "tool_calls", "model_calls"}:
                scope = entry.get("scope", "observed_at_collection")
                bucket = scope if scope in timelines else "observed_at_collection"
                timelines[bucket].append({"id": ident, "turn": turn, "kind": entry["kind"],
                    "at": reader._stamp(entry), "parent_ref": qualified(entry.get("parent_ref")),
                    "ordinal": entry.get("ordinal"), "copy_of": qualified(entry.get("copy_of"))})
        if not reader.entries:
            gaps.append({"id": f"{turn}.empty", "reason": "采集结果没有可解析的过程记录"})
        # 本轮最终回答同样要能被引用：否则「结论对不对」这类判断只能自造编号。
        final_ref = reader.final_output_ref()
        if final_ref is not None:
            ident = unique_id(f"{turn}.final_output", "final_output")
            evidence_ids.add(ident)
            evidence_ids.add(turn + final_ref)
            records.append({"id": ident, "kind": "final_output", "turn": turn, "scope": "current",
                            "source_id": "final_output", "parent_ref": turn,
                            "fields": {"output": {"status": "available", "ref": turn + final_ref,
                                                  "value": contents.add(resolve(reader.source, final_ref))}}})
            timelines["current"].append({"id": ident, "turn": turn, "kind": "final_output",
                                         "at": None, "parent_ref": turn, "ordinal": None, "copy_of": None})
        # Keep the caller's extracted response separate from the persisted run output.
        # Never substitute one for the other when the response was not captured.
        delivered = request.get("extracted_output") if isinstance(request, Mapping) else None
        if delivered:
            ident = unique_id(f"{turn}.delivered_output", "delivered_output")
            evidence_ids.add(ident)
            records.append({"id": ident, "kind": "delivered_output", "turn": turn, "scope": "current",
                            "parent_ref": turn, "source_id": "delivered_output",
                            "fields": {"output": {"status": "available", "value": contents.add(redact(delivered)),
                                                   "note": "调用方记录的 extracted_output；不是原始 HTTP 报文"}}})
            timelines["current"].append({"id": ident, "turn": turn, "kind": "delivered_output",
                                        "at": None, "parent_ref": turn, "ordinal": None, "copy_of": None})
        else:
            gaps.append({"id": f"{turn}.delivered_output_missing",
                         "reason": "没有保存调用方实收输出；运行落库结果不能代替实际交付证据"})
    for rows in timelines.values():
        # Unknown timestamps remain visible; hierarchy/ordinal are explicit, not invented timing.
        rows.sort(key=lambda r: (int(r["turn"][4:]), _epoch_sort(r["at"])))
    evidence_ids.update(contents.values)
    evidence_ids.update(g["id"] for g in gaps)
    return {"format": "process-dossier-v1", "sources": sources, "records": records,
            "contents": contents.values, "model_calls": calls, **timelines,
            "coverage": coverage, "gaps": gaps, "evidence_ids": sorted(evidence_ids),
            "reading_guide": "所有 contents 已全文提供。content_ref 指向同一案卷中的原文（仅完全相同内容去重，不合并执行）。records.fields.value 为原始字段；sources.original_records 保留未映射字段。按 turn 区分测试轮次，history 是各轮采集的历史，不能当成本轮结果。at=null 不知道确切时刻，使用 parent_ref/ordinal 了解局部顺序。copy_of 仅表示同一记录的另一表示，原文不一致也都保留。采集时状态、配置、记忆不证明实际已注入。"}


def source_record(dossier: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """每轮的原始请求响应，与 case.trace.records 里的那一条同形（评测方记下的这一轮请求与响应）。"""
    return {"id": source["id"], "kind": "request_response", "turn": source["id"],
            "fields": {"request_and_response": {"status": "available",
                                                "value": render_value(dossier, source["request_and_response"])}}}


def resources(dossier: Mapping[str, Any]) -> list[dict[str, Any]]:
    """案卷里的每条记录 → 一个直接资源（交给 ResourceTable.mount）。"""
    out = []
    for source in dossier.get("sources") or []:
        out.append({"uri": f"{SCHEME}://{source['id']}", "type": TYPE, "body": source_record(dossier, source),
                    "name": source["id"], "title": "本轮原始请求响应", "description": "request_response",
                    "meta": {SOURCE_KEY: {"record": source["id"], "fields": {}}}})
    for row in dossier.get("records") or []:
        body = record_body(dossier, row)
        fields = {name: info["ref"] for name, info in (row.get("fields") or {}).items() if info.get("ref")}
        out.append({"uri": f"{SCHEME}://{row['id']}", "type": TYPE, "body": body, "name": row["id"],
                    "title": body.get("name"),
                    "description": " · ".join(str(body[k]) for k in ("kind", "observation_type", "outcome") if body.get(k)),
                    "meta": {SOURCE_KEY: {"record": row.get("ref") or row["id"], "fields": fields}}})
    return out
