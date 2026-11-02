from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from impl.core import context_store
from impl.core.llm_client import LlmClient, _USE_CONFIG
from impl.core.live_transport import LiveTransport
from impl.core.schema import (
    MockContinueDecision,
    MockIntentOutput,
    SingleTurnCase,
)
from impl.core.trace import trace_from_live
from scripts.trace_canonicalize import VOLATILE_FIELDS, canonical_json, canonicalize
from tests.support.cassette import Cassette
from tests.test_core_live_protocol import (
    _MultiLive,
    _MultiMock,
    _fake_live_http,  # noqa: F401  pytest autouse fixture：import 即注册，替 urlopen 打桩
    _live,
)


class _LlmMock(_MultiMock):
    def __init__(self) -> None:
        super().__init__()
        self.client = LlmClient.__new__(LlmClient)
        self.client._caller = "mock"

    def decide_next_action(
        self,
        intent: MockIntentOutput,
        accumulated: dict[str, Any],
    ) -> MockContinueDecision:
        response = self.client.complete_json(
            "decide",
            json.dumps(accumulated),
            stage="continue_decision",
        )
        return MockContinueDecision(**response)


def _fake_complete(
    self: Any,
    system: str,
    user: str,
    trace_id: str | None = None,
    reasoning_effort: Any = _USE_CONFIG,
    output_spec: Any = None,
    stage: str = "",
    tools_override: Any = _USE_CONFIG,
) -> dict[str, Any]:
    assert reasoning_effort is _USE_CONFIG
    assert tools_override is _USE_CONFIG
    turn = json.loads(user)["current_turn"]
    if turn == 2:
        return {"action": "stop", "stop_reason": "goal_satisfied"}
    return {"action": "continue"}


def _run_fake() -> Any:
    return trace_from_live(
        _live(_MultiLive, _LlmMock()),
        SingleTurnCase(
            id="cassette", input={"query": "turn-1"}, user_intent="finish"
        ),
    )


def _no_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Replay accessed the network")


def test_fake_multiturn_record_replay_and_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(LlmClient, "complete_json", _fake_complete)
    original_save = context_store.save_context
    record = Cassette("record", tmp_path).install()
    try:
        expected = _run_fake()
    finally:
        record.uninstall()
    assert len(expected.turn_records) == 2
    assert len((tmp_path / "llm.jsonl").read_text().splitlines()) == 2
    replay = Cassette("replay", tmp_path).install()
    try:
        monkeypatch.setattr(urllib.request, "urlopen", _no_network)
        assert context_store.save_context(object()) == ""
        with pytest.raises(RuntimeError, match="remaining"):
            replay.assert_exhausted()
        actual = _run_fake()
        assert canonical_json(expected) == canonical_json(actual)
        replay.assert_exhausted()
        with pytest.raises(RuntimeError, match="exhausted"):
            _LlmMock().client.complete_json(
                "decide", "{}", stage="continue_decision"
            )
        with pytest.raises(RuntimeError, match="failures"):
            replay.assert_exhausted()
    finally:
        replay.uninstall()
    assert LlmClient.complete_json is _fake_complete
    assert context_store.save_context is original_save


