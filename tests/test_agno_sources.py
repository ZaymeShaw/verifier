from __future__ import annotations

import json
import sqlite3

import pytest

from impl.projects.llm_probe.business_trace import open_reader
from impl.projects.llm_probe.business_trace.providers.agno_sources import Sources, collect_sources


def snapshot():
    return {"provider": "agno", "status": "succeeded", "association": {"run_id": "r", "session_id": "s", "user_id": "u"},
            "records": {"run": {"run_id": "r", "workflow_id": "w", "content": "answer"},
                        "trace_summaries": [{"trace_id": "t", "run_id": "r"}],
                        "traces": [{"trace_id": "t", "run_id": "r", "tree": [
                            {"id": "span", "type": "LLM", "input": "__REDACTED__", "output": "__REDACTED__"},
                        ]}]}}


def test_additional_api_sources_are_scoped_and_marked_as_current_observations():
    snap = snapshot()
    paths = ["/config", "/sessions/{session_id}", "/workflows/{workflow_id}", "/memories"]
    calls = []
    def get(config, path, query=None):
        calls.append((path, query))
        if path == "/openapi.json":
            return {"paths": {p: {"get": {}} for p in paths}}
        if path == "/config":
            return {"agents": []}
        if path == "/sessions/s":
            assert query == {"user_id": "u"}
            return {"session_id": "s", "user_id": "u", "session_state": {"latest": "state"}}
        if path == "/workflows/w":
            return {"id": "w", "steps": [{"agent": {"name": "worker", "system_message": {"instructions": "current"},
                    "tools": {"tools": [{"name": "lookup", "description": "Find values", "parameters": {"type": "object"}}]}}}]}
        if path == "/memories":
            assert query["user_id"] == "u"
            return {"data": [{"memory_id": "m", "user_id": "u", "memory": "current memory"}], "meta": {"total_pages": 1}}
        raise AssertionError(path)
    collect_sources({}, snap, get)
    reader = open_reader(snap)
    defs = reader.list_records("definitions")["items"]
    assert [d.get("name") for d in defs] == ["w", "worker", "lookup"]
    assert all(d["scope"] == "observed_at_collection_not_verified_run_version" for d in defs)
    assert reader.list_records("sessions")["items"][0]["scope"] == "observed_at_collection"
    assert reader.list_records("memories")["items"][0]["scope"] == "observed_at_collection"
    assert all(not p.endswith("/runs") for p, _ in calls)


def test_other_users_session_and_memories_are_rejected():
    snap = snapshot()
    def get(config, path, query=None):
        if path == "/openapi.json":
            return {"paths": {p: {"get": {}} for p in ("/sessions/{session_id}", "/memories")}}
        if path.startswith("/sessions/"):
            return {"session_id": "s", "user_id": "other", "session_state": {"private": "value"}}
        if path == "/memories":
            return {"data": [{"user_id": "other", "memory": "private"}]}
        raise AssertionError(path)
    collect_sources({}, snap, get)
    assert "session" not in snap["records"]
    assert snap["records"]["memories"] == []
    assert sum(r["status"] == "rejected" for r in snap["sources"]) == 2
    assert "private" not in json.dumps(snap["records"])


def database(tmp_path, *, wrong_owner=False):
    path = tmp_path / "agno.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE agno_runs (run_id TEXT, session_id TEXT, user_id TEXT, run_data TEXT)")
        db.execute("CREATE TABLE agno_traces (trace_id TEXT,run_id TEXT,session_id TEXT,user_id TEXT)")
        db.execute("CREATE TABLE agno_spans (span_id TEXT,trace_id TEXT,parent_span_id TEXT,name TEXT,start_time TEXT,attributes TEXT)")
        db.execute("INSERT INTO agno_runs VALUES (?,?,?,?)", ("r", "s", "u", json.dumps({"run_id": "r", "content": "answer"})))
        db.execute("INSERT INTO agno_traces VALUES (?,?,?,?)", ("t", "other" if wrong_owner else "r", "s", "u"))
        db.execute("INSERT INTO agno_spans VALUES (?,?,?,?,?,?)", ("span", "t", None, "model.invoke", "2026-01-01T00:00:00Z", json.dumps({
            "openinference.span.kind": "LLM", "input.value": "__REDACTED__", "output.value": "__REDACTED__",
            "llm.invocation_parameters": json.dumps({"max_tokens": 100, "api_key": "DO_NOT_EXPOSE"}),
            "llm.token_count.prompt": 0,
        })))
    return path


