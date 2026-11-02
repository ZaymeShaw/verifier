from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pytest

from impl.core.capability_store import validate_entry
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace
from impl.projects.llm_probe.business_trace import validate_business_trace
from impl.projects.llm_probe.business_trace.providers import agno
from impl.projects.llm_probe.live import LlmProbeLive, resolve_http
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
from impl.projects.llm_probe.eval_axes.runner import run_axes
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.eval_axes.validate import scenario_axes_from_entry


def _post(path: str, payload: dict):
    import httpx

    from impl.server.app import create_app

    async def request():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, json=payload)

    return asyncio.run(request())


def _config() -> dict:
    return {
        "base_url": "http://127.0.0.1:7777",
        "headers": {"Authorization": "Bearer ${AGNO_TOKEN}"},
        "timeout_seconds": 5,
        "poll_attempts": 2,
        "poll_interval_seconds": 0,
        "bindings": {
            "session_id": {"source": "request", "pointer": "/body/session_id"},
            "user_id": {"source": "request", "pointer": "/body/user_id"},
            "business_trace_id": {"source": "response", "pointer": "/trace_id"},
        },
    }


def _trace(snapshot: dict | None = None) -> RunTrace:
    return RunTrace(
        trace_id="llm_probe:case:1",
        project_id="llm_probe",
        case_id="case",
        input={"capability_ref": "insurance", "body": {"session_id": "s1"}},
        normalized_request={"capability_ref": "insurance", "body": {"session_id": "s1"}},
        extracted_output={"output_text": '{"answer":"ok","trace_id":"biz-1"}'},
        project_fields={"business_trace": snapshot} if snapshot is not None else {},
    )


class _ExplorationLlm:
    """trace_analysis 探测 LLM 的确定性替身：返回空 findings，让勘察轴 succeed。"""

    def complete_json(self, *_a, **_k):
        return {"findings": [], "coverage_note": "ok"}

    def usage(self):
        return {"llm_calls": 1}


def _run_chain(monkeypatch, snapshot, axis_ids, scenario_id="example"):
    """跑 trace_analysis + 指定过程轴，返回 {axis_id: result}。

    过程轴的 Judge 由调用方自行 patch process_common.axis_llm；本助手只负责把勘察轴
    塞进链路并 mock 其探测 LLM，使 depend_on trace_analysis 的六轴不被 blocked。
    """
    from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as ta_mod
    monkeypatch.setattr(ta_mod, "axis_llm", lambda *_a, **_k: _ExplorationLlm())
    ids = ["trace_analysis", *[a for a in axis_ids if a != "trace_analysis"]]
    results = run_axes(load_project("llm_probe"), _trace(snapshot),
                       [ScenarioAxis(a, True, f"检查 {a}") for a in ids], scenario_id=scenario_id)
    return {r.axis_id: r for r in results}


def test_capability_entry_preserves_provider_specific_config() -> None:
    entry = validate_entry("insurance", {
        "capability": "回答保险问题",
        "business_trace": {"provider": "agno", "config": _config()},
    })
    assert entry["business_trace"]["provider"] == "agno"
    assert entry["business_trace"]["config"]["bindings"]["session_id"]["pointer"] == "/body/session_id"


def test_agno_provider_validation_is_specific_and_unknown_provider_is_rejected() -> None:
    clean = validate_business_trace({"provider": "agno", "config": _config()})
    assert clean["config"]["poll_attempts"] == 2
    with pytest.raises(ValueError, match="当前支持: agno"):
        validate_business_trace({"provider": "unknown", "config": {}})
    broken = _config()
    broken["bindings"] = {}
    with pytest.raises(ValueError, match="bindings.session_id"):
        validate_business_trace({"provider": "agno", "config": broken})
    wrong_source = _config()
    wrong_source["bindings"]["business_trace_id"]["source"] = "request"
    with pytest.raises(ValueError, match="business_trace_id.source 必须是 response"):
        validate_business_trace({"provider": "agno", "config": wrong_source})


