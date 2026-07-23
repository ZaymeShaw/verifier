from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from impl.core.project_loader import load_project, load_project_role_tools, resolve_role_assets
from impl.core.investigation import validate_investigation_package
from impl.core.investigation_validation import (
    require_investigation_validation_receipt,
    write_investigation_validation_receipt,
)
from impl.core.path_contract import LogicalPathRef, PathResolver, PathRoots, PathScope
from impl.core.context.embedding import DeterministicHashEmbeddingProvider
from impl.core.context.project import load_role_mandatory_context, role_asset_context_records
from impl.core import draft_promotion
from impl.core.schema import (
    EvidenceRef,
    InvestigationManifest,
    ProjectSpec,
    RoleAssetMapping,
    ToolImplementationRef,
    ToolRequirement,
    dump_investigation_manifest,
    load_investigation_manifest,
    validate_investigation_manifest,
)


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _project_spec(
    project_root: Path,
    *,
    verifier_root: Path | None = None,
    business_root: Path | None = None,
    **kwargs,
) -> ProjectSpec:
    roots = PathRoots(
        verifier_repo=(verifier_root or project_root).resolve(),
        business_source=business_root.resolve() if business_root else None,
        project_package=project_root.resolve(),
        knowledge_route=project_root.resolve(),
        artifact_package=project_root.resolve(),
    )
    verifier = dict(kwargs.pop("verifier", {}) or {})
    roles = dict(verifier.get("roles") or {})
    for role in ("attribute", "judge", "mock", "live"):
        draft = kwargs.pop(f"{role}_draft", None)
        if draft is None:
            continue
        canonical_draft = dict(draft)
        module = str(canonical_draft.get("module") or "")
        if module and not module.startswith("project://"):
            canonical_draft["module"] = f"project://{module}"
        roles[role] = {**dict(roles.get(role) or {}), "draft": canonical_draft}
    if roles:
        verifier["roles"] = roles
    assets = []
    for mapping in kwargs.pop("role_assets", []):
        production = mapping.logical_production_path or f"project://{mapping.production_path}"
        candidate = mapping.logical_candidate_path or (
            f"project://{mapping.candidate_path}" if mapping.candidate_path else ""
        )
        assets.append({
            "asset_id": mapping.asset_id,
            "kind": mapping.kind,
            "enabled": mapping.enabled,
            "roles": list(mapping.roles),
            "production_path": production,
            "candidate_path": candidate,
            "replace": mapping.replace,
        })
    if assets:
        verifier["assets"] = assets
    return ProjectSpec(
        project_id=str(kwargs.pop("project_id", "demo")),
        name=str(kwargs.pop("name", "demo")),
        path_roots=roots,
        path_resolver=PathResolver(roots),
        verifier=verifier,
        **kwargs,
    )


def _manifest() -> InvestigationManifest:
    return InvestigationManifest(
        schema_version=1,
        project_id="demo",
        role="attribute",
        source_revision="abc123",
        evidence_refs=[
            EvidenceRef(
                ref_id="source-doc",
                kind="document",
                location="docs/source.md",
                metadata={"source_revision": "abc123"},
            )
        ],
        tool_requirements=[
            ToolRequirement(
                tool_id="demo.replay",
                description="Replay a business transformation",
                applicable_scenario="distinguish parsing from post-processing",
                parameters={"type": "object", "properties": {}, "required": []},
                implementation=ToolImplementationRef(
                    tool_id="demo.replay",
                    module_path="../tools/replay.py",
                    factory="build_replay_tool",
                ),
            )
        ],
        artifacts={"docs/traces/main.mmd": "verified business execution flow"},
    )


def test_investigation_manifest_json_round_trip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    original = _manifest()

    dump_investigation_manifest(original, path)
    loaded = load_investigation_manifest(path)
    validate_investigation_manifest(loaded)

    assert loaded == original


def test_legacy_manifest_writer_cannot_target_registered_active_package(tmp_path: Path):
    path = (
        tmp_path
        / "impl"
        / "projects"
        / "demo"
        / "draft"
        / "investigation"
        / "attribute"
        / "manifest.json"
    )
    path.parent.mkdir(parents=True)

    with pytest.raises(ValueError, match="schema v1 cannot be written"):
        dump_investigation_manifest(_manifest(), path)


