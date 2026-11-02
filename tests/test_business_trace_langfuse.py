from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from impl.projects.llm_probe.business_trace import collect, open_reader, validate_business_trace
from impl.projects.llm_probe.business_trace.providers import langfuse
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from impl.projects.llm_probe.business_trace.links import build_links, link_ends
from impl.projects.llm_probe.business_trace.materials import material_view


def config(**overrides):
    return {**langfuse.describe()["default_config"], "quiet_seconds": 0,
            "poll_timeout_seconds": .1, "poll_interval_seconds": .01, **overrides}


def trace(ident="t", **kwargs):
    return {"id": ident, "metadata": {"business_trace_id": "B"},
            "timestamp": "2026-10-15T10:00:00Z", "input": "question", "output": "answer", **kwargs}


def observation(ident="m", typ="GENERATION", **kwargs):
    return {"id": ident, "traceId": "t", "type": typ, "name": ident,
            "input": [{"role": "user", "content": "question"}], "output": "answer",
            "startTime": "2026-10-15T10:00:00Z", "endTime": "2026-10-15T10:00:01Z", **kwargs}


def install_api(monkeypatch, *, observations=None, matched=None, detail=None):
    rows = observations if observations is not None else [observation()]
    calls = []
    def get(cfg, path, query=None):
        calls.append((path, query))
        if path == "/traces":
            return {"data": matched if matched is not None else [trace()], "meta": {"totalPages": 1}}
        if path == "/traces/t":
            return detail or trace()
        if path == "/observations":
            return {"data": rows, "meta": {"totalPages": 1}}
        if path.startswith("/observations/"):
            return next(r for r in rows if r["id"] == path.rsplit("/", 1)[-1])
        raise AssertionError(path)
    monkeypatch.setattr(langfuse, "_get_json", get)
    return calls


def run(cfg=None):
    return collect({"provider": "langfuse", "config": cfg or config()}, request={}, response={"trace_id": "B"})


def test_metadata_correlation_and_complete_frozen_read(monkeypatch):
    calls = install_api(monkeypatch)
    snap = run()
    assert snap["status"] == "succeeded"
    assert snap["association"]["trace_id"] == "t"
    filters = json.loads(next(q["filter"] for p, q in calls if p == "/traces"))
    assert filters == [{"type": "stringObject", "column": "metadata", "key": "business_trace_id", "operator": "=", "value": "B"}]
    monkeypatch.setattr(langfuse, "_get_json", lambda *args: pytest.fail("reader accessed network"))
    reader = open_reader(snap)
    assert reader.value(reader.entries[0], "input") == "question"
    assert reader.overview()["categories"]["model_calls"]["count"] == 1
    assert reader.limitations["exact_model_request"]["status"] == "unverified"
    assert "secret_key" not in json.dumps(snap)


@pytest.mark.parametrize("matches", [[], [trace("one"), trace("two")]])
def test_missing_or_ambiguous_association_never_guesses(monkeypatch, matches):
    install_api(monkeypatch, matched=matches)
    snap = run()
    assert snap["status"] == "failed" and snap["records"] == {}


def test_missing_binding_makes_no_request(monkeypatch):
    monkeypatch.setattr(langfuse, "_get_json", lambda *args: pytest.fail("missing ID must not query"))
    snap = langfuse.collect(config(), request={}, response={})
    assert snap["status"] == "failed"


def test_direct_id_is_checked(monkeypatch):
    calls = install_api(monkeypatch)
    snap = langfuse.collect(config(match_field="id"), request={}, response={"trace_id": "t"})
    assert snap["status"] == "succeeded"
    assert not any(p == "/traces" for p, _ in calls)


def test_detail_mismatch_is_not_accepted(monkeypatch):
    install_api(monkeypatch, detail=trace(metadata={"business_trace_id": "wrong"}))
    assert run()["status"] == "failed"


def test_unfinished_and_page_limit_are_partial(monkeypatch):
    install_api(monkeypatch, observations=[observation(endTime=None)])
    snap = run()
    assert snap["status"] == "partial"
    assert any("unfinished_observations" in e for e in snap["errors"])
    assert snap["records"]["observations"]
    monkeypatch.setattr(langfuse, "_get_json", lambda *args: {"data": [observation()], "meta": {"totalPages": 2}})
    rows, errors, _ = langfuse._pages(config(max_pages=1), "/observations", {})
    assert len(rows) == 1 and any("page_limit" in e for e in errors)


def test_detail_error_keeps_list_data(monkeypatch):
    install_api(monkeypatch)
    get = langfuse._get_json
    def failure(cfg, path, query=None):
        if path == "/observations/m":
            raise HTTPError("private", 500, "private body", {}, None)
        return get(cfg, path, query)
    monkeypatch.setattr(langfuse, "_get_json", failure)
    snap = run()
    assert snap["status"] == "partial"
    assert snap["records"]["observations"][0]["input"]
    assert "private" not in json.dumps(snap["errors"])