def test_enabled_trace_axis_requires_valid_business_trace_config() -> None:
    entry = {
        "capability": "回答保险问题",
        "axes": [{"type": "context_memory", "enabled": True}],
    }
    with pytest.raises(ValueError, match="需要 business_trace"):
        scenario_axes_from_entry(entry, owner="insurance")
    entry["business_trace"] = {"provider": "agno", "config": _config()}
    axes, report = scenario_axes_from_entry(entry, owner="insurance")
    assert report.ok and axes[0].type_id == "context_memory"


def test_fulfillment_alone_does_not_pull_in_expectations_axis() -> None:
    """需求轴只在除兑现轴外有别的轴需要它时才必须跑（demand/expectations.md §3）；只开兑现轴时兑现轴自推。"""
    entry = {
        "capability": "回答保险问题",
        "axes": [{"type": "fulfillment", "enabled": True, "description": "只回答保单问题"}],
    }
    axes, report = scenario_axes_from_entry(entry, owner="insurance")
    assert report.ok and [a.type_id for a in axes] == ["fulfillment"]


def test_capability_save_checks_trace_requirements_without_running_other_source_checks(monkeypatch) -> None:
    from impl.server import service

    stored = []
    monkeypatch.setattr(
        service.capability_store,
        "save_capability",
        lambda project, name, entry: stored.append((project, name, entry)) or {"entry": entry},
    )
    with pytest.raises(ValueError, match="需要 business_trace"):
        service.save_capability({
            "project": "llm_probe",
            "name": "insurance",
            "entry": {
                "capability": "回答保险问题",
                "axes": [{"type": "context_memory", "enabled": True, "description": "检查上下文"}],
            },
        })
    result = service.save_capability({
        "project": "llm_probe",
        "name": "insurance",
        "entry": {
            "capability": "回答保险问题",
            "business_trace": {"provider": "agno", "config": _config()},
            "axes": [{"type": "context_memory", "enabled": True, "description": "检查上下文"}],
        },
    })
    assert result["entry"]["business_trace"]["provider"] == "agno"
    assert len(stored) == 1


def _turn_request(text: str) -> dict:
    return {"body": {"session_id": "s1", "user_id": "u1", "messages": [{"role": "user", "content": text}]}}


def test_agno_collect_associates_by_session_and_turn_input_and_freezes_details(monkeypatch) -> None:
    # 业务响应的 trace_id 只回显请求方的值（此处为 null），与 run 内服务端 trace_id 不同，不参与关联。
    response = {"answer": "ok", "trace_id": None}
    stored = {"answer": "ok", "trace_id": "TR-server"}
    calls = []

    def fake_get(config, path, query=None):
        calls.append((path, query))
        if path == "/sessions/s1/runs":
            return [
                {"run_id": "r1", "run_input": "第一问", "created_at": "2026-09-24T09:32:00Z",
                 "content": json.dumps({"answer": "old", "trace_id": "TR-1"})},
                {"run_id": "r2", "run_input": "第二问", "created_at": "2026-09-24T09:32:30Z",
                 "content": json.dumps(stored), "step_results": [{"step_name": "agent"}]},
            ]
        if path == "/traces":
            assert query["run_id"] == "r2"
            return {"data": [{"trace_id": "t2", "run_id": "r2"}]}
        if path == "/traces/t2":
            return {"trace_id": "t2", "tree": [{"name": "conversation_turn"}]}
        if path == "/sessions/s1/runs/r2":
            return {"run_id": "r2", "content": json.dumps(stored), "step_results": [{"step_name": "agent"}], "citations": {"x": 1}}
        raise AssertionError(path)

    monkeypatch.setattr(agno, "_get_json", fake_get)
    snapshot = agno.collect(_config(), request=_turn_request(" 第二问 "), response=response)
    assert snapshot["status"] == "succeeded"
    assert snapshot["association"]["run_id"] == "r2"
    assert snapshot["association"]["user_text"] == "第二问"
    assert snapshot["records"]["run"]["run_id"] == "r2"
    assert snapshot["records"]["run"]["citations"] == {"x": 1}
    assert snapshot["records"]["traces"][0]["trace_id"] == "t2"
    assert [item["kind"] for item in snapshot["refs"]] == ["run", "trace"]
    assert snapshot["refs"][1]["url"].endswith("/traces/t2")
    assert len(snapshot["fingerprint"]) == 64


