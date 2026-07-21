from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "draft" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("test_draft_loop_script", _SCRIPTS / "draft_loop.py")
assert _SPEC is not None and _SPEC.loader is not None
draft_loop = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = draft_loop
_SPEC.loader.exec_module(draft_loop)
run_iteration = sys.modules["run_iteration"]

_UNSEEN_SPEC = importlib.util.spec_from_file_location(
    "test_draft_unseen_script", _SCRIPTS / "run_unseen.py"
)
assert _UNSEEN_SPEC is not None and _UNSEEN_SPEC.loader is not None
run_unseen = importlib.util.module_from_spec(_UNSEEN_SPEC)
sys.modules[_UNSEEN_SPEC.name] = run_unseen
_UNSEEN_SPEC.loader.exec_module(run_unseen)


def _project(tmp_path: Path) -> ProjectSpec:
    (tmp_path / "draft").mkdir()
    (tmp_path / "attribute.py").write_text("production", encoding="utf-8")
    (tmp_path / "draft" / "attribute.py").write_text("candidate-1", encoding="utf-8")
    (tmp_path / "project.yaml").write_text("project_id: demo\n", encoding="utf-8")
    return ProjectSpec(project_id="demo", name="demo", root=str(tmp_path))


def test_draft_loop_freezes_current_and_requires_review_between_iterations(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)
    monkeypatch.setattr(
        draft_loop,
        "run_frozen_iteration",
        lambda project_id, role, cases, **kwargs: {
            "project_id": project_id,
            "role": role,
            "rows": cases,
            "run_status": "completed",
        },
    )
    cases = {"iteration_cases": [{"case_key": "case-1", "value": 1}]}

    state = draft_loop.start_loop(
        "demo",
        "mock",
        cases,
        objective="improve diagnosis",
        review="must be more accurate with no regression",
        max_iterations=3,
    )
    assert state.status == "active"
    draft_loop.run_iteration("demo", "mock")
    with pytest.raises(ValueError, match="awaits Harness review"):
        draft_loop.run_iteration("demo", "mock")

    reviewed = draft_loop.record_review(
        "demo",
        "mock",
        decision="unchanged",
        route="solidify",
        reason="same output",
        evidence=["iterations/001-run.json#rows[0]"],
    )
    assert reviewed.status == "active"
    (tmp_path / "draft" / "attribute.py").write_text("candidate-2", encoding="utf-8")
    draft_loop.run_iteration("demo", "mock")

    (tmp_path / "attribute.py").write_text("production changed", encoding="utf-8")
    draft_loop.record_review(
        "demo",
        "mock",
        decision="insufficient_evidence",
        route="investigate",
        reason="missing counterexample",
        evidence=["iterations/002-run.json#rows[0]"],
    )
    with pytest.raises(RuntimeError, match="frozen Current changed"):
        draft_loop.run_iteration("demo", "mock")


def test_draft_loop_only_marks_ready_after_evidenced_improvement(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)
    monkeypatch.setattr(
        draft_loop,
        "run_frozen_iteration",
        lambda project_id, role, cases, **kwargs: {"rows": cases, "run_status": "completed"},
    )
    draft_loop.start_loop(
        "demo",
        "mock",
        {"iteration_cases": [{"case_key": "case-1"}]},
        objective="improve diagnosis",
        review="verified accuracy and no regression",
        max_iterations=2,
    )
    draft_loop.run_iteration("demo", "mock")
    state = draft_loop.record_review(
        "demo",
        "mock",
        decision="improved",
        route="promotion_checks",
        reason="draft identifies the verified mechanism while current does not",
        evidence=["iterations/001-run.json#rows[0]"],
    )
    assert state.status == "ready_for_promotion_checks"
    with pytest.raises(ValueError, match="not active"):
        draft_loop.run_iteration("demo", "mock")


def test_formal_attribute_run_rejects_runtime_infrastructure_failure():
    runtime = {
        "context": {
            "context_debug": {
                "errors": [{
                    "operation": "search_context_units",
                    "type": "ConnectionResetError",
                    "message": "connection reset",
                    "infrastructure": True,
                }]
            }
        },
        "evidence_registration_errors": [],
        "review_calls": [],
    }

    with pytest.raises(RuntimeError, match="draft attribute runtime invalid"):
        run_iteration._assert_formal_runtime_valid(
            "attribute", "draft", "case-1", runtime
        )
    assert run_iteration._formal_runtime_failures(
        "attribute",
        {
            "context": {
                "context_debug": {
                    "errors": [{
                        "operation": "load_context_units",
                        "type": "ContextNotFoundError",
                        "message": "missing",
                        "infrastructure": False,
                    }]
                }
            }
        },
    ) == []


def test_fulfilled_attribute_case_skips_environment_assembly():
    class FulfilledAttribute:
        def __init__(self):
            self.spec = ProjectSpec(project_id="demo", name="demo")
            self.configured = False

        def configure_execution_environment(self, _environment):
            self.configured = True

        def attribute_failure(self, trace, _judge):
            return {"trace_id": trace.trace_id, "status": "not_applicable"}

    implementation = FulfilledAttribute()
    result = run_iteration._run_role(
        "attribute",
        implementation,
        {
            "trace": RunTrace(trace_id="trace-fulfilled", project_id="demo"),
            "judge_result": JudgeResult(
                trace_id="trace-fulfilled",
                project_id="demo",
                overall_fulfillment={"status": "fulfilled"},
            ),
        },
    )

    assert result["status"] == "not_applicable"
    assert implementation.configured is False


