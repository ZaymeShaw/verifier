"""llmtracing provider 协议测试：事件合并、execution 切片、完结判定、reader 映射。不访问真实中转。"""
from __future__ import annotations

from tests.support.expectations import E
import json
from pathlib import Path

import pytest

from impl.projects.llm_probe.business_trace.providers import llmtracing
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript, render


EXEC = "e" * 32


class _Trace:
    turn_records = []
    normalized_request = {"capability_ref": "insurance-llmtracing", "message": "question"}
    extracted_output = {"output_text": "answer"}
OTHER = "f" * 32


def _event(event, call_id, *, execution_id=EXEC, case_id="case-1", ts="2026-09-29T10:00:00", **extra):
    return {"event": event, "ts": ts, "call_id": call_id, "case_id": case_id, "execution_id": execution_id,
            "attribution_status": "explicit", "case_id_source": "header", "protocol": "chat_completions",
            "model": "m", **extra}


def _pre(call_id, messages, **kw):
    return _event("pre_api_call", call_id, messages=messages, tools=[{"type": "function", "function": {"name": "lookup"}}],
                  optional_params={"stream": False}, client_request={"api_key": "sk-secret"}, **kw)


def _success(call_id, *, tool_calls=None, content="", **kw):
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return _event("success", call_id, response={"choices": [{"message": message}]}, latency_ms=12,
                  usage={"prompt_tokens": 3, "completion_tokens": 2}, **kw)


def _write(path: Path, events, *, tail=b""):
    with path.open("ab") as out:
        for event in events:
            out.write((json.dumps(event) + "\n").encode())
        out.write(tail)


def _config(path: Path, **kw):
    return {"log_path": str(path), "settle_timeout_seconds": 0, "poll_interval_seconds": 0, "quiet_seconds": 0, **kw}


