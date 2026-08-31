import copy
import hashlib
import importlib.util
import json

import pytest
from pathlib import Path

from impl.projects.client_search.draft.simulate_field_key_index import build_report

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / ".agents/skills/draft/scripts/validate_key_index_experiment.py"
REPORT_PATH = ROOT / "impl/projects/client_search/investigation/judge/experiments/field-key-index-simulation.json"


def _payload_sha256(payload) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_gate():
    spec = importlib.util.spec_from_file_location("validate_key_index_experiment", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _checked_report():
    return json.loads(REPORT_PATH.read_text())


def _build_or_skip():
    try:
        return build_report()
    except Exception as exc:
        message = str(exc)
        if "business://" in message and "PATH_NOT_FOUND" in message:
            pytest.skip("client_search business source checkout is unavailable")
        if "embedding cache input/projection drifted" in message:
            pytest.skip(message)
        raise


def _candidates(report):
    return {item["candidate_id"]: item for item in report["candidates"]}


def test_field_key_index_simulation_is_deterministic_with_frozen_splits():
    first = _build_or_skip()
    second = _build_or_skip()
    assert _payload_sha256(first) == _payload_sha256(second)
    assert first["schema_version"] == 2
    assert first["probe_sets"]["development"]["count"] == 30
    assert first["probe_sets"]["holdout"]["count"] == 8
    assert first["probe_sets"]["development"]["sha256"]
    assert first["probe_sets"]["holdout"]["sha256"]
    assert first["probe_sets"]["holdout"]["used_for_tuning"] is False
    assert first["all_entry_target_resolution_rate"] == 1.0
    assert first["decision"]["status"] == "unresolved"
    assert first["decision"]["shortlist"] == []
    assert "No candidate passes" in first["decision"]["reason"]


def test_candidates_declare_real_channels_and_search_hits_report_matches():
    report = _checked_report()
    candidates = _candidates(report)
    assert candidates["source-exact"]["retrieval_channels"] == ["exact"]
    assert candidates["source-phrase-idf-min2-bigram"]["retrieval_channels"] == ["lexical"]
    assert candidates["source-exact-plus-lexical"]["retrieval_channels"] == ["exact", "lexical"]
    for candidate in candidates.values():
        declared = set(candidate["retrieval_channels"])
        assert set(candidate["default_retrieval_channels"]) <= declared
        for split in ("development", "holdout"):
            for row in candidate["results"][split]["rows"]:
                for hit in row["hits"]:
                    assert hit["matched_channels"]
                    assert set(hit["matched_channels"]) <= declared


def test_simulation_records_unresolved_when_holdout_blocks_all_candidates():
    report = _checked_report()
    candidates = _candidates(report)
    embedded = candidates["source-exact-lexical-embedding-t45"]
    assert embedded["results"]["development"]["metrics"]["top8_recall_rate"] >= report["thresholds"]["top8_recall_rate_min"]
    assert embedded["results"]["holdout"]["metrics"]["top8_recall_rate"] < report["thresholds"]["top8_recall_rate_min"]
    assert embedded["results"]["holdout"]["metrics"]["irrelevant_rejection_rate"] < report["thresholds"]["irrelevant_rejection_rate_min"]
    assert report["decision"]["status"] == "unresolved"
    assert report["decision"]["shortlist"] == []


def test_three_phase_gate_stops_provisional_candidate_before_selection():
    gate = _load_gate()
    report = _checked_report()
    assert gate.validate(report, phase="investigate") == []
    assert gate.validate(report, phase="simulation") == []
    errors = gate.validate(report, phase="selection")
    assert "selection gate requires decision.status=selected" in errors
    assert "selected candidate requires loop_evidence" in errors
    assert gate.validate(report, require_selected=True) == errors


def test_real_embedding_is_audited_and_rerank_remains_optional():
    gate = _load_gate()
    report = _checked_report()
    assert report["channel_consideration"]["embedding"]["decision"] == "experiment"
    assert report["channel_consideration"]["rerank"]["decision"] == "deferred"
    embedding_candidates = [candidate for candidate in report["candidates"] if "embedding" in candidate["retrieval_channels"]]
    assert embedding_candidates
    for candidate in embedding_candidates:
        audit = candidate["embedding_audit"]
        assert audit["provider"] == "bailian"
        assert audit["model"]
        assert audit["model_version"]
        assert audit["projection_version"]
        assert audit["dimensions"] > 0
    assert gate.validate(report, phase="simulation") == []


def test_gate_rejects_fake_embedding_and_unknown_matched_channel():
    gate = _load_gate()
    report = _checked_report()
    candidate = report["candidates"][0]
    candidate["retrieval_channels"].append("embedding")
    candidate["default_retrieval_channels"].append("embedding")
    report["channel_consideration"]["embedding"]["decision"] = "experiment"
    row_with_hit = next(row for row in candidate["results"]["development"]["rows"] if row["hits"])
    row_with_hit["hits"][0]["matched_channels"] = ["lexical", "imaginary"]
    errors = gate.validate(report, phase="simulation")
    assert any("embedding_audit.model is required" in error for error in errors)
    assert any("undeclared channels ['imaginary']" in error for error in errors)


def test_gate_rejects_tuned_holdout_leakage_and_incomplete_suite():
    gate = _load_gate()
    report = _checked_report()
    report["probe_sets"]["holdout"]["used_for_tuning"] = True
    candidate = report["candidates"][1]
    candidate["forbidden_inputs"] = ["expected_trace"]
    candidate["suite"].pop("resolver")
    errors = gate.validate(report, phase="simulation")
    assert "probe_sets.holdout.used_for_tuning must be false" in errors
    assert any("forbidden_inputs" in error for error in errors)
    assert any("suite.resolver" in error for error in errors)


def test_investigation_gate_accepts_evidenced_alternative_exclusion():
    gate = _load_gate()
    report = _checked_report()
    report["candidates"] = report["candidates"][:1]
    report["alternative_exclusions"] = [{"alternative": "embedding", "reason": "No audited model/version contract exists yet."}]
    assert gate.validate(report, phase="investigate") == []


def test_selection_gate_requires_objective_cost_and_audit_evidence():
    gate = _load_gate()
    report = _checked_report()
    selected = "source-linked-coverage-lexical"
    report["thresholds"].update({
        "top8_recall_rate_min": 0.0,
        "irrelevant_rejection_rate_min": 0.0,
        "search_to_load_resolution_rate_min": 0.0,
        "average_loaded_entries_max": 100,
    })
    report["decision"].update({
        "status": "selected",
        "shortlist": [selected],
        "selected_candidate": selected,
        "loop_evidence": {
            "loop_id": "loop-1", "iteration": 1, "report_path": "reports/loop-1.json",
            "business_no_regression": True, "objective_improved": True,
            "full_collection_fallback_observed": False,
            "draft_prompt_tokens": 100, "draft_latency_seconds": 0.5,
            "search_load_authority_audit": {"passed": True},
        },
    })
    assert gate.validate(report, phase="selection") == []
    broken = copy.deepcopy(report)
    broken["decision"]["loop_evidence"].pop("objective_improved")
    broken["decision"]["loop_evidence"]["search_load_authority_audit"] = {"passed": False}
    errors = gate.validate(broken, phase="selection")
    assert "loop_evidence.objective_improved must be true" in errors
    assert "loop_evidence.search_load_authority_audit.passed must be true" in errors


def test_checked_in_simulation_report_matches_deterministic_builder():
    built = _build_or_skip()
    checked = json.loads(REPORT_PATH.read_text())
    assert _payload_sha256(checked) == _payload_sha256(built), (
        "checked-in field-key-index-simulation.json drifted; "
        "rerun simulate_field_key_index.py and rewrite the experiment report"
    )
