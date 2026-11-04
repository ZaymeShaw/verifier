"""按 trace 复评（spec/alg/trace-replay.md）：一个 case 不调业务，按 trace id 取回这一轮。

同一次执行里取一次：Session 投递前要用户原话（对话记录），投递时要交付与快照，两处共用这一次的结果。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Mapping, Optional

_FETCHED: ContextVar[Optional[dict]] = ContextVar("llm_probe_loop_from_trace", default=None)


def trace_id_of(request: Mapping[str, Any]) -> str:
    value = request.get("from_trace") if isinstance(request, Mapping) else None
    return str(value.get("trace_id") or "").strip() if isinstance(value, Mapping) else ""


def fetch(request: Mapping[str, Any]) -> dict[str, Any]:
    """取回这一轮（本执行上下文里同一 trace id 只取一次）。"""
    from impl.projects.llm_probe_loop.business_trace import from_trace
    from impl.projects.llm_probe_loop.capability import capability_business_trace_selection

    trace_id = trace_id_of(request)
    cached = _FETCHED.get()
    if cached is not None and cached.get("trace_id") == trace_id:
        return cached["result"]
    ref = str(request.get("capability_ref") or "").strip()
    result = from_trace(capability_business_trace_selection(ref), trace_id)
    _FETCHED.set({"trace_id": trace_id, "result": result})
    return result


def take(request: Mapping[str, Any]) -> dict[str, Any]:
    """投递时用：取回（或用已取的）并清掉，不留到下一个 case。"""
    result = fetch(request)
    _FETCHED.set(None)
    return result


def _messages(value: Any) -> Optional[list]:
    return value if isinstance(value, list) and value and all(isinstance(m, Mapping) and "role" in m for m in value) else None


def request_body(recorded: Any) -> dict[str, Any]:
    """trace 记录的本轮请求 → 运行记录里的请求体，与现场同形：对话消息数组原样作 messages（最后一条 user 是本轮原话，
    前面的问答是历史）；一段文本就是用户这一轮说的话；其他形状整份作为用户这一轮发来的东西，不猜字段名。"""
    if _messages(recorded) is not None:
        return {"messages": list(recorded)}
    if isinstance(recorded, str):
        return {"messages": [{"role": "user", "content": recorded}]}
    return dict(recorded) if isinstance(recorded, Mapping) else {"input": recorded}


def user_text(recorded: Any) -> str:
    """用户这一轮的原话（对话记录用）。"""
    body = request_body(recorded) if recorded is not None else {}
    users = [m for m in body.get("messages") or [] if isinstance(m, Mapping) and m.get("role") == "user"]
    if users:
        return str(users[-1].get("content") or "")
    import json
    return json.dumps(body, ensure_ascii=False) if body else ""


def _history_count(body: Mapping[str, Any]) -> int:
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    return max(0, len([m for m in messages if isinstance(m, Mapping) and m.get("role") in {"user", "assistant"}]) - 1)


def _as_json(text: Any) -> Any:
    import json
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def preview(ref: str, trace_id: str) -> dict[str, Any]:
    """资料管理页"试取复评"：按 trace id 取一次，看会取到什么、各取自哪里、取不到的原因（spec/alg/trace-replay.md §9）。"""
    import json

    from impl.projects.llm_probe_loop.business_trace import from_trace, supports_from_trace
    from impl.projects.llm_probe_loop.capability import capability_business_trace_selection

    selection = capability_business_trace_selection(ref)
    if not selection:
        raise ValueError(f"场景 {ref} 没有选 trace 源，不能按 trace 复评")
    if not supports_from_trace(selection):
        raise ValueError(f"场景 {ref} 的 trace 源 {selection['source']} 不支持按 trace 复评")
    got = from_trace(selection, trace_id)
    body = request_body(got["request"]) if got.get("request") is not None else {}
    snapshot = got.get("snapshot") or {}
    delivered = got.get("delivered")
    return {"trace_id": str(trace_id), "error": got.get("error") or "", "failure": got.get("failure") or "",
            "user_text": user_text(got["request"]) if got.get("request") is not None else "",
            "history_count": _history_count(body), "delivered_from": got.get("delivered_from") or "",
            "delivered": delivered if isinstance(delivered, str) or delivered is None else json.dumps(delivered, ensure_ascii=False),
            "collection_status": snapshot.get("status") or "",
            "observation_count": len(((snapshot.get("records") or {}).get("observations")) or [])}


def calibrate(ref: str, runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    """校准（spec/alg/trace-replay.md §7）：同一场景现场跑过的每一轮，比较评测方实际收到的与按 trace 取回的。
    trace id 取自这一轮快照的关联结果；不依赖业务细节。"""
    from impl.projects.llm_probe_loop.business_trace import from_trace
    from impl.projects.llm_probe_loop.capability import capability_business_trace_selection

    selection = capability_business_trace_selection(ref)
    if not selection:
        raise ValueError(f"场景 {ref} 没有选 trace 源，不能校准")
    rows, totals, fields = [], {"turns": 0, "user_text": 0, "history": 0, "delivered": 0}, {}
    for run in runs:
        trace = run.get("trace") if isinstance(run.get("trace"), Mapping) else {}
        if ((trace.get("normalized_request") or {}).get("capability_ref") or "") != ref:
            continue
        for n, turn in enumerate(trace.get("turn_records") or [], 1):
            request = turn.get("request") if isinstance(turn.get("request"), Mapping) else {}
            if trace_id_of(request):
                continue  # 本身就是按 trace 复评的轮次，没有实收可比
            snapshot = (turn.get("project_fields") or {}).get("business_trace") or {}
            trace_id = str(((snapshot.get("association") or {}).get("trace_id")) or "")
            row = {"case_id": str(run.get("case_id") or trace.get("case_id") or ""), "turn": f"t{n}", "trace_id": trace_id}
            if not trace_id:
                rows.append({**row, "error": "这一轮现场没有关联上 trace"})
                continue
            got = from_trace(selection, trace_id)
            if got.get("error") or got.get("failure"):
                rows.append({**row, "error": got.get("error") or f"业务失败：{got.get('failure')}"})
                continue
            body = request.get("body") if isinstance(request.get("body"), Mapping) else {}
            live_user = user_text(body.get("messages")) if isinstance(body.get("messages"), list) else user_text(dict(body))
            got_body = request_body(got["request"])
            live_out = _as_json(((turn.get("extracted_output") or {}).get("output_text")))
            got_out = got["delivered"]
            if isinstance(live_out, Mapping) and isinstance(got_out, Mapping):
                differ = sorted(k for k in set(live_out) | set(got_out) if live_out.get(k) != got_out.get(k))
            else:
                differ = [] if live_out == _as_json(got_out) else ["(整体)"]
            same = {"user_text": live_user == user_text(got["request"]),
                    "history": _history_count(body) == _history_count(got_body), "delivered": not differ}
            totals["turns"] += 1
            for key, ok in same.items():
                totals[key] += ok
            for key in differ:
                fields[key] = fields.get(key, 0) + 1
            rows.append({**row, **same, "delivered_from": got.get("delivered_from") or "", "differing_fields": differ})
    return {"capability_ref": ref, "summary": totals, "differing_fields": dict(sorted(fields.items(), key=lambda kv: -kv[1])),
            "rows": rows}
