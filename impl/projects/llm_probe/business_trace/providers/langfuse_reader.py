"""Map frozen Langfuse observations to the shared evidence directory."""
from __future__ import annotations

from typing import Mapping

from ..reader import TraceReader, _KIND_NOTES, resolve


def _observation_type(row):
    recorded = str(row.get("type") or "UNKNOWN").upper()
    metadata = row.get("metadata")
    attributes = metadata.get("attributes", {}) if isinstance(metadata, Mapping) else {}
    declared = attributes.get("openinference.span.kind") if isinstance(attributes, Mapping) else None
    # Some exporters explicitly encode OpenInference kinds inside generic SPANs.
    # This is a declared semantic type, never a guess from the span's name.
    if recorded == "SPAN":
        return {"LLM": "GENERATION", "EMBEDDING": "EMBEDDING", "TOOL": "TOOL",
                "RETRIEVER": "RETRIEVER", "AGENT": "AGENT", "CHAIN": "CHAIN"}.get(declared, recorded) if isinstance(declared, str) else recorded
    return recorded


def _content_status(value, limit):
    if isinstance(value, str):
        if "[REDACTED]" in value or "__REDACTED__" in value:
            return "redacted"
        if "[TRUNCATED]" in value or "[INCOMPLETE]" in value or (limit and len(value) >= limit):
            return "truncated"
    children = value.values() if isinstance(value, Mapping) else value if isinstance(value, list) else []
    statuses = {_content_status(child, limit) for child in children}
    return "redacted" if "redacted" in statuses else "truncated" if "truncated" in statuses else None