def test_agno_collect_rejects_ambiguous_association(monkeypatch) -> None:
    same = {"run_input": "同一句", "created_at": "2026-09-24T09:32:00Z"}
    monkeypatch.setattr(
        agno,
        "_get_json",
        lambda *_args, **_kwargs: [{"run_id": "r1", **same}, {"run_id": "r2", **same}],
    )
    snapshot = agno.collect(_config(), request=_turn_request("同一句"), response={"answer": "ok"})
    assert snapshot["status"] == "failed"
    assert snapshot["errors"] == ["association_ambiguous:2"]


def test_agno_collect_repeated_turn_text_picks_latest_run() -> None:
    runs = [
        {"run_id": "r1", "run_input": "再查一次", "created_at": "2026-09-24T09:32:00Z"},
        {"run_id": "r2", "run_input": "再查一次", "created_at": "2026-09-24T09:32:40Z"},
    ]
    assert [r["run_id"] for r in agno._select_turn_run(runs, "u1", "再查一次")[0]] == ["r2"]


def test_agno_collect_waits_for_current_turn_run(monkeypatch) -> None:
    polls = iter([
        [{"run_id": "r1", "run_input": "第一问", "created_at": "2026-09-24T09:32:00Z"}],
        [{"run_id": "r1", "run_input": "第一问", "created_at": "2026-09-24T09:32:00Z"},
         {"run_id": "r2", "run_input": "第二问", "created_at": "2026-09-24T09:32:30Z"}],
    ])

    def fake_get(_config, path, query=None):
        if path == "/sessions/s1/runs":
            return next(polls)
        raise RuntimeError("stop after association")

    monkeypatch.setattr(agno, "_get_json", fake_get)
    monkeypatch.setattr(agno.time, "sleep", lambda _s: None)
    snapshot = agno.collect(_config(), request=_turn_request("第二问"), response={"answer": "ok"})
    assert snapshot["association"]["session_id"] == "s1"
    assert "association_not_found" not in snapshot["errors"]
    assert "stop after association" in snapshot["errors"][0]


def test_agno_collect_reports_not_found_when_turn_input_absent(monkeypatch) -> None:
    monkeypatch.setattr(agno, "_get_json", lambda *_a, **_k: [
        {"run_id": "r1", "run_input": "别的问题", "created_at": "2026-09-24T09:32:00Z"},
    ])
    monkeypatch.setattr(agno.time, "sleep", lambda _s: None)
    snapshot = agno.collect(_config(), request=_turn_request("本轮问题"), response={"answer": "ok"})
    assert snapshot["errors"] == ["association_not_found"]
    assert snapshot["association"]["candidate_run_count"] == 1
    assert snapshot["association"]["input_matched_run_count"] == 0


def test_agno_reader_keeps_tool_result_and_redacts_json_encoded_secrets() -> None:
    snapshot = {"records": {"run": {"step_executor_runs": [{"messages": [
        {"role": "tool", "content": json.dumps({"premium": 1000, "api_key": "secret-value"})},
    ]}]}}}
    reader = agno.open_reader(snapshot)
    item = reader.list_records("messages")["items"][0]
    result = reader.read(item["fields"]["content"]["ref"])
    assert "1000" in result["text"]
    assert "secret-value" not in result["text"]
    assert "[REDACTED]" in result["text"]


def test_agno_reader_pages_long_evidence_without_losing_tail() -> None:
    snapshot = {"records": {"run": {"messages": [{"content": "x" * 20000 + "last fact"}]}}}
    reader = agno.open_reader(snapshot)
    ref = reader.list_records("messages")["items"][0]["fields"]["content"]["ref"]
    first = reader.read(ref)
    assert first["truncated"] is True
    assert first["next_offset"] == 12000
    last = reader.read(ref, offset=first["next_offset"])
    assert first["text"] + last["text"] == "x" * 20000 + "last fact"
    assert last["next_offset"] is None


