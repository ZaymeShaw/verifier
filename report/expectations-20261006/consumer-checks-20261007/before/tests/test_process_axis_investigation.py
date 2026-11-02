"""Verify evidence access and propagation without calling a model or business API."""
import json
from types import SimpleNamespace

from tests.support.expectations import E, PROJECTION

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
ABSENT = (common.ABSENT_OBLIGATION, f"{AXIS}:none")
RUNTIME = SimpleNamespace(spec=SimpleNamespace(project_id="llm_probe"), scenario_id="no-such-scenario",
                          trace_id="test", ensure_time_left=lambda *_: None, expectation_projection=PROJECTION)


def run(monkeypatch, answer, *, data=None, spec=None, axis_id=AXIS):
    data = data or dossier()
    holder = {}
    class Client:
        calls = 0
        def complete_json(self, system, user, **kwargs):
            self.calls += 1
            # A repair prompt appends its error after the original JSON.
            prompt, _ = json.JSONDecoder().raw_decode(user)
            holder["prompt"] = prompt
            return answer(None, self.calls, prompt)
        def usage(self):
            return {"llm_calls": self.calls}
    monkeypatch.setattr(common, "axis_llm", lambda *a, **kw: Client())
    outcome = common.run_process_axis(axis_id, {"expectations": E, "trace_analysis": {
        "dossier": data, "coverage": [], "selections": prepare_selections(data, {}, {axis_id: {"refs": ["visible"]}})}},
        ScenarioAxis(axis_id, True, ""), RUNTIME, spec or common.PROCESS_SPECS[axis_id])
    return outcome, holder


def result(refs, outcome="fail", missing=None, pairs=None):
    groups = {}
    for ob_id, link_id in pairs or [ABSENT]:
        groups.setdefault(ob_id, []).append(link_id)
    return {"reason": "observed transfer", "scope_note": "one transfer",
            "results": [{"obligation_id": ob_id, "link_ids": link_ids, "outcome": outcome,
                         'expectation_ids': [], 'matched_link_id': '', 'expectation_checks': [], "observed": "source and receiver differ",
                         "source_refs": [], "input_refs": refs, "output_refs": refs,
                         "missing": missing or [],
                         "problems": ([dict(problem_id=ob_id, phenomenon="source and receiver differ", expectation_ids=[],
                            observed="source and receiver differ", source_refs=["case"], input_refs=refs, output_refs=refs,
                            attribution_axes=[AXIS], impact="unknown")] if outcome == "fail" else [])} for ob_id, link_ids in groups.items()]}


def test_axis_receives_full_selected_body_without_retrieval(monkeypatch):
    data = dossier()
    data["records"][0]["fields"]["output"]["value"] = "full evidence " * 3000 + "TAIL FACT"
    def answer(index, attempt, prompt):
        assert index is None
        assert "catalog" not in prompt and "tool_budget" not in prompt
        assert "TAIL FACT" in json.dumps(prompt["dossier_view"])
        return result(["visible"])
    out, _ = run(monkeypatch, answer, data=data)
    assert out.output["assessment"]["verdict"] == "problematic"
    assert out.usage["tool_calls"] == 0
    assert out.output["view"]["evidence_audit"]["reads"][0]["id"] == "visible"


def test_unread_sibling_citation_is_rejected_as_evaluator_error(monkeypatch):
    data = dossier()
    data["records"].append(record("visible#reasoning", "unread model reasoning", kind="reasoning"))
    with pytest.raises(ValueError, match="未交付正文"):
        run(monkeypatch, lambda *_: result(["visible#reasoning"]), data=data)


def test_unprovided_body_citation_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="未交付正文"):
        run(monkeypatch, lambda *_: result(["visible", "large"]))


def test_format_retry_keeps_the_same_complete_material(monkeypatch):
    prompts = []
    def answer(index, attempt, prompt):
        prompts.append(prompt["dossier_view"])
        if attempt == 1:
            return result(["visible"], pairs=[("wrong", "x")])
        return result(["visible"])
    out, _ = run(monkeypatch, answer)
    assert len(prompts) == 2 and prompts[0] == prompts[1]
    assert out.output["view"]["unverified_refs"] == []
    assert out.usage["tool_calls"] == 0


def test_pass_may_state_scope_limits_without_being_downgraded(monkeypatch):
    out, _ = run(monkeypatch, lambda *_: result(["visible"], "pass", ["raw request redacted by platform"]))
    assert out.output["assessment"]["verdict"] == "sound"
    assert out.output["assessment"]["gaps"] == ["raw request redacted by platform"]


def test_confirmed_failure_survives_other_gaps(monkeypatch):
    out, _ = run(monkeypatch, lambda *_: result(["visible"], "fail", ["other transfer missing"]))
    assert out.output["assessment"]["verdict"] == "problematic"
    assert out.output["assessment"]["gaps"] == ["other transfer missing"]


def test_unselected_model_call_cannot_disappear_from_obligation_scope(monkeypatch):
    data = dossier()
    data["model_calls"] = [{"id": "unselected-call", "scope": "current", "input": {"status": "redacted"}}]
    def answer(index, attempt, prompt):
        # 限定前缀的义务管 context_memory:input；兜底的 arrives_intact 只管其余传递。
        assert prompt["pending"]["input_assembled"] == ["context_memory:input:unselected-call"]
        assert prompt["pending"]["history_and_state"] == ["context_memory:input:unselected-call"]
        assert "context_memory:input:unselected-call" not in prompt["pending"]["arrives_intact"]
        pairs = [(ob, link) for ob, links in prompt["pending"].items() for link in links]
        return result([], "insufficient_evidence", ["raw input missing"], pairs)
    out, _ = run(monkeypatch, answer, data=data, axis_id="context_memory")
    judged = {(r["obligation_id"], r["link_id"]): r for r in out.output["results"]}
    assert judged[("input_assembled", "context_memory:input:unselected-call")]["outcome"] == "insufficient_evidence"
    assert judged[("history_and_state", "context_memory:input:unselected-call")]["outcome"] == "insufficient_evidence"
    assert out.output["assessment"]["verdict"] == "not_evaluable"


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
        "results": [{"outcome": "fail", "source_refs": [], "evidence": {"input": ["large"], "output": []}}],
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
        "results": [{"outcome": "fail", "source_refs": [], "evidence": {"input": ["turn1"], "output": ["content#1"]}}],
        "view": {"evidence_audit": {"reads": index.read_receipts}}}}], {"output": {}}, data)
    assert view["contents"]["turn1"]["read_paths"] == {"/request_and_response": {"answer": "delivered"}}
    assert view["contents"]["content#1"]["read_paths"] == {"/useful": "known fact"}


@pytest.mark.parametrize("outcome", ["pass", "not_applicable"])
def test_empty_scope_cannot_claim_sound_or_unexercised(monkeypatch, outcome):
    def answer(*_):
        value = result(["visible"], outcome)
        value["scope_note"] = " "
        return value
    with pytest.raises(ValueError, match="scope_note"):
        run(monkeypatch, answer)


def test_not_applicable_requires_evidence_of_absence(monkeypatch):
    with pytest.raises(ValueError, match="引用"):
        run(monkeypatch, lambda *_: result([], "not_applicable"))


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


def test_unprovided_citation_cannot_support_pass(monkeypatch):
    with pytest.raises(ValueError, match="未交付正文"):
        run(monkeypatch, lambda *_: result(["hidden"], "pass"))
