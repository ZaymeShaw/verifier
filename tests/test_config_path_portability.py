from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from impl.core.config_check import (
    _run_full_gates_with_post_scan,
    _scan_active_path_artifacts,
    _scan_changed_and_untracked_files,
    _scan_path_construction_bypasses,
    _scan_portable_writer_bypasses,
    _validate_path_migration_ledger,
)
from impl.core.active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY
from impl.core.knowledge_route import load_project_knowledge_route
from impl.core.path_contract import LogicalPathRef, PathResolver, PathRoots, PathScope
from impl.core.portable_artifact import write_active_artifact
from impl.core.project_config import resolve_project_config
from impl.core.config_schema import ConfigError
from impl.tools.source_retrieval import ProjectSourceFileProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _portable_project_document() -> dict:
    return {
        "schema_version": 1,
        "project": {
            "id": "demo",
            "name": "Demo",
            "description": "portable project",
            "capabilities": ["check"],
            "resources": {
                "source": {
                    "repository": "",
                    "paths": {"entrypoint": "business://src/entry.py"},
                }
            },
        },
        "runtime": {
            "mode": "uploaded_output_evaluation",
            "application": {
                "interface": {"shape": "portable input/output", "source": "adapter.py"},
                "start_run": "uploaded output; no service",
                "boundary": "output evaluation only",
            },
            "ready": ["output"],
            "adapter": {
                "request_construction": {"builder": "Adapter.build_request", "required_inputs": ["query"]},
                "output_extraction": {"extractor": "Adapter.extract_output", "normalized_output": "normalized output"},
                "reference_handling": {"source_priority": ["input_reference", "missing"], "alignment": "normalized alignment"},
            },
            "batch_persistence": {
                "case_shape": "id, input, output, reference",
                "transient_results": "do not persist runtime analysis",
            },
        },
        "verifier": {
            "attribution": {
                "enabled": False,
                "trace": {"document": "attribution.md", "trace_nodes": ["output_extraction"]},
            },
            "judge": {"boundary": {"document": "judge_boundary.md", "gate": "evaluation boundary"}},
            "presentation": {"frontend_view": {"live": "live protocol", "summary": "summary protocol"}},
            "check_rules": {"evidence": {"documents": ["requirements.md"], "tests": []}},
        },
        "environment": {
            "variables": {
                "DEMO_REPO": {
                    "bind": "project.resources.source.repository",
                    "type": "path",
                    "required": True,
                    "secret": False,
                    "description": "demo source repository",
                }
            }
        },
        "metadata": {"initialized_from": "route://project.yaml", "source_revision": None},
    }