def test_agno_reader_indexes_nested_steps_and_message_parents() -> None:
    snapshot = {"records": {"run": {
        "step_results": [{"steps": [{"content": "agent input"}]}],
        "step_executor_runs": [{"messages": [{"role": "user", "content": "question"}]}],
    }}}
    reader = agno.open_reader(snapshot)
    assert reader.list_records("messages")["items"][0]["ref"] == "/records/run/step_executor_runs/0/messages/0"
    steps = reader.list_records("steps")["items"]
    assert steps[1]["ref"] == "/records/run/step_results/0/steps/0"
    assert steps[1]["parent_ref"] == steps[0]["ref"]


def test_agno_collect_rejects_unique_match_without_run_id_before_trace_query(monkeypatch) -> None:
    response = {"answer": "ok", "trace_id": "biz-1"}
    calls = []

    def fake_get(_config, path, query=None):
        calls.append((path, query))
        if path == "/sessions/s1/runs":
            return [{"content": json.dumps(response)}]
        raise AssertionError(f"不应在缺 run_id 时继续请求 {path}")

    monkeypatch.setattr(agno, "_get_json", fake_get)
    snapshot = agno.collect(_config(), request={"body": {"session_id": "s1"}}, response=response)
    assert snapshot["status"] == "failed"
    assert snapshot["association"]["matched_run_count"] == 1
    assert snapshot["association"]["run_id"] == ""
    assert snapshot["errors"] == ["association_missing_run_id"]
    assert calls == [("/sessions/s1/runs", {"user_id": None})]


@pytest.mark.parametrize(
    ("mismatch_path", "expected_error"),
    [
        ("summary", "trace_summary_run_mismatch:t1@other"),
        ("detail", "trace_detail_run_mismatch:t1@other"),
    ],
)
def test_agno_collect_rejects_trace_from_another_run(monkeypatch, mismatch_path, expected_error) -> None:
    response = {"answer": "ok", "trace_id": "biz-1"}

    def fake_get(_config, path, query=None):
        if path == "/sessions/s1/runs":
            return [{"run_id": "r1", "content": json.dumps(response)}]
        if path == "/sessions/s1/runs/r1":
            return {"run_id": "r1", "content": json.dumps(response)}
        if path == "/traces":
            assert query["run_id"] == "r1"
            return {"data": [{"trace_id": "t1", "run_id": "other" if mismatch_path == "summary" else "r1"}]}
        if path == "/traces/t1":
            return {"trace_id": "t1", "run_id": "other"}
        raise AssertionError(path)

    monkeypatch.setattr(agno, "_get_json", fake_get)
    snapshot = agno.collect(_config(), request={"body": {"session_id": "s1"}}, response=response)
    assert snapshot["status"] == "failed"
    assert snapshot["association"]["run_id"] == "r1"
    assert snapshot["errors"] == [expected_error]


def test_live_attaches_one_collected_snapshot_to_project_fields(monkeypatch) -> None:
    configured = {"provider": "agno", "config": _config()}
    collected = {"provider": "agno", "status": "succeeded", "fingerprint": "fixed"}
    seen = []
    monkeypatch.setattr("impl.projects.llm_probe.live.capability_business_trace", lambda _ref: configured)
    monkeypatch.setattr(
        "impl.projects.llm_probe.business_trace.collect",
        lambda value, *, request, response, association=None: seen.append((value, request, response)) or collected,
    )
    fields = LlmProbeLive(load_project("llm_probe")).project_fields(
        [{"answer": "ok", "trace_id": "biz-1"}],
        {"output_text": "ok"},
        {"capability_ref": "insurance", "body": {"session_id": "s1"}},
        {},
    )
    assert fields["business_trace"] is collected
    assert seen[0][2]["trace_id"] == "biz-1"


def test_invalid_trace_config_is_rejected_before_business_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "impl.projects.llm_probe.live.capability_business_trace",
        lambda _ref: {"provider": "agno", "config": {"base_url": "bad"}},
    )
    with pytest.raises(ValueError, match="base_url"):
        resolve_http(
            {"capability_ref": "client_search", "body": {"q": "x"}},
            load_project("llm_probe"),
        )








