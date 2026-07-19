from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from impl.core.live_protocol import RealServiceLive
from impl.core.live_transport import LiveTransport
from impl.core.schema import ProjectSpec
from impl.projects.deerflow.live import DeerflowLive
from impl.projects.client_search.live import ClientSearchLive


class _Response:
    def __init__(self, payload: Any, status: int = 200):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _deerflow_spec() -> ProjectSpec:
    return ProjectSpec(
        project_id="deerflow",
        name="deerflow",
        root=".",
        api={"base_url": "http://deerflow.test", "timeout": 10},
        common={"ready": []},
    )


def _ai_messages(text: str = "真实回答") -> list[dict[str, Any]]:
    return [{"content": {"type": "ai", "content": text, "tool_calls": []}}]


def test_live_transport_generates_immutable_exchange_and_raw_response(monkeypatch):
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _Response({"answer": "real"}),
    )
    request = {"query": "hello"}
    transport = LiveTransport()
    transport.post(
        "http://live.test/run", json_body=request,
        carries_live_request=True, contributes_raw_response=True,
    )
    transport.seal()

    exchanges = transport.exchanges
    assert len(exchanges) == 1
    assert exchanges[0].request == request
    assert exchanges[0].response == {"answer": "real"}
    assert transport.raw_responses() == [{"answer": "real"}]
    with pytest.raises(RuntimeError, match="sealed"):
        transport.get("http://live.test/again")


def test_live_transport_keeps_failed_optional_exchange_out_of_raw_response(monkeypatch):
    responses = iter([_Response({"answer": "main"}), urllib.error.URLError("optional unavailable")])

    def fake_urlopen(request, timeout=0):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    request = {"query": "hello"}
    transport = LiveTransport()
    transport.post(
        "http://live.test/main", json_body=request,
        carries_live_request=True, contributes_raw_response=True,
    )
    with pytest.raises(urllib.error.URLError):
        transport.post("http://live.test/optional", json_body={}, contributes_raw_response=True)
    transport.seal()

    from impl.core.live_transport import validate_real_transport
    validate_real_transport(transport, request)
    assert transport.raw_responses() == [{"answer": "main"}]
    assert transport.exchanges[-1].error


def test_client_search_succeeds_when_optional_downstream_is_unavailable(monkeypatch):
    main_response = {
        "code": 0,
        "msg": "ok",
        "data": {
            "robot_text": "找到年龄大于50岁的客户",
            "extra_output_params": {
                "query": "大于50岁的客户",
                "query_logic": "AND",
                "conditions": [{"field": "age", "op": "gt", "value": 50}],
            },
        },
    }

    def fake_urlopen(request, timeout=0):
        if request.full_url.endswith("client_search_query_parse_no_encipher"):
            return _Response(main_response)
        raise urllib.error.URLError("downstream unavailable")

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    spec = ProjectSpec(
        project_id="client_search", name="client_search", root=".", common={"ready": []},
        api={"base_url": "http://client.test", "endpoint": "/api/v1/client_search_query_parse_no_encipher", "method": "POST"},
        application={"downstream_search": {"enabled": True, "base_url": "http://downstream.test", "endpoint": "/search", "method": "POST"}},
    )
    live = ClientSearchLive(spec)
    request = {"user_text": "大于50岁的客户", "user_id": "u", "trace_id": "t", "session_id": "s", "source": "test"}

    output = live.deliver_turn(request)
    facts = live._take_turn_facts()

    assert output["conditions"] == [{"field": "age", "op": "gt", "value": 50}]
    assert facts["raw_response"] == [main_response]
    assert len(facts["live_exchanges"]) == 2
    assert facts["live_exchanges"][1].error


def test_real_service_live_requires_both_project_extensions():
    class MissingExtract(RealServiceLive):
        def deliver_real(self, request, transport):
            return transport

    class MissingDeliver(RealServiceLive):
        def extract_output(self, raw_response):
            return {}

    with pytest.raises(TypeError, match="abstract|extract_output"):
        MissingExtract(spec=None)
    with pytest.raises(TypeError, match="abstract|deliver_real"):
        MissingDeliver(spec=None)


def test_real_service_live_rejects_legacy_extension_signatures():
    with pytest.raises(TypeError, match="deliver_real.*signature"):
        class LegacyDeliver(RealServiceLive):
            def deliver_real(self, request):
                return request

            def extract_output(self, raw_response):
                return {}

    with pytest.raises(TypeError, match="extract_output.*signature"):
        class LegacyExtract(RealServiceLive):
            def deliver_real(self, request, transport):
                return transport

            def extract_output(self, raw_response, request=None):
                return {}


