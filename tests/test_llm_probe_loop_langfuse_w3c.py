"""Langfuse 按 W3C 关联（spec/alg/business-trace-langfuse.md）：评测方每次请求发 traceparent，按 trace-id 直接查；metadata 方式可选。"""
from __future__ import annotations

import re
import pytest

from impl.projects.llm_probe_loop import business_trace, live
from impl.projects.llm_probe_loop.business_trace.providers import agno, langfuse
from impl.projects.llm_probe_loop.eval_axes import sources
from impl.projects.llm_probe_loop.eval_axes.sources import registry

W3C = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-01")
CONNECTION = {"base_url": "http://127.0.0.1:3300", "public_key": "${LANGFUSE_PUBLIC_KEY}", "secret_key": "${LANGFUSE_SECRET_KEY}"}
TRACE_ID, PARENT = "4fbd5ccb0d1347b0b10498b224f0d721", "2c7ec0705b384898"
METADATA_BINDINGS = {"business_trace_id": {"source": "request", "pointer": "/body/trace_id"}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "knowledge_sources.json"
    monkeypatch.setattr(registry, "registry_path", lambda: path)
    sources.save_source("lf", {"type": "langfuse", "config": dict(CONNECTION)})
    sources.save_source("lf-meta", {"type": "langfuse", "config": {**CONNECTION, "match_field": "metadata.request_trace_id"}})
    sources.save_source("ag", {"type": "agno", "config": {"base_url": "http://127.0.0.1:1"}})
    return path


def config(**overrides):
    return {**langfuse.describe()["default_connection"], **CONNECTION, "quiet_seconds": 0,
            "poll_timeout_seconds": .2, "poll_interval_seconds": .01, "bindings": {}, **overrides}


def test_default_is_w3c_and_each_prepare_is_a_fresh_valid_traceparent():
    assert langfuse.describe()["default_connection"]["match_field"] == "id"
    sent = [langfuse.prepare(config())["traceparent"] for _ in range(20)]
    assert all(W3C.fullmatch(v) for v in sent)
    assert len(set(sent)) == 20
    assert all(set(W3C.fullmatch(v).group(1)) != {"0"} and set(W3C.fullmatch(v).group(2)) != {"0"} for v in sent)
    assert langfuse.prepare(config(match_field="metadata.request_trace_id", bindings=METADATA_BINDINGS)) == {}


def test_bindings_follow_the_registered_association():
    with pytest.raises(ValueError, match="W3C"):
        langfuse.validate_config(config(bindings=METADATA_BINDINGS))
    with pytest.raises(ValueError, match="business_trace_id"):
        langfuse.validate_config(config(match_field="metadata.request_trace_id"))
    assert langfuse.validate_config(config())["bindings"] == {}


def test_only_w3c_langfuse_sources_send_traceparent(store):
    assert set(business_trace.propagation_headers({"source": "lf", "bindings": {}})) == {"traceparent"}
    assert business_trace.propagation_headers({"source": "lf-meta", "bindings": METADATA_BINDINGS}) == {}
    assert business_trace.propagation_headers({"source": "ag", "bindings": agno.describe()["default_bindings"]}) == {}


def _deliver(monkeypatch, selection, payload=None, headers=None):
    """投递时的关联：resolve_http 合并好的请求头（case + service）进来，加上本次生成的关联头出去。"""
    monkeypatch.setattr(live, "capability_business_trace", lambda ref: selection)
    payload = payload if payload is not None else {"capability_ref": "scene", "body": {"text": "q"}}
    return payload, live.LlmProbeLive._propagate(payload, dict(headers or {"content-type": "application/json"}))


def test_each_delivery_sends_one_fresh_traceparent_and_records_it(store, monkeypatch):
    payload, headers = _deliver(monkeypatch, {"source": "lf", "bindings": {}})
    assert W3C.fullmatch(headers["traceparent"])
    assert payload["business_trace_association"] == {"headers": {"traceparent": headers["traceparent"]}}
    assert "headers" not in payload  # 不混进 case 自己的请求头
    # 多轮：下一轮沿用同一信封，上一轮的关联被覆盖，不当成手写
    _same, headers2 = _deliver(monkeypatch, {"source": "lf", "bindings": {}}, payload=payload)
    assert headers2["traceparent"] != headers["traceparent"]
    assert payload["business_trace_association"]["headers"]["traceparent"] == headers2["traceparent"]


def test_handwritten_traceparent_is_rejected_under_w3c(store, monkeypatch):
    with pytest.raises(ValueError, match="traceparent"):
        _deliver(monkeypatch, {"source": "lf", "bindings": {}}, headers={"TraceParent": f"00-{TRACE_ID}-{PARENT}-01"})


@pytest.mark.parametrize("selection", [{"source": "lf-meta", "bindings": METADATA_BINDINGS},
                                       {"source": "ag", "bindings": agno.describe()["default_bindings"]}, None])
def test_other_associations_send_nothing(store, monkeypatch, selection):
    payload, headers = _deliver(monkeypatch, selection,
                                payload={"capability_ref": "scene", "body": {}, "business_trace_association": {"headers": {"x": "old"}}})
    assert "traceparent" not in {k.lower() for k in headers} and "business_trace_association" not in payload


def _observation(ident, parent):
    return {"id": ident, "traceId": TRACE_ID, "type": "SPAN", "name": ident, "parentObservationId": parent,
            "input": "q", "output": "a", "startTime": "2026-11-02T10:00:00Z", "endTime": "2026-11-02T10:00:01Z"}


def _install(monkeypatch, rows):
    calls = []
    trace = {"id": TRACE_ID, "timestamp": "2026-11-02T10:00:00Z", "observations": rows}

    def get(cfg, path, query=None):
        calls.append(path)
        if path == "/traces/" + TRACE_ID:
            return trace
        raise AssertionError(path)
    monkeypatch.setattr(langfuse, "_get_json", get)
    return calls


def test_collect_uses_the_sent_trace_id(monkeypatch):
    calls = _install(monkeypatch, [_observation("root", PARENT), _observation("child", "root")])
    snap = langfuse.collect(config(), request={"business_trace_association": {"headers": {"traceparent": f"00-{TRACE_ID}-{PARENT}-01"}}}, response={})
    assert snap["status"] == "succeeded"
    assert {k: snap["association"][k] for k in ("method", "trace_id")} == {"method": "w3c", "trace_id": TRACE_ID}
    assert "parent_span_id" not in snap["association"]  # parent-id 只是格式要求带的一段，不记、不用
    assert "/traces" not in calls
    assert not any(path.startswith("/observations") for path in calls)  # 步骤取自 trace 详情，不走会超时的列表接口


@pytest.mark.parametrize("observations", [["root"], None])
def test_trace_detail_without_step_objects_is_not_guessed(monkeypatch, observations):
    _install(monkeypatch, [_observation("root", None)])
    get = langfuse._get_json
    monkeypatch.setattr(langfuse, "_get_json", lambda cfg, path, query=None: {**get(cfg, path, query), "observations": observations})
    snap = langfuse.collect(config(), request={"business_trace_association": {"headers": {"traceparent": f"00-{TRACE_ID}-{PARENT}-01"}}}, response={})
    assert snap["status"] == "failed" and "trace_observations_not_objects" in snap["errors"]


# 认根只看 trace 本身（spec/alg/business-trace-langfuse.md §2.4），和是谁发起的无关
@pytest.mark.parametrize("rows,expected", [
    ([_observation("root", "any-outside-caller"), _observation("child", "root")], ("available", [])),  # 唯一顶层步骤，上一级在外
    ([_observation("root", None), _observation("child", "root")], ("available", [])),                  # 普通根
    ([_observation("root", None), _observation("lost", "gone-1")], ("partial", ["gone-1"])),           # 已有根，另有一步挂空
    ([_observation("a", "gone-1"), _observation("b", "gone-2")], ("partial", ["gone-1", "gone-2"])),   # 顶层不唯一
])
def test_root_is_decided_by_the_trace_alone(monkeypatch, rows, expected):
    _install(monkeypatch, rows)
    snap = langfuse.collect(config(), request={"business_trace_association": {"headers": {"traceparent": f"00-{TRACE_ID}-{PARENT}-01"}}}, response={})
    hierarchy = langfuse.open_reader(snap).limitations["hierarchy"]
    assert (hierarchy["status"], hierarchy["missing_parent_ids"]) == expected


@pytest.mark.parametrize("request_record", [{}, {"business_trace_association": {"headers": {"traceparent": "not-w3c"}}},
                                            {"headers": {"traceparent": f"00-{TRACE_ID}-{PARENT}-01"}}])
def test_missing_or_malformed_traceparent_never_queries(monkeypatch, request_record):
    monkeypatch.setattr(langfuse, "_get_json", lambda *args: pytest.fail("no trace id must not query"))
    snap = langfuse.collect(config(), request=request_record, response={})
    assert snap["status"] == "failed" and snap["errors"] == ["binding_missing: traceparent"]


def test_saving_a_w3c_scene_rejects_handwritten_traceparent_in_service(store):
    from impl.projects.llm_probe_loop.eval_axes.validate import validate_scenario_entry
    entry = {"axes": [], "business_trace": {"source": "lf", "bindings": {}},
             "service": {"url": "http://127.0.0.1:9/chat", "headers": {"traceparent": f"00-{TRACE_ID}-{PARENT}-01"}}}
    with pytest.raises(ValueError, match="traceparent"):
        validate_scenario_entry(entry, owner="scene")
    validate_scenario_entry({**entry, "service": {"url": "http://127.0.0.1:9/chat"}}, owner="scene")
    validate_scenario_entry({**entry, "business_trace": {"source": "lf-meta", "bindings": METADATA_BINDINGS}}, owner="scene")
