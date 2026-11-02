"""Provider protocol tests, not synthetic business-quality evaluations."""
from __future__ import annotations

import copy
import json

import pytest

from impl.projects.llm_probe.business_trace import open_reader
from impl.projects.llm_probe.business_trace.providers import agno


def snapshot():
    return {
        "provider": "agno", "status": "succeeded", "association": {"run_id": "w1"},
        "records": {
            "run": {"run_id": "w1", "run_input": "question", "step_executor_runs": [
                {"run_id": "a1", "parent_run_id": "w1", "messages": [
                    {"role": "user", "content": "question"},
                    {"role": "tool", "tool_call_id": "c1", "content": "result"},
                ], "tools": [{"tool_call_id": "c1", "tool_name": "lookup", "tool_args": {"n": 0},
                              "tool_call_error": False, "result": "value"}],
                 "session_state": {"a/b": {"~": "fact"}, "api_key": "hidden-key"}},
                {"run_id": "a2", "tools": [{"tool_call_id": "c1", "tool_name": "lookup", "result": "another"}]},
            ]},
            "traces": [{"trace_id": "t1", "run_id": "w1", "tree": [
                {"id": "llm1", "type": "LLM", "name": "model.invoke", "input": "__REDACTED__",
                 "output": "__REDACTED__", "metadata": {"model": "example", "input_tokens": 10}},
                {"id": "tool-span", "type": "TOOL", "name": "lookup", "output": "__REDACTED__",
                 "metadata": {"parameters": '{"n":0}'}},
                {"id": "llm2", "type": "LLM", "input": "visible input", "output": "visible output"},
            ]}],
        },
    }


def overview_status(reader):
    return reader.overview()["limitations"]["exact_model_request"]["status"]


def test_index_distinguishes_hidden_missing_empty_false_and_unverified():
    reader = open_reader(snapshot())
    calls = reader.list_records("model_calls")["items"]
    assert calls[0]["fields"]["input"]["status"] == "redacted"
    assert calls[0]["fields"]["output_tokens"]["status"] == "missing"
    assert calls[1]["fields"]["input"]["status"] == "available"
    assert [c["fields"]["exact_request"]["status"] for c in calls] == ["unverified", "available"]
    assert overview_status(reader) == "unverified"  # one hidden call keeps the gap open
    tool = reader.list_records("tool_calls", run_id="a1")["items"][0]
    assert tool["fields"]["error"]["status"] == "available"
    assert reader.read(tool["fields"]["error"]["ref"])["text"] == "false"
    overview = reader.overview()
    assert overview["categories"]["model_calls"]["field_status_counts"]["input"] == {"redacted": 1, "available": 1}
    assert overview["limitations"]["raw_backend_http"]["status"] == "unsupported"


def test_step_executor_run_status_carries_agno_streaming_cancel_semantics():
    data = snapshot()
    executor, plain = data["records"]["run"]["step_executor_runs"]
    executor.update(status="CANCELLED", workflow_step_id="step-1")
    plain["status"] = "COMPLETED"
    runs = {r["run_id"]: r for r in open_reader(data).list_records("runs")["items"]}
    assert "CANCELLED 不表示被取消" in runs["a1"]["fields"]["status"]["note"]
    assert "note" not in runs["a2"]["fields"]["status"]  # 非 Workflow 步骤执行器不附注


def test_duplicate_tool_ids_in_different_runs_are_not_merged_or_inferred_from_spans():
    reader = open_reader(snapshot())
    a = reader.list_records("tool_calls", run_id="a1")["items"]
    b = reader.list_records("tool_calls", run_id="a2")["items"]
    assert len(a) == len(b) == 1
    assert a[0]["id"] == b[0]["id"] == "c1"
    assert a[0]["ref"] != b[0]["ref"]
    span = reader.list_records("tool_calls", run_id="w1")["items"][0]
    assert span["representation"] == "span"
    assert span["fields"]["arguments"]["status"] == "available"
    assert span["fields"]["result"]["status"] == "redacted"


def test_reader_escapes_pointers_is_frozen_and_never_exposes_secret_subpaths():
    source = snapshot()
    original = copy.deepcopy(source)
    reader = open_reader(source)
    state = reader.list_records("states")["items"][0]
    ref = state["fields"]["a/b"]["ref"]
    assert ref.endswith("/a~1b")
    assert reader.read(ref + "/~0")["text"] == "fact"
    secret = reader.read(state["fields"]["api_key"]["ref"])
    assert secret["status"] == "redacted" and "hidden-key" not in secret["text"]
    source["records"]["run"]["run_input"] = "later mutation"
    assert reader.read("/records/run/run_input")["text"] == "question"
    assert original["records"]["run"]["step_executor_runs"][0]["session_state"]["api_key"] == "hidden-key"
    assert reader.read("/records/run/not_present")["status"] == "missing"
    for bad in ["/association", "http://external/trace", "/records/run/~2", "/records/../secret"]:
        if bad.endswith("../secret"):
            assert reader.read(bad)["status"] == "missing"
        else:
            with pytest.raises(ValueError):
                reader.read(bad)


def test_directory_pages_do_not_drop_records_and_listing_does_not_claim_body_read():
    source = snapshot()
    source["records"]["run"]["messages"] = [{"role": "user", "content": str(i)} for i in range(83)]
    reader = open_reader(source)
    first = reader.list_records("messages", run_id="w1", limit=50)
    assert first["total"] == 83 and first["next_offset"] == 50
    last = reader.list_records("messages", run_id="w1", offset=50, limit=50)
    assert len(last["items"]) == 33 and last["next_offset"] is None
    ref = last["items"][-1]["fields"]["content"]["ref"]
    assert reader.read(ref)["text"] == "82"