@pytest.mark.parametrize(
    "failure",
    ["http_status", "url_error", "forbidden_content_type", "sse_read_error"],
)
def test_live_errors_preserve_exchange_and_exception(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200
        headers = {"Content-Type": "text/event-stream", "Set-Cookie": "secret"}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def getcode(self) -> int:
            return self.status

        def read(self, *args: Any) -> bytes:
            return b""

    def urlopen(*args: Any, **kwargs: Any) -> Response:
        if failure == "http_status":
            raise urllib.error.HTTPError(
                "http://live.test/fail",
                503,
                "Unavailable",
                {"Content-Type": "application/json"},
                io.BytesIO(b'{"error":"down"}'),
            )
        if failure == "url_error":
            raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    results = []
    for mode in ("record", "replay"):
        cassette = Cassette(mode, tmp_path).install()
        if mode == "replay":
            monkeypatch.setattr(urllib.request, "urlopen", _no_network)
        transport = LiveTransport()
        try:
            with pytest.raises(Exception) as caught:
                transport.request(
                    "post",
                    "http://live.test/fail",
                    json_body={"query": "hi"},
                    headers={"Authorization": "secret"},
                    carries_live_request=True,
                    contributes_raw_response=True,
                    forbid_content_types=["text/event-stream"],
                    sse_last_frame=failure == "sse_read_error",
                )
            results.append(
                (
                    type(caught.value),
                    str(caught.value),
                    canonicalize(
                        {
                            "exchanges": [
                                vars(item) for item in transport.exchanges
                            ],
                        }
                    ),
                )
            )
            cassette.assert_exhausted()
        finally:
            cassette.uninstall()
    assert results[0] == results[1]
    row = json.loads((tmp_path / "live.jsonl").read_text())
    assert row["raised"] == failure
    assert row["exchange"]["sequence"] == 0
    assert row["exchange"]["request_headers"]["Authorization"] == "[REDACTED]"


@pytest.mark.parametrize(
    "error",
    [ValueError("bad"), json.JSONDecodeError("bad", "x", 0)],
)
def test_llm_exception_type_and_message(
    error: Exception,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def complete(self: Any, system: str, user: str, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(LlmClient, "complete_json", complete)
    for mode in ("record", "replay"):
        cassette = Cassette(mode, tmp_path).install()
        try:
            with pytest.raises(type(error)) as caught:
                _LlmMock().client.complete_json("system", "user")
            assert str(caught.value) == str(error)
            cassette.assert_exhausted()
        finally:
            cassette.uninstall()


def test_canonicalize_masks_only_declared_volatility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(VOLATILE_FIELDS, "test", ["body.session_id"])
    source = {
        "trace_id": "remove",
        "nested": [{"elapsed_ms": 12, "keep": 12}],
        "body": {"session_id": "remove", "value": "keep"},
        "session_id": "keep",
        "text": (
            "ab12 550e8400-e29b-41d4-a716-446655440000 "
            "0123456789abcdef0123456789abcdef "
            "2026-09-08T12:30:40.123+08:00 2026-09-08T12:30:40 "
            "1788888888 1788888888000 x1788888888y"
        ),
    }
    actual = canonicalize(source, "test")
    assert actual == {
        "nested": [{"keep": 12}],
        "body": {"value": "keep"},
        "session_id": "keep",
        "text": (
            "ab12 <uuid> <uuid> <iso_ts> <iso_ts> "
            "<epoch> <epoch> x1788888888y"
        ),
    }
    assert "trace_id" in source


def test_llm_matches_occurrences_within_role_and_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def complete(
        self: Any,
        system: str,
        user: str,
        stage: str = "",
    ) -> dict[str, str]:
        return {"value": user}

    monkeypatch.setattr(LlmClient, "complete_json", complete)
    client = _LlmMock().client
    record = Cassette("record", tmp_path).install()
    try:
        client.complete_json("s", "first", stage="decision")
        client._caller = "judge"
        client.complete_json("s", "judge", stage="decision")
        client._caller = "mock"
        client.complete_json("s", "next", stage="next_turn")
        client.complete_json("s", "second", stage="decision")
    finally:
        record.uninstall()
    replay = Cassette("replay", tmp_path).install()
    try:
        assert client.complete_json("s", "changed", stage="next_turn") == {
            "value": "next"
        }
        assert client.complete_json("s", "changed", stage="decision") == {
            "value": "first"
        }
        assert client.complete_json("s", "changed", stage="decision") == {
            "value": "second"
        }
        client._caller = "judge"
        assert client.complete_json("s", "changed", stage="decision") == {
            "value": "judge"
        }
        replay.assert_exhausted()
    finally:
        replay.uninstall()


def test_live_matches_path_occurrences_and_preserves_view_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = Cassette("record", tmp_path).install()
    try:
        transport = LiveTransport()
        for path, query in [("/a?x=1", "a1"), ("/b", "b"), ("/a?x=1", "a2")]:
            transport.post(
                f"http://live.test{path}", json_body={"query": query}
            )
    finally:
        record.uninstall()
    replay = Cassette("replay", tmp_path).install()
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    try:
        transport = LiveTransport()
        for path, answer in [("/b", "b"), ("/a?x=1", "a1"), ("/a?x=1", "a2")]:
            view = transport.post(
                f"http://offline.test{path}",
                json_body={"query": "new"},
            )
            assert view.response == {"answer": answer}
            exchange = transport.exchanges[-1]
            assert view.exchange_id == exchange.exchange_id
            assert exchange.request == {"query": "new"}
            assert exchange.url == f"http://offline.test{path}"
        replay.assert_exhausted()
        with pytest.raises(RuntimeError, match="exhausted"):
            transport.get("http://offline.test/a?x=2")
        transport.seal()
        with pytest.raises(RuntimeError, match="sealed"):
            transport.get("http://offline.test/b")
    finally:
        replay.uninstall()


def test_record_passes_explicit_none_and_positional_arguments_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def complete(
        self: Any,
        system: str,
        user: str,
        trace_id: str | None = None,
        reasoning_effort: Any = _USE_CONFIG,
        output_spec: Any = None,
        stage: str = "",
        tools_override: Any = _USE_CONFIG,
    ) -> dict[str, str]:
        observed.append((reasoning_effort, tools_override))
        return {"stage": stage}

    monkeypatch.setattr(LlmClient, "complete_json", complete)
    client = _LlmMock().client
    record = Cassette("record", tmp_path).install()
    try:
        client.complete_json(
            "s", "u", reasoning_effort=None, tools_override=None
        )
        client.complete_json("s", "u", None, None, None, "positional", None)
        client.complete_json("s", "u")
    finally:
        record.uninstall()
    assert observed == [(None, None), (None, None), (_USE_CONFIG, _USE_CONFIG)]
    rows = [
        json.loads(line)
        for line in (tmp_path / "llm.jsonl").read_text().splitlines()
    ]
    assert [row["stage"] for row in rows] == ["", "positional", ""]