def test_investigation_manifest_rejects_untraceable_or_large_evidence():
    manifest = _manifest()
    manifest.evidence_refs = [EvidenceRef(ref_id="made-up", kind="analysis")]
    with pytest.raises(ValueError, match="requires location or payload"):
        validate_investigation_manifest(manifest)


def test_package_rejects_changed_evidence_content_or_missing_function(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "judge"
    package.mkdir(parents=True)
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    source = tmp_path / "business.py"
    source.write_text("def actual_function():\n    return 1\n", encoding="utf-8")
    manifest = InvestigationManifest(
        schema_version=1,
        project_id="demo",
        role="judge",
        source_revision="abc",
        evidence_refs=[
            EvidenceRef(
                ref_id="business-function",
                kind="function",
                location=f"{source}:missing_function",
                metadata={"sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            )
        ],
    )
    dump_investigation_manifest(manifest, package / "manifest.json")

    with pytest.raises(ValueError, match="function symbol not found"):
        validate_investigation_package(package, project_root=tmp_path)

    manifest.evidence_refs[0].location = f"{source}:actual_function"
    manifest.evidence_refs[0].metadata["sha256"] = "0" * 64
    dump_investigation_manifest(manifest, package / "manifest.json")
    with pytest.raises(ValueError, match="content hash changed"):
        validate_investigation_package(package, project_root=tmp_path)

    manifest.evidence_refs = [
        EvidenceRef(ref_id="too-large", kind="trace", payload={"content": "x" * 20_000})
    ]
    with pytest.raises(ValueError, match="payload exceeds"):
        validate_investigation_manifest(manifest)


def test_business_source_evidence_is_bound_to_configured_repo_and_revision(tmp_path: Path):
    project = tmp_path / "verifier-project"
    package = project / "draft" / "investigation" / "attribute"
    source_root = tmp_path / "business-source"
    outside = tmp_path / "unrelated-source"
    package.mkdir(parents=True)
    source_root.mkdir()
    outside.mkdir()
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    business_file = source_root / "business.py"
    business_file.write_text("def run():\n    return 1\n", encoding="utf-8")
    unrelated_file = outside / "business.py"
    unrelated_file.write_text("def run():\n    return 2\n", encoding="utf-8")
    evidence = EvidenceRef(
        ref_id="business-source",
        kind="function",
        location=f"{business_file}:run",
        metadata={
            "source_revision": "revision-1",
            "sha256": hashlib.sha256(business_file.read_bytes()).hexdigest(),
        },
    )
    manifest = InvestigationManifest(
        schema_version=1,
        project_id="demo",
        role="attribute",
        source_revision="revision-1",
        evidence_refs=[evidence],
    )
    dump_investigation_manifest(manifest, package / "manifest.json")

    result = validate_investigation_package(
        package,
        project_root=project,
        source_root=source_root,
        expected_source_revision="revision-1",
    )
    assert result["source_revision_verified"] is True

    manifest.evidence_refs[0].location = f"{unrelated_file}:run"
    manifest.evidence_refs[0].metadata["sha256"] = hashlib.sha256(unrelated_file.read_bytes()).hexdigest()
    dump_investigation_manifest(manifest, package / "manifest.json")
    with pytest.raises(ValueError, match="outside the verifier project"):
        validate_investigation_package(
            package,
            project_root=project,
            source_root=source_root,
            expected_source_revision="revision-1",
        )

    manifest.evidence_refs[0].location = f"{business_file}:run"
    dump_investigation_manifest(manifest, package / "manifest.json")
    with pytest.raises(ValueError, match="does not match"):
        validate_investigation_package(
            package,
            project_root=project,
            source_root=source_root,
            expected_source_revision="revision-2",
        )


def test_tool_requirement_requires_implementation_or_explicit_gap():
    manifest = _manifest()
    manifest.tool_requirements = [
        ToolRequirement(
            tool_id="demo.missing",
            description="Missing verification",
            applicable_scenario="current gap",
            parameters={"type": "object", "properties": {}},
        )
    ]

    with pytest.raises(ValueError, match="requires implementation_gap"):
        validate_investigation_manifest(manifest)

    manifest.tool_requirements[0].implementation_gap = "business probe is not implemented"
    validate_investigation_manifest(manifest)


def test_role_asset_resolution_uses_same_permissions_and_candidate_switch(tmp_path: Path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "draft" / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "verify.py").write_text("production", encoding="utf-8")
    (tmp_path / "draft" / "tools" / "verify.py").write_text("candidate", encoding="utf-8")
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="verify",
                kind="tool",
                enabled=True,
                roles=["attribute"],
                production_path="tools/verify.py",
                candidate_path="draft/tools/verify.py",
            )
        ],
    )

    current = resolve_role_assets(spec, "attribute", use_candidate=False)
    draft = resolve_role_assets(spec, "attribute", use_candidate=True)

    assert current[0]["path"] == tmp_path / "tools" / "verify.py"
    assert current[0]["source"] == "production"
    assert draft[0]["path"] == tmp_path / "draft" / "tools" / "verify.py"
    assert draft[0]["source"] == "candidate"
    assert resolve_role_assets(spec, "judge", use_candidate=True) == []


