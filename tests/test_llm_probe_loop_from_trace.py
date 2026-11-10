"""按 trace 复评（spec/alg/trace-replay.md）：只给 trace id，不调业务；取数规则、失败判定、case 校验、与现场同形的运行记录。"""
from __future__ import annotations

import pytest

from impl.core.live_transport import LiveHTTPStatusError, LiveRecordedFailure
from impl.core.project_loader import load_adapter, load_project
from impl.projects.llm_probe_loop import business_trace, from_trace as from_trace_turn, live
from impl.projects.llm_probe_loop.business_trace.providers import agno, langfuse
from impl.projects.llm_probe_loop.eval_axes.materials import _deliveries

CONNECTION = {"base_url": "http://127.0.0.1:3300", "public_key": "${LANGFUSE_PUBLIC_KEY}", "secret_key": "${LANGFUSE_SECRET_KEY}"}
Q = [{"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上一答"}, {"role": "user", "content": "保单P0的累计已交保费是多少？"}]
ANS = {"answer": "1089.1元"}
REF = "verify-insurance-langfuse"


def _obs(ident, parent=None, **kw):
    return {"id": ident, "traceId": "T", "type": "SPAN", "name": ident, "parentObservationId": parent,
            "startTime": "2026-11-03T10:00:00Z", "endTime": "2026-11-03T10:00:01Z", **kw}


def _replay(monkeypatch, observations, trace=None, status="succeeded"):
    snapshot = {"status": status, "errors": [] if status != "failed" else ["trace_not_visible"],
                "records": {"trace": {"id": "T", **(trace or {})}, "observations": observations} if status != "failed" else {}}
    monkeypatch.setattr(langfuse, "_settle", lambda clean, business_id, snap: {**snap, **snapshot})
    return langfuse.from_trace(CONNECTION, "T")


# ---- 取数规则（§3.1）：5 种常见上报写法 ----

def test_root_observation_io_is_taken_first(monkeypatch):
    got = _replay(monkeypatch, [_obs("root", input=Q, output=ANS), _obs("llm", "root", type="GENERATION", input=[{"role": "system"}], output="x")],
                  trace={"input": "trace-level", "output": "trace-level"})
    assert (got["request"], got["delivered"], got["delivered_from"], got["failure"], got["error"]) == (Q, ANS, "root_observation", "", "")


def test_trace_level_io_is_used_when_root_has_none(monkeypatch):
    got = _replay(monkeypatch, [_obs("root")], trace={"input": Q, "output": ANS})
    assert (got["request"], got["delivered"], got["delivered_from"]) == (Q, ANS, "trace")


def test_content_only_on_child_steps_is_not_used(monkeypatch):
    got = _replay(monkeypatch, [_obs("root", metadata={"attributes": {"http.route": "/chat"}}),
                                _obs("llm", "root", type="GENERATION", input=Q, output="1089.1元")])
    assert got["error"] == "这条 trace 没有记本轮的请求" and got["delivered"] is None


def test_root_with_external_parent_counts_as_root(monkeypatch):
    got = _replay(monkeypatch, [_obs("root", "caller-span-not-in-trace", input=Q, output=ANS)])
    assert got["delivered"] == ANS and got["error"] == ""


def test_trace_without_readable_steps_says_so(monkeypatch):
    assert _replay(monkeypatch, [])["error"] == "trace 有记录但没读到步骤"


@pytest.mark.parametrize("rows", [[_obs("a", input=Q, output=ANS), _obs("b", input=Q, output=ANS)],
                                  [_obs("a", "x1", input=Q, output=ANS), _obs("b", "x2", input=Q, output=ANS)]])
def test_root_must_be_unique(monkeypatch, rows):
    assert "唯一的根步骤" in _replay(monkeypatch, rows)["error"]


def _at(second):
    return f"2026-11-01T08:36:{second}Z"


def test_root_narrowed_by_trace_name_when_parents_are_missing(monkeypatch):
    """公司库实测：入口步骤和另外两个步骤的上一级都不在 trace 里（上报漏了一层），按 trace 名认出入口。"""
    rows = [_obs("gw", "0000000000000001", name="gateway-koudai-e-chat", startTime=_at("43.843"), input=Q, output=ANS),
            _obs("intent", "a5ba", name="intent", startTime=_at("44.905")),
            _obs("llm", "intent", type="GENERATION", name="intent", startTime=_at("44.913")),
            _obs("policy", "a5ba", name="policy-query", startTime=_at("46.025"))]
    got = _replay(monkeypatch, rows, trace={"name": "gateway-koudai-e-chat"})
    assert (got["request"], got["delivered"], got["error"]) == (Q, ANS, "")


