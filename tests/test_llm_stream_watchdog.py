"""看门狗单测：流式事件流挂住时，总时长到点必须抛 TimeoutError（走既有端点切换），而不是无限等。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator

from impl.core import llm_client as m


@dataclass
class FakeRunOutput:
    content: str = "ok"
    status: str = "COMPLETED"


class SlowDripAgent:
    """模拟"连接活着、隔很久滴一个字节、总时长远超预期"的流式调用。"""

    def __init__(self, **_kwargs):
        pass

    def run(self, _user, *, stream: bool = False, yield_run_output: bool = False, **_kw):
        assert stream and yield_run_output
        return self._events()

    def _events(self) -> Iterator[object]:
        # 每 0.05 秒滴一个事件，永不结束——读超时抓不住它，只有看门狗能
        while True:
            time.sleep(0.05)
            yield object()


def test_stream_watchdog_aborts_never_ending_drip(monkeypatch):
    monkeypatch.setattr(m, "Agent", SlowDripAgent)
    agent = SlowDripAgent()
    started = time.monotonic()
    try:
        m._run_agent(agent, "hi", stream=True, wall_deadline=time.monotonic() + 0.2)
        raise AssertionError("expected TimeoutError")
    except TimeoutError as exc:
        elapsed = time.monotonic() - started
        assert 0.15 <= elapsed < 1.5, f"watchdog fired at {elapsed:.2f}s"
        assert "wall-clock deadline" in str(exc)


def test_stream_watchdog_aborts_stream_that_stops_sending_entirely():
    """连接活着但一个事件都不再来：next() 本身阻塞，只在事件间查时间的看门狗抓不住。"""
    import threading

    release = threading.Event()

    class StalledAgent:
        def run(self, _user, *, stream: bool = False, yield_run_output: bool = False, **_kw):
            def events():
                yield object()
                release.wait(30)   # 模拟挂死的读
                yield FakeRunOutput()
            return events()

    started = time.monotonic()
    try:
        m._run_agent(StalledAgent(), "hi", stream=True, wall_deadline=time.monotonic() + 0.3)
        raise AssertionError("expected TimeoutError")
    except TimeoutError as exc:
        assert time.monotonic() - started < 2, "watchdog must not wait for the stalled read"
        assert "wall-clock deadline" in str(exc)
    finally:
        release.set()


def test_stream_errors_propagate_to_caller():
    class BrokenAgent:
        def run(self, _user, **_kw):
            def events():
                yield object()
                raise ConnectionError("reset")
            return events()

    try:
        m._run_agent(BrokenAgent(), "hi", stream=True, wall_deadline=time.monotonic() + 5)
        raise AssertionError("expected ConnectionError")
    except ConnectionError as exc:
        assert "reset" in str(exc)


def test_stream_watchdog_not_triggered_when_stream_completes(monkeypatch):
    class FastAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _user, *, stream: bool = False, yield_run_output: bool = False, **_kw):
            assert stream and yield_run_output
            return iter([object(), object(), FakeRunOutput()])

    result = m._run_agent(FastAgent(), "hi", stream=True, wall_deadline=time.monotonic() + 30)
    assert m._response_content(result) == "ok"


def test_non_stream_ignores_deadline():
    agent = SlowDripAgent()
    # 非流式分支保持原样：不迭代事件流，deadline 不参与
    import types
    calls = {}

    class LegacyAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _user, **kwargs):
            calls.update(kwargs)
            return FakeRunOutput()

    result = m._run_agent(LegacyAgent(), "hi", stream=False, wall_deadline=time.monotonic() + 0.05)
    assert m._response_content(result) == "ok"
    assert "stream" not in calls and "yield_run_output" not in calls


# --------------------------------------------------------------------------- 流式错误事件


def test_stream_error_event_raises_instead_of_passing_as_reply():
    """agno 流式出错时以 RunErrorEvent 收尾（content="Connection error."），不能被当成模型回复。"""
    from agno.run.agent import RunErrorEvent

    class ErrorAgent:
        def run(self, _user, **_kw):
            return iter([RunErrorEvent(content="Connection error.")])

    try:
        m._run_agent(ErrorAgent(), "hi", stream=True, wall_deadline=time.monotonic() + 5)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Connection error." in str(exc)


def test_unreachable_endpoint_fails_the_streamed_attempt():
    """真实 agno + 连不上的端点：流式尝试必须失败（原先错误文本被当成回复，端点重试不触发）。"""
    from agno.agent import Agent
    from agno.models.openai.like import OpenAILike

    agent = Agent(model=OpenAILike(id="m", api_key="k", base_url="http://127.0.0.1:9/v1", max_retries=0))
    try:
        m._run_agent(agent, "hi", stream=True, wall_deadline=time.monotonic() + 30)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Connection error" in str(exc)
