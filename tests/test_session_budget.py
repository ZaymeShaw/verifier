"""阶段 2 门禁：Session 预算强制、stop_reason 归责分组、driver_health 派生。

spec/mock/protocol.md 4.6 / 4.7 / 4.8 / 4.9。
"""
from __future__ import annotations

from typing import Any

import pytest

from impl.core import stop_reasons
from impl.core.schema import RunTrace
from impl.core.session import Session, SessionBudget, SessionBudgetExceeded
from impl.core.table_view import build_trace_table_row
from impl.core.trace import TraceContext
from tests.test_core_live_protocol import _MultiLive, _MultiMock, _fake_live_http, _live  # noqa: F401


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _session(budget: SessionBudget, clock: _Clock | None = None) -> tuple[Session, TraceContext]:
    live = _live(_MultiLive, _MultiMock())
    ctx = TraceContext(project_id="demo", case_id="case-budget", multi_turn=True)
    session = Session(
        live,
        ctx,
        session_id="interactive-budget",
        budget=budget,
        clock=clock or _Clock(),
    )
    return session, ctx


def test_hung_driver_is_closed_by_turn_wait_timeout_and_trace_stays_judgeable() -> None:
    clock = _Clock()
    session, ctx = _session(SessionBudget(max_turns=5, turn_wait_timeout_ms=1000), clock)

    first = session.send_request({"query": "turn-1"})
    assert first.ok
    clock.advance(5.0)

    with pytest.raises(SessionBudgetExceeded) as exc_info:
        session.send_request({"query": "turn-2"})

    assert exc_info.value.stop_reason == "driver_timeout"
    assert session.closed
    assert ctx.stop_reason == "driver_timeout"
    assert ctx.completion_status == "incomplete"
    assert ctx.final_output_turn == 1
    assert ctx.turn_count == 1
    assert ctx.interaction_controller_status == "not_run"


def test_session_timeout_closes_session() -> None:
    clock = _Clock()
    session, ctx = _session(SessionBudget(max_turns=5, session_timeout_ms=2000), clock)
    session.send_request({"query": "turn-1"})
    clock.advance(3.0)

    assert session.expire_if_over_budget() == "session_timeout"
    assert ctx.stop_reason == "session_timeout"
    assert ctx.completion_status == "incomplete"
    assert session.expire_if_over_budget() is None


def test_max_turns_budget_uses_new_stop_reason_name() -> None:
    session, ctx = _session(SessionBudget(max_turns=2))
    session.send_request({"query": "turn-1"})
    session.send_request({"query": "turn-2"})

    with pytest.raises(SessionBudgetExceeded) as exc_info:
        session.send_request({"query": "turn-3"})

    assert exc_info.value.stop_reason == "max_turns"
    assert ctx.stop_reason == "max_turns"
    assert ctx.turn_count == 2


def test_token_limit_closes_session() -> None:
    session, ctx = _session(SessionBudget(max_turns=5, token_limit=100))
    session.send_request({"query": "turn-1"})
    session.report_tokens(60)
    assert not session.closed
    session.report_tokens(60)

    assert session.closed
    assert ctx.stop_reason == "driver_budget_exceeded"
    assert session.budget_usage()["tokens_used"] == 120


def test_user_decision_completes_without_flag() -> None:
    session, ctx = _session(SessionBudget(max_turns=5))
    session.send_request({"query": "turn-1"})
    session.close("goal_satisfied")

    assert ctx.completion_status == "completed"


def test_close_without_output_is_failed() -> None:
    session, ctx = _session(SessionBudget(max_turns=5))
    session.close("driver_error")

    assert ctx.completion_status == "failed"
    assert ctx.final_output_turn is None


@pytest.mark.parametrize(
    ("stop_reason", "group", "counts"),
    [
        ("goal_satisfied", "user", True),
        ("user_abandons", "user", True),
        ("perceived_no_progress", "user", True),
        ("live_error", "live", True),
        ("max_turns", "budget", False),
        ("safety_max_turns", "budget", False),
        ("session_timeout", "budget", False),
        ("driver_timeout", "budget", False),
        ("driver_budget_exceeded", "budget", False),
        ("driver_error", "driver", False),
        ("adapter_error", "adapter", False),
        ("request_build_error", "adapter", False),
        ("intent_unavailable", "legacy", False),
        ("decision_error", "legacy", False),
        ("single_turn_completed", "user", True),
        ("", "user", True),
        ("something_new", "unknown", False),
    ],
)
def test_stop_reason_attribution_covers_old_and_new_names(stop_reason: str, group: str, counts: bool) -> None:
    assert stop_reasons.attribution(stop_reason) == group
    assert stop_reasons.counts_toward_live_quality(stop_reason) is counts


def test_driver_health_marks_driver_side_failures_as_error() -> None:
    health = stop_reasons.driver_health("request_build_error", "error", "boom")
    assert health.status == "error"
    assert health.attribution == "adapter"
    assert health.counts_toward_live_quality is False

    live_failure = stop_reasons.driver_health("live_error", "ok", "")
    assert live_failure.status == "ok"
    assert live_failure.counts_toward_live_quality is True


def test_table_row_exposes_attribution_and_driver_health() -> None:
    trace = RunTrace(
        trace_id="t-1",
        project_id="demo",
        case_id="case-1",
        stop_reason="driver_timeout",
        interaction_controller_status="ok",
    )
    row = build_trace_table_row(trace, None, None, None, None, case_context={"id": "case-1"})

    assert row.stop_attribution == "budget"
    assert row.driver_health["counts_toward_live_quality"] is False
    assert row.driver_health["attribution"] == "budget"
