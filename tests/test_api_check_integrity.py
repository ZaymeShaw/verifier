from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _registry():
    path = Path(__file__).parents[1] / "hooks" / "api-check" / "api_check_registry.py"
    spec = importlib.util.spec_from_file_location("api_check_integrity_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_api_check_includes_deerflow():
    assert "deerflow" in _registry().PROJECT_IDS


def test_canonical_flow_is_updated_by_real_api_rows(monkeypatch):
    registry = _registry()
    registry._PROJECT_FLOW_CACHE.clear()
    trace = {"trace_id": "trace-1", "project_id": "QA"}
    run_chain = {
        "trace": trace,
        "judge": {"trace_id": "trace-1", "overall_fulfillment": {"status": "fulfilled"}},
        "attribute": {"trace_id": "trace-1"},
        "cluster": {"cluster_id": "c"},
        "check": {"passed": True},
        "frontend_view": {},
    }
    responses = {
        "/api/run_chain": run_chain,
        "/api/judge": {"trace_id": "trace-1", "overall_fulfillment": {"status": "not_fulfilled"}},
    }
    monkeypatch.setattr(registry, "call_api_raw", lambda path, request: (200, responses[path]))
    monkeypatch.setattr(registry.ApiCase, "assert_response_schema", lambda *args, **kwargs: None)

    run_case = registry.ApiCase(
        "run_chain",
        "/api/run_chain",
        lambda project_id: {"project": project_id, "input": {}},
        "ignored",
    )
    judge_case = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "judge")

    registry.run_api_case(run_case, "QA")
    registry.run_api_case(judge_case, "QA")

    flow = registry.project_flow("QA")
    assert flow["judge"] == responses["/api/judge"]
    attribute_case = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "attribute")
    assert attribute_case.request_for_project("QA")["judge"] == responses["/api/judge"]


def test_business_status_does_not_treat_schema_pass_as_business_success():
    registry = _registry()
    status = registry.business_status(
        "live_run",
        {
            "status": "error",
            "completion_status": "failed",
            "stop_reason": "decision_error",
            "error": "decision_error",
        },
    )
    assert status["business_check"] == "fail"
    assert status["trace_status"] == "error"
