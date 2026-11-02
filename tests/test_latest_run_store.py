import sqlite3

import pytest

from impl.core import run_store
from impl.core.run_store import LatestRunStore, WorkspaceBusy


@pytest.fixture
def store(tmp_path):
    return LatestRunStore(tmp_path / "latest.sqlite3")


def case(name="a", text="request"):
    return {"id": name, "project_id": "p", "scenario": "s", "intent": None,
            "live_request": {"text": text}, "output": None, "reference": None, "seed": None}


def complete(store, job, cases, positions=None, marker="result"):
    identities = store.start("p", job, cases, positions)
    for identity in identities:
        store.save_run("p", job, identity, {"status": "done", "trace": {"marker": marker},
                       "judge": {"verdict": marker}, "eval_axes": {"items": [marker]}})
    store.finish("p", job, {"project_id": "p", "total": len(cases)})
    return identities


def test_restart_restores_full_latest_results(store):
    complete(store, "job", [case()])
    loaded = LatestRunStore(store.path).load("p")
    assert loaded["runs"][0]["trace"] == {"marker": "result"}
    assert loaded["runs"][0]["eval_axes"] == {"items": ["result"]}
    assert loaded["batch"]["status"] == "completed"
    assert loaded["cases"][0]["request_key"] == "job:0"


def test_partial_rerun_preserves_unselected_rows_without_history(store):
    cases = [case("a"), case("b")]
    complete(store, "old", cases)
    complete(store, "new", [cases[1]], [1], "new-result")
    loaded = store.load("p")
    assert [r["request_key"] for r in loaded["runs"]] == ["old:0", "new:0"]
    assert loaded["batch"]["job_id"] == "new"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM current_cases").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM current_batches").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM current_cases WHERE run_json LIKE '%old:1%'").fetchone()[0] == 0


def test_duplicate_case_ids_keep_distinct_row_identity(store):
    cases = [case(), case(text="other")]
    ids = complete(store, "old", cases)
    assert ids[0]["request_case_id"] == ids[1]["request_case_id"]
    complete(store, "new", [cases[1]], [1])
    assert [r["request_key"] for r in store.load("p")["runs"]] == ["old:0", "new:0"]


def test_new_workspace_discards_old_results_and_other_projects_are_untouched(store):
    complete(store, "job", [case()])
    store.replace("q", [case("q")], "manual")
    store.replace("p", [case("different")], "manual")
    assert store.load("p")["runs"] == []
    assert store.load("p")["batch"] is None
    assert len(store.load("q")["cases"]) == 1


@pytest.mark.parametrize("keep_cases", [True, False])
def test_clear_is_durable_and_does_not_resurrect(store, keep_cases):
    complete(store, "job", [case()])
    store.clear("p", keep_cases=keep_cases)
    state = LatestRunStore(store.path).load("p")
    assert state["runs"] == [] and state["batch"] is None
    assert len(state["cases"]) == int(keep_cases)
    if keep_cases:
        assert state["cases"][0]["status"] == "pending"
        assert state["cases"][0]["request_key"] is None
    with pytest.raises(ValueError):
        store.update_run("p", "job:0", {"status": "done"})


def test_active_batch_blocks_clear_replace_and_another_batch(store):
    store.start("p", "active", [case()])
    for action in [lambda: store.clear("p", keep_cases=True),
                   lambda: store.replace("p", [], "manual"),
                   lambda: store.start("p", "second", [case()])]:
        with pytest.raises(WorkspaceBusy):
            action()
    assert store.load("p")["batch"]["job_id"] == "active"


def test_crashed_worker_keeps_completed_rows_and_marks_only_unfinished(store, monkeypatch):
    ids = store.start("p", "job", [case("a"), case("b")])
    store.save_run("p", "job", ids[0], {"status": "done", "judge": {"verdict": "saved"}})
    monkeypatch.setattr(run_store, "_alive", lambda pid: False)
    loaded = store.load("p")
    assert loaded["batch"]["status"] == "failed"
    assert loaded["batch"]["done"] == 1
    assert [r["status"] for r in loaded["cases"]] == ["done", "error"]
    assert loaded["runs"][0]["judge"] == {"verdict": "saved"}
    store.clear("p", keep_cases=True)


def test_failed_latest_attempt_replaces_old_success(store):
    complete(store, "old", [case()])
    ids = store.start("p", "new", [case()], [0])
    store.save_run("p", "new", ids[0], {"status": "error", "error": "latest failure"})
    store.finish("p", "new", {})
    loaded = store.load("p")
    assert loaded["runs"] == [{**ids[0], "status": "error", "error": "latest failure"}]


def test_rejects_stale_pool_positions_and_late_writes(store):
    ids = complete(store, "old", [case()])
    with pytest.raises(ValueError, match="变化"):
        store.start("p", "bad", [case(text="changed")], [0])
    assert store.load("p")["batch"]["job_id"] == "old"
    complete(store, "new", [case()], [0])
    with pytest.raises(ValueError, match="过期"):
        store.save_run("p", "old", ids[0], {"status": "done"})


def test_manual_attribute_updates_latest_only(store):
    complete(store, "job", [case()])
    run = store.get_run("p", "job:0")
    run["attribute"] = {"finding": "persisted"}
    store.update_run("p", "job:0", run)
    assert LatestRunStore(store.path).get_run("p", "job:0")["attribute"] == {"finding": "persisted"}
    assert store.load("q")["runs"] == []
    with pytest.raises(KeyError):
        store.get_run("q", "job:0")


def test_overwrite_and_clear_reclaim_disk_space(store):
    complete(store, "first", [case()], marker="x" * 500_000)
    size = store.path.stat().st_size
    for i in range(8):
        complete(store, f"repeat{i}", [case()], [0], marker="y" * 500_000)
    assert store.path.stat().st_size <= size + 8192
    store.clear("p", keep_cases=True)
    assert store.path.stat().st_size < size / 10
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA auto_vacuum").fetchone()[0] == 1
        assert db.execute("PRAGMA freelist_count").fetchone()[0] == 0