class LangfuseReader(TraceReader):
    kind_notes = dict(_KIND_NOTES, model_calls="SDK 记录的 GENERATION/EMBEDDING 输入输出；不证明模型实际收到的完整请求",
                      tool_calls="TOOL/RETRIEVER observation 的输入输出；未埋点的调用不可见",
                      steps="AGENT/CHAIN/SPAN 等 observation，parentObservationId 只证明父子关系，不证明串行控制流")
    recorder = "Langfuse"
    link_limits = ("环节表只列程序从 Langfuse 已记录结构能确定的环节与机器事实，不是全部环节。"
                   "SDK 输入不是已证明的完整模型请求；父子关系不等于相邻步骤串行；未埋点、脱敏、截断和未采齐的部分均为缺证。"
                   "facts 只陈述关系，不说明对错；业务 scores 只是原始资料，不是 verifier 的结论。")

    def field(self, ref, *, note=""):
        info = super().field(ref, note=note)
        if ref.rsplit("/", 1)[-1] in {"input", "output"} and "ref" in info:
            status = _content_status(resolve(self.source, ref), self.snapshot.get("content_char_limit"))
            if status:
                info.update(status=status, note="内容包含脱敏标记" if status == "redacted" else
                            "字段达到业务配置的长度上限，按可能截断处理；原始内容仍可读取")
        if ref.rsplit("/", 1)[-1] in {"timestamp", "startTime", "endTime"} and "ref" in info:
            from .langfuse import _stamp
            if _stamp(resolve(self.source, ref)) is None:
                info.update(status="missing", note="时间戳无效或超出数据库支持范围；仅保留原文，不用于时序判断")
        return info

    def __init__(self, snapshot):
        super().__init__(snapshot)
        records = self.source["records"]
        trace = records.get("trace") or {}
        if trace:
            self._trace(trace, "/records/trace", "current")
        for i, historical in enumerate(records.get("history_traces") or []):
            self._trace(historical, f"/records/history_traces/{i}", "history")
        observations = records.get("observations") or []
        refs = {row["id"]: f"/records/observations/{i}" for i, row in enumerate(observations)}
        by_id = {row["id"]: row for row in observations}
        missing_parents, unknown = [], []
        for i, row in enumerate(observations):
            ref = refs[row["id"]]
            typ = _observation_type(row)
            kind = ("model_calls" if typ in {"GENERATION", "EMBEDDING"} else
                    "tool_calls" if typ in {"TOOL", "RETRIEVER"} else "events" if typ == "EVENT" else "steps")
            parent_id = row.get("parentObservationId")
            parent = refs.get(parent_id) if parent_id else "/records/trace"
            if parent_id and not parent:
                missing_parents.append(parent_id)
            if typ not in {"GENERATION", "EMBEDDING", "TOOL", "RETRIEVER", "EVENT",
                           "AGENT", "CHAIN", "SPAN", "GUARDRAIL", "EVALUATOR"}:
                unknown.append(typ)
            fields = {"input": "input", "output": "output", "start_time": "startTime", "end_time": "endTime",
                      "metadata": "metadata", "level": "level", "status_message": "statusMessage"}
            metadata = {"id": row["id"], "name": row.get("name"), "scope": "current",
                        "run_id": trace.get("id"), "parent_ref": parent, "ordinal": i,
                        "representation": "observation", "observation_type": typ,
                        "sequence_known": False,
                        "outcome": "error" if row.get("level") == "ERROR" else "recorded" if row.get("endTime") else "unfinished"}
            if kind == "model_calls":
                fields.update(model="model", model_parameters="modelParameters", usage="usage", usage_details="usageDetails")
                metadata["recorded_request"] = True
                # Only a recorded parent input is an input-side task; never guess by name or nearest time.
                ancestor, visited = parent_id, set()
                while ancestor in by_id and ancestor not in visited:
                    visited.add(ancestor)
                    owner = by_id[ancestor]
                    if _observation_type(owner) in {"AGENT", "CHAIN", "SPAN"} and owner.get("input") is not None:
                        metadata["task_ref"] = refs[ancestor]
                        break
                    ancestor = owner.get("parentObservationId")
                if not parent_id:
                    metadata["task_ref"] = "/records/trace"
            if kind == "tool_calls":
                ancestor, visited = parent_id, set()
                metadata["run_id"] = parent_id or trace.get("id")
                while ancestor in by_id and ancestor not in visited:
                    visited.add(ancestor)
                    owner = by_id[ancestor]
                    if _observation_type(owner) == "AGENT":
                        metadata["run_id"] = ancestor
                        break
                    ancestor = owner.get("parentObservationId")
                fields.update(arguments="input", result="output")
                if row.get("level") == "ERROR":
                    fields["error"] = "statusMessage" if row.get("statusMessage") else "level"
                metadata["pairing"] = {"status": "single_record", "reason": "同一 observation 保存输入与输出；不推断与模型请求的配对"}
            self.add(kind, ref, fields=fields, **metadata)
            if typ == "RETRIEVER":
                self.add("references", ref, fields={"query": "input", "documents": "output"},
                         id=row["id"], scope="current", run_id=trace.get("id"))
        content_items = self._content_items(observations, refs)
        self.limitations = {
            "exact_model_request": {"status": "unverified", "reason": "SDK 保存的 input 不保证包含模型收到的完整请求或工具定义"},
            "instrumentation": {"status": "partial", "reason": "只覆盖业务已埋点且未采样丢弃的调用；未记录不等于未发生"},
            "content": {"status": "partial" if content_items else "unverified", "items": content_items,
                        "reason": "逐条列出内容缺口：not_recorded=只记了结构没记输入输出；redacted=含脱敏标记；"
                                  "truncated=长度达到业务配置上限。保留上游原文；没有标记也不能证明上游未截断"},
            "history": snapshot.get("history_coverage") or {"status": "not_collected"},
            "collection": {"status": "available" if snapshot.get("status") == "succeeded" else "partial",
                           "reason": "仅是采集时稳定快照，不保证此后无迟到数据", "errors": snapshot.get("errors", [])},
            "hierarchy": {"status": "partial" if missing_parents else "available", "missing_parent_ids": missing_parents},
            "scores": {"status": "unverified", "reason": "业务 scores 是上游资料，不能作为 verifier 结论"},
        }
        if unknown:
            self.limitations["unknown_observation_types"] = {"status": "partial", "types": sorted(set(unknown))}

    _WHY = {"redacted": "内容含脱敏标记，被替换的值看不到",
            "truncated": "长度达到业务配置的上限，按可能被截断处理，后半段可能缺失"}

    def _content_items(self, observations, refs):
        """内容缺口逐条结构化：哪一步、哪个字段、缺的是什么、为什么缺。只陈述采集事实，不判影响。"""
        by_ref = {e["ref"]: e for e in self.entries if e["ref"].startswith("/records/observations/")}
        items = []
        for row in observations:
            ref = refs[row["id"]]
            entry = by_ref.get(ref)
            if entry is None:
                continue
            fields = {name: entry["fields"].get(name, {}).get("status") for name in ("input", "output")}
            if all(status == "missing" for status in fields.values()):
                metadata = row.get("metadata")
                attributes = metadata.get("attributes", {}) if isinstance(metadata, Mapping) else {}
                kept = sorted(k for k in attributes if not str(k).startswith("langfuse.")) if isinstance(attributes, Mapping) else []
                items.append({"ref": ref, "name": row.get("name"), "field": ["input", "output"], "kind": "not_recorded",
                              "why": "这一步只记了结构，没有记录输入输出内容", "recorded_attributes": kept})
                continue
            for name, status in fields.items():
                if status in self._WHY:
                    items.append({"ref": ref, "name": row.get("name"), "field": [name], "kind": status, "why": self._WHY[status]})
        return items

    def _trace(self, trace, ref, scope):
        self.add("runs", ref, fields={"input": "input", "content": "output", "output": "output",
                 "start_time": "timestamp", "metadata": "metadata", "tags": "tags",
                 "session_id": "sessionId", "user_id": "userId", "scores": "scores"},
                 id=trace["id"], run_id=trace["id"], name=trace.get("name"), scope=scope,
                 representation="trace")

    def _stamp(self, entry):
        from .langfuse import _stamp
        value = super()._stamp(entry)
        return value if _stamp(value) is not None else None

    def final_output_ref(self):
        info = self.field("/records/trace/output")
        return info.get("ref") if info["status"] == "available" else None

    def model_call_note(self, entry):
        return "input 是 Langfuse SDK 已保存的请求表示，不保证等于实际完整请求；缺失、脱敏或截断不能补造。"