def test_project_moves_between_machine_roots_without_yaml_change(tmp_path: Path) -> None:
    projects = tmp_path / "verifier" / "impl" / "projects"
    project_root = projects / "demo"
    project_root.mkdir(parents=True)
    config_path = project_root / "project.yaml"
    config_path.write_text(
        yaml.safe_dump(_portable_project_document(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    original = config_path.read_bytes()
    machine_a = tmp_path / "machine-a" / "business"
    machine_b = tmp_path / "machine-b" / "business"
    for root, content in ((machine_a, "a"), (machine_b, "b")):
        entry = root / "src" / "entry.py"
        entry.parent.mkdir(parents=True)
        entry.write_text(content, encoding="utf-8")

    spec_a = resolve_project_config(
        "demo",
        projects_dir=projects,
        dotenv_path=tmp_path / "missing.env",
        environ={"DEMO_REPO": str(machine_a)},
        require_values=True,
        verifier_root=tmp_path / "verifier",
    )
    spec_b = resolve_project_config(
        "demo",
        projects_dir=projects,
        dotenv_path=tmp_path / "missing.env",
        environ={"DEMO_REPO": str(machine_b)},
        require_values=True,
        verifier_root=tmp_path / "verifier",
    )

    assert spec_a.source_path("entrypoint") == str((machine_a / "src" / "entry.py").resolve())
    assert spec_b.source_path("entrypoint") == str((machine_b / "src" / "entry.py").resolve())
    assert spec_a.path_roots.verifier_repo == (tmp_path / "verifier").resolve()
    assert spec_a.path_roots.knowledge_route == (tmp_path / "verifier" / "projects" / "demo").resolve()
    assert config_path.read_bytes() == original


def test_two_layouts_load_all_roots_validate_active_artifact_and_run_consumer(
    tmp_path: Path,
) -> None:
    project_document = _portable_project_document()
    project_document["project"]["resources"]["documents"] = {
        "guide": "project://guide.md",
    }
    project_yaml = yaml.safe_dump(
        project_document,
        allow_unicode=True,
        sort_keys=False,
    )
    route_document = {
        "schema_version": 1,
        "project": {
            "id": "demo",
            "name": "Demo",
            "description": "portable knowledge route",
        },
        "documents": {
            "reference": {
                "path": "route://reference.md",
                "type": "reference",
                "required": True,
                "description": "portable reference",
            }
        },
        "source": {"repository": "${DEMO_REPO}"},
        "onboarding": {"interaction": "single_turn", "ready": ["output"]},
        "environment": {
            "variables": {
                "DEMO_REPO": {
                    "bind": "source.repository",
                    "type": "path",
                    "required": True,
                    "secret": False,
                    "description": "demo source repository",
                }
            }
        },
    }
    route_yaml = yaml.safe_dump(route_document, allow_unicode=True, sort_keys=False)
    observed_yaml: list[tuple[bytes, bytes]] = []

    for machine in ("machine-a", "machine-b"):
        machine_root = tmp_path / machine
        verifier_root = machine_root / "verifier-checkout"
        business_root = machine_root / "business-checkout"
        project_root = verifier_root / "impl" / "projects" / "demo"
        route_root = verifier_root / "projects" / "demo"
        artifact_root = machine_root / "run-artifacts"
        roots = {
            PathScope.VERIFIER_REPO: verifier_root,
            PathScope.BUSINESS_SOURCE: business_root,
            PathScope.PROJECT_PACKAGE: project_root,
            PathScope.KNOWLEDGE_ROUTE: route_root,
            PathScope.ARTIFACT_PACKAGE: artifact_root,
        }
        for scope, root in roots.items():
            root.mkdir(parents=True, exist_ok=True)
            (root / "same.txt").write_text(
                f"{machine}:{scope.value}",
                encoding="utf-8",
            )
            decoy = root / "src" / "entry.py"
            decoy.parent.mkdir(parents=True, exist_ok=True)
            decoy.write_text(f"DECOY = {scope.value!r}\n", encoding="utf-8")

        business_entry = business_root / "src" / "entry.py"
        business_entry.write_text(f"VALUE = {machine!r}\n", encoding="utf-8")
        (project_root / "adapter.py").write_text("ADAPTER = True\n", encoding="utf-8")
        (project_root / "guide.md").write_text("project guide\n", encoding="utf-8")
        (project_root / "project.yaml").write_text(project_yaml, encoding="utf-8")
        (route_root / "reference.md").write_text(
            "---\n"
            "doc_type: reference\n"
            "schema_version: 1\n"
            "---\n"
            "资料来源 source\n用途 purpose\n适用范围 scope\n",
            encoding="utf-8",
        )
        (route_root / "project.yaml").write_text(route_yaml, encoding="utf-8")
        observed_yaml.append((
            (project_root / "project.yaml").read_bytes(),
            (route_root / "project.yaml").read_bytes(),
        ))

        environment = {"DEMO_REPO": str(business_root)}
        spec = resolve_project_config(
            "demo",
            projects_dir=verifier_root / "impl" / "projects",
            dotenv_path=verifier_root / ".env",
            environ=environment,
            require_values=True,
            verifier_root=verifier_root,
        )
        route = load_project_knowledge_route(
            "demo",
            knowledge_root=verifier_root / "projects",
            dotenv_path=verifier_root / ".env",
            environ=environment,
            verifier_root=verifier_root,
        )
        assert route.document_path("reference") == (route_root / "reference.md").resolve()
        assert route.path_roots is not None
        assert route.path_roots.verifier_repo == verifier_root.resolve()

        resolver = PathResolver(PathRoots(
            verifier_repo=verifier_root,
            business_source=business_root,
            project_package=project_root,
            knowledge_route=route_root,
            artifact_package=artifact_root,
        ))
        for scope, root in roots.items():
            reference = LogicalPathRef(scope, "same.txt")
            resolved = reference.resolve(resolver, expected_type="file").physical
            assert resolved == (root / "same.txt").resolve()
            assert resolved.read_text(encoding="utf-8") == f"{machine}:{scope.value}"

        manifest_path = project_root / "tools" / "api_discover" / "_manifest.json"
        write_active_artifact(
            "endpoint_discovery_manifest",
            manifest_path,
            {
                "schema_version": 2,
                "project_id": "demo",
                "endpoint_count": 1,
                "endpoints": [{
                    "endpoint_id": "demo-entry",
                    "source": {
                        "location_scope": "business_source",
                        "location": "src/entry.py",
                    },
                }],
            },
            repository_root=verifier_root,
        )
        assert DEFAULT_ACTIVE_ARTIFACT_REGISTRY.validate(
            verifier_root,
            environ=environment,
        ) == []


        provider = ProjectSourceFileProvider(spec)
        source_item = next(
            item for item in provider.list_files()
            if Path(item["path"]).resolve() == business_entry.resolve()
        )
        assert provider.read_file(source_item["key"]) == f"VALUE = {machine!r}\n"
        assert spec.source_path("entrypoint") == str(business_entry.resolve())

    assert observed_yaml[0] == observed_yaml[1]


def test_all_real_projects_resolve_equivalently_across_two_machine_layouts(tmp_path: Path) -> None:
    project_ids = (
        "QA",
        "client_search",
        "deerflow",
        "marketting-planning-intent",
        "marketting-planning",
    )
    resolved_by_machine = {}

    for machine in ("machine-a", "machine-b"):
        verifier_root = tmp_path / machine / "verifier"
        projects_dir = verifier_root / "impl" / "projects"
        knowledge_root = verifier_root / "projects"
        environments = {}
        business_roots = {}

        for project_id in project_ids:
            shutil.copytree(
                REPOSITORY_ROOT / "impl" / "projects" / project_id,
                projects_dir / project_id,
            )
            shutil.copytree(
                REPOSITORY_ROOT / "projects" / project_id,
                knowledge_root / project_id,
            )
            document = yaml.safe_load(
                (projects_dir / project_id / "project.yaml").read_text(encoding="utf-8")
            )
            source = (((document.get("project") or {}).get("resources") or {}).get("source") or {})
            variables = ((document.get("environment") or {}).get("variables") or {})
            source_variables = [
                name
                for name, variable in variables.items()
                if variable.get("bind") == "project.resources.source.repository"
            ]
            environment = {}
            if source_variables:
                business_root = tmp_path / machine / "business" / project_id
                business_root.mkdir(parents=True)
                business_roots[project_id] = business_root
                for logical in (source.get("paths") or {}).values():
                    assert str(logical).startswith("business://")
                    target = business_root / str(logical).removeprefix("business://")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"{machine}:{project_id}:{target.name}\n", encoding="utf-8")
                for variable_name in source_variables:
                    environment[variable_name] = str(business_root)
            for variable_name, variable in variables.items():
                if variable.get("bind", "").endswith(".base_url"):
                    environment[variable_name] = str(_binding_value(document, variable["bind"]))
            environments[project_id] = environment

        machine_specs = {}
        for project_id in project_ids:
            spec = resolve_project_config(
                project_id,
                projects_dir=projects_dir,
                verifier_root=verifier_root,
                dotenv_path=verifier_root / ".env",
                environ=environments[project_id],
                require_values=True,
            )
            project = copy.deepcopy(spec.project)
            source = (((project.get("resources") or {}).get("source") or {}))
            if "repository" in source:
                source["repository"] = "<business-root>"
            machine_specs[project_id] = {
                "project": project,
                "runtime": spec.runtime,
                "verifier": spec.verifier,
                "scenarios": spec.scenarios,
                "mock_scenarios": spec.mock_scenarios,
                "intent_labels": spec.intent_labels,
                "documents": spec.document_paths,
                "assets": [
                    (item.asset_id, item.logical_production_path, item.logical_candidate_path)
                    for item in spec.asset_mappings()
                ],
            }
            for document_id in spec.document_paths:
                document_path = spec.project_document_path(document_id)
                assert document_path is not None
                assert document_path.is_relative_to(projects_dir / project_id)
            for source_id in ((((spec.project.get("resources") or {}).get("source") or {}).get("paths") or {})):
                assert Path(spec.source_path(source_id)).is_relative_to(business_roots[project_id])
        resolved_by_machine[machine] = machine_specs

    assert resolved_by_machine["machine-a"] == resolved_by_machine["machine-b"]


def _binding_value(document: dict, binding: str):
    current = document
    for part in binding.split("."):
        current = current[part]
    return current


def test_formal_project_yaml_rejects_legacy_bare_paths(tmp_path: Path) -> None:
    projects = tmp_path / "impl" / "projects"
    config_path = projects / "demo" / "project.yaml"
    config_path.parent.mkdir(parents=True)
    document = _portable_project_document()
    document["project"]["resources"]["source"]["paths"]["entrypoint"] = "src/entry.py"
    config_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="PATH_PREFIX_REQUIRED"):
        resolve_project_config(
            "demo",
            projects_dir=projects,
            dotenv_path=tmp_path / "missing.env",
            environ={"DEMO_REPO": str(tmp_path / "business")},
        )


def test_active_artifact_scan_fails_closed_on_bare_path(tmp_path: Path) -> None:
    manifest = tmp_path / "impl" / "projects" / "demo" / "tools" / "api_discover" / "_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schema_version": 2, "source_path": "src/api.py"}),
        encoding="utf-8",
    )

    issues = _scan_active_path_artifacts(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_SCHEMA_BYPASS"]


def test_active_draft_state_scan_rejects_physical_run_report(tmp_path: Path) -> None:
    state = (
        tmp_path
        / "impl"
        / "projects"
        / "demo"
        / "draft"
        / ".state"
        / "mock"
        / "loop.json"
    )
    report = state.parent / "iterations" / "001-run.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    state.write_text(
        json.dumps({
            "schema_version": 1,
            "project_id": "demo",
            "role": "mock",
            "iterations": [{
                "iteration": 1,
                "run_report": str(report),
                "draft_fingerprint": "fingerprint",
            }],
        }),
        encoding="utf-8",
    )

    issues = _scan_active_path_artifacts(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_SCHEMA_BYPASS"]


def test_active_draft_state_scan_follows_only_portable_references(tmp_path: Path) -> None:
    state = (
        tmp_path
        / "impl"
        / "projects"
        / "demo"
        / "draft"
        / ".state"
        / "mock"
        / "loop.json"
    )
    report = state.parent / "iterations" / "001-run.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"schema_version": 2, "run_status": "completed"}),
        encoding="utf-8",
    )
    report_sha256 = hashlib.sha256(report.read_bytes()).hexdigest()
    state.write_text(
        json.dumps({
            "schema_version": 2,
            "project_id": "demo",
            "role": "mock",
            "objective": "portable",
            "review": "review",
            "max_iterations": 1,
            "cases_sha256": "cases",
            "frozen_current_sha256": "current",
            "source_revision": "revision",
            "status": "active",
            "iterations": [{
                "iteration": 1,
                "run_report": {
                    "location_scope": "project_package",
                    "location": "draft/.state/mock/iterations/001-run.json",
                    "sha256": report_sha256,
                },
                "draft_fingerprint": "fingerprint",
                "decision": "",
                "route": "",
                "reason": "",
                "evidence": [],
            }],
        }),
        encoding="utf-8",
    )

    assert _scan_active_path_artifacts(tmp_path) == []