def test_sqlite_copy_of_the_same_run_is_linked_and_interchangeable_as_evidence():
    source = snapshot()
    source["records"]["raw_runs"] = [{"run_id": "w1", "run_data": copy.deepcopy(source["records"]["run"])}]
    reader = open_reader(source)
    canonical = "/records/run/step_executor_runs/0/messages/1"
    mirror = "/records/raw_runs/0/run_data/step_executor_runs/0/messages/1"
    entries = {e["ref"]: e for e in reader.entries if e["kind"] == "messages"}
    assert "copy_of" not in entries[canonical] and entries[mirror]["copy_of"] == canonical
    assert reader.overview()["categories"]["messages"]["copy_count"] == 2
    assert reader.read(canonical)["text"] == reader.read(mirror)["text"]


def test_history_excludes_other_users_future_overlapping_and_unordered_runs():
    runs = [
        {"run_id": "old", "user_id": "u", "created_at": 10, "status": "COMPLETED", "metrics": {"duration": 2}},
        {"run_id": "other", "user_id": "v", "created_at": 10, "status": "COMPLETED", "metrics": {"duration": 1}},
        {"run_id": "future", "user_id": "u", "created_at": 30, "status": "COMPLETED", "metrics": {"duration": 1}},
        {"run_id": "overlap", "user_id": "u", "created_at": 19, "status": "COMPLETED", "metrics": {"duration": 10}},
        {"run_id": "unknown", "user_id": "u", "created_at": 12},
    ]
    history, coverage = agno._history(runs, {"run_id": "now", "created_at": 20}, "u")
    assert [r["run_id"] for r in history] == ["old"]
    assert coverage["status"] == "partial" and coverage["excluded_unordered_runs"] == 2


def test_history_orders_back_to_back_turns_by_trace_timestamps():
    # created_at is second-precision: prior turn 44s + 17.86s duration cannot be proven
    # to end before a turn created at 02s, unless the root traces settle it.
    prior = {"run_id": "prev", "user_id": "u", "created_at": "2026-09-15T01:15:44Z", "status": "COMPLETED", "metrics": {"duration": 17.86}}
    now = {"run_id": "now", "user_id": "u", "created_at": "2026-09-15T01:16:02Z"}
    history, coverage = agno._history([prior, now], now, "u")
    assert history == [] and coverage["excluded_unordered_runs"] == 1
    windows = {"prev": (1.0, 18.6), "now": (18.65, 44.0)}
    history, coverage = agno._history([prior, now], now, "u", windows)
    assert [r["run_id"] for r in history] == ["prev"] and history[0]["ordering"] == "trace_timestamps"
    assert coverage["status"] == "available" and coverage["ordered_by_trace_timestamps"] == 1
    overlapping = {"prev": (1.0, 18.7), "now": (18.65, 44.0)}
    history, coverage = agno._history([prior, now], now, "u", overlapping)
    assert history == [] and coverage["excluded_unordered_runs"] == 1




def test_trace_pagination_reads_later_pages_and_reports_partial_fetch(monkeypatch):
    page1 = {"data": [{"trace_id": "t1"}], "meta": {"total_pages": 3, "total_count": 3}}
    pages = []
    def get(config, path, query):
        pages.append(query["page"])
        if query["page"] == 3:
            raise TimeoutError("unavailable")
        return {"data": [{"trace_id": "t2"}]}
    monkeypatch.setattr(agno, "_get_json", get)
    records, errors = agno._trace_pages({}, "r1", page1)
    assert [r["trace_id"] for r in records] == ["t1", "t2"]
    assert pages == [2, 3]
    assert any(e.startswith("trace_page_failed:3:") for e in errors)
    assert "trace_list_incomplete:2/3" in errors


@pytest.mark.parametrize("detail_fails", [False, True])
def test_collection_freezes_all_pages_and_does_not_substitute_summary_for_failed_detail(monkeypatch, detail_fails):
    config = agno.describe()["default_config"]
    config["poll_attempts"] = 1
    response = {"trace_id": "business-1", "answer": "done"}
    current = {"run_id": "w1", "user_id": "u1", "created_at": 20, "content": json.dumps(response)}
    prior = {"run_id": "old", "user_id": "u1", "created_at": 10, "status": "COMPLETED",
             "metrics": {"duration": 2}, "content": "prior answer"}
    def get(_config, path, query=None):
        if path == "/sessions/s1/runs":
            return [current, prior]
        if path == "/sessions/s1/runs/w1":
            if detail_fails:
                raise TimeoutError("detail not available")
            return current
        if path == "/traces":
            page = query.get("page", 1)
            return {"data": [{"trace_id": f"t{page}", "run_id": "w1"}],
                    "meta": {"total_pages": 2, "total_count": 2}}
        if path.startswith("/traces/t"):
            return {"trace_id": path.rsplit("/", 1)[1], "run_id": "w1", "tree": [
                {"id": "span", "type": "LLM", "input": "__REDACTED__"},
            ]}
        raise AssertionError(path)
    monkeypatch.setattr(agno, "_get_json", get)
    result = agno.collect(config, request={"body": {"session_id": "s1", "user_id": "u1"}}, response=response)
    assert len(result["records"]["traces"]) == 2
    assert result["coverage"]["categories"]["model_calls"]["count"] == 2
    if detail_fails:
        assert result["status"] == "partial"
        assert "run" not in result["records"]
        assert result["history_coverage"]["status"] == "not_collected"
        assert any(e.startswith("run_detail_failed:") for e in result["errors"])
    else:
        assert result["status"] == "succeeded"
        assert [r["run_id"] for r in result["records"]["history_runs"]] == ["old"]
        records = open_reader(result).list_records("runs", run_id="old")["items"]
        assert records[0]["scope"] == "history"