def test_role_asset_resolution_fails_closed_for_missing_or_unsafe_candidate(tmp_path: Path):
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="missing",
                kind="context",
                enabled=True,
                roles=["attribute"],
                production_path="investigation/attribute",
                candidate_path="draft/investigation/attribute",
            )
        ],
    )
    with pytest.raises(FileNotFoundError, match="candidate role asset"):
        resolve_role_assets(spec, "attribute", use_candidate=True)

    spec.verifier["assets"][0] = {
        "asset_id": "unsafe",
        "kind": "context",
        "enabled": True,
        "roles": ["attribute"],
        "production_path": "project://../outside",
        "candidate_path": "",
        "replace": False,
    }
    with pytest.raises(ValueError, match="PATH_TRAVERSAL"):
        resolve_role_assets(spec, "attribute", use_candidate=False)

    spec.verifier["assets"][0] = {
        "asset_id": "wrong-layer",
        "kind": "context",
        "enabled": True,
        "roles": ["attribute"],
        "production_path": "project://draft/context.md",
        "candidate_path": "",
        "replace": False,
    }
    with pytest.raises(ValueError, match="outside draft"):
        resolve_role_assets(spec, "attribute", use_candidate=False)


def test_unpromoted_investigation_becomes_context_only_in_draft(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    package.mkdir(parents=True)
    (package / "overview.md").write_text("business flow", encoding="utf-8")
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="attribute_investigation",
                kind="investigation",
                enabled=True,
                roles=["attribute"],
                production_path="investigation/attribute",
                candidate_path="draft/investigation/attribute",
            )
        ],
    )

    assert role_asset_context_records(
        spec,
        role="attribute",
        use_candidate=False,
    ) == []
    draft_records = role_asset_context_records(
        spec,
        role="attribute",
        use_candidate=True,
    )

    assert [record.id for record in draft_records] == [
        "project.demo.asset.attribute_investigation"
    ]
    assert draft_records[0].content_ref == (package / "overview.md").resolve().as_uri()
    assert draft_records[0].roles == ("attribute",)