def test_static_scan_finds_unregistered_project_root_join(tmp_path: Path) -> None:
    consumer = tmp_path / "impl" / "projects" / "demo" / "consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "from pathlib import Path\n"
        "def consume(spec):\n"
        "    return Path(spec.root) / 'hidden.json'\n",
        encoding="utf-8",
    )

    issues = _scan_path_construction_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_CONSTRUCTION_BYPASS"]


def test_static_scan_finds_legacy_root_passed_directly(tmp_path: Path) -> None:
    consumer = tmp_path / "impl" / "context" / "consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "from pathlib import Path\n"
        "def load(spec):\n"
        "    return downstream(project_root=Path(spec.root))\n",
        encoding="utf-8",
    )

    issues = _scan_path_construction_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_CONSTRUCTION_BYPASS"]
    assert issues[0].line == 3


def test_static_scan_follows_alias_of_configured_root(tmp_path: Path) -> None:
    consumer = tmp_path / "impl" / "projects" / "demo" / "consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "from pathlib import Path\n"
        "def consume(spec):\n"
        "    root = Path(spec.source_project)\n"
        "    return root / 'hidden.json'\n",
        encoding="utf-8",
    )

    issues = _scan_path_construction_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_CONSTRUCTION_BYPASS"]
    assert issues[0].line == 3