def test_new_case_session_is_unique_and_query_is_not_reinterpreted(monkeypatch):
    from impl.projects.llm_probe import capability

    template = {"session_id": "{session_id}", "nested": ["{session_id}", "{query}"], "fixed": "keep"}
    monkeypatch.setattr(capability, "load_capability_map", lambda: {"example": {"mock_body": template}})
    first = capability.fresh_delivery_placeholders(capability.mock_body("example", "literal {session_id} {query}"))
    second = capability.fresh_delivery_placeholders(capability.mock_body("example", "another query"))
    assert first["session_id"] != second["session_id"]
    assert first["nested"][0] == first["session_id"]
    assert first["nested"][1] == "literal {session_id} {query}"
    assert first["fixed"] == "keep"
    assert template["session_id"] == "{session_id}"














def test_materials_page_exposes_provider_config_and_connection_check() -> None:
    html = (Path(__file__).parents[1] / "impl" / "frontend" / "materials.html").read_text(encoding="utf-8")
    assert 'id="businessTraceProvider"' in html
    assert 'id="businessTraceConfig"' in html
    assert "/api/business_trace/check" in html


def test_business_trace_provider_endpoints_expose_agno_and_check(monkeypatch) -> None:
    providers = _post("/api/business_trace/providers", {"project": "llm_probe"})
    assert providers.status_code == 200
    assert [item["provider"] for item in providers.json()["providers"]] == ["agno", "llmtracing", "langfuse"]
    monkeypatch.setattr(
        "impl.projects.llm_probe.business_trace.check_connection",
        lambda value: {"ok": True, "provider": value["provider"], "base_url": value["config"]["base_url"]},
    )
    checked = _post(
        "/api/business_trace/check",
        {"project": "llm_probe", "business_trace": {"provider": "agno", "config": _config()}},
    )
    assert checked.status_code == 200
    assert checked.json()["ok"] is True
    assert checked.json()["provider"] == "agno"


def test_trace_analysis_request_failure_is_failed_axis_with_error_text(monkeypatch) -> None:
    """v2 §5.2：勘察轴的请求层失败 → 轴 failed，error 保留原始错误文本，不进结构修复/salvage。"""
    from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as ta_mod

    class _RequestFailedLlm:
        def complete_step(self, *_a, **_k):
            raise RuntimeError("HTTP 401 invalid api-key")

        def usage(self):
            return {"llm_calls": 1}

    monkeypatch.setattr(ta_mod, "axis_llm", lambda *_a, **_k: _RequestFailedLlm())
    snapshot = {
        "provider": "agno",
        "status": "succeeded",
        "config": _config(),
        "records": {"run": {"messages": [{"content": "用户问保单状态"}]}},
    }

    results = run_axes(
        load_project("llm_probe"),
        _trace(snapshot),
        [ScenarioAxis("trace_analysis", True, "检查案卷")],
        scenario_id="example",
    )
    result = {r.axis_id: r for r in results}["trace_analysis"]

    assert result.status == "failed"
    assert result.usage["llm_error"] == "llm_request_failed"
    assert "401" in result.usage["llm_error_text"]
    assert result.error.startswith("[运行环境] 模型请求失败 llm_request_failed")


def test_request_id_placeholder_is_fresh_on_every_delivery_and_not_fixed_at_case_generation(monkeypatch):
    from impl.projects.llm_probe import capability

    template = {"session_id": "{session_id}", "trace_id": "{request_id}", "messages": [{"content": "{query}"}]}
    monkeypatch.setattr(capability, "load_capability_map", lambda: {"example": {"mock_body": template}})
    case_body = capability.mock_body("example", "q")
    assert case_body["trace_id"] == "{request_id}"  # 生成用例时不落定，保存的用例里仍是占位符
    first = capability.fresh_delivery_placeholders(case_body)
    second = capability.fresh_delivery_placeholders(case_body)
    assert first["trace_id"].startswith("llm-probe-req-") and first["trace_id"] != second["trace_id"]
    assert first["trace_id"] != first["session_id"]
    assert case_body["trace_id"] == "{request_id}"
