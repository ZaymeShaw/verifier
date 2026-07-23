from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.core import pipeline
from impl.core.config_schema import ConfigError, load_yaml_document
from impl.core.knowledge_route import load_project_knowledge_route, parse_project_knowledge_route
from impl.core.local_service import _service_environment, _start_and_wait, _write_redacted_log, ensure_project_service
from impl.core.path_contract import PathResolver, PathRoots
from impl.core.project_config import parse_project_document, resolve_project_config
from impl.core.project_loader import list_projects, load_project
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace
from impl.core.attribute_protocol import ProjectAttribute
from scripts.scaffold_project import _write_scaffold_file


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
        assert spec.metadata["initialized_from"] == "route://project.yaml"


def test_mode_contract_distinguishes_uploaded_output_and_service_projects():
    qa = load_project("QA")
    client_search = load_project("client_search")

    assert qa.runtime_mode == "uploaded_output_evaluation"
    assert qa.ready == ["output", "reference"]
    assert qa.service() == {}
    assert qa.attribution_enabled is False
    assert client_search.runtime_mode == "existing_service_required"
    assert client_search.service()["endpoint"] == "/api/v1/client_search_query_parse_no_encipher"
    assert client_search.role_tool_call_limit("attribute") == 8
    assert client_search.attribution_enabled is True


def test_behavioral_fields_have_canonical_semantic_owners():
    qa = load_project("QA")
    client_search = load_project("client_search")
    deerflow = load_project("deerflow")
    intent = load_project("marketting-planning-intent")
    planning = load_project("marketting-planning")

    assert qa.judge_score_dimensions[0] == "correctness"
    assert qa.judge_error_taxonomy[-1] == "none"
    assert client_search.core_forbidden_markers == [
        "matched_level",
        "clientAge",
        "annPremSegNum",
        "clientSex",
    ]
    assert deerflow.interactive_scenarios == ["multi_turn_dimension_accumulation"]
    assert intent.intent_labels[0] == "other"
    assert intent.intent_descriptions["nbev_planning"] == "NBEV 达成路径规划分析"
    assert planning.stream_event_aliases["done"] == ["card_end", "done", "complete", "completed"]
    assert planning.stream_terminal_events == ["done", "complete", "completed", "card_end"]

    for spec in (qa, client_search, deerflow, intent, planning):
        assert spec.mock_scenarios
        assert set(spec.mock_scenarios).issubset(spec.scenarios)
        assert set(spec.adapter_contract) == {
            "request_construction",
            "output_extraction",
            "reference_handling",
        }
        assert spec.application_contract["interface"]["shape"]
        assert spec.batch_persistence_contract["case_shape"]
        assert spec.judge_boundary_contract["gate"]
        assert spec.attribution_trace_contract["trace_nodes"]
        assert spec.frontend_view_contract["live"]
        assert spec.check_evidence_contract["documents"]
        assert "scenarios" not in spec.presentation
        assert "core_forbidden_markers" not in spec.presentation