def test_attribute_investigation_package_validates_mermaid_and_tool(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    tools = tmp_path / "draft" / "tools"
    role_root = tmp_path / "role_contracts"
    traces.mkdir(parents=True)
    tools.mkdir(parents=True)
    (role_root / "attribute").mkdir(parents=True)
    (role_root / "attribute" / "ROLE.md").write_text("# Attribute", encoding="utf-8")
    (package / "overview.md").write_text("# demo investigation", encoding="utf-8")
    (traces / "main.mmd").write_text(
        "flowchart LR\n  INPUT[Input]\n  CORE[Core]\n  INPUT --> CORE\n",
        encoding="utf-8",
    )
    (traces / "main.md").write_text(
        "# Flow\n\n"
        "## How to use this trace map\nstart from the observed input\n\n"
        "## Operational index\n| Node | Observe | Verify | Boundary |\n|---|---|---|---|\n"
        "| INPUT | request | trace | no execution proof |\n"
        "| CORE | result | replay | no downstream proof |\n\n"
        "## Investigation procedure\nfollow INPUT to CORE and stop when replay is unavailable\n\n"
        "## Node: INPUT\ninput\n\n## Node: CORE\ncore\n",
        encoding="utf-8",
    )
    (tools / "replay.py").write_text(
        "from impl.tools.protocol import ToolResult, VerifiableTool\n"
        "def _run():\n"
        "    return ToolResult(tool_id='demo.replay', status='succeeded')\n"
        "def build_replay_tool():\n"
        "    return VerifiableTool(tool_id='demo.replay', description='Replay business flow', "
        "applicable_scenario='diagnosis', parameters={'type':'object','properties':{},'required':[]}, execute_fn=_run)\n",
        encoding="utf-8",
    )
    manifest = InvestigationManifest(
        schema_version=1,
        project_id="demo",
        role="attribute",
        source_revision="abc123",
        evidence_refs=[
            EvidenceRef(
                ref_id="flow-source",
                kind="document",
                location="docs/traces/main.md",
                metadata={"source_revision": "abc123"},
            )
        ],
        tool_requirements=[
            ToolRequirement(
                tool_id="demo.replay",
                description="Replay business flow",
                applicable_scenario="diagnosis",
                parameters={"type": "object", "properties": {}, "required": []},
                implementation=ToolImplementationRef(
                    tool_id="demo.replay",
                    module_path="draft/tools/replay.py",
                    factory="build_replay_tool",
                ),
            )
        ],
        artifacts={
            "docs/traces/main.mmd": "business flow",
            "docs/traces/main.md": "node evidence",
        },
    )
    dump_investigation_manifest(manifest, package / "manifest.json")

    result = validate_investigation_package(
        package,
        project_root=tmp_path,
        expected_project_id="demo",
        expected_role="attribute",
        role_contract_root=role_root,
        execute_tools=True,
    )

    assert result["ok"] is True
    assert result["tools"][0]["execution"] == "succeeded"
    assert result["mermaid_nodes"][str(traces / "main.mmd")] == ["INPUT", "CORE"]


def test_attribute_trace_requires_every_mermaid_node_in_operational_index(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    traces.mkdir(parents=True)
    (package / "overview.md").write_text("# overview\n", encoding="utf-8")
    (traces / "main.mmd").write_text(
        "flowchart LR\n  INPUT[Input]\n  CORE[Core]\n  INPUT --> CORE\n",
        encoding="utf-8",
    )
    (traces / "main.md").write_text(
        "# Flow\n\n"
        "## How to use this trace map\nstart at INPUT\n\n"
        "## Operational index\n| Node | Verify |\n|---|---|\n| INPUT | trace |\n\n"
        "## Investigation procedure\nfollow the indexed nodes\n\n"
        "## Node: INPUT\ninput\n\n## Node: CORE\ncore\n",
        encoding="utf-8",
    )
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=1,
            project_id="demo",
            role="attribute",
            source_revision="abc123",
            artifacts={
                "docs/traces/main.mmd": "business flow",
                "docs/traces/main.md": "operational guide",
            },
        ),
        package / "manifest.json",
    )

    with pytest.raises(ValueError, match="missing from Operational index.*CORE"):
        validate_investigation_package(
            package,
            project_root=tmp_path,
            expected_project_id="demo",
            expected_role="attribute",
        )


def test_client_search_draft_blocks_tools_without_successful_execution_receipt(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "impl.core.investigation_validation.validation_receipt_path",
        lambda spec, role: tmp_path / role / "missing-receipt.json",
    )
    current = load_project("client_search")
    roles = dict(current.verifier.get("roles") or {})
    roles["attribute"] = {
        **dict(roles.get("attribute") or {}),
        "draft": {"enabled": True, "module": "project://draft/attribute.py"},
    }
    draft = replace(
        current,
        verifier={**current.verifier, "roles": roles},
    )

    with pytest.raises(FileNotFoundError, match="no successful Tool validation receipt"):
        load_project_role_tools(draft, "attribute")
    records = role_asset_context_records(
        draft,
        role="attribute",
        use_candidate=True,
    )

    assert {Path(record.content_ref.removeprefix("file://")).name for record in records} == {
        "overview.md",
        "client-search-parse.md",
        "client-search-parse.mmd",
    }
    assert all("manifest.json" not in record.content_ref for record in records)
    assert [record.id for record in records] == [
        "project.client_search.attribute.investigation.overview",
        "project.client_search.attribute.investigation.parse_flow",
        "project.client_search.attribute.investigation.parse_graph",
    ]


