"""Provider-neutral, read-only access to a frozen business trace.

Providers map their own records to named fields. Readers never infer business facts,
model-call boundaries or evaluator verdicts from those fields.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Mapping

KINDS = ("runs", "steps", "messages", "tool_calls", "model_calls", "states", "references",
         "events", "requirements", "definitions", "sessions", "memories", "checkpoints", "reasoning", "artifacts")
# 中性说明：只讲每类记录在任何 provider 下都成立的含义；provider 的表示语义由子类 kind_notes 覆盖。
_KIND_NOTES = {
    "runs": "被测系统记录的运行输入输出；scope 区分本轮和历史",
    "steps": "运行内部步骤；不同表示不能直接相加为执行次数",
    "messages": "已记录的消息；不保证等于每次模型调用的完整原始消息列表",
    "tool_calls": "已记录的工具调用；未配对的按 pairing.reason 理解",
    "model_calls": "已记录的模型调用；字段状态说明请求/响应是否被完整保存",
    "states": "已记录的状态；不是状态修改历史",
    "references": "已记录的引用/出处；业务 facts/evidence 还可能位于工具结果或状态正文中",
    "events": "已记录的运行事件；未记录事件不表示事件没有发生",
    "requirements": "暂停、确认、用户输入、外部执行等实际运行要求及处理状态",
    "definitions": "采集时的配置/定义；不是已证明的运行时配置版本",
    "sessions": "采集时会话详情及状态；不能当成本轮开始前快照",
    "memories": "采集时的持久化记忆；存在不等于当时已注入模型",
    "checkpoints": "已记录的续跑边界；不是原始逐模型请求",
    "reasoning": "业务模型已记录的推理文本或步骤；模型自述不是过程正确或根因的证明",
    "artifacts": "已记录的媒体和附件元数据/引用；不自动下载外部文件",
}
_READING = ("list_records 返回字段状态和 ref；read 按 ref 读正文，next_offset 非空时可继续。timeline 按时间顺序给出记录及其关联。"
            "带 copy_of 的记录是同一记录的另一份表示，引用任一路径等价，不要重复计数。目录存在不代表内容完整或业务正确。")
_SECRETS = re.compile(r"authorization|cookie|password|secret|api[_-]?key|access[_-]?token", re.I)
_HIDDEN = ("__REDACTED__", "[REDACTED]")


def pointer(parent: str, token: Any) -> str:
    return parent + "/" + str(token).replace("~", "~0").replace("/", "~1")


def redact(value: Any) -> Any:
    """Also scrub JSON-encoded tool results; keep their original string type."""
    if isinstance(value, Mapping):
        return {str(k): "[REDACTED]" if _SECRETS.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        safe = redact(decoded)
        return value if safe == decoded else json.dumps(safe, ensure_ascii=False)
    return value


def resolve(root: Any, ref: str) -> Any:
    if not ref.startswith("/records/") or re.search(r"~(?![01])", ref):
        raise ValueError("ref 必须是 /records/ 下的有效 JSON Pointer")
    current = root
    for raw in ref.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(current):
            current = current[int(token)]
        else:
            raise KeyError(ref)
    return current


def _epoch_sort(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return float("inf")
    return float("inf")


def _tally(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count entries by ``entry[key]`` (or its ``status`` when it is a mapping); missing counts as absent."""
    counts: dict[str, int] = {}
    for entry in entries:
        info = entry.get(key)
        label = str(info.get("status")) if isinstance(info, Mapping) else str(info) if info is not None else "absent"
        counts[label] = counts.get(label, 0) + 1
    return counts


def availability(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, str) and value in _HIDDEN:
        return "redacted"
    if value == "" or value == [] or value == {}:
        return "empty"
    return "available"