def test_same_count_updates_must_settle(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(langfuse.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(langfuse.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    install_api(monkeypatch)
    get = langfuse._get_json
    reads = []
    def updated(cfg, path, query=None):
        result = copy.deepcopy(get(cfg, path, query))
        if path == "/observations/m":
            result["output"] = "old" if clock[0] < .03 else "new"
            reads.append(clock[0])
        return result
    monkeypatch.setattr(langfuse, "_get_json", updated)
    snap = run(config(quiet_seconds=.04, poll_timeout_seconds=.2))
    assert snap["status"] == "succeeded"
    assert snap["records"]["observations"][0]["output"] == "new"
    assert clock[0] >= .07


def test_history_excludes_future_wrong_session_and_ambiguous_timestamp(monkeypatch):
    rows = [trace("old", sessionId="s", timestamp="2026-10-15T09:00:00Z"),
            trace("future", sessionId="s", timestamp="2026-10-15T11:00:00Z"),
            trace("other", sessionId="else", timestamp="2026-10-15T09:00:00Z"),
            trace("unknown", sessionId="s", timestamp=None)]
    def api(cfg, path, query=None):
        return {"data": rows, "meta": {"totalPages": 1}} if path == "/traces" else rows[0]
    monkeypatch.setattr(langfuse, "_get_json", api)
    history, coverage = langfuse._history(config(), trace(sessionId="s"))
    assert [r["id"] for r in history] == ["old"]
    assert coverage["status"] == "partial"


@pytest.mark.parametrize("changes", [{"secret_key": "plaintext"}, {"poll_timeout_seconds": float("nan")},
    {"max_pages": 1.5}, {"page_size": True}, {"base_url": "https://name:secret@example.com"},
    {"match_field": "latest"}, {"quiet_seconds": 100}])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        validate_business_trace({"provider": "langfuse", "config": config(**changes)})


def test_langfuse_records_flow_through_dossier_links_materials_without_false_exactness():
    snap = {"provider": "langfuse", "status": "succeeded", "records": {"trace": trace(), "observations": [
        observation("agent", "AGENT", input="task"),
        observation(parentObservationId="agent"),
        observation("tool", "TOOL", input={"query": "q"}, output="result", parentObservationId="agent"),
        observation("next", "CHAIN", input="another task"),
    ]}}
    dossier = build_dossier(SimpleNamespace(), snap)
    links = build_links(dossier)
    model = next(l for l in links["links"] if l["link_type"] == "model_capability")
    assert model["facts"]["input_source"] == "recorded_input"
    assert model["input"][0]["field"] == "input"
    assert "Langfuse" in links["limits"]
    assert not any(l["link_id"].startswith("context_memory:step:") for l in links["links"])
    material = material_view(dossier, links["links"], [])
    assert material
    assert set(ref for l in links["links"] for ref in link_ends(l)) <= set(dossier["evidence_ids"])
    assert {l["link_type"] for l in links["links"]} == {
        "intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability", "context_memory"}


def test_redaction_truncation_and_unknown_types_are_visible_and_raw_content_is_kept():
    snap = {"provider": "langfuse", "status": "partial", "content_char_limit": 10,
            "records": {"trace": trace(output="[REDACTED]"), "observations": [
                observation(input="1234567890", output={"value": "name [REDACTED]"}),
                observation("new", "FUTURE_TYPE", parentObservationId="missing")]}}
    original = copy.deepcopy(snap)
    reader = open_reader(snap)
    model = next(e for e in reader.entries if e["kind"] == "model_calls")
    assert model["fields"]["input"]["status"] == "truncated"
    assert model["fields"]["output"]["status"] == "redacted"
    assert reader.value(model, "input") == "1234567890"
    assert reader.final_output_ref() is None
    assert reader.limitations["hierarchy"]["status"] == "partial"
    assert reader.limitations["unknown_observation_types"]["status"] == "partial"
    assert snap == original


def test_explicit_openinference_types_are_mapped_without_guessing_from_names():
    snap = {"provider": "langfuse", "status": "succeeded", "records": {"trace": trace(), "observations": [
        observation("owner", "SPAN", metadata={"attributes": {"openinference.span.kind": "AGENT"}}),
        observation("tool", "SPAN", parentObservationId="owner", input="[INCOMPLETE]",
                    metadata={"attributes": {"openinference.span.kind": "TOOL"}}),
        observation("tool-named-but-unknown", "SPAN", name="tool.call"),
    ]}}
    reader = open_reader(snap)
    tools = [e for e in reader.entries if e["kind"] == "tool_calls"]
    assert len(tools) == 1 and tools[0]["id"] == "tool"
    assert tools[0]["run_id"] == "owner"
    assert tools[0]["fields"]["arguments"]["status"] == "truncated"


def test_inflated_total_items_after_all_pages_is_a_note_not_an_incomplete_listing(monkeypatch):
    pages = {1: {"data": [observation()], "meta": {"totalPages": 3, "totalItems": 3}},
             2: {"data": [], "meta": {"totalPages": 3, "totalItems": 3}},
             3: {"data": [], "meta": {"totalPages": 3, "totalItems": 3}}}
    monkeypatch.setattr(langfuse, "_get_json", lambda cfg, path, query=None: pages[query["page"]])
    rows, errors, notes = langfuse._pages(config(), "/traces", {})
    assert len(rows) == 1 and errors == []
    assert notes == ["/traces: total_items_reported=3 returned=1"]


def test_page_read_failure_is_still_an_incomplete_listing(monkeypatch):
    def fail_second(cfg, path, query=None):
        if query["page"] == 2:
            raise RuntimeError("boom")
        return {"data": [observation()], "meta": {"totalPages": 2, "totalItems": 2}}
    monkeypatch.setattr(langfuse, "_get_json", fail_second)
    rows, errors, notes = langfuse._pages(config(), "/traces", {})
    assert len(rows) == 1 and errors and errors[0].startswith("/traces: ") and notes == []


def test_overflow_timestamp_is_partial_and_never_used_for_history(monkeypatch):
    calls = install_api(monkeypatch, detail=trace(timestamp="9999-12-31T23:59:59Z", sessionId="s"),
                        observations=[observation(startTime="9999-12-31T23:59:59Z")])
    snap = run()
    assert snap["status"] == "partial"
    assert any(e.startswith("invalid_timestamps:") for e in snap["errors"])
    assert snap["history_coverage"]["status"] == "not_collected"
    assert open_reader(snap).timeline()["total"] == 0
    assert not any(q and "sessionId" in q for _, q in calls)


@pytest.mark.parametrize("metadata", ["text", [], {"attributes": {"openinference.span.kind": []}}])
def test_arbitrary_json_metadata_does_not_crash_reader(metadata):
    reader = open_reader({"provider": "langfuse", "status": "succeeded", "records": {
        "trace": trace(), "observations": [observation(typ="SPAN", metadata=metadata)]}})
    assert reader.overview()["categories"]["steps"]["count"] == 1


def test_content_gaps_are_structured_per_step_and_turn_qualified_in_dossier():
    snap = {"provider": "langfuse", "status": "succeeded", "content_char_limit": 10, "records": {"trace": trace(), "observations": [
        observation("rpc", "SPAN", input=None, output=None,
                    metadata={"attributes": {"request.bytes": "306", "http.response.status_code": "200", "langfuse.environment": "dev"}}),
        observation("llm", input="1234567890", output={"value": "name [REDACTED]"}),
        observation("tool", "TOOL", input={"query": "q"}, output="ok"),
    ]}}
    items = open_reader(snap).limitations["content"]["items"]
    assert items == [
        {"ref": "/records/observations/0", "name": "rpc", "field": ["input", "output"], "kind": "not_recorded",
         "why": "这一步只记了结构，没有记录输入输出内容", "recorded_attributes": ["http.response.status_code", "request.bytes"]},
        {"ref": "/records/observations/1", "name": "llm", "field": ["input"], "kind": "truncated",
         "why": "长度达到业务配置的上限，按可能被截断处理，后半段可能缺失"},
        {"ref": "/records/observations/1", "name": "llm", "field": ["output"], "kind": "redacted",
         "why": "内容含脱敏标记，被替换的值看不到"},
    ]
    gap = next(g for g in build_dossier(SimpleNamespace(), snap)["gaps"] if g["id"].endswith(".gap.content"))
    assert [item["ref"] for item in gap["items"]] == [
        "turn1/records/observations/0", "turn1/records/observations/1", "turn1/records/observations/1"]


def test_no_content_gap_items_when_everything_is_recorded():
    snap = {"provider": "langfuse", "status": "succeeded", "records": {"trace": trace(), "observations": [observation()]}}
    content = open_reader(snap).limitations["content"]
    assert content == {**content, "status": "unverified", "items": []}


def test_collect_succeeds_when_trace_listing_reports_inflated_total(monkeypatch):
    install_api(monkeypatch)
    original = langfuse._get_json

    def inflated(cfg, path, query=None):
        data = original(cfg, path, query)
        if path == "/traces" and isinstance(data, dict) and "meta" in data:
            data = dict(data, meta={"totalPages": 1, "totalItems": 3})
        return data
    monkeypatch.setattr(langfuse, "_get_json", inflated)
    snap = run()
    assert snap["status"] == "succeeded", snap["errors"]
    assert snap["association"]["matched_trace_count"] == 1
    assert snap["association"]["listing_notes"] == ["/traces: total_items_reported=3 returned=1"]
