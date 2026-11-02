"""llmtracing 快照 → 一份按位置编号的线性对话稿（transcript），确定性重建，不调模型。

llmtracing 只记录模型协议流量：每次调用的请求上下文（messages/tools/参数）与响应。
同一次业务执行里后一次调用通常带着前一次的上下文，所以只展开每次调用新增的消息，
加上该次响应，就是模型实际看到与产出的完整过程。评测直接读这份对话稿，不经 dossier/links。

位置编号（引用只用这些）：
  t{n}.request / t{n}.final        第 n 轮业务请求与业务最终答复（verifier 侧记录）
  t{n}.c{k}                         第 n 轮第 k 次模型调用（状态、耗时、token、上下文关系）
  t{n}.c{k}.system / .tools         该次调用的系统提示词 / 工具定义（与前次相同时只写"同 xx"）
  t{n}.c{k}.m{j}                    该次请求里第 j 条消息（只列本次新增的）
  t{n}.c{k}.response                该次模型响应（正文与发起的工具调用）
  t{n}.gap.{name}                   本轮证据限制
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ..reader import redact
from .llmtracing import limitations

KIND = "llmtracing_transcript"
# 单份对话稿上限：超出时按比例截断最长的条目（工具定义、长工具结果），截断处写明原长。
BUDGET_CHARS = 100_000
_MIN_ENTRY_CHARS = 600


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [p.get("text") if isinstance(p, Mapping) and isinstance(p.get("text"), str) else
                 json.dumps(p, ensure_ascii=False, default=str) for p in value]
        return "\n".join(str(p) for p in parts)
    return json.dumps(value, ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _tool_calls_text(calls: Any) -> str:
    out = []
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, Mapping):
            continue
        function = call.get("function") if isinstance(call.get("function"), Mapping) else {}
        out.append(f"→ 调用 {function.get('name')}#{call.get('id')}({function.get('arguments')})")
    return "\n".join(out)


def _message_text(message: Mapping[str, Any], tool_names: Mapping[str, str]) -> tuple[str, str]:
    role = str(message.get("role") or "unknown")
    if role == "tool":
        tool_id = str(message.get("tool_call_id") or "")
        label = f"tool {tool_names.get(tool_id, '?')}#{tool_id}"
    else:
        label = role
    body = _text(message.get("content"))
    calls = _tool_calls_text(message.get("tool_calls"))
    return label, "\n".join(x for x in (body, calls) if x)


def _response_message(outcome: Mapping[str, Any]) -> Mapping[str, Any]:
    response = outcome.get("response") if isinstance(outcome.get("response"), Mapping) else {}
    choices = response.get("choices") if isinstance(response.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], Mapping) else {}
    message = first.get("message")
    return message if isinstance(message, Mapping) else {}


def _turns(trace: Any, snapshot: Any) -> list[dict[str, Any]]:
    records = getattr(trace, "turn_records", None) or []
    if records:
        return [{"request": r.get("mock_message") or r.get("request"), "final": r.get("extracted_output"),
                 "snapshot": (r.get("project_fields") or {}).get("business_trace")} for r in records]
    return [{"request": getattr(trace, "normalized_request", None), "final": getattr(trace, "extracted_output", None),
             "snapshot": snapshot}]


def _turn_entries(n: int, snapshot: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not isinstance(snapshot, Mapping) or snapshot.get("status") == "failed":
        errors = snapshot.get("errors", []) if isinstance(snapshot, Mapping) else []
        entries.append({"id": f"t{n}.gap.collection", "kind": "gap",
                        "text": "本轮 llmtracing 快照缺失或采集失败；不能据此断言本轮没有模型调用。errors="
                                + json.dumps(errors, ensure_ascii=False)})
        return entries, {"turn": f"turn{n}", "status": "failed", "errors": errors}
    raw_calls = [c for c in (snapshot.get("records") or {}).get("calls") or [] if isinstance(c, Mapping)]
    calls = redact(raw_calls)
    tool_names: dict[str, str] = {}
    seen: dict[str, dict[str, str]] = {"system": {}, "tools": {}, "params": {}}
    previous: list[Any] = []
    for k, call in enumerate(calls, start=1):
        cid = f"t{n}.c{k}"
        pre = call.get("pre") if isinstance(call.get("pre"), Mapping) else {}
        outcome = call.get("outcome") if isinstance(call.get("outcome"), Mapping) else {}
        messages = [m for m in pre.get("messages") or [] if isinstance(m, Mapping)]
        system = [m for m in messages if m.get("role") == "system"]
        body = [m for m in messages if m.get("role") != "system"]
        shared = 0
        while shared < min(len(previous), len(body)) and _digest(previous[shared]) == _digest(body[shared]):
            shared += 1
        if k == 1 or not previous:
            relation = "首次调用"
        elif shared == len(previous):
            relation = f"上下文 = 上一次调用的上下文（{shared} 条）+ 新增 {len(body) - shared} 条"
        else:
            relation = (f"上下文与上一次调用只在前 {shared} 条一致；上一次的后 {len(previous) - shared} 条"
                        f"未出现在本次请求里（被改写、压缩或丢弃），本次从第 {shared + 1} 条起列出")
        usage = outcome.get("usage") if isinstance(outcome.get("usage"), Mapping) else {}
        # tools 已单列为 .tools 条目；参数与前次相同只写出处。
        params = {k: v for k, v in (pre.get("optional_params") or {}).items() if k != "tools"}
        params_digest = _digest(params)
        params_ref = seen["params"].setdefault(params_digest, cid)
        header = {"model": pre.get("model") or outcome.get("model"), "protocol": pre.get("protocol"),
                  "status": outcome.get("event") or "unfinished", "start": pre.get("ts"), "end": outcome.get("ts"),
                  "latency_ms": outcome.get("latency_ms"), "prompt_tokens": usage.get("prompt_tokens"),
                  "completion_tokens": usage.get("completion_tokens"),
                  "params": params if params_ref == cid else f"同 {params_ref}", "context": relation}
        entries.append({"id": cid, "kind": "call", "text": json.dumps(header, ensure_ascii=False, default=str)})
        for key, value in (("system", system), ("tools", pre.get("tools"))):
            if not value:
                continue
            digest = _digest(value)
            first = seen[key].get(digest)
            if first:
                entries.append({"id": f"{cid}.{key}", "kind": key, "text": f"同 {first}"})
            else:
                seen[key][digest] = f"{cid}.{key}"
                text = "\n\n".join(_text(m.get("content")) for m in value) if key == "system" else \
                    json.dumps(value, ensure_ascii=False, default=str)
                entries.append({"id": f"{cid}.{key}", "kind": key, "text": text})
        offset = len(system)
        for j in range(shared, len(body)):
            label, text = _message_text(body[j], tool_names)
            entries.append({"id": f"{cid}.m{offset + j + 1}", "kind": "message", "role": label, "text": text})
        previous = body
        if outcome.get("event") == "failure":
            entries.append({"id": f"{cid}.response", "kind": "error", "text": _text(outcome.get("error"))})
        elif outcome:
            message = _response_message(outcome)
            for tool in message.get("tool_calls") or []:
                if isinstance(tool, Mapping) and tool.get("id"):
                    function = tool.get("function") if isinstance(tool.get("function"), Mapping) else {}
                    tool_names[str(tool["id"])] = str(function.get("name") or "?")
            label, text = _message_text(message, tool_names)
            entries.append({"id": f"{cid}.response", "kind": "response", "role": label, "text": text})
        else:
            entries.append({"id": f"{cid}.response", "kind": "error", "text": "调用未完结：中转日志里没有响应事件"})
    limits = limitations(raw_calls)
    for name, item in limits.items():
        if item.get("status") != "complete":
            entries.append({"id": f"t{n}.gap.{name}", "kind": "gap", "text": json.dumps(item, ensure_ascii=False)})
    return entries, {"turn": f"turn{n}", "status": snapshot.get("status"), "calls": len(calls),
                     "errors": list(snapshot.get("errors") or []), "limitations": limits}


def build_transcript(trace: Any, snapshot: Any) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    coverage = []
    for n, turn in enumerate(_turns(trace, snapshot), start=1):
        entries.append({"id": f"t{n}.request", "kind": "request",
                        "text": json.dumps(redact(turn["request"]), ensure_ascii=False, default=str)})
        body, cover = _turn_entries(n, turn["snapshot"])
        entries += body
        coverage.append(cover)
        entries.append({"id": f"t{n}.final", "kind": "final",
                        "text": json.dumps(turn["final"], ensure_ascii=False, default=str)})
    return {"kind": KIND, "records": entries, "coverage": coverage,
            "model_calls": sum(c.get("calls") or 0 for c in coverage)}


def is_transcript(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("kind") == KIND


def transcript_ids(transcript: Mapping[str, Any]) -> set[str]:
    return {e["id"] for e in transcript["records"]}


def render(transcript: Mapping[str, Any], *, budget_chars: int = BUDGET_CHARS) -> str:
    """每条一段 `[id] 角色` + 正文。超预算时把最长条目截到同一上限（不删条目，编号一个不丢）。"""
    entries = transcript["records"]

    def head(e: Mapping[str, Any]) -> str:
        return f"[{e['id']}] {e.get('role') or e['kind']}"

    fixed = sum(len(head(e)) + 2 for e in entries)
    lengths = sorted(len(e["text"]) for e in entries)
    cap = None
    if fixed + sum(lengths) > budget_chars:
        room = max(budget_chars - fixed, 0)
        # 找最大的 cap 使 sum(min(len, cap)) ≤ room。
        total, cap = 0, _MIN_ENTRY_CHARS
        for i, length in enumerate(lengths):
            remaining = len(lengths) - i
            if total + length * remaining > room:
                cap = max((room - total) // remaining, _MIN_ENTRY_CHARS)
                break
            total += length
    blocks = []
    for e in entries:
        text = e["text"]
        if cap is not None and len(text) > cap:
            text = text[:cap] + f"\n…（截断：原文 {len(text)} 字，此处只保留前 {cap} 字）"
        blocks.append(f"{head(e)}\n{text}")
    return "\n\n".join(blocks)


__all__ = ["BUDGET_CHARS", "KIND", "build_transcript", "is_transcript", "render", "transcript_ids"]
