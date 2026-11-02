"""程序判定条目 v2（派发方接管后的事后更正，见 CORRECTION-3.md）。

v1（new_arm.program_entries）的两个缺陷：
- 只在「本批单位的材料视图」里比对，工具执行轴的视图通常不含下一次模型请求，于是把
  「看不到」误判成「没送达」；且按轴、按批重复计算同一事实。
- 「交付链新增缺口」靠逐字找出处：包裹步骤用自己的话转述工具返回里的真实缺口时，逐字比对判不出，
  这是语义判断，不该由程序直接定成问题。

v2 只保留**能逐字判定**的三类，每个 case 在**完整案卷**上算一次，引用真实记录 id：
1. 工具返回原样进入下一次模型输入：按工具记录的调用 id（source_id）找到之后第一次模型请求里
   tool_call_id 相同的 tool 消息，与工具结果逐字（解析后）比较。相同=达到；不同=没达到；
   之后没有任何模型请求带它=无法核（例如澄清后本轮结束）。
2. 执行余量提示随用量更新：本轮各次模型请求里的「[本轮执行余量]…」块；≥2 次调用且全部逐字相同=没达到。
3. 交付里的缺口说明有逐字出处：交付（delivered_output）的 gaps / limitations 每一条，须在本轮某个
   模型产出、工具返回或 tool 消息里逐字出现；都找不到 = 没达到（包裹步骤凭空加的）。
   残留局限：包裹步骤用自己的话转述工具里的真实缺口时，逐字比对仍会判成「没达到」，结果里须单独标出。

usage: python program_checks_v2.py            # 8 个 case 全算，写 program_v2/<tag>.json
"""
from __future__ import annotations

import json
import re
import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import new_arm as N  # noqa: E402

HINT = re.compile(r"\[本轮执行余量\](.*?)\[/本轮执行余量\]", re.S)


def _value(rec, field):
    info = (rec.get("fields") or {}).get(field) or {}
    return info.get("value") if info.get("status") == "available" else None


def _canon(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value.strip()
    return value


def _model_calls(records):
    calls = [r for r in records if r.get("kind") == "model_calls" and isinstance(_value(r, "exact_request"), dict)]
    return sorted(calls, key=lambda r: str(_value(r, "start_time") or ""))


def check_tool_returns(records):
    calls = _model_calls(records)
    entries = []
    for tool in records:
        if tool.get("kind") != "tool_calls" or "/step_executor_runs/" not in tool["id"]:
            continue
        result = _value(tool, "result")
        call_id = tool.get("source_id")
        if result is None or not call_id:
            continue
        carrier = None
        for call in calls:
            for msg in _value(call, "exact_request").get("messages") or []:
                if msg.get("role") == "tool" and msg.get("tool_call_id") == call_id:
                    carrier = (call, msg)
                    break
            if carrier:
                break
        name = tool.get("name") or "tool"
        if carrier is None:
            entries.append({"check": "工具返回原样进入下一次模型输入", "verdict": "无法核",
                            "observed": f"{name}（{tool['id']}）之后没有任何模型请求带上它的返回（本轮可能在此结束）",
                            "refs": [tool["id"]]})
            continue
        call, msg = carrier
        same = _canon(msg.get("content")) == _canon(result)
        entries.append({"check": "工具返回原样进入下一次模型输入", "verdict": "达到" if same else "没达到",
                        "observed": (f"{name} 的返回与 {call['id']} 请求里 tool_call_id={call_id} 的 tool 消息逐字一致"
                                     if same else
                                     f"{name} 的返回与 {call['id']} 请求里对应 tool 消息不一致"),
                        "refs": [tool["id"], call["id"]]})
    return entries


def check_budget_hint(records):
    calls = _model_calls(records)
    hints = []
    for call in calls:
        users = [m.get("content") for m in _value(call, "exact_request").get("messages") or [] if m.get("role") == "user"]
        text = "\n".join(u for u in users if isinstance(u, str))
        match = HINT.search(text)
        if match:
            hints.append((call["id"], match.group(1).strip()))
    if len(hints) < 2:
        return [{"check": "执行余量提示随用量更新", "verdict": "无法核",
                 "observed": f"本轮只有 {len(hints)} 次带余量提示的模型请求，无从比较", "refs": [h[0] for h in hints]}]
    same = len({h for _, h in hints}) == 1
    tools = sum(1 for r in records if r.get("kind") == "tool_calls" and "/step_executor_runs/" in r["id"])
    return [{"check": "执行余量提示随用量更新", "verdict": "没达到" if same else "达到",
             "observed": (f"{len(hints)} 次模型请求里的余量提示逐字相同（{hints[0][1][:40]}…），"
                          f"期间已发生 {len(hints) - 1} 次模型调用、{tools} 次工具调用" if same else
                          f"{len(hints)} 次模型请求的余量提示随用量变化"),
             "refs": [h[0] for h in hints]}]


def _leaves(value):
    if isinstance(value, str):
        yield value
        parsed = _canon(value)
        if not isinstance(parsed, str):
            yield from _leaves(parsed)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)