def test_static_scan_finds_source_root_hidden_behind_loader_call(tmp_path: Path) -> None:
    consumer = tmp_path / "impl" / "projects" / "demo" / "consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "from pathlib import Path\n"
        "def consume():\n"
        "    return Path(load_project('demo').source_project) / 'hidden.json'\n",
        encoding="utf-8",
    )

    issues = _scan_path_construction_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_CONSTRUCTION_BYPASS"]


def test_static_scan_finds_raw_structured_artifact_writer(tmp_path: Path) -> None:
    producer = tmp_path / "impl" / "projects" / "demo" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import json\n"
        "def persist(path, payload):\n"
        "    path.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]


def test_static_scan_includes_formal_impl_tools_directory(tmp_path: Path) -> None:
    producer = tmp_path / "impl" / "tools" / "new_active_producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import json\n"
        "def persist(path, payload):\n"
        "    path.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]


def test_static_scan_fails_closed_for_unclassified_writer_domain(tmp_path: Path) -> None:
    producer = tmp_path / "new_runtime" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import json\n"
        "def persist(path, payload):\n"
        "    path.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_EXECUTION_DOMAIN_UNCLASSIFIED"]


def test_static_scan_keeps_independent_migration_tools_out_of_runtime_writer_policy(tmp_path: Path) -> None:
    producer = tmp_path / "scripts" / "migrate_once.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import json\n"
        "def persist(path, payload):\n"
        "    path.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    assert _scan_portable_writer_bypasses(tmp_path) == []