@pytest.mark.parametrize("rows, name, want", [
    ([_obs("r", name="T", startTime=_at("02")), _obs("x", name="o", startTime=_at("01"))], "T", "r"),
    ([_obs("r", name="a", startTime=_at("01")), _obs("x", name="b", startTime=_at("02"))], "T", "r"),
    ([_obs("r", name="T", startTime=_at("02")), _obs("x", name="T", startTime=_at("01")), _obs("y", name="o", startTime=_at("00"))], "T", "x"),
    ([_obs("r", name="a", startTime=_at("01")), _obs("x", name="b", startTime=_at("01"))], "T", None),
    ([_obs("r", name="a", startTime=None), _obs("x", name="b", startTime=None)], "T", None),
    ([_obs("r", name="a", startTime=_at("01")), _obs("x", name="b", startTime="not-a-time")], "T", None),
    ([_obs("a", "b"), _obs("b", "a")], "T", None),
    ([_obs("r", "caller"), _obs("c", "r")], "T", "r"),
    ([_obs("r"), _obs("x", "ghost")], "T", "r"),
])
def test_root_id_narrowing(rows, name, want):
    assert langfuse.root_id(rows, name) == want


def test_root_rule_matches_the_reader(monkeypatch):
    """已有上一级为空的根时，另一个挂空的步骤不是根（和读取代码同一认法）。"""
    got = _replay(monkeypatch, [_obs("root", input=Q, output=ANS), _obs("lost", "gone", input="x", output="y")])
    assert got["delivered"] == ANS and got["error"] == ""


def test_trace_not_collected_is_an_error(monkeypatch):
    assert _replay(monkeypatch, [], status="failed")["error"].startswith("trace 没采到")


# ---- 失败判定（§5）：HTTP 状态码优先，没有再看 level ----

@pytest.mark.parametrize("attrs,level,message,expected", [
    ({"http.response.status_code": 429}, "ERROR", None, "HTTP 429"),
    ({"http.response.status_code": 500}, "DEFAULT", None, "HTTP 500"),
    ({"http.response.status_code": 200}, "ERROR", "x", ""),
    ({}, "ERROR", "下游超时", "下游超时"),
    ({}, "DEFAULT", None, ""),
])
def test_failure_uses_standard_status_then_level(monkeypatch, attrs, level, message, expected):
    got = _replay(monkeypatch, [_obs("root", input=Q, output=ANS, level=level, statusMessage=message, metadata={"attributes": attrs})])
    assert got["failure"] == expected
    assert got["request"] == Q  # 失败了也记用户这一轮说了什么


# ---- trace 源能力与 case 校验（§2、§3） ----

@pytest.fixture
def selection(monkeypatch):
    chosen = {"value": {"source": "lf", "bindings": {}}}
    types = {"lf": "langfuse", "ag": "agno"}
    monkeypatch.setattr(business_trace, "validate_selection", lambda v: {"type": types[v["source"]], "config": {}})
    monkeypatch.setattr("impl.projects.llm_probe_loop.capability.capability_business_trace_selection", lambda ref: chosen["value"])
    return chosen


def test_only_sources_that_implement_from_trace_support_it(selection):
    assert business_trace.supports_from_trace({"source": "lf", "bindings": {}}) is True
    assert business_trace.supports_from_trace({"source": "ag", "bindings": {}}) is False
    assert not hasattr(agno, "from_trace")


@pytest.mark.parametrize("request_,error", [
    ({"capability_ref": REF, "from_trace": {"trace_id": "T"}, "body": {"q": 1}}, "二选一"),
    ({"capability_ref": REF, "from_trace": {"trace_id": ""}}, "非空 trace id"),
    ({"capability_ref": REF, "from_trace": {"trace_id": "T", "x": 1}}, "只写"),
    ({"capability_ref": REF}, "body 必须是非空"),
])
def test_case_validation(selection, request_, error):
    from impl.projects.llm_probe_loop.live_schema import check
    assert any(error in e for e in check.request_errors(request_))


def test_case_rejected_when_scene_source_cannot_from_trace(selection):
    from impl.projects.llm_probe_loop.live_schema import check
    request_ = {"capability_ref": REF, "from_trace": {"trace_id": "T"}}
    assert check.request_errors(request_) == []
    selection["value"] = {"source": "ag", "bindings": {}}
    assert any("不支持按 trace 复评" in e for e in check.request_errors(request_))
    selection["value"] = None
    assert any("没有选 trace 源" in e for e in check.request_errors(request_))


# ---- 执行链路（§4、§6）：不调业务、单轮、与现场同形 ----