def check_delivered_gaps(records):
    delivered = next((r for r in records if r.get("kind") == "delivered_output"), None)
    if delivered is None:
        return []
    out = _canon(_value(delivered, "output"))
    envelope = _canon(out.get("output_text")) if isinstance(out, dict) and "output_text" in out else out
    if not isinstance(envelope, dict):
        return []
    gaps = list(dict.fromkeys(str(g).strip() for g in (envelope.get("gaps") or []) + (envelope.get("limitations") or [])
                              if str(g).strip()))
    if not gaps:
        return [{"check": "交付缺口说明有逐字出处", "verdict": "达到", "observed": "交付没有缺口说明", "refs": [delivered["id"]]}]
    sources = []
    for rec in records:
        if rec.get("kind") == "model_calls":
            sources += list(_leaves(_value(rec, "output")))
        elif rec.get("kind") == "tool_calls":
            sources += list(_leaves(_value(rec, "result")))
        elif rec.get("kind") == "messages" and rec.get("role") == "tool":
            sources += list(_leaves(_value(rec, "content")))
    orphan = [g for g in gaps if not any(g in leaf for leaf in sources)]
    if not orphan:
        return [{"check": "交付缺口说明有逐字出处", "verdict": "达到",
                 "observed": f"交付的 {len(gaps)} 条缺口说明都能在模型产出或工具返回里找到逐字出处", "refs": [delivered["id"]]}]
    bridge = [r["id"] for r in records if r.get("kind") == "steps" and r.get("name") == "agent_bridge"]
    status = envelope.get("completeness") or envelope.get("status")
    return [{"check": "交付缺口说明有逐字出处", "verdict": "没达到",
             "observed": f"交付带 {len(orphan)} 条缺口说明在本轮任何模型产出、工具返回里都找不到逐字出处"
                         f"（completeness={status!r}）：{orphan[0][:120]}",
             "refs": [delivered["id"]] + bridge[:1]}]


def run_case(tag):
    frozen, dossier, analysis = N.build_case(tag)
    records = dossier.get("records") or []
    entries = check_tool_returns(records) + check_budget_hint(records) + check_delivered_gaps(records)
    for n, entry in enumerate(entries, 1):
        entry["id"] = f"v2-{n}"
    return entries


def main():
    unseen = "--unseen" in sys.argv  # 泛化验证用的 case，结果另存，不进 8 case 的评分
    tags = list(io.UNSEEN) if unseen else list(io.CASES)
    out_dir = io.HERE / ("program_v2_unseen" if unseen else "program_v2")
    out_dir.mkdir(exist_ok=True)
    summary = {}
    for tag in tags:
        entries = run_case(tag)
        io.save_json(out_dir / f"{tag}.json", {"tag": tag, "entries": entries}, exclusive=False)
        summary[tag] = {v: sum(1 for e in entries if e["verdict"] == v) for v in ("达到", "没达到", "无法核")}
    io.save_json(out_dir / "summary.json", summary, exclusive=False)
    for tag, s in summary.items():
        print(f"{tag:40s} {s}")


if __name__ == "__main__":
    main()
