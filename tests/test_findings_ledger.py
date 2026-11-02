"""spec/mock/protocol.md 5.4：发现台账去重与分类。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from impl.core import findings_ledger
from impl.core.active_artifacts import _findings_ledger_payload


@pytest.fixture
def memory_ledger(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[Dict[str, Any]]]:
    store: Dict[str, List[Dict[str, Any]]] = {}
    monkeypatch.setattr(findings_ledger, "_read", lambda project_id: json.loads(json.dumps(store.get(project_id, []))))

    def write(project_id: str, records: List[Dict[str, Any]]) -> None:
        _findings_ledger_payload(None, None, records)  # type: ignore[arg-type]
        store[project_id] = json.loads(json.dumps(records))

    monkeypatch.setattr(findings_ledger, "_write", write)
    return store


def test_same_signature_is_not_a_new_finding(memory_ledger) -> None:
    first = findings_ledger.add(
        "policy_search",
        signature="amount_filter:not_fulfilled",
        session_id="s1",
        trigger_summary="只说“保额高的”不给数字",
        realism="high",
        harness_verdict="not_fulfilled",
        judge_verdict="not_fulfilled",
        run_id="r1",
    )
    assert first["new"] is True
    assert first["record"]["category"] == "live_defect"
    second = findings_ledger.add(
        "policy_search",
        signature="amount_filter:not_fulfilled",
        session_id="s2",
        trigger_summary="换个说法",
        realism="medium",
        harness_verdict="not_fulfilled",
        judge_verdict="not_fulfilled",
    )
    assert second["new"] is False
    assert second["record"]["duplicate_sessions"] == ["s2"]
    assert findings_ledger.query("policy_search")["total"] == 1
    assert findings_ledger.query("policy_search", session_id="s2")["total"] == 1


def test_disagreement_becomes_judge_calibration_and_fuzz_is_separate(memory_ledger) -> None:
    calibration = findings_ledger.add(
        "policy_search",
        signature="x:1",
        session_id="s1",
        trigger_summary="",
        realism="low",
        harness_verdict="fulfilled",
        judge_verdict="not_fulfilled",
    )
    assert calibration["record"]["category"] == "judge_calibration"
    fuzz = findings_ledger.add(
        "policy_search",
        signature="x:2",
        session_id="s1",
        trigger_summary="",
        realism="low",
        harness_verdict="not_fulfilled",
        judge_verdict="not_fulfilled",
        protocol_fuzz=True,
    )
    assert fuzz["record"]["category"] == "protocol_fuzz"
    by_category = findings_ledger.query("policy_search")["by_category"]
    assert by_category == {"judge_calibration": 1, "protocol_fuzz": 1}
    assert findings_ledger.query("policy_search", category="protocol_fuzz")["total"] == 1


def test_invalid_values_are_rejected(memory_ledger) -> None:
    with pytest.raises(ValueError):
        findings_ledger.add("policy_search", signature="", session_id="s", trigger_summary="", realism="high", harness_verdict="fulfilled")
    with pytest.raises(ValueError):
        findings_ledger.add("policy_search", signature="a", session_id="s", trigger_summary="", realism="very", harness_verdict="fulfilled")
    with pytest.raises(ValueError):
        findings_ledger.add("policy_search", signature="a", session_id="s", trigger_summary="", realism="high", harness_verdict="maybe")