def test_candidate_tool_receipt_is_required_and_invalidated_by_code_change(tmp_path: Path):
    verifier_root = tmp_path / "verifier"
    project_root = verifier_root / "impl" / "projects" / "demo"
    package = project_root / "draft" / "investigation" / "attribute"
    tools = project_root / "draft" / "tools"
    package.mkdir(parents=True)
    tools.mkdir(parents=True)
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    tool_path = tools / "replay.py"
    tool_path.write_text(
        "from impl.tools.protocol import ToolResult, VerifiableTool\n"
        "def _run():\n    return ToolResult(tool_id='demo.replay', status='succeeded')\n"
        "def build_tool():\n"
        "    return VerifiableTool(tool_id='demo.replay', description='replay', "
        "applicable_scenario='attribute', parameters={'type':'object','properties':{}}, execute_fn=_run)\n",
        encoding="utf-8",
    )
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=2,
            project_id="demo",
            role="attribute",
            source_revision="revision-1",
            tool_requirements=[ToolRequirement(
                tool_id="demo.replay",
                description="replay",
                applicable_scenario="attribute",
                parameters={"type": "object", "properties": {}},
                    implementation=ToolImplementationRef(
                        tool_id="demo.replay",
                        module_path="tools/replay.py",
                        factory="build_tool",
                        module_ref=LogicalPathRef(
                            PathScope.PROJECT_PACKAGE,
                            "draft/tools/replay.py",
                        ),
                    ),
            )],
        ),
        package / "manifest.json",
    )
    spec = _project_spec(
        project_root,
        verifier_root=verifier_root,
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
        role_assets=[
            RoleAssetMapping(
                asset_id="investigation",
                kind="investigation",
                enabled=True,
                roles=["attribute"],
                production_path="investigation/attribute",
                candidate_path="draft/investigation/attribute",
            ),
            RoleAssetMapping(
                asset_id="replay",
                kind="tool",
                enabled=True,
                roles=["attribute"],
                production_path="tools/replay.py",
                candidate_path="draft/tools/replay.py",
            ),
        ],
    )
    result = validate_investigation_package(
        package,
        project_root=project_root,
        expected_project_id="demo",
        expected_role="attribute",
        execute_tools=True,
        tool_module_overrides={"tools/replay.py": tool_path},
    )
    write_investigation_validation_receipt(spec, "attribute", result, {})
    assert require_investigation_validation_receipt(spec, "attribute")["role"] == "attribute"

    tool_path.write_text(tool_path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Tool changed"):
        require_investigation_validation_receipt(spec, "attribute")


def test_investigation_package_rejects_missing_mermaid_companion_node(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    traces.mkdir(parents=True)
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    (traces / "main.mmd").write_text("flowchart LR\n  INPUT[Input]\n  CORE[Core]\n", encoding="utf-8")
    (traces / "main.md").write_text("## Node: INPUT\n", encoding="utf-8")
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=1,
            project_id="demo",
            role="attribute",
            source_revision="abc",
            artifacts={"docs/traces/main.mmd": "flow", "docs/traces/main.md": "nodes"},
        ),
        package / "manifest.json",
    )

    with pytest.raises(ValueError, match="CORE"):
        validate_investigation_package(package, project_root=tmp_path)


