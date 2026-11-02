"""Link instances enumerated from recorded execution structure (W1 §1: t → Λ, Φ).

A link is one processing unit with an input side and an output side, both given as
dossier record ids (plus the field names on each side). ``facts`` holds only relations
the program can check exactly (same name+arguments, text containment, equality,
timing). Facts state relations; they never judge whether a link behaved correctly.

Only execution concepts are used: runs, steps (nested step_results), model calls, tool
calls, messages, final/delivered output. No business field names are read.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Mapping

from impl.projects.llm_probe.business_trace.dossier import render_value

LINK_TYPES = {
    "intent_understanding": "表达：用户原文 → 系统内部表达",
    "planning_routing": "编排：任务与当时状态 → 走哪条路、调什么、何时重试或停止",
    "tool_execution": "执行：调用参数 → 返回",
    "knowledge_data": "数据源：已正确执行的查询 → 数据是否存在",
    "model_capability": "模型：一次调用的实际输入 → 该次输出",
    "context_memory": "传递：一处产出 → 下一处输入",
}
# π：环节类型 → 唯一轴。
AXIS_LINK_TYPES = {
    "intent_understanding": ("intent_understanding",), "planning_routing": ("planning_routing",), "tool_execution": ("tool_execution",),
    "knowledge_data": ("knowledge_data",), "model_capability": ("model_capability",), "context_memory": ("context_memory",),
}
TYPE_AXES = {t: tuple(a for a, types in AXIS_LINK_TYPES.items() if t in types) for t in LINK_TYPES}
LIMITS = ("环节表只列程序从 Agno 结构能确定的环节与机器事实，不是可疑判断，也不是全部环节。"
          "facts 只陈述关系（同名同参、包含、相等、时序），不说明对错；contains=false 可能只是表示形式不同，须读两端原文。"
          "planning_routing:path 与 knowledge_data 以一轮为单位：输入端是本轮用户输入（与运行末态），输出端是本轮全部调用与步骤产出。表外的环节须另行补出。")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _value(dossier: Mapping[str, Any], row: Mapping[str, Any] | None, field: str) -> Any:
    info = ((row or {}).get("fields") or {}).get(field) or {}
    if info.get("status") != "available" or "value" not in info:
        return None
    return render_value(dossier, info["value"])


def _norm(text: str) -> str:
    return "".join(text.split())


def _contains(outer: Any, inner: Any) -> bool | None:
    """None when either side is unrecorded; otherwise whitespace-insensitive containment."""
    if outer is None or inner is None:
        return None
    small = _norm(_text(inner))
    if not small:
        return None
    return small in _norm(_text(outer))


def _parsed(value: Any) -> Any:
    """Unwrap a single-key text holder and JSON text so that equal content compares equal."""
    if isinstance(value, Mapping) and len(value) == 1:
        value = next(iter(value.values()))
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _key_diff(stored: Any, delivered: Any) -> dict[str, list[str]] | None:
    """Top-level keys changed, dropped or added on delivery; None when either side is unrecorded."""
    if stored is None or delivered is None:
        return None
    a, b = _parsed(stored), _parsed(delivered)
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return {"changed": sorted(k for k in a if k in b and a[k] != b[k]),
                "dropped": sorted(k for k in a if k not in b), "added": sorted(k for k in b if k not in a)}
    return {"changed": [] if a == b else ["<whole>"], "dropped": [], "added": []}


def _time(dossier: Mapping[str, Any], row: Mapping[str, Any], key: str) -> float | None:
    metrics = _value(dossier, row, "metrics")
    value = metrics.get(key) if isinstance(metrics, Mapping) else None
    return float(value) if isinstance(value, (int, float)) else None


def _live(rows: Iterable[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [r for r in rows if r.get("kind") == kind and r.get("scope") == "current" and not r.get("copy_of")]


def _link(link_id: str, link_type: str, turn: Any, inputs: list[tuple[str, str]], outputs: list[tuple[str, str]],
          basis: str, **facts: Any) -> dict[str, Any]:
    return {"link_id": link_id, "link_type": link_type, "turn": turn,
            "input": [{"ref": ref, "field": field} for ref, field in inputs],
            "output": [{"ref": ref, "field": field} for ref, field in outputs],
            "facts": {k: v for k, v in facts.items() if v is not None}, "basis": basis}


def _agent_definitions(rows: Mapping[str, Mapping[str, Any]], call: Mapping[str, Any]) -> list[str]:
    """重建输入只有消息；Agno 每次请求还带该 Agent 的工具定义。按调用所属 run 的组件名找同轮组件定义下的工具定义（采集时版本）。"""
    run_id = (call.get("reconstructed_input") or {}).get("run_id")
    run = next((r for r in rows.values() if r.get("kind") == "runs" and run_id and r.get("run_id") == run_id), None)
    if not run or not run.get("name"):
        return []
    owners = [r["id"] for r in rows.values() if r.get("kind") == "definitions" and r.get("turn") == call.get("turn")
              and r.get("definition_type") == "component" and r.get("name") == run["name"]]
    return [r["id"] for r in rows.values() if r.get("kind") == "definitions" and r.get("definition_type") == "tool"
            and any(r["id"].startswith(f"{owner}/") for owner in owners)]


def _model_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    links = []
    for call in dossier.get("model_calls") or []:
        if call.get("scope") != "current":
            continue
        exact = (call.get("exact_request") or {}).get("status") == "available"
        messages = [ref for ref in (call.get("reconstructed_input") or {}).get("message_refs") or [] if ref in rows]
        inputs = ([(call["id"], "exact_request")] if exact else
                  [(ref, "content") for ref in messages] + [(ref, "definition") for ref in _agent_definitions(rows, call)])
        if call.get("recorded_request"):
            inputs = [(call["id"], "input")]
        # 与输入端同理：端点选实际保存了内容的字段。持久化消息常不存助手正文，此时用 span 记录的输出。
        out = call.get("output_message_ref")
        saved = ((rows.get(out) or {}).get("fields") or {}).get("content", {}).get("status") == "available"
        outputs = [(out, "content")] if saved or (out in rows and (call.get("output") or {}).get("status") != "available") \
            else [(call["id"], "output")]
        links.append(_link(f"model_capability:{call['id']}", "model_capability", call.get("turn"), inputs, outputs,
                           "SDK 记录的请求表示（完整性未证实）" if call.get("recorded_request") else
                           "span 记录的请求" if exact else "持久化消息重建的请求",
                           input_source="recorded_input" if call.get("recorded_request") else "exact_request" if exact else
                           (call.get("reconstructed_input") or {}).get("status", "missing")))
    return links


def _tool_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    links, groups = [], defaultdict(list)
    # A span paired with a persisted call is the same execution seen twice.
    for tool in [t for t in _live(rows.values(), "tool_calls") if not t.get("persisted_ref")]:
        start, end = _time(dossier, tool, "start_time"), _time(dossier, tool, "end_time")
        links.append(_link(f"tool_execution:{tool['id']}", "tool_execution", tool.get("turn"), [(tool["id"], "arguments")],
                           [(tool["id"], "result"), (tool["id"], "error")], "工具调用参数 → 返回",
                           tool=tool.get("name"), tool_error=_value(dossier, tool, "error") or None,
                           duration_s=round(end - start, 3) if start is not None and end is not None else None))
        args = _value(dossier, tool, "arguments")
        groups[(tool.get("run_id"), tool.get("name"), _text(args))].append((start, end, tool))
    for (_run, name, _args), calls in groups.items():
        if len(calls) < 2:
            continue
        calls.sort(key=lambda c: (c[0] is None, c[0] or 0))
        for (p_start, p_end, prior), (start, _end, tool) in zip(calls, calls[1:]):
            same_result = _value(dossier, prior, "result") == _value(dossier, tool, "result")
            links.append(_link(f"planning_routing:repeat:{tool['id']}", "planning_routing", tool.get("turn"),
                               [(prior["id"], "result"), (prior["id"], "error")], [(tool["id"], "arguments")],
                               "同一 agent run 内同名同参再次调用：前次结果 → 编排与模型是否再次发出",
                               tool=name, repeat_of=prior["id"],
                               started_after_prior_ended=(start >= p_end) if start is not None and p_end is not None else None,
                               same_result=same_result))
    return links


def _transfer_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    links, seen = [], set()
    for call in dossier.get("model_calls") or []:
        if call.get("scope") != "current":
            continue
        for ref in (call.get("reconstructed_input") or {}).get("message_refs") or []:
            message = rows.get(ref) or {}
            tool = rows.get(message.get("tool_call_ref"))
            # Later calls re-read the same history; the first model input carrying it is the transfer.
            if message.get("role") != "tool" or not tool or tool["id"] in seen:
                continue
            seen.add(tool["id"])
            links.append(_link(f"context_memory:tool→model:{tool['id']}→{call['id']}", "context_memory", call.get("turn"),
                               [(tool["id"], "result")], [(ref, "content")], "工具返回 → 下次模型输入中的工具消息",
                               contains=_contains(_value(dossier, message, "content"), _value(dossier, tool, "result"))))
    return links


def _step_spans(rows: Mapping[str, Mapping[str, Any]]) -> dict[tuple[Any, str], Mapping[str, Any]]:
    """步骤在 trace 里的 span，按（轮次, 步骤名）配对；同名出现多次（如循环）时无法一一对应，不配。"""
    groups = defaultdict(list)
    for r in _live(rows.values(), "steps"):
        if r.get("representation") == "span":
            groups[(r.get("turn"), str(r.get("name") or "").split(".")[0])].append(r)
    return {key: spans[0] for key, spans in groups.items() if len(spans) == 1}


def _step_end(dossier: Mapping[str, Any], spans: Mapping[tuple[Any, str], Mapping[str, Any]],
              step: Mapping[str, Any], field: str) -> tuple[str, str]:
    """端点选实际保存了内容的字段：Agno 的 step_results 常不存步骤输入输出，此时用同一步骤 span 记录的。"""
    span = spans.get((step.get("turn"), step.get("name")))
    if _value(dossier, step, field) is None and _value(dossier, span, field) is not None:
        return span["id"], field
    return step["id"], field


def _end_value(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]], end: tuple[str, str]) -> Any:
    return _value(dossier, rows.get(end[0]), end[1])


def _step_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    steps = [r for r in _live(rows.values(), "steps") if r.get("representation") != "span"
             and r.get("sequence_known") is not False]
    spans, children = _step_spans(rows), defaultdict(list)
    for step in steps:
        children[step.get("parent_ref")].append(step)
    links = []
    for parent, siblings in children.items():
        for prev, nxt in zip(siblings, siblings[1:]):
            produced, received = _step_end(dossier, spans, prev, "output"), _step_end(dossier, spans, nxt, "input")
            recorded = _end_value(dossier, rows, received)
            outputs = [received] if recorded is not None else [_step_end(dossier, spans, nxt, "output")]
            links.append(_link(f"context_memory:step:{prev['id']}→{nxt['id']}", "context_memory", nxt.get("turn"), [produced], outputs,
                               "步骤产出 → 下一步骤" + ("输入" if recorded is not None else "（下一步输入未记录，输出端为其产出）"),
                               next_input_recorded=recorded is not None,
                               contains=_contains(recorded, _end_value(dossier, rows, produced)) if recorded is not None else None))
        for step in siblings:
            nested = children.get(step["id"]) or []
            if nested:
                previous = siblings[siblings.index(step) - 1] if siblings.index(step) else None
                links.append(_link(f"planning_routing:branch:{step['id']}", "planning_routing", step.get("turn"),
                                   [_step_end(dossier, spans, previous, "output")] if previous else [(parent, "input")],
                                   [_step_end(dossier, spans, step, "output")], "带子步骤的控制步骤（Condition/Router/Loop 等）→ 实际执行的子步骤",
                                   executed=[c.get("name") for c in nested]))
    return links


def _input_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """context_memory:input：Agent 收到的任务（及会话历史）→ 系统为该次模型调用组装的实际输入。"""
    spans = {r["agent_run_id"]: r for r in _live(rows.values(), "steps") if r.get("agent_run_id")}
    agent_runs = defaultdict(list)
    for run in _live(rows.values(), "runs"):
        if run.get("parent_ref"):
            agent_runs[run.get("turn")].append(run)
    links = []
    for call in dossier.get("model_calls") or []:
        if call.get("scope") != "current":
            continue
        out = rows.get(call.get("output_message_ref")) or {}
        runs = agent_runs.get(call.get("turn")) or []
        owner = [r for r in runs if out.get("run_id") and r.get("run_id") == out.get("run_id")] or runs[:1]
        exact = (call.get("exact_request") or {}).get("status") == "available"
        messages = [ref for ref in (call.get("reconstructed_input") or {}).get("message_refs") or [] if ref in rows]
        outputs = [(call["id"], "exact_request")] if exact else [(ref, "content") for ref in messages]
        task = None
        if owner:  # 同上：run 记录常不存 Agent 收到的任务，此时用该 run 的 span（agent_run_id 相同）记录的输入。
            span = spans.get(owner[0].get("run_id"))
            task = (span["id"], "input") if _value(dossier, owner[0], "input") is None and _value(dossier, span, "input") is not None \
                else (owner[0]["id"], "input")
        if call.get("recorded_request"):
            outputs = [(call["id"], "input")]
            task = (call["task_ref"], "input") if call.get("task_ref") in rows else None
        links.append(_link(f"context_memory:input:{call['id']}", "context_memory", call.get("turn"),
                           [task] if task else [], outputs,
                           "Agent 收到的任务 → 该次模型调用的实际输入（系统组装）"))
    return links


def _turn_links(dossier: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    links, spans = [], _step_spans(rows)
    agent_spans = {r["agent_run_id"]: r for r in _live(rows.values(), "steps") if r.get("agent_run_id")}
    current = [r for r in rows.values() if r.get("scope") == "current" and not r.get("copy_of")]
    said, expressed = [], []  # 意图：截至本轮的用户原文与内部表达
    for source in dossier.get("sources") or []:
        turn = source["id"]
        turn_rows = [r for r in current if r.get("turn") == turn]
        runs = [r for r in turn_rows if r["kind"] == "runs" and not r.get("parent_ref")]
        top = [r for r in turn_rows if r["kind"] == "steps" and r.get("representation") != "span"
               and runs and r.get("parent_ref") == runs[0]["id"]]
        calls = [c for c in dossier.get("model_calls") or [] if c.get("turn") == turn and c.get("scope") == "current"]
        if runs:
            tasks = []
            for run in (r for r in turn_rows if r["kind"] == "runs" and r.get("parent_ref")):
                span = agent_spans.get(run.get("run_id"))
                tasks.append((span["id"], "input") if span and _value(dossier, run, "input") is None
                             and _value(dossier, span, "input") is not None else (run["id"], "input"))
            said.append((runs[0]["id"], "input"))
            expressed += [_step_end(dossier, spans, step, "output") for step in top] + tasks
            expressed += [(c["output_message_ref"], "tool_calls") for c in calls if c.get("output_message_ref") in rows]
            links.append(_link(f"intent_understanding:{turn}", "intent_understanding", turn, list(said), list(expressed),
                               "第 1 轮到本轮的用户原文 → 截至本轮的内部表达（各步骤产出、交给 Agent 的任务、各次模型调用发出的工具调用）"))
            tools = sorted((t for t in turn_rows if t["kind"] == "tool_calls" and not t.get("persisted_ref")),
                           key=lambda t: (_time(dossier, t, "start_time") is None, _time(dossier, t, "start_time") or 0))
            states = [(r["id"], "") for r in turn_rows if r["kind"] == "states"]
            steps_out = [_step_end(dossier, spans, s, "output") for s in top]
            tool_ends = [(t["id"], "arguments") for t in tools] + [(t["id"], "result") for t in tools]
            links.append(_link(f"planning_routing:path:{turn}", "planning_routing", turn, [(runs[0]["id"], "input")] + states,
                               steps_out + tool_ends, "本轮任务与运行末态 → 实际走的路径、调用序列与收尾",
                               tool_sequence=[t.get("name") for t in tools], model_calls=len(calls)))
            links.append(_link(f"knowledge_data:{turn}", "knowledge_data", turn,
                               [(runs[0]["id"], "input")] + [(t["id"], "arguments") for t in tools],
                               [(t["id"], "result") for t in tools] or steps_out,
                               "本轮问题与已发出的查询 → 外部数据源实际给出的数据" + ("" if tools else "（无工具调用，输出端为步骤产出）"),
                               tool_calls=len(tools)))
        stored = next((r for r in turn_rows if r["kind"] == "final_output"), None)
        delivered = next((r for r in turn_rows if r["kind"] == "delivered_output"), None)
        last = top[-1] if top else None
        if delivered and (stored or last):
            source = _step_end(dossier, spans, last, "output") if last else (stored["id"], "output")
            delivered_value = _value(dossier, delivered, "output")
            links.append(_link(f"context_memory:deliver:{turn}", "context_memory", turn, [source], [(delivered["id"], "output")],
                               "最后步骤产出 → 调用方实收",
                               vs_stored=_key_diff(_value(dossier, stored, "output"), delivered_value)
                               if stored else None))
    return links


def program_suspects(links: Iterable[Mapping[str, Any]], *, recorder: str = "Agno") -> list[dict[str, Any]]:
    """Links whose facts depart from identity. Recall-oriented: a hit is a place to look, not a finding."""
    hits = []
    for link in links:
        facts, why = link["facts"], []
        if facts.get("repeat_of"):
            why.append(f"同名同参再次调用（前次 {facts['repeat_of']}）")
        if facts.get("contains") is False:
            why.append("输出端不含输入端原文")
        diff = facts.get("vs_stored") or {}
        if diff.get("changed"):
            why.append(f"实收相对落库改变了 {diff['changed']}")
        if diff.get("dropped"):
            why.append(f"实收相对落库缺少 {diff['dropped']}")
        if facts.get("tool_error"):
            why.append(f"{recorder} 标记工具出错")
        if why:
            hits.append({"link_id": link["link_id"], "why": "；".join(why), "origin": "program"})
    return hits


def link_ends(link: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(end["ref"] for side in ("input", "output") for end in link[side]))


def build_links(dossier: Mapping[str, Any], *, axis_id: str | None = None) -> dict[str, Any]:
    """All link instances, or only those π assigns to ``axis_id``."""
    rows = {row["id"]: row for row in dossier.get("records") or []}
    links = (_turn_links(dossier, rows) + _step_links(dossier, rows) + _model_links(dossier, rows)
             + _tool_links(dossier, rows) + _transfer_links(dossier, rows) + _input_links(dossier, rows))
    types = AXIS_LINK_TYPES.get(axis_id, ()) if axis_id else tuple(LINK_TYPES)
    return {"types": {t: LINK_TYPES[t] for t in types}, "links": [l for l in links if l["link_type"] in types],
            "limits": "\n".join(dict.fromkeys(s["link_limits"] for s in dossier.get("sources", [])
                                              if s.get("link_limits"))) or LIMITS}