class TraceReader:
    """Model-facing record directory and paged exact-source reads; no network access.

    Subclasses describe their own representations through the class attributes below;
    the base never assumes a provider's representation names or record layout.
    """

    kind_notes: Mapping[str, str] = _KIND_NOTES
    reading: str = _READING
    timeline_kinds: tuple[str, ...] = ("runs", "steps", "messages", "tool_calls", "model_calls")
    timeline_note: str = "按开始时间排序；每个节点的 ref 可用 read 深入。没有时间戳的记录不在此视图，不表示不存在。"
    invocation_note: str = "计数是记录数，不是已证明的执行次数；unpaired 表示不能关联，不表示调用没发生"

    def __init__(self, snapshot: Mapping[str, Any]):
        self.snapshot = copy.deepcopy(dict(snapshot))
        self.source = {"records": redact(self.snapshot.get("records") or {})}
        self.entries: list[dict[str, Any]] = []
        self.reads: list[dict[str, Any]] = []
        self.limitations: dict[str, dict[str, Any]] = {}
        self.copy_prefixes: dict[str, str] = {}

    def field(self, ref: str, *, note: str = "") -> dict[str, Any]:
        try:
            value = resolve(self.source, ref)
        except KeyError:
            return {"status": "missing", "note": note or "本记录没有保存此字段"}
        return {"status": availability(value), "ref": ref, **({"note": note} if note else {})}

    def value(self, entry: Mapping[str, Any], field: str) -> Any:
        info = entry["fields"].get(field)
        if not isinstance(info, Mapping) or "ref" not in info:
            return None
        try:
            return resolve(self.source, info["ref"])
        except KeyError:
            return None

    def add(self, kind: str, ref: str, *, fields: Mapping[str, str | tuple[str, ...]], **metadata: Any) -> None:
        field_refs = {}
        for name, source in fields.items():
            path = ref
            for token in (source,) if isinstance(source, str) else source:
                path = pointer(path, token)
            field_refs[name] = self.field(path)
        self.entries.append({
            "kind": kind, "ref": ref, **metadata,
            "fields": field_refs,
        })

    def mark_copies(self, *, canonical: str) -> None:
        """Link secondary representations of the same persisted run (e.g. a SQLite row that
        mirrors the API run) to the canonical record: entries under the copy get ``copy_of``
        and refs on either side count as the same evidence."""
        runs = [e for e in self.entries if e["kind"] == "runs" and e.get("run_id")]
        canonical_refs = {e["run_id"]: e["ref"] for e in runs if e.get("representation") == canonical}
        for entry in runs:
            target = canonical_refs.get(entry["run_id"])
            if entry.get("representation") != canonical and target and target != entry["ref"]:
                self.copy_prefixes[entry["ref"]] = target
        for entry in self.entries:
            alias = self._alias(entry["ref"])
            if alias is not None:
                entry["copy_of"] = alias

    def _alias(self, ref: str) -> str | None:
        """Canonical counterpart of a ref inside a copy record, if it exists in the snapshot."""
        for prefix in sorted(self.copy_prefixes, key=len, reverse=True):
            if ref == prefix or ref.startswith(prefix + "/"):
                candidate = self.copy_prefixes[prefix] + ref[len(prefix):]
                try:
                    resolve(self.source, candidate)
                except KeyError:
                    return None
                return candidate
        return None


    def overview(self) -> dict[str, Any]:
        categories = {}
        for kind in KINDS:
            selected = [e for e in self.entries if e["kind"] == kind]
            fields: dict[str, dict[str, int]] = {}
            for entry in selected:
                for name, field in entry["fields"].items():
                    counts = fields.setdefault(name, {})
                    counts[field["status"]] = counts.get(field["status"], 0) + 1
            categories[kind] = {
                "count": len(selected), "status": "available" if selected else "not_recorded",
                "copy_count": sum(1 for e in selected if e.get("copy_of")),
                "field_status_counts": fields, "meaning": self.kind_notes[kind],
            }
        return {
            "provider": self.snapshot.get("provider"),
            "fingerprint": self.snapshot.get("fingerprint"),
            "captured_at": self.snapshot.get("captured_at"),
            "association": self.snapshot.get("association") or {},
            "collection_status": self.snapshot.get("status"),
            "collection_errors": self.snapshot.get("errors") or [],
            "sources": self.snapshot.get("sources") or [],
            "categories": categories,
            "invocations": self.invocation_summary(),
            "limitations": self.limitations,
            "reading": self.reading,
        }

    def final_output_ref(self) -> str | None:
        """Ref of the system's own recorded final answer for this turn; None when the provider has none."""
        return None

    def model_call_note(self, entry: Mapping[str, Any]) -> str:
        """What a model_calls entry does and does not prove about the request actually sent."""
        return ""

    def invocation_summary(self) -> dict[str, Any]:
        """Current-scope call counts by outcome and pairing status; counts are of records, not proven executions."""
        model = [e for e in self.entries if e["kind"] == "model_calls" and e.get("scope") == "current"]
        tools = [e for e in self.entries if e["kind"] == "tool_calls" and e.get("scope") == "current"]
        return {"scope": "current",
                "model_calls": {"records": len(model), "outcomes": _tally(model, "outcome")},
                "tool_calls": {"records": len(tools), "pairing": _tally(tools, "pairing")},
                "meaning": self.invocation_note}

    @staticmethod
    def _field_status(entries: list[dict[str, Any]], name: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in entries:
            label = entry["fields"].get(name, {}).get("status", "missing")
            counts[label] = counts.get(label, 0) + 1
        return counts

    def _stamp(self, entry: Mapping[str, Any]) -> Any:
        for field in ("start_time", "created_at"):
            info = entry["fields"].get(field)
            if isinstance(info, Mapping) and "ref" in info:
                try:
                    value = resolve(self.source, info["ref"])
                except KeyError:
                    continue
                if isinstance(value, (int, float, str)) and value != "" and not isinstance(value, bool):
                    return value
        return None

    def timeline(self, run_id: str = "", limit: int = 60) -> dict[str, Any]:
        """Chronological view of timestamped records of ``timeline_kinds``; copies are counted, not repeated."""
        if not 1 <= limit <= 200:
            raise ValueError("limit 必须为 1–200")
        nodes, untimed, skipped_copies = [], 0, 0
        for entry in self.entries:
            if entry["kind"] not in self.timeline_kinds:
                continue
            if entry.get("copy_of"):
                skipped_copies += 1
                continue
            if run_id and entry.get("run_id") != run_id:
                continue
            stamp = self._stamp(entry)
            if stamp is None:
                untimed += 1
                continue
            node = {"at": stamp, "kind": entry["kind"], "ref": entry["ref"], "name": entry.get("name")}
            for key in ("outcome", "protocol", "parent_ref", "call_ref", "result_ref", "pairing"):
                if entry.get(key) is not None:
                    node[key] = entry[key]
            duration = self.value(entry, "duration_ms")
            if duration is not None:
                node["duration_ms"] = duration
            nodes.append(node)
        nodes.sort(key=lambda n: (_epoch_sort(n["at"]), n["ref"]))
        return {"nodes": nodes[:limit], "total": len(nodes), "truncated": len(nodes) > limit,
                "untimed_records": untimed, "skipped_copy_records": skipped_copies, "meaning": self.timeline_note}

    def list_records(self, kind: str, run_id: str = "", offset: int = 0, limit: int = 20) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind 必须为 {', '.join(KINDS)}")
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("offset >= 0，limit 必须为 1–50")
        selected = [e for e in self.entries if e["kind"] == kind and (not run_id or e.get("run_id") == run_id)]
        return {"kind": kind, "items": copy.deepcopy(selected[offset:offset + limit]),
                "total": len(selected), "offset": offset,
                "next_offset": offset + limit if offset + limit < len(selected) else None}

    def read(self, ref: str, offset: int = 0, max_chars: int = 12000) -> dict[str, Any]:
        if offset < 0 or not 1 <= max_chars <= 24000:
            raise ValueError("offset >= 0，max_chars 必须为 1–24000")
        try:
            value = resolve(self.source, ref)
        except KeyError:
            return {"ref": ref, "status": "missing", "reason": "快照没有此路径；不会猜测或访问外部来源"}
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if offset > len(text):
            raise ValueError("offset 超过正文长度")
        end = min(offset + max_chars, len(text))
        result = {"ref": ref, "status": availability(value), "text": text[offset:end],
                  "format": "text" if isinstance(value, str) else "json", "offset": offset,
                  "total_chars": len(text), "truncated": offset > 0 or end < len(text),
                  "next_offset": end if end < len(text) else None}
        self.reads.append({k: v for k, v in result.items() if k != "text"} | {
            "sha256": hashlib.sha256(result["text"].encode()).hexdigest(),
        })
        return result

    def exists(self, ref: str) -> bool:
        try:
            resolve(self.source, ref)
        except (KeyError, ValueError):
            return False
        return True