def test_project_live_modules_do_not_bypass_public_transport():
    projects_root = Path(__file__).parents[1] / "impl" / "projects"
    forbidden = ("urllib.request", "requests.", "httpx.", "urlopen(")
    violations = []
    for path in projects_root.glob("*/live.py"):
        text = path.read_text(encoding="utf-8")
        if "RealServiceLive" not in text:
            continue
        for marker in forbidden:
            if marker in text:
                violations.append(f"{path.parent.name}: {marker}")
    assert violations == []

def test_deerflow_new_thread_records_every_exchange_and_sends_exact_request(monkeypatch):
    responses = iter([
        _Response({"status": "ok"}),
        _Response({"thread_id": "thread-1"}),
        _Response({"run_id": "run-1"}),
        _Response(_ai_messages()),
    ])
    captured = []

    def fake_urlopen(request, timeout=0):
        captured.append(request)
        return next(responses)

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    request = {
        "input": {"messages": [{"role": "user", "content": "真实问题"}]},
        "config": {"configurable": {"model_name": "request-model", "user_id": "user-1"}},
    }
    live = DeerflowLive(_deerflow_spec())

    output = live.deliver_turn(request)
    facts = live._take_turn_facts()

    exchanges = facts["live_exchanges"]
    assert [item.method for item in exchanges] == ["GET", "POST", "POST", "GET"]
    assert exchanges[2].url.endswith("/api/threads/thread-1/runs/wait")
    assert exchanges[2].carries_live_request is True
    assert exchanges[2].request == request
    assert json.loads(captured[2].data.decode("utf-8")) == request
    assert facts["raw_response"] == [{"thread_id": "thread-1"}, _ai_messages()]
    assert output["reply_text"] == "真实回答"
    assert output["session_summary"]["thread_id"] == "thread-1"


def test_deerflow_reuses_existing_thread_without_creating_one(monkeypatch):
    responses = iter([
        _Response({"status": "ok"}),
        _Response({"run_id": "run-1"}),
        _Response(_ai_messages("已有会话回答")),
    ])
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: next(responses),
    )
    request = {
        "input": {"messages": [{"role": "user", "content": "继续提问"}]},
        "config": {"configurable": {"thread_id": "existing-thread", "model_name": "m"}},
    }
    live = DeerflowLive(_deerflow_spec())

    output = live.deliver_turn(request)
    exchanges = live._take_turn_facts()["live_exchanges"]

    assert len(exchanges) == 3
    assert all(item.url != "http://deerflow.test/api/threads" for item in exchanges)
    assert exchanges[1].url.endswith("/api/threads/existing-thread/runs/wait")
    assert exchanges[1].request == request
    assert output["reply_text"] == "已有会话回答"


def test_deerflow_reports_stale_thread_instead_of_gateway_unavailable(monkeypatch):
    responses = iter([
        _Response({"status": "ok"}),
        urllib.error.HTTPError(
            "http://deerflow.test/api/threads/stale-thread/runs/wait",
            404,
            "Not Found",
            {},
            None,
        ),
    ])

    def fake_urlopen(request, timeout=0):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    live = DeerflowLive(_deerflow_spec())
    request = {
        "input": {"messages": [{"role": "user", "content": "继续"}]},
        "config": {"configurable": {"thread_id": "stale-thread"}},
    }

    with pytest.raises(RuntimeError, match="thread_not_found.*stale-thread"):
        live.deliver_turn(request)

    facts = live._take_turn_facts()
    assert facts["live_exchanges"][-1].status_code == 404
    assert facts["live_exchanges"][-1].url.endswith("/api/threads/stale-thread/runs/wait")


def test_deerflow_ignores_middleware_title_when_extracting_business_reply():
    live = DeerflowLive(_deerflow_spec())
    raw_response = [
        {"thread_id": "thread-real"},
        [
            {
                "event_type": "llm.ai.response",
                "content": {"type": "ai", "content": "真实业务回答", "tool_calls": []},
                "metadata": {"caller": "lead_agent"},
            },
            {
                "event_type": "llm.ai.response",
                "content": {"type": "ai", "content": "Test Code Response", "tool_calls": []},
                "metadata": {"caller": "middleware:title"},
            },
        ],
    ]

    output = live.extract_output(raw_response)

    assert output["reply_text"] == "真实业务回答"
    assert output["session_summary"]["thread_id"] == "thread-real"