def test_attribute_trace_companion_requires_operational_usage_sections(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    traces.mkdir(parents=True)
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    (traces / "main.mmd").write_text(
        "flowchart LR\n  INPUT[Input]\n  CORE[Core]\n  INPUT --> CORE\n",
        encoding="utf-8",
    )
    (traces / "main.md").write_text(
        "## Node: INPUT\ninput\n\n## Node: CORE\ncore\n",
        encoding="utf-8",
    )
    manifest = InvestigationManifest(
        schema_version=1,
        project_id="demo",
        role="attribute",
        source_revision="abc123",
        evidence_refs=[
            EvidenceRef(
                ref_id="flow",
                kind="document",
                location="docs/traces/main.md",
                metadata={"source_revision": "abc123"},
            )
        ],
        artifacts={
            "docs/traces/main.mmd": "flow",
            "docs/traces/main.md": "operational guide",
        },
    )
    dump_investigation_manifest(manifest, package / "manifest.json")

    with pytest.raises(ValueError, match="lacks operational sections"):
        validate_investigation_package(package, project_root=tmp_path)


def test_package_execution_requires_and_runs_explicit_anyof_smoke_inputs(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "judge"
    tool_dir = tmp_path / "draft" / "tools"
    package.mkdir(parents=True)
    tool_dir.mkdir(parents=True)
    (package / "overview.md").write_text("# overview", encoding="utf-8")
    (tool_dir / "lookup.py").write_text(
        "from impl.tools import ToolResult, VerifiableTool\n"
        "def build_lookup():\n"
        "    def execute(**kwargs):\n"
        "        status = 'succeeded' if kwargs.get('keyword') == 'known' else 'inconclusive'\n"
        "        return ToolResult(tool_id='demo.lookup', status=status, actual=kwargs)\n"
        "    return VerifiableTool(tool_id='demo.lookup', description='lookup', "
            "applicable_scenario='review', parameters={'type':'object','properties':"
            "{'keyword':{'type':'string','description':'keyword selector'},"
            "'field':{'type':'string','description':'field selector'}},'required':[],"
        "'anyOf':[{'required':['keyword']},{'required':['field']}]}, execute_fn=execute)\n",
        encoding="utf-8",
    )
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=1,
            project_id="demo",
            role="judge",
            source_revision="abc",
            tool_requirements=[
                ToolRequirement(
                    tool_id="demo.lookup",
                    description="lookup",
                    applicable_scenario="review",
                    parameters={
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "keyword selector"},
                            "field": {"type": "string", "description": "field selector"},
                        },
                        "required": [],
                        "anyOf": [
                            {"required": ["keyword"]},
                            {"required": ["field"]},
                        ],
                    },
                    implementation=ToolImplementationRef(
                        tool_id="demo.lookup",
                        module_path="draft/tools/lookup.py",
                        factory="build_lookup",
                    ),
                )
            ],
        ),
        package / "manifest.json",
    )

    with pytest.raises(ValueError, match="requires smoke inputs"):
        validate_investigation_package(
            package,
            project_root=tmp_path,
            execute_tools=True,
        )

    result = validate_investigation_package(
        package,
        project_root=tmp_path,
        execute_tools=True,
        tool_test_inputs={"demo.lookup": [{"keyword": "known"}]},
    )

    assert result["tools"][0]["execution"] == "succeeded"
    assert result["tools"][0]["execution_count"] == 1

    with pytest.raises(RuntimeError, match="did not succeed"):
        validate_investigation_package(
            package,
            project_root=tmp_path,
            execute_tools=True,
            tool_test_inputs={"demo.lookup": [{"field": "unknown"}]},
        )

    with pytest.raises(ValueError, match="unknown or unimplemented"):
        validate_investigation_package(
            package,
            project_root=tmp_path,
            execute_tools=True,
            tool_test_inputs={"demo.typo": [{}]},
        )


def test_validate_investigation_cli_fails_when_required_tool_inputs_are_missing():
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / ".agents/skills/draft/scripts/validate_investigation.py"),
            "--project",
            "client_search",
            "--role",
            "attribute",
            "--execute-tools",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert result.returncode != 0
    assert "requires smoke inputs" in result.stderr


def test_check_draft_promotion_requires_nonempty_successful_unseen_cases():
    script = _REPO_ROOT / ".agents/skills/draft/scripts/check_draft.py"
    common = [
        sys.executable,
        str(script),
        "--project",
        "client_search",
        "--role",
        "attribute",
        "--promotion",
    ]
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    missing = subprocess.run(
        common,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )
    empty = subprocess.run(
        [*common, "--unseen-cases", "[]"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert missing.returncode != 0
    assert "not provided" in missing.stderr
    assert empty.returncode != 0
    assert "empty; generalization check failed" in empty.stderr


def test_judge_and_mock_load_only_their_mandatory_role_assets(tmp_path: Path):
    (tmp_path / "evaluation.md").write_text("judge contract", encoding="utf-8")
    (tmp_path / "mock.md").write_text("mock input rules", encoding="utf-8")
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="judge_contract",
                kind="context",
                enabled=True,
                roles=["judge"],
                production_path="evaluation.md",
            ),
            RoleAssetMapping(
                asset_id="mock_contract",
                kind="context",
                enabled=True,
                roles=["mock"],
                production_path="mock.md",
            ),
        ],
    )
    embedder = DeterministicHashEmbeddingProvider()

    judge = load_role_mandatory_context(
        spec,
        role="judge",
        operation="judge",
        embedding_provider=embedder,
    )
    mock = load_role_mandatory_context(
        spec,
        role="mock",
        operation="mock",
        embedding_provider=embedder,
    )

    assert judge is not None and judge["unit_ids"] == ["project.demo.asset.judge_contract"]
    assert "judge contract" in judge["content"]
    assert "mock input rules" not in judge["content"]
    assert mock is not None and mock["unit_ids"] == ["project.demo.asset.mock_contract"]
    assert "mock input rules" in mock["content"]
    assert "judge contract" not in mock["content"]


