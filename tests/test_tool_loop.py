"""ToolLoop 阶段 1 验收（spec/adapter/tool-loop-plan-20260922.md §10）。

真实 LlmClient.complete_step（agno Agent + OpenAILike）打到本地假 OpenAI 服务；只有模型回复是脚本化的。
每个用例在非流式与流式（SSE，生产默认）两条路径上各跑一遍。
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from impl.core import context_store, llm_client
from impl.core.config import get_llm_config
from impl.core.llm_client import LlmClient
from impl.core.tool_loop import (
    Abort,
    Allow,
    BudgetStop,
    DEFAULT_BUDGET,
    Continue,
    DependsOn,
    Deny,
    Done,
    Failed,
    History,
    Hook,
    LoopContext,
    RequireDone,
    ToolLoop,
    after,
    cites_read,
    take_accepted,
    until_accepted,
)
from impl.tools.protocol import VerifiableTool
from tests.support.fake_openai import FakeOpenAI

SAVED: list = []  # 每次模型请求一条 ContextRecord


def _client(fake: FakeOpenAI, stream: bool, caller: str) -> LlmClient:
    config = replace(get_llm_config(), api_key="k", base_url=fake.base_url, model="fake-m",
                     fallbacks=(), stream=stream, role_policies={})
    client = LlmClient(config=config)
    client._project_id, client._caller = "p", caller
    return client


def _segments(caller: str) -> list[tuple[str, str]]:
    """某个 caller 落档的 (trace_id, stage) 序列。"""
    return [(r.trace_id, r.response["runtime"]["stage"]) for r in SAVED if r.caller == caller]


def _param(name: str) -> dict:
    return {"type": "object", "properties": {name: {"type": "string", "description": name}}, "required": [name]}


def _tools(log: list | None = None) -> list[VerifiableTool]:
    log = log if log is not None else []

    def read(id: str) -> dict:
        log.append(("read", id))
        return {"id": id, "text": f"body of {id}"}

    def cite(id: str) -> dict:
        log.append(("cite", id))
        return {"cited": id}

    def submit(answer: str) -> dict:
        log.append(("submit", answer))
        return {"accepted": answer != "bad", "answer": answer}

    def boom(x: str) -> dict:
        raise ValueError("kaput")

    return [
        VerifiableTool("read", "read an item", parameters=_param("id"), execute_fn=read),
        VerifiableTool("cite", "cite an item", parameters=_param("id"), execute_fn=cite),
        VerifiableTool("submit", "submit the answer", parameters=_param("answer"), execute_fn=submit),
        VerifiableTool("boom", "always fails", parameters=_param("x"), execute_fn=boom),
    ]


CTX = LoopContext(trace_id="t-1")


STREAM = {"on": False}  # 由 _both_paths 夹具切换


@pytest.fixture(autouse=True, params=[False, True], ids=["run", "stream"])
def _both_paths(request, monkeypatch):
    SAVED.clear()
    monkeypatch.setattr(context_store, "save_context", lambda record: SAVED.append(record) or "")
    monkeypatch.setattr(LlmClient, "_endpoint_probe", staticmethod(lambda _endpoint: True))
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setitem(STREAM, "on", request.param)
    return request.param


def _loop(fake: FakeOpenAI, key: str = "MAIN", **kwargs) -> tuple[ToolLoop, str]:
    loop_id = kwargs.pop("id", "main")
    client = _client(fake, STREAM["on"], caller=loop_id)
    tools = kwargs.pop("tools", None) or _tools(kwargs.pop("log", None))
    completion = kwargs.pop('completion_hook', Hook())
    return ToolLoop(id=loop_id, system_prompt=key, tools=tools, client=client,
                    completion_hook=completion, **kwargs), loop_id


def _tool_messages(request: dict) -> list[dict]:
    return [m for m in request["messages"] if m["role"] == "tool"]


def _roles(request: dict) -> list[str]:
    return [m["role"] for m in request["messages"]]


# --------------------------------------------------------------------------- 默认完成条件，无辅助 hooks


def test_no_hooks_stops_when_model_stops_calling_tools(_both_paths):
    with FakeOpenAI({"MAIN": [[("read", {"id": "a"})], "done: a"]}) as fake:
        loop, caller = _loop(fake)
        result = loop.run("go", CTX)

    assert all(bool(r.get("stream")) is _both_paths for r in fake.requests)
    assert all(r.get("parallel_tool_calls") is True for r in fake.requests)
    assert result.status == "complete"
    assert result.value == "done: a"
    assert result.segments == 1
    assert [(c.tool, c.args, c.ok) for c in result.calls] == [("read", {"id": "a"}, True)]
    assert json.loads(_tool_messages(fake.requests[1])[0]["content"]) == {"id": "a", "text": "body of a"}
    assert [m["role"] for m in result.messages] == ["system", "user", "assistant", "tool", "assistant"]
    # 一次模型请求一条记录；messages 仅是发出的输入，返回的会话视图单列。循环没有输出契约，不带 governance。
    assert _segments(caller) == [("t-1", "main:s0:r0"), ("t-1", "main:s0:r1")]
    assert [m["role"] for m in SAVED[0].messages] == ["system", "user"]
    assert [m["role"] for m in SAVED[1].messages] == ["system", "user", "assistant", "tool"]
    assert [m["role"] for m in SAVED[0].response["run_messages"]] == ["system", "user", "assistant"]
    assert [m["role"] for m in SAVED[1].response["run_messages"]] == ["system", "user", "assistant", "tool", "assistant"]
    assert all(r.governance == {} and r.error is None for r in SAVED)


def test_slow_tool_does_not_count_against_request_timeout(_both_paths):
    """工具执行（比如子 loop）比单次请求超时还长：工具在请求之外执行，不算模型超时、调用只执行一次。

    只有流式路径有总时长看门狗（非流式靠 SDK 读超时），故只在流式上跑。
    """
    import time as _time

    if not _both_paths:
        pytest.skip("非流式路径没有总时长看门狗")

    log = []

    def slow(x: str) -> dict:
        log.append(x)
        _time.sleep(1.5)
        return {"ok": x}

    with FakeOpenAI({"MAIN": [[("slow", {"x": "a"})], "done"]}) as fake:
        client = _client(fake, True, caller="main")
        client.request_timeout_seconds = 1.0
        loop = ToolLoop(id="main", system_prompt="MAIN", client=client, completion_hook=Hook(),
                        tools=[VerifiableTool("slow", "slow tool", parameters=_param("x"), execute_fn=slow)])
        result = loop.run("go", CTX)

    assert result.status == "complete" and result.value == "done"
    assert log == ["a"] and len(fake.requests) == 2
    assert all([a["status"] for a in r.response["runtime"]["attempts"]] == ["succeeded"] for r in SAVED)


# --------------------------------------------------------------------------- DependsOn


def test_depends_on_denies_then_model_completes_prerequisite():
    log: list = []
    with FakeOpenAI({"MAIN": [[("cite", {"id": "a"})], [("read", {"id": "a"})], [("cite", {"id": "a"})], "ok"]}) as fake:
        loop, _ = _loop(fake, log=log, hooks={'pre_tool': [DependsOn({"cite": after("read")})]})
        result = loop.run("go", CTX)

    assert result.status == "complete"
    assert log == [("read", "a"), ("cite", "a")]  # 被拒的 cite 没有执行
    denied = json.loads(_tool_messages(fake.requests[1])[0]["content"])
    assert denied["status"] == "denied" and "read" in denied["reason"]
    assert [c.ok for c in result.calls] == [False, True, True]


def test_depends_on_unsatisfiable_fails_at_max_blocked():
    # 模型永远只 cite，从不 read；每段结束 RequireDone 拦回，直到 max_blocked。
    steps = []
    for _ in range(3):
        steps += [[("cite", {"id": "a"})], "gave up"]
    with FakeOpenAI({"MAIN": steps}) as fake:
        loop, _ = _loop(fake, completion_hook=RequireDone(["cite"], accepted=lambda c: True),
                        hooks={'pre_tool': [DependsOn({"cite": after("read")})]}, max_blocked=2)
        result = loop.run("go", CTX)

    assert result.status == "failed"
    assert result.value is None
    assert result.reason.startswith("max_blocked=2")
    assert result.segments == 3
    assert all(c.denied for c in result.calls)


def test_same_batch_read_and_cite_rejects_cite():
    log: list = []
    batch = [("read", {"id": "a"}), ("cite", {"id": "a"})]
    with FakeOpenAI({"MAIN": [batch, [("cite", {"id": "a"})], "ok"]}) as fake:
        loop, _ = _loop(fake, log=log, hooks={'pre_tool': [DependsOn({"cite": cites_read("id", "read", "id")})]})
        result = loop.run("go", CTX)

    assert result.status == "complete"
    first, second, third = result.calls
    assert (first.tool, first.ok, first.batch) == ("read", True, 0)
    assert (second.tool, bool(second.denied), second.batch) == ("cite", True, 0)
    assert (third.tool, third.ok, third.batch) == ("cite", True, 1)
    assert log == [("read", "a"), ("cite", "a")]


# --------------------------------------------------------------------------- RequireDone


def test_require_done_blocks_back_with_reason_then_completes():
    steps = ["finished", [("submit", {"answer": "bad"})], "finished", [("submit", {"answer": "42"})], "finished"]
    with FakeOpenAI({"MAIN": steps}) as fake:
        loop, caller = _loop(fake, completion_hook=RequireDone(["submit"]), end=take_accepted("submit"))
        result = loop.run("go", CTX)

    assert result.status == "complete"
    assert result.value == {"answer": "42"}
    assert result.segments == 3
    # 第二段的请求里带着上一段的全部消息 + 拦回原因，且 system 只有一条
    second = fake.requests[1]
    assert _roles(second) == ["system", "user", "assistant", "user"]
    assert "submit" in second["messages"][-1]["content"]
    assert [stage for _, stage in _segments(caller)] == ["main:s0:r0", "main:s1:r0", "main:s1:r1", "main:s2:r0", "main:s2:r1"]


def test_require_done_fails_at_max_blocked_without_partial_result():
    ended = []
    with FakeOpenAI({"MAIN": ["finished"] * 3}) as fake:
        loop, _ = _loop(fake, completion_hook=RequireDone(["submit"]), end=lambda h: ended.append(1), max_blocked=2)
        result = loop.run("go", CTX)

    assert result.status == "failed"
    assert result.value is None
    assert "submit" in result.reason
    assert result.segments == 3
    assert ended == []  # failed 不调 end


# --------------------------------------------------------------------------- BudgetStop


def test_budget_stop_aborts_loop_as_failed():
    log: list = []
    ended = []
    batch = [("read", {"id": "a"}), ("read", {"id": "b"}), ("read", {"id": "c"})]
    with FakeOpenAI({"MAIN": [batch]}) as fake:  # 中止后不应再请求模型
        loop, _ = _loop(fake, log=log, budget=BudgetStop(tool_calls=2), end=lambda h: ended.append(1))
        result = loop.run("go", CTX)

    assert result.status == "failed"
    assert result.reason.startswith("budget: tool_calls")
    assert result.value is None and ended == []
    assert log == [("read", "a"), ("read", "b")]
    assert len(fake.requests) == 1  # 中止发生在请求之后，不再请求模型
    assert len(SAVED) == 1 and SAVED[0].error is None  # 那次请求本身是成功的


def test_one_round_can_execute_many_tools_and_an_accepted_submission():
    class Completed(RequireDone):
        def ready_to_finish(self, history):
            return any(c.ok and self.accepted(c) for c in history.of('submit'))

    log = []
    batch = [('read', {'id': str(i)}) for i in range(13)] + [('submit', {'answer': 'good'})]
    with FakeOpenAI({'MAIN': [batch]}) as fake:
        loop, _ = _loop(fake, log=log, completion_hook=Completed(['submit']),
                        budget=BudgetStop(llm_calls=1), end=take_accepted('submit'))
        result = loop.run('go', CTX)
    assert result.status == 'complete' and result.llm_calls == 1
    assert len(fake.requests) == 1 and len(result.calls) == len(log) == 14
    assert result.value['answer'] == 'good'


def test_default_budget_stops_runaway_segment_without_explicit_budget():
    # 段内反复被拒的 submit：max_blocked 管不到段内，内置预算必须把它停下。
    limit = DEFAULT_BUDGET.tool_calls
    steps = [[("submit", {"answer": "bad"})]] * (limit + 1)
    with FakeOpenAI({"MAIN": steps}) as fake:
        loop, _ = _loop(fake, completion_hook=RequireDone(["submit"]))
        result = loop.run("go", CTX)

    assert result.status == "failed"
    assert result.reason == f"budget: tool_calls 已达上限 {limit}"
    assert result.segments == 1
    assert len(result.calls) == limit + 1 and result.calls[-1].denied == result.reason


# --------------------------------------------------------------------------- 端点重试


def test_endpoint_retry_resends_only_the_failed_request():
    # 第二次请求空回 → 端点重试只重发这一次请求；此前那批工具不重新执行，History 里只有真实发生的调用。
    log: list = []
    steps = [[("read", {"id": "a"})], "", "done"]
    with FakeOpenAI({"MAIN": steps}) as fake:
        loop, caller = _loop(fake, log=log, budget=BudgetStop(llm_calls=2))
        result = loop.run("go", CTX)

    assert result.status == "complete" and result.value == "done"
    assert result.llm_calls == 2 and len(fake.requests) == 3
    assert log == [("read", "a")]
    assert [(c.id, c.args, c.batch) for c in result.calls] == [(0, {"id": "a"}, 0)]
    assert fake.requests[1]["messages"] == fake.requests[2]["messages"]  # 重试原样重发
    assert _segments(caller) == [("t-1", "main:s0:r0"), ("t-1", "main:s0:r1")]
    assert [a["status"] for a in SAVED[-1].response["runtime"]["attempts"]] == ["failed", "succeeded"]


def test_invalid_tool_calls_are_reported_to_model_without_extra_requests():
    # 一批全是不合法调用（未知工具、参数不是 JSON）：每个都回错误结果，一次请求一批，不多发请求。
    batch = [("nope", {"id": "a"}), ("read", "{not json")]
    with FakeOpenAI({"MAIN": [batch, "ok"]}) as fake:
        loop, _ = _loop(fake)
        result = loop.run("go", CTX)

    assert result.status == "complete" and len(fake.requests) == 2
    unknown, broken = result.calls
    assert (unknown.tool, broken.tool) == ("nope", "read")
    assert "nope" in unknown.error and "JSON" in broken.error
    views = [json.loads(m["content"]) for m in _tool_messages(fake.requests[1])]
    assert [v["status"] for v in views] == ["error", "error"]


def test_segment_failing_every_attempt_raises():
    with FakeOpenAI({"MAIN": ["", ""]}) as fake:
        loop, _ = _loop(fake)
        with pytest.raises(RuntimeError, match="no response content"):
            loop.run("go", CTX)
    assert len(SAVED) == 1 and "no response content" in SAVED[0].error


# --------------------------------------------------------------------------- 可选挂点


def test_start_hook_appends_context_before_first_request():
    class Start(Hook):
        def start(self, history, ctx):
            return [f"trace={ctx.trace_id}"]

    with FakeOpenAI({"MAIN": ["ok"]}) as fake:
        loop, _ = _loop(fake, hooks={'start': [Start()]})
        loop.run("go", CTX)

    messages = fake.requests[0]["messages"]
    assert [(m["role"], m["content"]) for m in messages[1:]] == [("user", "go"), ("user", "trace=t-1")]


def test_post_tool_rewrites_what_model_sees():
    class Redact(Hook):
        def post_tool(self, history, call):
            return {**call.result, "text": "<redacted>"}

    with FakeOpenAI({"MAIN": [[("read", {"id": "a"})], "ok"]}) as fake:
        loop, _ = _loop(fake, hooks={'post_tool': [Redact()]})
        result = loop.run("go", CTX)

    assert json.loads(_tool_messages(fake.requests[1])[0]["content"])["text"] == "<redacted>"
    assert result.calls[0].result["text"] == "<redacted>"


def test_post_batch_note_follows_tool_results():
    seen = []

    class Note(Hook):
        def post_batch(self, history, calls):
            seen.append([c.tool for c in calls])
            return [f"batch of {len(calls)}"]

    with FakeOpenAI({"MAIN": [[("read", {"id": "a"}), ("read", {"id": "b"})], "ok"]}) as fake:
        loop, _ = _loop(fake, hooks={'post_batch': [Note()]})
        result = loop.run("go", CTX)

    assert result.status == "complete"
    assert seen == [["read", "read"]]
    assert _roles(fake.requests[1]) == ["system", "user", "assistant", "tool", "tool", "user"]
    assert fake.requests[1]["messages"][-1]["content"] == "batch of 2"


def test_pre_tool_allow_rewrites_args():
    log: list = []

    class Upper(Hook):
        def pre_tool(self, history, call):
            return Allow(args={"id": call.args["id"].upper()})

    with FakeOpenAI({"MAIN": [[("read", {"id": "a"})], "ok"]}) as fake:
        loop, _ = _loop(fake, log=log, hooks={'pre_tool': [Upper()]})
        result = loop.run("go", CTX)

    assert log == [("read", "A")]
    assert result.calls[0].args == {"id": "A"}


def test_hook_composition_priorities():
    class Always(Hook):
        def __init__(self, pre=None, stop=None):
            self._pre, self._stop = pre, stop

        def pre_tool(self, history, call):
            return self._pre or Allow()

        def stop(self, history, blocked):
            return self._stop or Done()

    # pre_tool：Deny 与 Allow 同时出现 → Deny
    with FakeOpenAI({"MAIN": [[("read", {"id": "a"})], "ok"]}) as fake:
        loop, _ = _loop(fake, hooks={'pre_tool': [Always(pre=Allow()), Always(pre=Deny("no"))]})
        assert loop.run("go", CTX).calls[0].denied == "no"
    # pre_tool：Abort 压过 Deny
    with FakeOpenAI({"MAIN": [[("read", {"id": "a"})]]}) as fake:
        loop, _ = _loop(fake, hooks={'pre_tool': [Always(pre=Deny("no")), Always(pre=Abort("stop"))]})
        result = loop.run("go", CTX)
        assert (result.status, result.reason) == ("failed", "stop")
    # stop：Failed > Continue > Done
    with FakeOpenAI({"MAIN": ["ok"]}) as fake:
        loop, _ = _loop(fake, completion_hook=Always(stop=Continue("more")),
                        hooks={'stop': [Always(stop=Failed("bad")), Always()]})
        result = loop.run("go", CTX)
        assert (result.status, result.reason, result.segments) == ("failed", "bad", 1)


def test_accepted_rules_and_dynamic_require_done():
    """tool 以结果报告失败（ok 但 accepted=false）不满足 after(accepted=)；被接受后 until_accepted 拒重复；
    RequireDone 的清单可以随 history 变化。"""
    from impl.core.tool_loop import Call, is_accepted

    rejected = Call(0, "prep", {}, 0, result={"accepted": False})
    history = History(calls=[rejected])
    assert after("prep")(history, Call(1, "use", {}, 1)) is None                     # 只看成功调用：放行
    assert "没有被接受的调用" in after("prep", accepted=is_accepted)(history, Call(1, "use", {}, 1))
    assert until_accepted()(history, Call(1, "prep", {}, 1)) is None                 # 没接受过：可以再调
    history.calls.append(Call(1, "prep", {}, 1, result={"accepted": True}))
    assert after("prep", accepted=is_accepted)(history, Call(2, "use", {}, 2)) is None
    assert "已被接受" in until_accepted()(history, Call(2, "prep", {}, 2))

    todo = RequireDone(lambda h: ["prep", *(["use"] if h.of("prep") else [])])
    assert "prep" in todo.stop(History(), 0).reason
    verdict = todo.stop(history, 0)
    assert isinstance(verdict, Continue) and "use" in verdict.reason and "prep" not in verdict.reason


def test_tool_exception_is_shown_to_model_and_not_ok():
    with FakeOpenAI({"MAIN": [[("boom", {"x": "1"})], "ok"]}) as fake:
        loop, _ = _loop(fake, hooks={'pre_tool': [DependsOn({"submit": after("boom")})]})
        result = loop.run("go", CTX)

    assert result.status == "complete"
    assert result.calls[0].error == "ValueError: kaput"
    assert not result.calls[0].ok
    assert json.loads(_tool_messages(fake.requests[1])[0]["content"])["status"] == "error"


# --------------------------------------------------------------------------- 嵌套


def _nested(fake: FakeOpenAI, render=None) -> ToolLoop:
    child = ToolLoop(
        id="child",
        system_prompt="CHILD",
        tools=_tools(),
        client=_client(fake, STREAM["on"], caller="child"),
        completion_hook=RequireDone(["submit"]),
        end=take_accepted("submit"),
        max_blocked=1,
    )
    return ToolLoop(
        id="parent",
        system_prompt="PARENT",
        tools=[child.as_tool("delegate to child", _param("task"), render=render)],
        client=_client(fake, STREAM["on"], caller="parent"),
        completion_hook=Hook(),
    )


def test_nested_loop_returns_only_end_value_to_parent():
    scripts = {
        "PARENT": [[("child", {"task": "x"})], "parent done"],
        "CHILD": [[("read", {"id": "a"})], [("submit", {"answer": "42"})], "child done"],
    }
    with FakeOpenAI(scripts) as fake:
        parent = _nested(fake)
        result = parent.run("go", LoopContext(trace_id="t-9", stage="eval"))

    assert result.status == "complete"
    assert result.calls[0].result == {"answer": "42"}
    assert json.loads(_tool_messages(fake.requests_for("PARENT")[1])[0]["content"]) == {"answer": "42"}
    assert json.loads(fake.requests_for("CHILD")[0]["messages"][-1]["content"]) == {"task": "x"}
    assert _segments("parent") == [("t-9", "eval/parent:s0:r0"), ("t-9", "eval/parent:s0:r1")]
    assert _segments("child") == [("t-9", f"eval/parent:s0:r0/child:s0:r{i}") for i in range(3)]


def test_failed_child_loop_returns_failure_to_parent():
    scripts = {
        "PARENT": [[("child", {"task": "x"})], "parent saw failure"],
        "CHILD": ["nothing", "still nothing"],
    }
    with FakeOpenAI(scripts) as fake:
        parent = _nested(fake)
        result = parent.run("go", CTX)

    assert result.status == "complete"
    failure = result.calls[0].result
    assert failure["status"] == "failed" and failure["loop"] == "child"
    assert failure["reason"].startswith("max_blocked=1")
    assert [stage for _, stage in _segments("child")] == ["parent:s0:r0/child:s0:r0", "parent:s0:r0/child:s1:r0"]


def test_as_tool_render_builds_child_input_from_args():
    scripts = {
        "PARENT": [[("child", {"task": "x"})], "parent done"],
        "CHILD": [[("submit", {"answer": "42"})], "child done"],
    }
    with FakeOpenAI(scripts) as fake:
        parent = _nested(fake, render=lambda args: f"program material for {args['task']}")
        result = parent.run("go", CTX)

    assert result.status == "complete"
    assert fake.requests_for("CHILD")[0]["messages"][-1]["content"] == "program material for x"


def test_as_tool_outside_parent_segment_raises():
    with FakeOpenAI({}) as fake:
        parent = _nested(fake)
    with pytest.raises(RuntimeError, match="as_tool"):
        parent.tools[0].execute_fn(task="x")