@pytest.mark.parametrize("wrong_owner", [False, True])
def test_sqlite_raw_spans_join_by_exact_trace_and_span_and_stay_read_only(tmp_path, wrong_owner):
    path = database(tmp_path, wrong_owner=wrong_owner)
    before = path.read_bytes()
    snap = snapshot()
    source = Sources({"sqlite_path": str(path)}, snap, lambda *_a: None)
    source._sqlite(snap["records"]["run"], "s", "u")
    assert path.read_bytes() == before
    if wrong_owner:
        assert source.receipts[-1]["status"] == "failed"
        assert "raw_spans" not in snap["records"]
        return
    assert source.receipts[-1]["status"] == "available"
    reader = open_reader(snap)
    models = reader.list_records("model_calls")["items"]
    assert len(models) == 1  # API and SQLite are one model span, not two calls.
    model = models[0]
    assert model["fields"]["input"]["status"] == "redacted"
    assert model["fields"]["exact_request"]["status"] == "unverified"
    params = reader.read(model["fields"]["invocation_parameters"]["ref"])
    assert "100" in params["text"] and "DO_NOT_EXPOSE" not in params["text"]
    assert reader.read(model["fields"]["input_tokens"]["ref"])["text"] == "0"
    assert reader.limitations["exact_model_request"]["status"] == "unverified"


def test_recorded_span_input_is_exact_request_and_closes_gap():
    snap = snapshot()
    snap["records"]["traces"][0]["tree"][0]["input"] = json.dumps({"messages": [{"role": "system", "content": "rules"}]})
    reader = open_reader(snap)
    model = reader.list_records("model_calls")["items"][0]
    assert model["fields"]["exact_request"]["status"] == "available"
    assert "rules" in reader.read(model["fields"]["exact_request"]["ref"])["text"]
    assert reader.limitations["exact_model_request"]["status"] == "available"


def test_rich_run_fields_are_indexed_without_promoting_reasoning_to_truth():
    snap = snapshot()
    snap["records"]["run"].update({
        "events": [{"event": "RunCompleted", "content": "done"}],
        "step_requirements": [{"type": "user_input"}],
        "reasoning_steps": [{"title": "model's own explanation"}],
        "files": [{"url": "https://example.invalid/private.pdf"}],
        "member_responses": [{"run_id": "child", "messages": [{"role": "user", "content": "subtask"}]}],
    })
    reader = open_reader(snap)
    for kind in ("events", "requirements", "reasoning", "artifacts"):
        assert reader.list_records(kind)["total"] == 1
    assert reader.list_records("messages", run_id="child")["total"] == 1
    assert "自述" in reader.overview()["categories"]["reasoning"]["meaning"]


def test_registered_agent_checkpoints_are_derived_and_bad_snapshot_identity_is_rejected():
    snap = snapshot()
    snap["records"]["run"]["step_executor_runs"] = [{"agent_id": "a", "run_id": "child"}]
    checkpoint_path = "/agents/a/runs/child/checkpoints"
    def get(config, path, query=None):
        if path == "/openapi.json":
            return {"paths": {p: {"get": {}} for p in (
                "/config", "/agents/{agent_id}/runs/{run_id}/checkpoints",
                "/agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}")}}
        if path == "/config":
            return {"agents": [{"id": "a"}]}
        assert query == {"session_id": "s"}
        if path == checkpoint_path:
            return {"run_id": "child", "session_id": "s", "checkpoints": [{"message_index": 1}, {"message_index": 3}]}
        if path == checkpoint_path + "/1":
            return {"run_id": "child", "session_id": "s", "messages": [{"role": "user", "content": "saved"}]}
        if path == checkpoint_path + "/3":
            return {"run_id": "other", "session_id": "s", "messages": [{"content": "UNRELATED"}]}
        raise AssertionError(path)
    collect_sources({}, snap, get)
    reader = open_reader(snap)
    checkpoint = reader.list_records("checkpoints")["items"][0]
    assert checkpoint["scope"] == "derived_from_persisted_run"
    text = reader.read(checkpoint["fields"]["snapshots"]["ref"])["text"]
    assert "saved" in text and "UNRELATED" not in text
    assert any(r["name"] == "checkpoint:child:3" and r["status"] == "rejected" for r in snap["sources"])


def test_supplemental_reads_stop_at_request_budget_and_do_not_replace_core_trace():
    snap = snapshot()
    before = json.dumps(snap["records"], sort_keys=True)
    calls = []
    source = Sources({}, snap, lambda *_a: calls.append(1) or {})
    for _ in range(42):
        source.fetch("probe", "/read")
    assert len(calls) == 40
    assert source.receipts[-1]["status"] == "not_collected"
    assert json.dumps(snap["records"], sort_keys=True) == before