def _case(trace_id="T"):
    from impl.core.interaction_protocol import normalize_case_interaction
    from impl.core.mock import mock_case_to_single_turn, parse_mock_case
    case = {"id": "from-trace-1", "project_id": "llm_probe_loop", "scenario": REF, "output": None, "reference": None,
            "live_request": {"capability_ref": REF, "from_trace": {"trace_id": trace_id}}}
    return normalize_case_interaction("llm_probe_loop", mock_case_to_single_turn(parse_mock_case(case)), 0)


def _run(monkeypatch, result, traced=True):
    from impl.core.trace import trace_from_live
    calls = []
    monkeypatch.setattr("impl.projects.llm_probe_loop.capability.capability_business_trace_selection", lambda ref: {"source": "lf", "bindings": {}})
    monkeypatch.setattr(business_trace, "supports_from_trace", lambda v: True)
    monkeypatch.setattr(business_trace, "from_trace", lambda v, tid: calls.append(tid) or result)
    monkeypatch.setattr(live, "capability_business_trace", lambda ref: {"source": "lf", "bindings": {}} if traced else None)
    monkeypatch.setattr(business_trace, "collect", lambda *a, **k: pytest.fail("复评不采第二遍"))
    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", lambda *a, **k: pytest.fail("复评不调业务"))
    return trace_from_live(load_adapter(load_project("llm_probe_loop")).live(), _case()), calls


def test_from_trace_case_runs_one_turn_without_calling_business(monkeypatch):
    snap = {"provider": "langfuse", "status": "succeeded", "records": {"trace": {"id": "T"}}}
    trace, calls = _run(monkeypatch, {"snapshot": snap, "failure": "", "request": Q, "delivered": ANS,
                                      "delivered_from": "root_observation", "error": ""})
    assert calls == ["T"]  # 用户原话与交付共用一次取回
    assert trace.execution_mode == "provided" and len(trace.turn_records) == 1
    turn = trace.turn_records[0]
    assert turn["request"]["body"] == {"messages": Q}
    assert turn["request"]["business_trace_association"] == {"from_trace": {"trace_id": "T", "delivered_from": "root_observation"}}
    assert turn["extracted_output"] == {"output_text": '{"answer": "1089.1元"}'}
    assert turn["project_fields"]["business_trace"] == snap
    assert [m["content"] for m in trace.conversation_transcript if m["role"] == "user"] == ["保单P0的累计已交保费是多少？"]
    delivered = _deliveries(trace)
    assert delivered[0]["output_text"] == '{"answer": "1089.1元"}' and "取自业务 trace 的记录（根步骤）" in delivered[0]["source"]


@pytest.mark.parametrize("failure,kind", [("HTTP 429", "live_http_error"), ("下游超时", "live_http_error")])
def test_recorded_business_failure_is_a_business_call_failure(monkeypatch, failure, kind):
    from impl.core.live_protocol import business_call_failure
    trace, _ = _run(monkeypatch, {"snapshot": {}, "failure": failure, "request": Q, "delivered": None, "delivered_from": "", "error": ""})
    assert failure in business_call_failure(trace)


def test_unreadable_trace_is_a_run_failure_not_a_business_failure(monkeypatch):
    from impl.core.live_protocol import business_call_failure
    trace, _ = _run(monkeypatch, {"snapshot": {}, "failure": "", "request": None, "delivered": None, "delivered_from": "",
                                  "error": "这条 trace 没有记本轮的请求"})
    assert business_call_failure(trace) == "" and "没有记本轮的请求" in (trace.error or "")


def test_failure_exceptions_share_the_live_http_class():
    from impl.core.live_protocol import LIVE_HTTP_ERROR, live_failure_type
    assert live_failure_type(LiveRecordedFailure("下游超时")) == LIVE_HTTP_ERROR
    assert live_failure_type(LiveHTTPStatusError(429, None)) == LIVE_HTTP_ERROR


def test_request_body_keeps_the_live_shape():
    assert from_trace_turn.request_body(Q) == {"messages": Q}
    assert from_trace_turn.request_body("一句话") == {"messages": [{"role": "user", "content": "一句话"}]}
    assert from_trace_turn.request_body({"text": "q", "uid": 1}) == {"text": "q", "uid": 1}
    assert from_trace_turn.user_text(Q) == "保单P0的累计已交保费是多少？"


def test_live_deliveries_carry_no_source():
    class T:
        turn_records = [{"request": {"body": {"q": 1}}, "extracted_output": {"output_text": "x"}}]
        extracted_output = {}
    assert _deliveries(T()) == [{"turn": "t1", "output_text": "x"}]