def test_improved_review_rejects_completed_report_with_runtime_failure(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)
    monkeypatch.setattr(
        draft_loop,
        "run_frozen_iteration",
        lambda project_id, role, cases, **kwargs: {
            "rows": [{
                "case_key": "case-1",
                "current_runtime": {},
                "draft_runtime": {
                    "evidence_registration_errors": ["embedding unavailable"]
                },
            }],
            "run_status": "completed",
        },
    )
    draft_loop.start_loop(
        "demo",
        "mock",
        {"iteration_cases": [{"case_key": "case-1"}]},
        objective="improve generation",
        review="must be better",
        max_iterations=2,
    )
    draft_loop.run_iteration("demo", "mock")

    with pytest.raises(ValueError, match="infrastructure failures"):
        draft_loop.record_review(
            "demo",
            "mock",
            decision="improved",
            route="promotion_checks",
            reason="looks better",
            evidence=["iterations/001-run.json#rows[0]"],
        )


def test_draft_loop_validates_all_cases_before_writing_state(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)

    with pytest.raises(TypeError, match=r"case\[1\]"):
        draft_loop.start_loop(
            "demo",
            "mock",
            {"iteration_cases": [{"case_key": "valid"}, "invalid"]},
            objective="improve generation",
            review="must be better",
            max_iterations=2,
        )

    assert not (tmp_path / "draft" / ".state" / "mock" / "loop.json").exists()


def test_draft_loop_preserves_failed_iteration_and_requires_real_evidence(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)

    def fail_iteration(project_id, role, cases, **kwargs):
        callback = kwargs["progress_callback"]
        callback({
            "phase": "current_completed",
            "case_index": 0,
            "completed_rows": [],
            "partial_row": {"case_key": "case-1", "current": {"status": "done"}},
        })
        raise ConnectionError("embedding unavailable")

    monkeypatch.setattr(draft_loop, "run_frozen_iteration", fail_iteration)
    draft_loop.start_loop(
        "demo",
        "mock",
        {"iteration_cases": [{"case_key": "case-1"}]},
        objective="improve generation",
        review="must be better",
        max_iterations=2,
    )

    with pytest.raises(RuntimeError, match="partial facts preserved"):
        draft_loop.run_iteration("demo", "mock")

    state = draft_loop._read_state(tmp_path / "draft" / ".state" / "mock" / "loop.json")
    assert len(state.iterations) == 1
    report_path = Path(state.iterations[0].run_report)
    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["run_status"] == "failed"
    assert report["partial_row"]["current"]["status"] == "done"

    with pytest.raises(ValueError, match="does not exist"):
        draft_loop.record_review(
            "demo",
            "mock",
            decision="blocked",
            route="blocked",
            reason="infrastructure failed",
            evidence=["missing.json"],
        )

    reviewed = draft_loop.record_review(
        "demo",
        "mock",
        decision="blocked",
        route="blocked",
        reason="infrastructure failed",
        evidence=[str(report_path)],
    )
    assert reviewed.status == "blocked"


def test_draft_loop_does_not_expose_stale_report_from_restarted_loop(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path)
    monkeypatch.setattr(draft_loop, "load_project", lambda project_id: spec)
    state_dir = tmp_path / "draft" / ".state" / "mock"
    report_path = state_dir / "iterations" / "001-run.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"run_status":"completed","stale":true}\n', encoding="utf-8")

    def inspect_before_new_result(project_id, role, cases, **kwargs):
        assert not report_path.exists()
        return {"rows": cases, "run_status": "completed"}

    monkeypatch.setattr(draft_loop, "run_frozen_iteration", inspect_before_new_result)
    draft_loop.start_loop(
        "demo",
        "mock",
        {"iteration_cases": [{"case_key": "case-1"}]},
        objective="improve generation",
        review="must be better",
        max_iterations=2,
    )
    draft_loop.run_iteration("demo", "mock")

    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["run_status"] == "completed"
    assert "stale" not in report


def test_unseen_runner_uses_common_frozen_protocol_for_mock(monkeypatch, capsys):
    captured = {}

    def fake_run(project_id, role, cases):
        captured.update(project_id=project_id, role=role, cases=cases)
        return {"case_count": len(cases), "rows": [{"case_key": "mock-1"}]}

    monkeypatch.setattr(run_unseen, "run_frozen_iteration", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_unseen.py",
            "--project",
            "demo",
            "--role",
            "mock",
            "--cases",
            '[{"case_key":"mock-1","scenario":"boundary"}]',
        ],
    )

    assert run_unseen.main() == 0
    assert captured == {
        "project_id": "demo",
        "role": "mock",
        "cases": [{"case_key": "mock-1", "scenario": "boundary"}],
    }
    output = capsys.readouterr().out
    assert '"case_count": 1' in output
