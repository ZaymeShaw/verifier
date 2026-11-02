"""Agno-specific mapping of saved runs and spans; independent of evaluation axes."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from ..reader import TraceReader, _epoch_sort, _tally, pointer, resolve

_PAIR_TOLERANCE_S = 5.0
# Agno 3.0.6 流式 Workflow 下步骤执行器运行的 status 语义（来源见 _run 内注释）。
STREAMED_EXECUTOR_STATUS_NOTE = ("Workflow 步骤执行器运行：流式运行时 Agno 会在运行完成后把此 status 改写为 CANCELLED，"
                                 "故 CANCELLED 不表示被取消或中断；该步骤结局以 workflow_step_id 对应 step 记录的 success/error 为准")

_KIND_NOTES = {
    "runs": "已保存的 Workflow/Agent 运行输入输出；scope 区分本轮和历史",
    "steps": "Workflow 步骤结果及非 LLM/TOOL span；不同表示不能直接相加为执行次数",
    "messages": "持久化消息；不保证等于每次模型调用的完整原始消息列表；assistant 消息的 model_call_ref 指向对应 LLM span",
    "tool_calls": "持久化工具调用与 TOOL span；同一次调用的两种表示由 pairing/span_ref/persisted_ref 关联，未配对的按 pairing.reason 理解",
    "model_calls": "LLM span 的实际调用记录；input/output 多被隐藏，reconstructed_input 的 message_refs 是按持久化消息重建的候选输入；token 数相符仅支持配对，不证明完整模型请求",
    "states": "运行保存的 session_state；不是状态修改历史",
    "references": "Agno 原生 references/citations；业务 facts/evidence 还可能位于 tool_calls.result 或 states 正文中",
    "events": "已持久化的运行事件；未记录事件不表示事件没有发生",
    "requirements": "暂停、确认、用户输入、外部执行等实际运行要求及处理状态",
    "definitions": "采集时的 Workflow/Agent/工具/输出设置；不是已证明的运行时配置版本",
    "sessions": "采集时会话详情及状态；不能当成本轮开始前快照",
    "memories": "采集时该用户的持久化记忆；存在不等于当时已注入模型",
    "checkpoints": "Agno 从持久化消息派生的续跑边界；不是原始逐模型请求",
    "reasoning": "业务模型已记录的推理文本或步骤；模型自述不是过程正确或根因的证明",
    "artifacts": "运行保存的媒体和附件元数据/引用；不自动下载外部文件",
}
_TIMELINE_REPRESENTATIONS = {"api", "span", "sqlite_span"}

def _epoch(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _is_agent_span(entry: Mapping[str, Any]) -> bool:
    return entry.get("span_type") in {"AGENT", "TEAM"} and bool(entry.get("agent_run_id"))


def _json_object(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class AgnoReader(TraceReader):
    kind_notes = _KIND_NOTES
    reading = ("list_records 返回字段状态和 ref；read 按 ref 读正文，next_offset 非空时可继续。timeline 按时间顺序给出步骤/模型/工具调用及其关联。"
               "带 copy_of 的记录是同一持久化运行的另一份表示（如 SQLite 镜像），引用任一路径等价，不要重复计数。目录存在不代表内容完整或业务正确。")

    def __init__(self, snapshot: Mapping[str, Any]):
        super().__init__(snapshot)
        records = self.source["records"]
        run = records.get("run")
        if isinstance(run, Mapping):
            self._run(run, "/records/run", scope="current")
        for i, run in enumerate(records.get("history_runs") or []):
            self._run(run, f"/records/history_runs/{i}", scope="history")
        for i, trace in enumerate(records.get("traces") or []):
            if isinstance(trace, Mapping):
                self._spans(trace.get("tree") or [], f"/records/traces/{i}/tree", trace)
        for i, run in enumerate(records.get("raw_runs") or []):
            self._run(run["run_data"], f"/records/raw_runs/{i}/run_data", scope="current", representation="sqlite")
        self._raw_spans(records.get("raw_spans") or [])
        session = records.get("session")
        if isinstance(session, Mapping):
            self.add("sessions", "/records/session", fields={k: k for k in (
                "session_state", "session_data", "session_summary", "chat_history", "agent_data", "workflow_data", "metadata", "updated_at")},
                scope="observed_at_collection", id=session.get("session_id"))
        for i, definition in enumerate(records.get("definitions") or []):
            self._definitions(definition.get("data"), f"/records/definitions/{i}/data", root=True)
        for i, memory in enumerate(records.get("memories") or []):
            self.add("memories", f"/records/memories/{i}", id=memory.get("memory_id"), scope="observed_at_collection",
                     fields={k: k for k in ("memory", "topics", "updated_at", "agent_id", "team_id", "user_id")})
        for i, checkpoint in enumerate(records.get("checkpoints") or []):
            self.add("checkpoints", f"/records/checkpoints/{i}", run_id=checkpoint.get("run_id"),
                     scope="derived_from_persisted_run", fields={"boundaries": "data", "snapshots": "snapshots"})
        self._link()
        self.mark_copies(canonical="api")
        self.limitations = {
            "exact_model_request": self._exact_request_coverage(),
            "state_transitions": {"status": "unsupported", "reason": "此 provider 不把 run/session 末态重建为逐次状态变化"},
            "raw_backend_http": {"status": "unsupported", "reason": "Agno 工具结果可能已经过业务适配，不保证原始下游 HTTP 请求响应"},
            "source_documents": {"status": "unsupported", "reason": "仅提供已记录 references 和工具正文；不自动访问外部文档或推断版本"},
            "history": snapshot.get("history_coverage") or {"status": "not_collected", "reason": "本快照未采集历史 run"},
        }

    def final_output_ref(self) -> str | None:
        run = self.source["records"].get("run")
        return "/records/run/content" if isinstance(run, Mapping) and run.get("content") is not None else None

    def model_call_note(self, entry: Mapping[str, Any]) -> str:
        if entry["fields"].get("exact_request", {}).get("status") == "available":
            return "exact_request 是插桩在调用处记录的请求消息；工具定义见原始 span 属性 llm.tools.*。"
        return "持久化消息重建不是完整请求；token 数吻合不能证明完整性。工具定义、参数和实际注入内容须分别有记录。"

    def invocation_summary(self) -> dict[str, Any]:
        """Call-level counts by representation and link status; counts are of records, not proven executions."""
        model = [e for e in self.entries if e["kind"] == "model_calls" and e.get("scope") == "current"]
        tools = [e for e in self.entries if e["kind"] == "tool_calls" and e.get("scope") == "current"]
        spans = [e for e in tools if e.get("representation") in {"span", "sqlite_span"}]
        persisted = [e for e in tools if e.get("representation") == "api"]
        duplicates: dict[str, int] = {}
        for e in tools:
            rep = str(e.get("representation"))
            if rep not in _TIMELINE_REPRESENTATIONS:
                duplicates[rep] = duplicates.get(rep, 0) + 1
        return {
            "scope": "current",
            "model_calls": {
                "records": len(model),
                "reconstructed_input": _tally(model, "reconstructed_input"),
                "input_status": self._field_status(model, "input"),
                "output_status": self._field_status(model, "output"),
            },
            "tool_calls": {
                "persisted_records": len(persisted), "span_records": len(spans),
                "persisted_pairing": _tally(persisted, "pairing"), "span_pairing": _tally(spans, "pairing"),
                "other_representation_records": duplicates,
            },
            "steps_without_model_or_tool_spans": [
                {"ref": e["ref"], "name": e.get("name")} for e in self.entries
                if e["kind"] == "steps" and e.get("has_model_or_tool_spans") is False and e.get("parent_ref")
            ][:20],
            "meaning": "reconstructed_input/pairing 是确定性关联结果；unresolved/unpaired 表示不能关联，不表示调用没发生；steps_without_model_or_tool_spans 是有输出但没有 LLM/TOOL span 的步骤：它们内部若直连了后端，调用与结果只会出现在步骤输出或 states 里，需要用 read 去看",
        }

    def timeline(self, run_id: str = "", limit: int = 60) -> dict[str, Any]:
        """Chronological view of span-backed steps, model calls and tool calls with their links; no new facts."""
        if not 1 <= limit <= 200:
            raise ValueError("limit 必须为 1–200")
        nodes = []
        untimed = 0
        skipped_copies = 0
        for entry in self.entries:
            if entry["kind"] not in {"steps", "model_calls", "tool_calls"}:
                continue
            if entry.get("representation") not in _TIMELINE_REPRESENTATIONS:
                skipped_copies += 1  # e.g. SQLite copies of the same persisted run
                continue
            if run_id and run_id not in {entry.get("run_id"), entry.get("agent_run_id")}:
                continue
            if entry["kind"] == "tool_calls" and entry.get("span_ref"):
                continue  # paired persisted record is reachable from its span node
            stamp = self._stamp(entry)
            if stamp is None:
                untimed += 1
                continue
            node = {"at": stamp, "kind": entry["kind"], "ref": entry["ref"], "name": entry.get("name"),
                    "representation": entry.get("representation"), "parent_ref": entry.get("parent_ref")}
            for key in ("agent_run_id", "persisted_ref", "output_message_ref", "has_model_or_tool_spans"):
                if entry.get(key) is not None:
                    node[key] = entry[key]
            for key in ("duration_ms", "status", "status_code", "input_tokens", "output_tokens"):
                info = entry["fields"].get(key)
                if isinstance(info, Mapping) and info.get("status") == "available":
                    try:
                        node[key] = resolve(self.source, info["ref"])
                    except KeyError:
                        pass
            if isinstance(entry.get("reconstructed_input"), Mapping):
                r = entry["reconstructed_input"]
                node["reconstructed_input"] = {k: r.get(k) for k in ("status", "call_ordinal", "message_refs") if k in r}
                node["token_check"] = (r.get("token_check") or {}).get("result")
            if isinstance(entry.get("pairing"), Mapping):
                node["pairing"] = {k: entry["pairing"].get(k) for k in ("status", "method", "persisted_ref", "reason") if k in entry["pairing"]}
            nodes.append(node)
        nodes.sort(key=lambda n: (_epoch_sort(n["at"]), n["ref"]))
        return {"nodes": nodes[:limit], "total": len(nodes), "truncated": len(nodes) > limit,
                "untimed_records": untimed, "skipped_copy_records": skipped_copies,
                "meaning": "按开始时间排序的 span/步骤视图；每个节点的 ref 可用 read 深入，已配对的持久化工具记录附在 persisted_ref，重建输入见 message_refs。没有时间戳的记录不在此视图，不表示不存在。"}

    def _run(self, run: Any, ref: str, *, scope: str, parent_ref: str = "", representation: str = "api") -> None:
        if not isinstance(run, Mapping):
            return
        run_id = str(run.get("run_id") or "")
        meta = {"run_id": run_id, "scope": scope, "parent_ref": parent_ref, "representation": representation}
        extra = {"workflow_step_id": str(run["workflow_step_id"])} if run.get("workflow_step_id") else {}
        self.add("runs", ref, id=run_id, parent_run_id=run.get("parent_run_id"), **extra,
                 name=run.get("agent_name") or run.get("workflow_id") or run.get("agent_id"),
                 fields={"input": "run_input" if "run_input" in run else "input", "output": "content",
                         "status": "status", "metrics": "metrics", "events": "events", "metadata": "metadata",
                         "provider_data": "model_provider_data", "output_format": "run_response_format"}, **meta)
        status = self.entries[-1]["fields"]["status"]
        if extra and status.get("status") != "missing":
            # Agno 3.0.6 流式 Step：step 取到 RunOutput 后 break（workflow/step.py），生成器随后被关闭，
            # Agent 把 GeneratorExit 当客户端断开，就地把已 COMPLETED 的同一对象改成 CANCELLED（agent/_run.py）。
            # 已用最小 Workflow(Step(agent)) 复现：非流式 COMPLETED，流式 CANCELLED，step.success 均为 True。
            status["note"] = STREAMED_EXECUTOR_STATUS_NOTE
        meta = {**meta, "parent_ref": ref}
        for i, msg in enumerate(run.get("messages") or []):
            if isinstance(msg, Mapping):
                self.add("messages", f"{ref}/messages/{i}", id=msg.get("id"), role=msg.get("role"),
                         tool_call_id=msg.get("tool_call_id"), ordinal=i,
                         fields={"content": "content", "tool_calls": "tool_calls", "tool_name": "tool_name",
                                 "arguments": "tool_args", "error": "tool_call_error", "from_history": "from_history"}, **meta)
                if msg.get("reasoning_content"):
                    self.add("reasoning", f"{ref}/messages/{i}", fields={"text": "reasoning_content"}, **meta)
        for i, tool in enumerate(run.get("tools") or []):
            if isinstance(tool, Mapping):
                self.add("tool_calls", f"{ref}/tools/{i}", id=tool.get("tool_call_id"), name=tool.get("tool_name"),
                         child_run_id=tool.get("child_run_id"),
                         fields={"arguments": "tool_args", "result": "result", "error": "tool_call_error",
                                 "metrics": "metrics", "created_at": "created_at"}, **meta)
                if any(tool.get(k) for k in ("requires_confirmation", "requires_user_input", "external_execution_required")):
                    self.add("requirements", f"{ref}/tools/{i}", id=tool.get("tool_call_id"),
                             fields={k: k for k in ("requires_confirmation", "confirmed", "confirmation_note", "requires_user_input",
                                                    "user_input_schema", "answered", "external_execution_required", "approval_type", "approval_id")}, **meta)
        if "session_state" in run:
            state_ref = pointer(ref, "session_state")
            state = run["session_state"]
            fields: dict[str, str | tuple[str, ...]] = {}
            if isinstance(state, Mapping):
                for key, value in state.items():
                    fields[str(key)] = str(key)
                    if isinstance(value, Mapping) and len(value) <= 40:
                        for sub in value:
                            fields[f"{key}.{sub}"] = (str(key), str(sub))
            self.add("states", state_ref, fields=fields,
                     state_semantics="persisted_run_state_not_transition_log", **meta)
        for key in ("references", "citations"):
            if run.get(key):
                self.add("references", pointer(ref, key), fields={}, source_type=key, **meta)
        for i, event in enumerate(run.get("events") or []):
            if isinstance(event, Mapping):
                self.add("events", f"{ref}/events/{i}", name=event.get("event"),
                         fields={k: k for k in ("event", "created_at", "content", "tool", "metrics")}, **meta)
        for key in ("step_requirements", "requirements"):
            if run.get(key):
                self.add("requirements", pointer(ref, key), fields={}, **meta)
        for key in ("reasoning_content", "reasoning_steps", "reasoning_messages"):
            if run.get(key):
                self.add("reasoning", pointer(ref, key), fields={}, **meta)
        for key in ("images", "videos", "audio", "files", "response_audio", "input_media"):
            if run.get(key):
                self.add("artifacts", pointer(ref, key), fields={}, media_type=key, **meta)
        self._steps(run.get("step_results") or [], pointer(ref, "step_results"), meta)
        for key in ("step_executor_runs", "member_responses"):
            for i, child in enumerate(run.get(key) or []):
                self._run(child, f"{ref}/{key}/{i}", scope=scope, parent_ref=ref, representation=representation)

    def _exact_request(self, ref: str) -> dict[str, Any]:
        """OpenInference LLM span 的 input.value 是插桩在模型调用处记录的请求消息；被隐藏时只能用重建输入。"""
        info = self.field(ref)
        if info["status"] == "available":
            return {**info, "note": "插桩在模型调用处记录的请求消息；工具定义在原始 span 属性 llm.tools.*"}
        return {"status": "unverified", "note": "span 输入未记录或被隐藏；重建输入见 reconstructed_input 及其 token 校验"}

    def _exact_request_coverage(self) -> dict[str, Any]:
        calls = [e for e in self.entries if e["kind"] == "model_calls" and not e.get("copy_of")]
        recorded = sum(1 for e in calls if (e["fields"].get("exact_request") or {}).get("status") == "available")
        if calls and recorded == len(calls):
            return {"status": "available", "count": recorded,
                    "reason": "每次模型调用的 span 都记录了请求消息（model_calls.exact_request）"}
        return {"status": "unverified", "recorded": recorded, "total": len(calls),
                "reason": "部分或全部模型调用的 span 输入被隐藏；这些调用只有 model_calls.reconstructed_input（按 assistant 消息分段并经 token 校验，不含工具定义）"}

    def _definitions(self, value: Any, ref: str, *, root: bool = False) -> None:
        if isinstance(value, Mapping):
            is_tool = "name" in value and "parameters" in value
            if root or is_tool or "system_message" in value or "response_settings" in value:
                self.add("definitions", ref, name=value.get("name") or value.get("id"),
                         definition_type="tool" if is_tool else "component",
                         scope="observed_at_collection_not_verified_run_version",
                         fields={k: k for k in ("description", "parameters", "model", "system_message",
                                                "response_settings", "output_schema", "instruction_templates", "tools", "steps", "input_schema") if k in value})
            for key, child in value.items():
                if isinstance(child, (Mapping, list)):
                    self._definitions(child, pointer(ref, key))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                self._definitions(child, pointer(ref, i))

    def _raw_spans(self, spans: list[Any]) -> None:
        mapped = {(e.get("trace_id"), e.get("id")): e for e in self.entries if e.get("representation") == "span"}
        for i, span in enumerate(spans):
            ref = f"/records/raw_spans/{i}"
            entry = mapped.get((span.get("trace_id"), span.get("span_id")))
            attrs = span.get("attributes") or {}
            if entry is None:
                kind = attrs.get("openinference.span.kind")
                group = "model_calls" if kind == "LLM" else "tool_calls" if kind == "TOOL" else "steps"
                self.add(group, ref, fields={"attributes": "attributes"}, id=span.get("span_id"), name=span.get("name"),
                         trace_id=span.get("trace_id"), run_id=self.snapshot.get("association", {}).get("run_id"),
                         scope="current", representation="sqlite_span")
                entry = self.entries[-1]
            entry["raw_ref"] = ref
            entry["parent_span_id"] = span.get("parent_span_id")
            entry["fields"]["raw_attributes"] = self.field(pointer(ref, "attributes"))
            mapping = {
                "input": "input.value", "output": "output.value", "model": "llm.model_name", "provider": "llm.provider",
                "invocation_parameters": "llm.invocation_parameters", "tool_definitions": "llm.tools",
                "input_messages": "llm.input_messages", "output_messages": "llm.output_messages",
                "input_tokens": "llm.token_count.prompt", "output_tokens": "llm.token_count.completion",
                "cache_read_tokens": "llm.token_count.prompt_details.cache_read",
                "tool_description": "tool.description", "arguments": "tool.parameters",
            }
            for name, key in mapping.items():
                if key in attrs:
                    entry["fields"][name] = self.field(pointer(pointer(ref, "attributes"), key))
            for key in ("status_code", "status_message", "duration_ms", "start_time", "end_time"):
                entry["fields"][key] = self.field(pointer(ref, key))
            if entry["kind"] == "model_calls":
                entry["fields"]["exact_request"] = self._exact_request(pointer(pointer(ref, "attributes"), "input.value"))

    def _steps(self, steps: Any, path: str, meta: dict[str, Any]) -> None:
        if not isinstance(steps, list):
            return
        for i, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            ref = pointer(path, i)
            decoded = _json_object(step.get("content"))
            extra: dict[str, Any] = {}
            if isinstance(decoded, Mapping) and not isinstance(step.get("content"), Mapping):
                extra = {"output_format": "json_object_text", "output_keys": [str(k) for k in decoded][:20]}
            for key in ("executor_type", "executor_name"):
                if step.get(key):
                    extra[key] = str(step[key])
            self.add("steps", ref, id=step.get("step_id"), name=step.get("step_name"),
                     fields={"output": "content", "success": "success", "error": "error", "metrics": "metrics"}, **meta, **extra)
            self._steps(step.get("steps") or [], pointer(ref, "steps"), {**meta, "parent_ref": ref})

    def _spans(self, spans: Any, path: str, trace: Mapping[str, Any], parent_ref: str = "") -> None:
        if not isinstance(spans, list):
            return
        for i, span in enumerate(spans):
            if not isinstance(span, Mapping):
                continue
            ref = pointer(path, i)
            kind = str(span.get("type") or "").upper()
            group = "model_calls" if kind == "LLM" else "tool_calls" if kind == "TOOL" else "steps"
            fields: dict[str, Any] = {
                "input": "input", "output": "output", "status": "status", "error": "error",
                "start_time": "start_time", "end_time": "end_time", "metadata": "metadata", "extra_data": "extra_data",
            }
            if kind == "LLM":
                fields.update({"model": ("metadata", "model"), "input_tokens": ("metadata", "input_tokens"),
                               "output_tokens": ("metadata", "output_tokens")})
            elif kind == "TOOL":
                fields.update({"arguments": ("metadata", "parameters"), "result": "output"})
            extra: dict[str, Any] = {}
            metadata = span.get("metadata")
            if kind in {"AGENT", "TEAM"} and isinstance(metadata, Mapping) and metadata.get("run_id"):
                extra["agent_run_id"] = str(metadata["run_id"])
            self.add(group, ref, id=span.get("id"), name=span.get("name"), representation="span",
                     span_type=kind, trace_id=trace.get("trace_id"), run_id=trace.get("run_id"),
                     scope="current", parent_ref=parent_ref,
                     fields=fields, **extra)
            if kind == "LLM":
                self.entries[-1]["fields"]["exact_request"] = self._exact_request(pointer(ref, "input"))
            self._spans(span.get("spans") or [], pointer(ref, "spans"), trace, parent_ref=ref)

    # ---- cross-representation linking (deterministic, source-backed; never invents content) ----

    def _span_owner(self, entry: Mapping[str, Any], by_ref: Mapping[str, dict[str, Any]],
                    children: Mapping[str, list[dict[str, Any]]]) -> tuple[str | None, str]:
        """Agent run that a LLM/TOOL span belongs to: nearest AGENT ancestor, else the single AGENT sibling."""
        parent = entry.get("parent_ref") or ""
        cursor = parent
        while cursor:
            node = by_ref.get(cursor)
            if node is None:
                break
            if _is_agent_span(node):
                return node["agent_run_id"], "agent_span_ancestor"
            cursor = node.get("parent_ref") or ""
        siblings = [n for n in children.get(parent, []) if _is_agent_span(n)]
        if len(siblings) == 1:
            return siblings[0]["agent_run_id"], "single_agent_span_sibling"
        return None, "ambiguous" if siblings else "no_agent_span"

    def _link(self) -> None:
        spans = [e for e in self.entries if e.get("representation") in {"span", "sqlite_span"}]
        by_ref = {e["ref"]: e for e in spans}
        children: dict[str, list[dict[str, Any]]] = {}
        for e in spans:
            children.setdefault(e.get("parent_ref") or "", []).append(e)
        api_runs = [e for e in self.entries if e["kind"] == "runs" and e.get("representation") == "api" and e.get("scope") == "current"]
        runs_with_messages = {e["id"] for e in api_runs
                              if any(m.get("parent_ref") == e["ref"] for m in self.entries if m["kind"] == "messages")}
        for e in spans:
            if e["kind"] == "steps":
                stack = list(children.get(e["ref"], []))
                found = False
                while stack and not found:
                    node = stack.pop()
                    found = node["kind"] in {"model_calls", "tool_calls"}
                    stack.extend(children.get(node["ref"], []))
                e["has_model_or_tool_spans"] = found
                continue
            owner, method = self._span_owner(e, by_ref, children)
            if owner is None and len(runs_with_messages) == 1:
                owner, method = next(iter(runs_with_messages)), "single_agent_run_fallback"
            e["agent_run_id"] = owner
            e["agent_run_attribution"] = method
        attributed = {e.get("agent_run_id") for e in spans if e["kind"] in {"model_calls", "tool_calls"}}
        for e in spans:
            if _is_agent_span(e) and e["agent_run_id"] in attributed:
                e["has_model_or_tool_spans"] = True  # Agno emits an agent's LLM/TOOL spans as siblings, not children
        for run in api_runs:
            self._link_model_calls(run, spans)
            self._link_tool_calls(run, spans)

    def _start(self, entry: Mapping[str, Any]) -> float | None:
        stamp = _epoch(self.value(entry, "start_time"))
        if stamp is not None:
            return stamp
        metrics = self.value(entry, "metrics")
        if isinstance(metrics, Mapping):
            stamp = _epoch(metrics.get("start_time"))
            if stamp is not None:
                return stamp
        # Agno 工具记录的 created_at 可能在执行结束时生成，不能覆盖真实开始时间。
        return _epoch(self.value(entry, "created_at"))

    def _link_model_calls(self, run: Mapping[str, Any], spans: list[dict[str, Any]]) -> None:
        run_ref, run_id = run["ref"], run["id"]
        messages = [m for m in self.entries if m["kind"] == "messages" and m.get("parent_ref") == run_ref]
        assistants = [m for m in messages if m.get("role") == "assistant"]
        calls = sorted((s for s in spans if s["kind"] == "model_calls" and s.get("agent_run_id") == run_id),
                       key=lambda s: self._start(s) or 0.0)
        if not assistants and not calls:
            return
        if len(assistants) != len(calls):
            for span in calls:
                span["reconstructed_input"] = {
                    "status": "unresolved", "run_id": run_id,
                    "reason": f"assistant_messages={len(assistants)} llm_spans={len(calls)}；分段与 span 数不一致，不重建",
                }
            return
        for ordinal, (assistant, span) in enumerate(zip(assistants, calls)):
            before = [m["ref"] for m in messages if m["ordinal"] < assistant["ordinal"]]
            raw = self.value(assistant, "content")
            metrics = None
            try:
                metrics = resolve(self.source, pointer(assistant["ref"], "metrics"))
            except KeyError:
                pass
            msg_in = _int(metrics.get("input_tokens")) if isinstance(metrics, Mapping) else None
            msg_out = _int(metrics.get("output_tokens")) if isinstance(metrics, Mapping) else None
            span_in = _int(self.value(span, "input_tokens"))
            span_out = _int(self.value(span, "output_tokens"))
            comparable = [(a, b) for a, b in ((msg_in, span_in), (msg_out, span_out)) if a is not None and b is not None]
            if not comparable:
                status, result = "unverified", "token_counts_unavailable"
            elif all(a == b for a, b in comparable):
                status, result = "verified", "match"
            else:
                status, result = "mismatch", "mismatch"
            span["reconstructed_input"] = {
                "status": status, "method": "persisted_messages_before_assistant", "run_id": run_id,
                "call_ordinal": ordinal, "assistant_message_ref": assistant["ref"], "message_refs": before,
                "token_check": {"result": result, "message_input_tokens": msg_in, "span_input_tokens": span_in,
                                "message_output_tokens": msg_out, "span_output_tokens": span_out},
                "excludes": "工具定义、模型参数等非消息内容（见 definitions / invocation_parameters）；正文以 message_refs 为准",
            }
            span["output_message_ref"] = assistant["ref"]
            span["output_visibility"] = "assistant_message_persisted" if raw not in (None, "") else "assistant_message_empty"
            assistant["model_call_ref"] = span["ref"]
            assistant["call_ordinal"] = ordinal

    def _link_tool_calls(self, run: Mapping[str, Any], spans: list[dict[str, Any]]) -> None:
        run_ref, run_id = run["ref"], run["id"]
        persisted = [t for t in self.entries if t["kind"] == "tool_calls" and t.get("parent_ref") == run_ref
                     and t.get("representation") == "api"]
        tool_spans = [s for s in spans if s["kind"] == "tool_calls" and s.get("agent_run_id") == run_id]
        tool_messages = {m.get("tool_call_id"): m for m in self.entries
                         if m["kind"] == "messages" and m.get("parent_ref") == run_ref and m.get("tool_call_id")}
        free = list(tool_spans)
        for tool in sorted(persisted, key=lambda t: self._start(t) or 0.0):
            if tool.get("id") in tool_messages:
                tool["tool_message_ref"] = tool_messages[tool["id"]]["ref"]
                tool_messages[tool["id"]]["tool_call_ref"] = tool["ref"]
            same_name = [s for s in free if s.get("name") == tool.get("name")]
            args = self.value(tool, "arguments")
            same_args = [s for s in same_name if _json_object(self.value(s, "arguments")) == args]
            t_start = self._start(tool)

            def delta(span: Mapping[str, Any]) -> float:
                s_start = self._start(span)
                return abs(s_start - t_start) if s_start is not None and t_start is not None else float("inf")

            if len(same_args) == 1:
                chosen, method = same_args[0], "name_and_arguments"
            elif same_args:
                chosen = min(same_args, key=delta)
                method = "name_arguments_and_nearest_start_time" if delta(chosen) != float("inf") else ""
            elif same_name:
                chosen = min(same_name, key=delta)
                method = "name_and_nearest_start_time" if delta(chosen) <= _PAIR_TOLERANCE_S else ""
            else:
                chosen, method = None, ""
            if chosen is None or not method:
                tool["pairing"] = {"status": "unpaired", "reason": "没有可唯一对应的 TOOL span" if not same_name else "同名 span 参数或时间无法唯一对应"}
                continue
            free.remove(chosen)
            d = delta(chosen)
            pairing = {"status": "paired", "method": method,
                       "start_delta_ms": None if d == float("inf") else round(d * 1000, 1)}
            tool["pairing"] = pairing | {"span_ref": chosen["ref"]}
            tool["span_ref"] = chosen["ref"]
            chosen["pairing"] = pairing | {"persisted_ref": tool["ref"]}
            chosen["persisted_ref"] = tool["ref"]
            chosen["tool_call_id"] = tool.get("id")
        for span in free:
            span["pairing"] = {"status": "unpaired", "reason": "没有对应的持久化工具记录"}
