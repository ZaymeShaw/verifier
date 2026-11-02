"""Verify evidence access and propagation without calling a model or business API."""
import json
import re
from types import SimpleNamespace

from tests.support.expectations import E

import pytest

from impl.projects.llm_probe.business_trace.dossier import build_axis_view, view_ids
from impl.projects.llm_probe.business_trace.tools import EvidenceIndex
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES  # noqa: F401  注册六轴 PROCESS_SPECS
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections
from impl.projects.llm_probe.judge import _main_judge_material


def record(ident, body, **metadata):
    return {"id": ident, "kind": "steps", "turn": "turn1", "scope": "current",
            "fields": {"output": {"status": "available", "value": body}}, **metadata}


def dossier():
    return {"records": [record("visible", "initial evidence"), record("hidden", "retained reason"),
                        record("large", "UNREAD SECRET " * 2000)],
            "contents": {}, "sources": [], "gaps": [], "coverage": [], "model_calls": [],
            "current": [], "history": [], "observed_at_collection": []}


AXIS = "knowledge_data"
RUNTIME = SimpleNamespace(spec=SimpleNamespace(project_id="llm_probe"), scenario_id="no-such-scenario",
                          trace_id="test", ensure_time_left=lambda *_: None)


def test_view_pointer_does_not_count_as_reading_the_referenced_message():
    data = dossier()
    data["records"][0]["output_message_ref"] = "hidden"
    data["records"][0]["parent_ref"] = "parent"
    view = build_axis_view(data, {"refs": ["visible", "large"]}, budget_chars=100_000)
    assert view_ids(view) == {"visible"}


def test_investigated_slices_reach_main_judge_without_unread_siblings():
    data = dossier()
    data["records"][2]["fields"]["small"] = {"status": "available", "value": "precise fact"}
    index = EvidenceIndex(data)
    index.read("large", "/fields/small/value")
    results = [{"type_id": "context_memory", "output": {
        "results": [{"verdict": "没达到", "refs": ["large"]}],
        "view": {"evidence_audit": {"reads": index.read_receipts}}}}]
    view = _main_judge_material(results, {"output": {"structure": {}}}, data)
    assert view["records"][0]["read_paths"] == {"/fields/small/value": "precise fact"}
    assert "evidence_audit" not in view["structure"]


def test_source_and_large_content_slices_reach_main_judge():
    data = dossier()
    data["sources"] = [{"id": "turn1", "request_and_response": {"answer": "delivered"},
                        "original_records": {"unused": "z" * 15000}}]
    data["contents"] = {"content#1": {"useful": "known fact", "unused": "z" * 15000}}
    index = EvidenceIndex(data)
    index.read("turn1", "/request_and_response")
    index.read("content#1", "/useful")
    view = _main_judge_material([{"type_id": "test", "output": {
        "results": [{"verdict": "没达到", "refs": ["turn1", "content#1"]}],
        "view": {"evidence_audit": {"reads": index.read_receipts}}}}], {"output": {}}, data)
    assert view["contents"]["turn1"]["read_paths"] == {"/request_and_response": {"answer": "delivered"}}
    assert view["contents"]["content#1"]["read_paths"] == {"/useful": "known fact"}


def test_captured_delivery_and_persisted_output_are_independent():
    from pathlib import Path
    from impl.projects.llm_probe.business_trace.dossier import build_dossier, record_body
    root = Path(__file__).resolve().parents[1]
    snap = json.loads((root / "report/business-trace-agno-20260913/snapshots/snap-cash-value.json").read_text())
    trace = SimpleNamespace(turn_records=[], normalized_request={}, extracted_output={"output_text": "ACTUAL DELIVERY"})
    data = build_dossier(trace, snap)
    actual = next(r for r in data["records"] if r["kind"] == "delivered_output")
    stored = next(r for r in data["records"] if r["kind"] == "final_output")
    assert record_body(data, actual)["fields"]["output"]["value"] == {"output_text": "ACTUAL DELIVERY"}
    assert record_body(data, stored)["fields"]["output"]["value"] == snap["records"]["run"]["content"]
    trace.extracted_output = {}
    data = build_dossier(trace, snap)
    assert not any(r["kind"] == "delivered_output" for r in data["records"])
    assert any(g["id"] == "turn1.delivered_output_missing" for g in data["gaps"])


def test_stale_analysis_packets_are_rejected(monkeypatch):
    data = dossier()
    with pytest.raises(ValueError, match="交付的环节材料"):
        common.run_process_axis(AXIS, {"expectations": E, "trace_analysis": {"dossier": data,
            "selections": {AXIS: {"materials": []}}}}, ScenarioAxis(AXIS, True, ""), RUNTIME, common.PROCESS_SPECS[AXIS])