def _tool_round(path: Path):
    user = {"role": "user", "content": "question"}
    call = {"id": "t1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\": 1}"}}
    _write(path, [
        _pre("c1", [user], ts="2026-09-29T10:00:00"),
        _event("first_frame", "c1", first_frame_ms=5),
        _success("c1", tool_calls=[call], ts="2026-09-29T10:00:01"),
        _pre("c2", [user, {"role": "assistant", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": "t1", "content": "value"}], ts="2026-09-29T10:00:02"),
        _success("c2", content="answer", ts="2026-09-29T10:00:03"),
    ])


def test_validate_config_requires_absolute_log_path():
    with pytest.raises(ValueError):
        llmtracing.validate_config({"log_path": "relative.jsonl"})
    with pytest.raises(ValueError):
        llmtracing.validate_config({"log_path": "/tmp/x.jsonl", "quiet_seconds": -1})


def test_prepare_generates_headers_and_offset(tmp_path):
    log = tmp_path / "calls.jsonl"
    _write(log, [_pre("old", [])])
    prepared = llmtracing.prepare(_config(log), case_id="llm-probe/insurance 01", run_id="run-1")
    headers, assoc = prepared["headers"], prepared["association"]
    assert headers[llmtracing.HEADER_CASE] == "llm-probe_insurance_01"
    assert headers[llmtracing.HEADER_RUN] == "run-1"
    assert headers[llmtracing.HEADER_EXECUTION] == assoc["execution_id"]
    assert assoc["log_offset"] == log.stat().st_size
    other = llmtracing.prepare(_config(log), case_id="x")
    assert other["association"]["execution_id"] != assoc["execution_id"]


def test_read_calls_merges_by_call_id_and_filters_execution(tmp_path):
    log = tmp_path / "calls.jsonl"
    _write(log, [_pre("before", [], ts="2026-09-29T09:00:00")])
    start = log.stat().st_size
    _tool_round(log)
    _write(log, [_pre("foreign", [], execution_id=OTHER), _success("foreign", execution_id=OTHER)])
    calls, consumed = llmtracing.read_calls(log, start_offset=start, execution_id=EXEC)
    assert [c["call_id"] for c in calls] == ["c1", "c2"]
    assert set(calls[0]) >= {"pre", "first_frame", "outcome"}
    assert consumed == log.stat().st_size


def test_read_calls_ignores_incomplete_last_line(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", [])], tail=json.dumps(_success("c1")).encode()[:40])
    calls, consumed = llmtracing.read_calls(log, start_offset=0, execution_id=EXEC)
    assert "outcome" not in calls[0]
    assert consumed < log.stat().st_size


def _collect(log, assoc, **cfg):
    return llmtracing.collect(_config(log, **cfg), request={}, response={}, association=assoc)


def test_collect_complete_snapshot_and_transcript(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    assoc = llmtracing.prepare(_config(log), case_id="case-1")["association"] | {"execution_id": EXEC}
    _tool_round(log)
    snap = _collect(log, assoc)
    assert snap["status"] == "succeeded", snap["errors"]
    assert snap["association"]["matched_call_count"] == 2
    assert snap["coverage"]["calls"] == 2
    assert "sk-secret" not in json.dumps(snap["coverage"])

    transcript = build_transcript(_Trace(), snap)
    ids = [e["id"] for e in transcript["records"]]
    # 第二次调用只列新增的两条（assistant 工具调用 + 工具结果），首轮 user 不重复。
    assert ids[:10] == ["t1.request", "t1.c1", "t1.c1.tools", "t1.c1.params", "t1.c1.m1", "t1.c1.response",
                       "t1.c2", "t1.c2.tools", "t1.c2.params", "t1.c2.m2"]
    assert "t1.c2.m3" in ids and "t1.c2.m1" not in ids and ids[-1] == "t1.final"
    by_id = {e["id"]: e for e in transcript["records"]}
    assert by_id["t1.c2.tools"]["text"] == "同 t1.c1.tools"
    assert by_id["t1.c2.m3"]["role"] == "tool lookup#t1" and by_id["t1.c2.m3"]["text"] == "value"
    assert "→ 调用 lookup#t1" in by_id["t1.c1.response"]["text"]
    assert "新增 2 条" in json.loads(by_id["t1.c2"]["text"])["context"]
    assert "t1.gap.visibility" in ids
    text = render(transcript)
    assert "sk-secret" not in text and "[t1.c2.m3] tool lookup#t1" in text


def test_transcript_flags_dropped_context_and_truncates_without_losing_ids(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    first = {"role": "user", "content": "first " + "x" * 5000}
    _write(log, [_pre("c1", [first, {"role": "user", "content": "again"}]), _success("c1", content="a"),
                 _pre("c2", [{"role": "user", "content": "fresh"}]), _success("c2", content="b")])
    transcript = build_transcript(_Trace(), _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0}))
    call2 = next(e for e in transcript["records"] if e["id"] == "t1.c2")
    assert "未出现在本次请求里" in json.loads(call2["text"])["context"]
    small = render(transcript, budget_chars=3000)
    assert "截断：原文" in small
    assert all(f"[{e['id']}]" in small for e in transcript["records"])


def test_collect_partial_when_call_unfinished(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", [])])
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    assert snap["status"] == "partial"
    assert any(e.startswith("calls_unfinished") for e in snap["errors"])


def test_collect_waits_for_outcome(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", [])])
    ticks = iter(range(100))

    def sleep(_):
        if not any('"success"' in line for line in log.read_text().splitlines()):
            _write(log, [_success("c1", content="done")])

    snap = llmtracing.collect(_config(log, settle_timeout_seconds=50, quiet_seconds=2), request={}, response={},
                              association={"execution_id": EXEC, "case_id": "case-1", "log_offset": 0},
                              clock=lambda: float(next(ticks)), sleep=sleep)
    assert snap["status"] == "succeeded"


def test_collect_failure_event_counts_as_finished(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", []), _event("failure", "c1", error="upstream 500")])
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    assert snap["status"] == "succeeded"
    response = next(e for e in build_transcript(_Trace(), snap)["records"] if e["id"] == "t1.c1.response")
    assert response["kind"] == "error" and "upstream 500" in response["text"]


def test_collect_no_calls_is_declared(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    assert snap["status"] == "succeeded"
    assert "no_calls" in snap["coverage"]["limitations"]


def test_collect_case_mismatch_fails(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", [], case_id="other"), _success("c1", case_id="other")])
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    assert snap["status"] == "failed"
    assert snap["errors"][0].startswith("case_id_mismatch")


def test_collect_truncated_log_fails(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 999})
    assert snap["status"] == "failed"
    assert "log_truncated" in snap["errors"][0]


def test_collect_without_association_fails(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    assert llmtracing.collect(_config(log), request={}, response={})["status"] == "failed"


def test_non_chat_protocol_declares_tool_parsing_gap(tmp_path):
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _write(log, [_pre("c1", [], protocol="anthropic_messages"), _success("c1", protocol="anthropic_messages")])
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    assert snap["coverage"]["limitations"]["tool_call_parsing"]["status"] == "partial"


def test_check_connection(tmp_path):
    log = tmp_path / "calls.jsonl"
    with pytest.raises(FileNotFoundError):
        llmtracing.check_connection(_config(log))
    log.write_bytes(b"x\n")
    assert llmtracing.check_connection(_config(log))["size_bytes"] == 2


def test_llmtracing_transcript_is_analysed_but_six_axes_report_unsupported(tmp_path, monkeypatch):
    """llmtracing 不经 dossier/links：分析步确定性重建；过程六轴暂不支持对话稿，记运行错误、不调模型。"""
    from types import SimpleNamespace

    from impl.projects.llm_probe.eval_axes import registry  # noqa: F401  注册六轴定义
    from impl.projects.llm_probe.eval_axes.adapters import process_common, process_expected, trace_analysis
    from impl.projects.llm_probe.eval_axes.types import ScenarioAxis

    monkeypatch.setattr(trace_analysis, "build_dossier", lambda *a: pytest.fail("不应走案卷"))
    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    _tool_round(log)
    snap = _collect(log, {"execution_id": EXEC, "case_id": "case-1", "log_offset": 0})
    runtime = SimpleNamespace(spec=SimpleNamespace(project_id="llm_probe"), scenario_id="no-such-scenario",
                              trace_id="x", ensure_time_left=lambda _: None, enabled_axes=())
    analysis = trace_analysis.AXIS_TYPE.run({"trace": _Trace(), "business_trace": snap}, ScenarioAxis("trace_analysis", True, "d"), runtime)
    assert set(analysis.output) == set(trace_analysis.AXIS_TYPE.output_fields)
    assert analysis.output["verdict"] == "complete" and analysis.usage["llm_calls"] == 0

    monkeypatch.setattr(process_expected, "axis_llm", lambda *a, **kw: pytest.fail("对话稿不应调用评测模型"))
    outcome = process_common.run_process_axis("planning_routing", {"expectations": E, "trace_analysis": analysis.output},
                                              ScenarioAxis("planning_routing", True, "d"), runtime,
                                              process_common.PROCESS_SPECS["planning_routing"])
    assert outcome.failed and "暂不支持对话稿" in outcome.failure_reason


def test_reader_base_carries_no_agno_representation_semantics():
    from impl.projects.llm_probe.business_trace.reader import KINDS, TraceReader

    base = TraceReader({"provider": "x", "records": {}})
    text = json.dumps([base.overview(), base.timeline(), base.invocation_summary()], ensure_ascii=False)
    for word in ("Agno", "span", "SQLite", "session_state", "重建"):
        assert word not in text
    assert base.final_output_ref() is None
    assert set(TraceReader.kind_notes) == set(KINDS)


# ---- live 接入：prepare → 请求头 → collect(association) ----

def _live_with_llmtracing(monkeypatch, log, sent):
    from impl.core.project_loader import load_project
    from impl.projects.llm_probe import live as live_module

    trace = {"provider": "llmtracing", "config": _config(log)}
    monkeypatch.setattr(live_module, "capability_business_trace", lambda ref: trace if ref == "probe" else None)
    monkeypatch.setattr(live_module, "resolve_http", lambda payload, spec: (
        "http://business.test/chat", "POST", {"x-eval-execution-id": "stale", "Authorization": "keep"},
        payload["body"], 5.0, "json"))

    def fake_urlopen(request, timeout=0):
        sent.append({k.lower(): v for k, v in request.header_items()})
        return _Response(b'{"answer": "ok"}')

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    return live_module.LlmProbeLive(load_project("llm_probe")), live_module


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, data):
        self._data = data

    def read(self, *_):
        return self._data

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_live_sends_fresh_association_headers_and_collects_by_them(tmp_path, monkeypatch):
    from impl.core.live_transport import LiveTransport

    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    sent = []
    live, live_module = _live_with_llmtracing(monkeypatch, log, sent)
    token = live_module._CASE_ID.set("case-1")
    try:
        first = {"body": {"q": 1}, "capability_ref": "probe"}
        live.deliver_real(first, LiveTransport())
        second = {"body": {"q": 2}, "capability_ref": "probe"}
        live.deliver_real(second, LiveTransport())
    finally:
        live_module._CASE_ID.reset(token)
    exec_ids = [h["x-eval-execution-id"] for h in sent]
    assert len(set(exec_ids)) == 2 and "stale" not in exec_ids
    assert all(h["x-eval-case-id"] == "case-1" and h["authorization"] == "keep" for h in sent)
    assert first["business_trace_association"]["execution_id"] == exec_ids[0]

    # 业务侧把头透传到模型请求后，中转写下的事件只会被对应那次投递切到。
    _write(log, [_pre("c-first", [], execution_id=exec_ids[0]), _success("c-first", execution_id=exec_ids[0])])
    from impl.core.schema import LiveRequest
    request = LiveRequest(project_id="llm_probe", raw_input={}, case_id="case-1", normalized_request=first,
                          execution_mode="live", session_id="s")
    fields = live.project_fields([{"answer": "ok"}], {}, request, {})
    snap = fields["business_trace"]
    assert snap["status"] == "succeeded"
    assert [c["call_id"] for c in snap["records"]["calls"]] == ["c-first"]


def test_live_without_trace_config_sends_no_association(tmp_path, monkeypatch):
    from impl.core.live_transport import LiveTransport

    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    sent = []
    live, _ = _live_with_llmtracing(monkeypatch, log, sent)
    request = {"body": {"q": 1}, "capability_ref": "other", "business_trace_association": {"execution_id": "old"}}
    live.deliver_real(request, LiveTransport())
    assert "x-eval-case-id" not in sent[0]
    assert "business_trace_association" not in request


def test_multi_turn_case_gets_one_execution_per_turn_and_real_case_id(tmp_path, monkeypatch):
    """走真实 Session/ReplayDriver：case_id 来自 ctx，每轮投递各自一个 execution_id 并各自切片。"""
    from impl.core.interaction_protocol import normalize_case_interaction
    from impl.core.mock import mock_case_to_single_turn, parse_mock_case
    from impl.core.project_loader import load_adapter, load_project
    from impl.core.trace import trace_from_live
    from impl.projects.llm_probe import live as live_module

    log = tmp_path / "calls.jsonl"
    log.write_bytes(b"")
    trace_config = {"provider": "llmtracing", "config": _config(log)}
    monkeypatch.setattr(live_module, "capability_business_trace", lambda ref: trace_config)
    sent = []

    def fake_urlopen(request, timeout=0):
        headers = {k.lower(): v for k, v in request.header_items()}
        sent.append(headers)
        exec_id = headers["x-eval-execution-id"]
        call = f"call-{len(sent)}"
        _write(log, [_pre(call, [], execution_id=exec_id, case_id=headers["x-eval-case-id"]),
                     _success(call, execution_id=exec_id, case_id=headers["x-eval-case-id"])])
        return _Response(json.dumps({"answer": f"reply-{len(sent)}", "trace_id": f"t{len(sent)}"}).encode())

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    body = {"session_id": "{session_id}", "messages": [{"role": "user", "content": "第一问"}]}
    turns = [{"turn_index": i + 1, "message": {"type": "text", "text": text},
              "request": {"capability_ref": "insurance-agno-e2e", "method": "POST",
                          "body": {"session_id": "{session_id}", "messages": [{"role": "user", "content": text}]}}}
             for i, text in enumerate(["第一问", "第二问"])]
    case = {"id": "llmtracing-multi-turn", "project_id": "llm_probe", "scenario": "insurance-agno-e2e",
            "live_request": {"capability_ref": "insurance-agno-e2e", "method": "POST", "body": body},
            "output": None, "reference": None,
            "seed": {"level": "transcript", "mode": "replay", "session_mode": "text", "protocol_fuzz": False,
                     "stop_reason": "goal_satisfied", "prefix": [], "prefix_mode": None, "turns": turns,
                     "intent_history": []}}
    normalized = normalize_case_interaction("llm_probe", mock_case_to_single_turn(parse_mock_case(case)), 0)
    monkeypatch.setattr(live_module, "resolve_http", lambda payload, spec: (
        "http://business.test/chat", "POST", {}, payload["body"], 5.0, "json"))
    trace = trace_from_live(load_adapter(load_project("llm_probe")).live(), normalized)

    assert len(sent) == 2
    assert {h["x-eval-case-id"] for h in sent} == {"llmtracing-multi-turn"}
    assert sent[0]["x-eval-execution-id"] != sent[1]["x-eval-execution-id"]
    assert live_module._CASE_ID.get() == ""
    snaps = [(t.get("project_fields") or {}).get("business_trace") for t in trace.turn_records]
    assert [[c["call_id"] for c in s["records"]["calls"]] for s in snaps] == [["call-1"], ["call-2"]]


# ---- 场景数据：insurance-llmtracing 是 insurance-agno-e2e 的同题副本，只换 provider ----

_DATA = Path(__file__).parents[1] / "impl/data/llm_probe"
_AGNO, _LLMT = "insurance-agno-e2e", "insurance-llmtracing"


def test_llmtracing_scenario_differs_from_agno_only_in_trace_evidence():
    from impl.projects.llm_probe.business_trace import validate_business_trace

    presets = json.loads((_DATA / "capability_map.json").read_text(encoding="utf-8"))
    agno_preset, llmt_preset = dict(presets[_AGNO]), dict(presets[_LLMT])
    assert validate_business_trace(llmt_preset["business_trace"])["provider"] == "llmtracing"
    # boundary 只改了"过程证据来源"一句，其余字段必须同步维护。
    for key in ("business_trace", "boundary"):
        agno_preset.pop(key), llmt_preset.pop(key)
    assert agno_preset == llmt_preset


def test_llmtracing_cases_mirror_agno_cases():
    cases = json.loads((_DATA / "mock_cases.json").read_text(encoding="utf-8"))
    agno_cases = {c["id"]: c for c in cases if c.get("scenario") == _AGNO}
    llmt_cases = {c["id"]: c for c in cases if c.get("scenario") == _LLMT}
    assert set(llmt_cases) == {f"{case_id}-llmtracing" for case_id in agno_cases}
    for case_id, case in agno_cases.items():
        mirrored = json.loads(json.dumps(llmt_cases[f"{case_id}-llmtracing"], ensure_ascii=False)
                              .replace(f'"{_LLMT}"', f'"{_AGNO}"'))
        mirrored["id"] = case_id
        assert mirrored == case, case_id


def test_llmtracing_scenario_is_registered_in_project():
    text = (Path(__file__).parents[1] / "impl/projects/llm_probe/project.yaml").read_text(encoding="utf-8")
    import yaml

    data = yaml.safe_load(text)
    # 凡是登记了 agno 场景的列表（default_scenarios、scenarios.allowed）都要同时登记 llmtracing 场景。
    found = []

    def walk(node, path=()):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + (k,))
        elif isinstance(node, list) and _AGNO in node:
            found.append((path, _LLMT in node))

    walk(data)
    assert found and all(ok for _, ok in found), found