def test_mandatory_context_fails_when_enabled_asset_is_missing(tmp_path: Path):
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="judge_contract",
                kind="context",
                enabled=True,
                roles=["judge"],
                production_path="missing.md",
            )
        ],
    )

    with pytest.raises(FileNotFoundError, match="enabled Context role asset"):
        load_role_mandatory_context(
            spec,
            role="judge",
            operation="judge",
            embedding_provider=DeterministicHashEmbeddingProvider(),
        )


def test_unavailable_production_mandatory_context_does_not_change_current(tmp_path: Path):
    candidate = tmp_path / "draft" / "investigation" / "mock"
    candidate.mkdir(parents=True)
    (candidate / "contract.md").write_text("candidate-only contract", encoding="utf-8")
    spec = _project_spec(
        tmp_path,
        mock_draft={"enabled": False, "module": "draft/mock.py"},
        role_assets=[
            RoleAssetMapping(
                asset_id="mock_contract",
                kind="investigation",
                enabled=True,
                roles=["mock"],
                production_path="investigation/mock",
                candidate_path="draft/investigation/mock",
                replace=True,
            )
        ],
    )

    assert load_role_mandatory_context(
        spec,
        role="mock",
        operation="mock",
        embedding_provider=DeterministicHashEmbeddingProvider(),
    ) is None


def test_missing_selected_candidate_mandatory_context_fails_closed(tmp_path: Path):
    spec = _project_spec(
        tmp_path,
        mock_draft={"enabled": True, "module": "draft/mock.py"},
        role_assets=[
            RoleAssetMapping(
                asset_id="mock_contract",
                kind="investigation",
                enabled=True,
                roles=["mock"],
                production_path="investigation/mock",
                candidate_path="draft/investigation/mock",
                replace=True,
            )
        ],
    )

    with pytest.raises(FileNotFoundError, match="enabled candidate role asset"):
        load_role_mandatory_context(
            spec,
            role="mock",
            operation="mock",
            embedding_provider=DeterministicHashEmbeddingProvider(),
        )


def test_mandatory_context_accepts_a_symlinked_project_root(tmp_path: Path):
    actual_root = tmp_path / "actual"
    actual_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(actual_root, target_is_directory=True)
    (actual_root / "mock.md").write_text("symlink-safe contract", encoding="utf-8")
    spec = _project_spec(
        linked_root,
        role_assets=[
            RoleAssetMapping(
                asset_id="mock_contract",
                kind="context",
                enabled=True,
                roles=["mock"],
                production_path="mock.md",
            )
        ],
    )

    result = load_role_mandatory_context(
        spec,
        role="mock",
        operation="mock",
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )

    assert result is not None
    assert "symlink-safe contract" in result["content"]


def _promotion_spec(tmp_path: Path, *, shared: bool = False) -> ProjectSpec:
    (tmp_path / "draft" / "tools").mkdir(parents=True)
    (tmp_path / "draft" / "attribute.py").write_text("candidate role", encoding="utf-8")
    (tmp_path / "attribute.py").write_text("production role", encoding="utf-8")
    (tmp_path / "draft" / "tools" / "verify.py").write_text("candidate tool", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "project.yaml").write_text(
        "schema_version: 1\n"
        "project:\n"
        "  id: demo\n"
        "  name: demo\n"
        "verifier:\n"
        "  roles:\n"
        "    attribute:\n"
        "      draft:\n"
        "        enabled: true\n"
        "        module: project://draft/attribute.py\n"
        "    judge:\n"
        "      draft:\n"
        f"        enabled: {'true' if shared else 'false'}\n"
        "        module: project://draft/judge.py\n"
        "  assets:\n"
        "    - asset_id: verify\n"
        "      kind: tool\n"
        "      enabled: true\n"
        "      roles: [attribute]\n"
        "      production_path: project://tools/verify.py\n"
        "      candidate_path: project://draft/tools/verify.py\n"
        "      replace: true\n",
        encoding="utf-8",
    )
    return _project_spec(
        tmp_path,
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
        judge_draft={"enabled": shared, "module": "draft/judge.py"},
        role_assets=[
            RoleAssetMapping(
                asset_id="verify",
                kind="tool",
                enabled=True,
                roles=["attribute", "judge"] if shared else ["attribute"],
                production_path="tools/verify.py",
                candidate_path="draft/tools/verify.py",
                replace=True,
            )
        ],
    )