def test_static_scan_rejects_formal_absolute_path_and_presentation_consumer(tmp_path: Path) -> None:
    consumer = tmp_path / "impl" / "projects" / "demo" / "live.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "from pathlib import Path\n"
        "ROOT = Path('/machine/project')\n"
        "def read(spec):\n"
        "    return spec.presentation\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == [
        "PATH_ABSOLUTE_LITERAL",
        "PRESENTATION_BEHAVIOR_BYPASS",
    ]


def test_static_scan_rejects_direct_low_level_portable_writer(tmp_path: Path) -> None:
    producer = tmp_path / "impl" / "core" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "from impl.core.portable_artifact import PortableArtifactWriter\n"
        "def persist(path, payload):\n"
        "    PortableArtifactWriter().write_json(path, payload)\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]
    assert issues[0].line == 3


def test_static_scan_follows_serializer_alias_and_assigned_payload(tmp_path: Path) -> None:
    producer = tmp_path / "impl" / "projects" / "demo" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import json as codec\n"
        "def persist(path, payload):\n"
        "    encoded = codec.dumps(payload)\n"
        "    with path.open('w', encoding='utf-8') as stream:\n"
        "        stream.write(encoded)\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]
    assert issues[0].line == 5


def test_static_scan_follows_imported_serializer_alias(tmp_path: Path) -> None:
    producer = tmp_path / "impl" / "projects" / "demo" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "from json import dumps as encode\n"
        "def persist(path, payload):\n"
        "    path.write_text(encode(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]
    assert issues[0].line == 3