def test_project_contract_rejects_missing_typed_implementation_slice(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["runtime"].pop("adapter")

    with pytest.raises(ConfigError, match="missing required project contract runtime.adapter"):
        parse_project_document(document, project_id=None, project_root=root)


def test_behavioral_fields_are_rejected_under_presentation(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["verifier"]["presentation"] = {"scenarios": ["happy_path"]}

    with pytest.raises(ConfigError, match=r"unknown field verifier\.presentation\.scenarios"):
        parse_project_document(document, project_id=None, project_root=root)


def test_scenario_contract_rejects_implicit_mock_fallback(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["runtime"].pop("mock_cases")

    with pytest.raises(ConfigError, match="requires explicit runtime.mock_cases.default_scenarios"):
        parse_project_document(document, project_id=None, project_root=root)


def test_scenario_contract_rejects_unknown_or_incompatible_interactive_scenario(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["verifier"]["scenarios"]["interactive"] = ["unknown_scenario"]

    with pytest.raises(ConfigError, match="interactive must be declared"):
        parse_project_document(document, project_id=None, project_root=root)

    document["verifier"]["scenarios"]["allowed"].append("unknown_scenario")
    with pytest.raises(ConfigError, match="requires runtime.interaction.mode multi_turn"):
        parse_project_document(document, project_id=None, project_root=root)


def test_intent_descriptions_must_reference_declared_labels(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["project"]["taxonomies"] = {
        "intent": {
            "labels": ["known"],
            "descriptions": {"unknown": "not declared"},
        }
    }

    with pytest.raises(ConfigError, match="descriptions must reference a declared label"):
        parse_project_document(document, project_id=None, project_root=root)


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


def test_knowledge_route_resolves_registered_repository_and_tracks_source(tmp_path):
    dotenv = tmp_path / ".env"
    repository = tmp_path / "external-project"
    repository.mkdir()
    dotenv.write_text(f"DEERFLOW_REPO={repository}\n", encoding="utf-8")

    route = load_project_knowledge_route(
        "deerflow",
        dotenv_path=dotenv,
        environ={},
    )

    assert route.source_repository == str(repository.resolve())
    assert route.source_repository_reference == "${DEERFLOW_REPO}"
    assert route.config_sources["source.repository"].kind == "dotenv"
    assert route.missing_required == ()


def test_required_project_and_knowledge_values_can_be_strictly_enforced(tmp_path):
    with pytest.raises(ConfigError, match="missing required project configuration.*repository"):
        resolve_project_config(
            "deerflow",
            dotenv_path=tmp_path / "missing.env",
            environ={},
            require_values=True,
        )

    route = load_project_knowledge_route(
        "deerflow",
        dotenv_path=tmp_path / "missing.env",
        environ={},
    )
    assert route.missing_required == ("source.repository",)


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


def test_optional_service_mode_without_service_requires_provided_output(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["runtime"] = {
        "mode": "existing_service_optional",
        "interaction": {"mode": "single_turn"},
        "ready": ["reference"],
    }

    with pytest.raises(ConfigError, match="requires runtime.ready to include output"):
        parse_project_document(document, project_id=None, project_root=root)


def test_project_extra_requires_a_project_specific_value_schema(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["verifier"]["extra"] = {
        "special_rule": {
            "description": "demo special rule",
            "value_type": "mapping",
            "schema_version": 1,
            "consumers": ["impl.projects.demo.consumer"],
            "value": {"enabled": True},
        }
    }

    with pytest.raises(ConfigError, match="extra fields require project schema"):
        parse_project_document(document, project_id=None, project_root=root)


def test_promoted_role_asset_accepts_cleared_candidate_path(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "mock.md").write_text("promoted mock contract", encoding="utf-8")
    document = load_yaml_document(ROOT / "impl" / "projects" / "project.template.yaml")
    document["verifier"]["assets"] = [
        {
            "asset_id": "mock_contract",
            "kind": "context",
            "enabled": True,
            "roles": ["mock"],
            "production_path": "project://mock.md",
            "candidate_path": "",
            "replace": True,
        }
    ]

    parsed, _registry = parse_project_document(
        document,
        project_id=None,
        project_root=root,
    )

    assert parsed["verifier"]["assets"][0]["candidate_path"] == ""


def test_knowledge_route_rejects_unknown_fields_and_path_escape(tmp_path):
    route_root = tmp_path / "demo"
    route_root.mkdir()
    (route_root / "demand.md").write_text("业务目标、范围、非目标、核心场景\n", encoding="utf-8")
    document = {
        "schema_version": 1,
        "project": {"id": "demo", "name": "Demo", "description": "Demo route"},
        "documents": {
            "requirements": {
                "path": "route://../outside.md",
                "type": "requirements",
                "required": True,
                "description": "requirements",
            }
        },
        "onboarding": {"interaction": "single_turn", "ready": []},
    }

    with pytest.raises(ConfigError, match="PATH_TRAVERSAL"):
        parse_project_knowledge_route(document, project_id="demo", route_root=route_root)

    document["documents"]["requirements"]["path"] = "route://demand.md"
    document["common"] = {}
    with pytest.raises(ConfigError, match="unknown field common"):
        parse_project_knowledge_route(document, project_id="demo", route_root=route_root)


def test_missing_optional_knowledge_document_is_removed_from_resolved_route(tmp_path):
    route_root = tmp_path / "demo"
    route_root.mkdir()
    (route_root / "requirements.md").write_text("业务目标、范围、非目标、核心场景", encoding="utf-8")
    document = {
        "schema_version": 1,
        "project": {"id": "demo", "name": "Demo", "description": "Demo route"},
        "documents": {
            "requirements": {
                "path": "route://requirements.md", "type": "requirements", "required": True, "description": "requirements"
            },
            "optional_reference": {
                "path": "route://missing.md", "type": "reference", "required": False, "description": "optional"
            },
        },
        "onboarding": {"interaction": "single_turn", "ready": []},
    }

    route = parse_project_knowledge_route(document, project_id="demo", route_root=route_root)

    assert set(route.documents) == {"requirements"}


def test_scaffold_force_never_overwrites_human_project_config(tmp_path):
    path = tmp_path / "project.yaml"
    path.write_text("human: decision\n", encoding="utf-8")

    status = _write_scaffold_file(path, "ai: proposal\n", force=True, protected=True)

    assert status == "review_required"
    assert path.read_text(encoding="utf-8") == "human: decision\n"


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
    assert trace.attribution_runs[-1]["status"] == "skipped"
    assert trace.attribution_runs[-1]["execution_source"] == "project_default"


def test_manual_attribution_override_is_idempotent_and_recorded_on_trace(monkeypatch):
    class CompletedAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {}

    spec = load_project("QA")
    adapter = type("Adapter", (), {"attribute": lambda self: CompletedAttribute(spec)})()
    monkeypatch.setattr(pipeline, "load_project", lambda _project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda _spec: adapter)
    pipeline._manual_attribute_cache.clear()
    trace = RunTrace(trace_id="qa-manual-idempotent", project_id="QA", case_id="case-1")
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id="QA",
        overall_fulfillment={"status": "fulfilled"},
    )

    first = pipeline.attribute("QA", trace, judge, manual_override=True)
    second = pipeline.attribute("QA", trace, judge, manual_override=True)

    assert first.summary["execution_status"] == "completed"
    assert second.summary["execution_status"] == "reused"
    assert [item["status"] for item in trace.attribution_runs] == ["completed", "reused"]
    assert spec.attribution_enabled is False


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


def test_local_service_project_lock_prevents_duplicate_concurrent_start(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    spec = load_project("deerflow")
    initial_checks = threading.Barrier(2)
    state = {"calls": 0, "healthy": False, "starts": 0}
    state_lock = threading.Lock()

    def healthy(*_args):
        with state_lock:
            state["calls"] += 1
            call = state["calls"]
            value = state["healthy"]
        if call <= 2:
            initial_checks.wait(timeout=2)
            return False
        return value

    def start(*_args):
        with state_lock:
            state["starts"] += 1
            state["healthy"] = True

    monkeypatch.setattr("impl.core.local_service._healthy", healthy)
    monkeypatch.setattr("impl.core.local_service._start_and_wait", start)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ensure_project_service, spec) for _ in range(2)]
        for future in futures:
            future.result(timeout=3)

    assert state["starts"] == 1


def _local_service_spec(tmp_path):
    script = tmp_path / "scripts" / "start.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    roots = PathRoots(
        verifier_repo=tmp_path,
        project_package=tmp_path,
        knowledge_route=tmp_path,
        artifact_package=tmp_path,
    )
    return ProjectSpec(
        project_id="demo",
        name="demo",
        path_roots=roots,
        path_resolver=PathResolver(roots),
    )


def test_local_service_zero_exit_continues_waiting_until_health(tmp_path, monkeypatch):
    spec = _local_service_spec(tmp_path)
    health_results = iter([False, True])
    process = SimpleNamespace(stdout=None, poll=lambda: 0)
    monkeypatch.setattr("impl.core.local_service.subprocess.Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr("impl.core.local_service._healthy", lambda *_args: next(health_results))

    _start_and_wait(
        spec,
        {"base_url": "http://127.0.0.1:1"},
        {"startup_timeout_seconds": 1, "interval_seconds": 0.001},
    )


def test_local_service_nonzero_exit_and_timeout_fail_closed(tmp_path, monkeypatch):
    spec = _local_service_spec(tmp_path)
    process = SimpleNamespace(stdout=None, poll=lambda: 7)
    monkeypatch.setattr("impl.core.local_service.subprocess.Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr("impl.core.local_service._healthy", lambda *_args: False)

    with pytest.raises(ConfigError, match="exit=7"):
        _start_and_wait(
            spec,
            {"base_url": "http://127.0.0.1:1"},
            {"startup_timeout_seconds": 1, "interval_seconds": 0.001},
        )

    process = SimpleNamespace(stdout=None, poll=lambda: 0)
    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setattr("impl.core.local_service.subprocess.Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr("impl.core.local_service.time.monotonic", lambda: next(monotonic_values))

    with pytest.raises(ConfigError, match="health timeout"):
        _start_and_wait(
            spec,
            {"base_url": "http://127.0.0.1:1"},
            {"startup_timeout_seconds": 1, "interval_seconds": 0.001},
        )


def test_local_service_only_passes_process_bootstrap_and_registered_project_values(monkeypatch):
    monkeypatch.setenv("DEERFLOW_REPO", "/tmp/deerflow")
    monkeypatch.setenv("UNREGISTERED_PRODUCT_SETTING", "must-not-leak")
    monkeypatch.setenv("PATH", "/bin")
    spec = load_project("deerflow")

    environment = _service_environment(spec)

    assert environment["PATH"] == "/bin"
    assert "UNREGISTERED_PRODUCT_SETTING" not in environment
    assert "DEERFLOW_REPO" in environment


def test_local_service_log_redacts_registered_secrets(tmp_path):
    import io

    path = tmp_path / "service.log"
    _write_redacted_log(io.StringIO("token=super-secret-value\n"), path, ("super-secret-value",))

    assert path.read_text(encoding="utf-8") == "token=***\n"


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
