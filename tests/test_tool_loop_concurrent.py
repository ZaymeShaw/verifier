"""同一次回复里标了 concurrent 的工具同时执行；pre_tool / post_tool / 回放仍按原顺序。"""
from __future__ import annotations

import json
import threading
import time

from impl.core.tool_loop import Allow, Deny, History, Hook, LoopContext, Step, ToolLoop
from impl.tools.protocol import VerifiableTool


def _param(name: str) -> dict:
    return {"type": "object", "properties": {name: {"type": "string", "description": name}}, "required": [name]}


class Recorder(Hook):
    def __init__(self):
        self.pre, self.post = [], []

    def pre_tool(self, history: History, call):
        self.pre.append(call.args.get("q"))
        return Deny("不许") if call.args.get("q") == "deny" else Allow()

    def post_tool(self, history: History, call):
        self.post.append(call.args.get("q"))
        return call.result

    def stop(self, history: History, blocked: int):
        from impl.core.tool_loop import Done
        return Done()


class OneBatch:
    def __init__(self, calls):
        self.calls, self.step, self.replies = calls, 0, None

    def complete_step(self, messages, functions, **_):
        self.step += 1
        if self.step == 1:
            return Step({"role": "assistant", "tool_calls": [
                {"id": f"t{i}", "type": "function", "function": {"name": name, "arguments": json.dumps({"q": q})}}
                for i, (name, q) in enumerate(self.calls)]})
        self.replies = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        return Step({"role": "assistant", "content": "完"})


def test_concurrent_tools_in_one_reply_run_together_and_replay_in_order():
    running, peak, lock = [0], [0], threading.Lock()

    def slow(q: str) -> dict:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        return {"q": q}

    tools = [VerifiableTool("query", "外部查询", parameters=_param("q"), execute_fn=slow, concurrent=True),
             VerifiableTool("local", "本地", parameters=_param("q"), execute_fn=lambda q: {"q": q})]
    hook = Recorder()
    client = OneBatch([("query", "a"), ("local", "b"), ("query", "deny"), ("query", "c"), ("query", "d")])
    loop = ToolLoop("x", "sys", tools, client, completion_hook=hook, hooks={"pre_tool": [hook], "post_tool": [hook]})
    started = time.monotonic()
    result = loop.run("go", LoopContext(trace_id="t"))
    assert result.status == "complete"
    assert peak[0] == 3 and time.monotonic() - started < 0.5          # a、c、d 同时跑，不是 0.6s 串行
    assert hook.pre == ["a", "b", "deny", "c", "d"] and hook.post == ["a", "b", "c", "d"]
    assert [r.get("q") or r.get("status") for r in client.replies] == ["a", "b", "denied", "c", "d"]


def test_tools_not_marked_concurrent_run_one_by_one():
    running, peak = [0], [0]

    def slow(q: str) -> dict:
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        running[0] -= 1
        return {"q": q}

    hook = Recorder()
    tools = [VerifiableTool("local", "本地", parameters=_param("q"), execute_fn=slow)]
    loop = ToolLoop("x", "sys", tools, OneBatch([("local", "a"), ("local", "b")]), completion_hook=hook,
                    hooks={"pre_tool": [hook], "post_tool": [hook]})
    assert loop.run("go", LoopContext(trace_id="t")).status == "complete"
    assert peak[0] == 1
