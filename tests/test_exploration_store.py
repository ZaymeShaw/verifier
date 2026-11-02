"""探索批次仓库（spec/mock/protocol.md 5.1：方向输入与探索报告）。"""
from __future__ import annotations

import json

import pytest

from impl.core import exploration_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "explorations.json"
    monkeypatch.setattr(exploration_store, "explorations_path", lambda project_id: path)
    monkeypatch.setattr(exploration_store, "_write", lambda project_id, records: path.write_text(json.dumps(records)))
    return path


def test_direction_saved_then_report_attached(store):
    record = exploration_store.save_direction("policy_search", "run-1", {
        "coverage_targets": ["clarification_reply"],
        "focus": "边界值",
        "strategy_hints": ["boundary", "drift"],
        "budget": {"sessions": 4},
    })
    assert record["report"] is None
    assert record["direction"]["strategy_hints"] == ["boundary", "drift"]

    report = exploration_store.save_report("policy_search", "run-1", {
        "sessions": 4,
        "findings": {"total": 1, "by_category": {"live_defect": 1}, "records": []},
        "coverage": {"clarification_reply": 4},
        "budget_usage": {"sessions": 4},
        "notes": "ok",
    })
    assert report["report"]["run_id"] == "run-1"
    assert exploration_store.get("policy_search", "run-1")["report"]["sessions"] == 4
    assert [item["run_id"] for item in exploration_store.list_runs("policy_search")] == ["run-1"]


def test_direction_rejects_unknown_strategy_and_locked_after_report(store):
    with pytest.raises(ValueError):
        exploration_store.save_direction("policy_search", "run-2", {"strategy_hints": ["random"]})
    exploration_store.save_direction("policy_search", "run-2", {})
    exploration_store.save_report("policy_search", "run-2", {"sessions": 0})
    with pytest.raises(ValueError):
        exploration_store.save_direction("policy_search", "run-2", {"focus": "late change"})


def test_report_requires_known_run(store):
    with pytest.raises(KeyError):
        exploration_store.save_report("policy_search", "missing", {"sessions": 1})