def test_draft_promotion_check_is_zero_write(tmp_path: Path):
    spec = _promotion_spec(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    plan = draft_promotion.plan_draft_promotion(spec, "attribute")

    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert [item["action"] for item in plan["operations"]] == ["move", "move"]


def test_draft_promotion_apply_moves_exclusive_assets_and_disables_switch(tmp_path: Path, monkeypatch):
    spec = _promotion_spec(tmp_path)
    monkeypatch.setattr(
        draft_promotion,
        "load_project",
        lambda project_id: _project_spec(tmp_path),
    )
    monkeypatch.setattr(draft_promotion, "load_adapter", lambda loaded: object())
    monkeypatch.setattr(draft_promotion, "load_project_role_instance", lambda loaded, role, adapter: object())

    result = draft_promotion.apply_draft_promotion(spec, "attribute")

    assert result["applied"] is True
    assert (tmp_path / "attribute.py").read_text(encoding="utf-8") == "candidate role"
    assert not (tmp_path / "draft" / "attribute.py").exists()
    assert (tmp_path / "tools" / "verify.py").read_text(encoding="utf-8") == "candidate tool"
    assert not (tmp_path / "draft" / "tools" / "verify.py").exists()
    assert "enabled: false" in (tmp_path / "project.yaml").read_text(encoding="utf-8")
    assert 'candidate_path: ""' in (tmp_path / "project.yaml").read_text(encoding="utf-8")


def test_draft_promotion_rejects_legacy_top_level_role_switch() -> None:
    legacy = (
        "schema_version: 1\n"
        "attribute_draft:\n"
        "  enabled: true\n"
        "  module: draft/attribute.py\n"
    )

    with pytest.raises(
        ValueError,
        match=r"verifier\.roles\.attribute\.draft",
    ):
        draft_promotion._disable_role_draft(legacy, "attribute")


def test_unavailable_production_role_asset_is_reported_to_current(tmp_path: Path):
    candidate = tmp_path / "draft" / "mock.md"
    candidate.parent.mkdir()
    candidate.write_text("candidate", encoding="utf-8")
    spec = _project_spec(
        tmp_path,
        role_assets=[
            RoleAssetMapping(
                asset_id="mock_contract",
                kind="context",
                enabled=True,
                roles=["mock"],
                production_path="mock.md",
                candidate_path="draft/mock.md",
            )
        ],
    )

    current = resolve_role_assets(spec, "mock", use_candidate=False)
    draft = resolve_role_assets(spec, "mock", use_candidate=True)

    assert current[0]["available"] is False
    assert current[0]["source"] == "production"
    assert draft[0]["available"] is True
    assert draft[0]["source"] == "candidate"


def test_draft_promotion_copies_asset_still_used_by_another_draft_role(tmp_path: Path):
    spec = _promotion_spec(tmp_path, shared=True)

    plan = draft_promotion.plan_draft_promotion(spec, "attribute")

    assert plan["operations"][1]["action"] == "copy"
    assert plan["operations"][1]["shared_consumers"] == ["judge"]


def test_draft_promotion_rolls_back_files_and_config_when_regression_load_fails(tmp_path: Path, monkeypatch):
    spec = _promotion_spec(tmp_path)
    original_config = (tmp_path / "project.yaml").read_bytes()
    monkeypatch.setattr(draft_promotion, "load_project", lambda project_id: spec)
    monkeypatch.setattr(draft_promotion, "load_adapter", lambda loaded: object())
    monkeypatch.setattr(
        draft_promotion,
        "load_project_role_instance",
        lambda loaded, role, adapter: (_ for _ in ()).throw(RuntimeError("regression failed")),
    )

    with pytest.raises(RuntimeError, match="regression failed"):
        draft_promotion.apply_draft_promotion(spec, "attribute")

    assert (tmp_path / "attribute.py").read_text(encoding="utf-8") == "production role"
    assert (tmp_path / "draft" / "attribute.py").read_text(encoding="utf-8") == "candidate role"
    assert not (tmp_path / "tools" / "verify.py").exists()
    assert (tmp_path / "draft" / "tools" / "verify.py").read_text(encoding="utf-8") == "candidate tool"
    assert (tmp_path / "project.yaml").read_bytes() == original_config