def test_static_scan_treats_yaml_safe_dump_without_stream_as_serialized_value(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "impl" / "projects" / "demo" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "import yaml as codec\n"
        "def persist(path, payload):\n"
        "    encoded = codec.safe_dump(payload)\n"
        "    path.write_text(encoded, encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = _scan_portable_writer_bypasses(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]
    assert issues[0].line == 4


def test_full_gate_rescans_artifacts_created_by_commands(tmp_path: Path, monkeypatch) -> None:
    def create_unknown_artifact(_root: Path, _environ=None, **_kwargs):
        artifact = (
            tmp_path
            / "impl"
            / "projects"
            / "demo"
            / "draft"
            / ".state"
            / "attribute"
            / "generated.json"
        )
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}\n", encoding="utf-8")
        return []

    monkeypatch.setattr(
        "impl.core.config_check._run_full_gates",
        create_unknown_artifact,
    )

    issues, _summary = _run_full_gates_with_post_scan(
        tmp_path,
        environ={},
        changed_from=None,
    )

    assert any(issue.code == "PATH_ACTIVE_UNKNOWN" for issue in issues)


def test_changed_file_scan_rejects_untracked_symlink_escape(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "impl" / "projects" / "demo" / "draft" / ".state" / "escape.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    issues, summary = _scan_changed_and_untracked_files(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_SYMLINK_ESCAPE"]
    assert "inspected 1 changed/untracked path" in summary


def test_changed_file_scan_reads_complete_formal_source_content(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    producer = tmp_path / "impl" / "tools" / "new_active_producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_text(
        "# first byte is harmless\n"
        "import json\n"
        "def persist(path, payload):\n"
        "    path.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues, summary = _scan_changed_and_untracked_files(tmp_path)

    assert [issue.code for issue in issues] == ["PATH_WRITER_BYPASS"]
    assert "inspected 1 changed/untracked path" in summary


def test_migration_ledger_rejects_unknown_project_and_probe(tmp_path: Path) -> None:
    ledger = tmp_path / "spec" / "adapter" / "config-prefixpath-20260721-ledger.yaml"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        yaml.safe_dump({
            "schema_version": 2,
            "baseline": "20260721",
            "probes": {"known": "tests/test_probe.py::test_probe"},
            "entries": [{
                "entry_id": "bad-entry",
                "project": "unknown",
                "historical_location": "old.path",
                "semantic_scope": "business_source",
                "lifecycle": "config_input",
                "canonical_target": {
                    "kind": "yaml_field",
                    "value": "impl/projects/unknown/project.yaml#project.resources.source",
                },
                "consumers": ["consumer"],
                "probe_id": "missing",
                "disposition": "migrate",
                "compatibility": {"status": "removed"},
            }],
        }, sort_keys=False),
        encoding="utf-8",
    )

    issues = _validate_path_migration_ledger(tmp_path, {"demo"})

    assert issues
    assert all(issue.code == "PATH_LEDGER_INVALID" for issue in issues)
    assert any("unknown" in issue.message for issue in issues)
    assert any("probe_id" in issue.message for issue in issues)
