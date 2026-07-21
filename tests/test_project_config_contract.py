from __future__ import annotations

from pathlib import Path

import pytest

from impl.core import pipeline
from impl.core.config_schema import ConfigError, load_yaml_document
from impl.core.knowledge_route import load_project_knowledge_route, parse_project_knowledge_route
from impl.core.local_service import ensure_project_service
from impl.core.project_config import parse_project_document, resolve_project_config
from impl.core.project_loader import list_projects, load_project
from impl.core.schema import JudgeResult, RunTrace


ROOT = Path(__file__).resolve().parents[1]


def test_all_projects_have_one_canonical_runtime_config_and_matching_knowledge_route():
    project_ids = list_projects()

    assert project_ids == ["QA", "client_search", "deerflow", "marketting-planning", "marketting-planning-intent"]
    for project_id in project_ids:
        spec = load_project(project_id)
        route = load_project_knowledge_route(project_id)
        assert spec.schema_version == route.schema_version == 1
        assert spec.project_id == route.project_id == project_id
        assert isinstance(spec.attribution_enabled, bool)
        assert spec.metadata["initialized_from"].endswith(f"projects/{project_id}/project.yaml")


def test_mode_contract_distinguishes_uploaded_output_and_service_projects():
    qa = load_project("QA")
    client_search = load_project("client_search")

    assert qa.runtime_mode == "uploaded_output_evaluation"
    assert qa.ready == ["output", "reference"]
    assert qa.service() == {}
    assert qa.attribution_enabled is False
    assert client_search.runtime_mode == "existing_service_required"
    assert client_search.service()["endpoint"] == "/api/v1/client_search_query_parse_no_encipher"
    assert client_search.attribution_enabled is True


def test_project_environment_override_is_registered_and_source_tracked(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("CLIENT_SEARCH_BASE_URL=http://127.0.0.1:18000\n", encoding="utf-8")

    spec = resolve_project_config(
        "client_search",
        dotenv_path=dotenv,
        environ={},
    )

    assert spec.service()["base_url"] == "http://127.0.0.1:18000"
    assert spec.config_sources["runtime.services.primary.base_url"].kind == "dotenv"


def test_uploaded_mode_rejects_service_configuration(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["runtime"]["services"] = {
        "primary": {
            "base_url": "http://127.0.0.1:8000",
            "endpoint": "/health",
            "method": "GET",
            "timeout_seconds": 1,
        }
    }

    with pytest.raises(ConfigError, match="runtime.services is forbidden"):
        parse_project_document(document, project_id=None, project_root=root)


def test_knowledge_route_rejects_unknown_fields_and_path_escape(tmp_path):
    route_root = tmp_path / "demo"
    route_root.mkdir()
    (route_root / "demand.md").write_text("# Demand\n", encoding="utf-8")
    document = {
        "schema_version": 1,
        "project": {"id": "demo", "name": "Demo", "description": "Demo route"},
        "documents": {
            "requirements": {
                "path": "../outside.md",
                "type": "requirements",
                "required": True,
                "description": "requirements",
            }
        },
        "onboarding": {"interaction": "single_turn", "ready": []},
    }

    with pytest.raises(ConfigError, match="route-relative path"):
        parse_project_knowledge_route(document, project_id="demo", route_root=route_root)

    document["documents"]["requirements"]["path"] = "demand.md"
    document["common"] = {}
    with pytest.raises(ConfigError, match="unknown field common"):
        parse_project_knowledge_route(document, project_id="demo", route_root=route_root)


def test_qa_main_chain_skips_attribution_but_manual_endpoint_remains_available():
    trace = RunTrace(trace_id="qa-config-switch", project_id="QA", case_id="case-1")
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id="QA",
        overall_fulfillment={"status": "not_fulfilled"},
    )

    result = pipeline.attribute("QA", trace, judge, manual_override=False)

    assert result.summary["attribution_status"] == "skipped"
    assert result.summary["manual_override"] is False


def test_local_service_reuses_health_and_starts_only_when_needed(monkeypatch):
    spec = load_project("deerflow")
    starts: list[str] = []

    monkeypatch.setattr("impl.core.local_service._healthy", lambda *_args: True)
    monkeypatch.setattr("impl.core.local_service._start_and_wait", lambda *_args: starts.append("start"))
    ensure_project_service(spec)
    assert starts == []

    monkeypatch.setattr("impl.core.local_service._healthy", lambda *_args: False)
    ensure_project_service(spec)
    assert starts == ["start"]


def test_repository_configs_do_not_store_personal_absolute_paths():
    config_files = [
        ROOT / "impl" / "config.yaml",
        *sorted((ROOT / "impl" / "projects").glob("*/project.yaml")),
        *sorted((ROOT / "projects").glob("*/project.yaml")),
    ]
    for path in config_files:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "/home/" not in text
