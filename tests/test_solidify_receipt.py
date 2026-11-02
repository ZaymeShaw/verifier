from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from impl.core import solidify
from impl.core.path_contract import LogicalPathRef, PathResolver, PathRoots, PathScope
from impl.core.project_loader import (
    load_project,
    resolve_project_package_root,
    resolve_role_assets,
)
from impl.core.schema import (
    EvidenceRef,
    InvestigationArtifactRef,
    InvestigationManifest,
    ProjectSpec,
    dump_investigation_manifest,
)


def _judge_contract() -> dict:
    return {
        "schema_version": 1,
        "business_expectations": [{
            "expectation_id": "qualified-client-set",
            "user_role": "筛选目标客户的业务人员",
            "use_scenario": "按自然语言组合条件筛选客户",
            "desired_outcome": "获得满足完整筛选要求的客户集合",
        }],
        "live_boundary": {
            "live_role": "把自然语言筛选需求转换为下游查询",
            "in_scope_responsibilities": ["保留筛选条件", "交付可消费查询"],
            "out_of_scope_responsibilities": ["保证数据库存在匹配客户"],
            "external_constraints": ["客户数据库当前数据分布"],
        },
        "evaluation_dimensions": [{
            "dimension_id": "intent-completeness",
            "expectation_ids": ["qualified-client-set"],
            "name": "意图承接完整性",
            "evaluation_question": "查询是否完整承接明确筛选条件？",
            "fulfilled_when": ["所有明确条件均被正确表达"],
            "not_fulfilled_when": ["遗漏或错误改写明确条件"],
            "not_evaluable_when": ["无法取得查询或下游协议"],
        }],
        "mandatory_reviews": {
            "honest_refusal_is_not_fulfilled": "如实拒绝不是办成",
            "three_states_exclusive": "三态互斥",
            "no_escape": "不许逃逸",
        },
    }


def _mock_contract() -> dict:
    return {
        "schema_version": 1,
        "business_values": [{
            "value_id": "target-client-analysis",
            "beneficiary": "需要定位目标客户的业务人员",
            "business_need": "从大量客户中找到符合经营条件的群体",
            "system_contribution": "把自然语言需求转换为客户筛选查询",
            "desired_outcome": "获得可继续分析和触达的目标客户集合",
            "evidence_ref_ids": ["business-contract"],
        }],
        "evaluation_scope": {"dimensions": [{
            "dimension_id": "intent-completeness",
            "name": "意图承接完整性",
            "definition": "用户明确条件应被完整保留",
            "judgment_question": "Live 是否完整承接用户条件？",
            "evidence_ref_ids": ["business-contract"],
        }]},
        "demand_spaces": [{
            "space_id": "multi-condition-search",
            "name": "多条件客户筛选",
            "business_value_ids": ["target-client-analysis"],
            "demand_definition": "用户组合多种业务条件寻找目标客户",
            "evaluation_coverage": [{
                "dimension_id": "intent-completeness",
                "mock_data_requirement": "输入包含多个可独立核对且可变化的筛选条件",
            }],
            "variation_space": ["条件数量和类型变化"],
            "validity_constraints": ["同一用户事实内部一致"],
            "evidence_ref_ids": ["business-contract"],
        }],
    }


def _candidate_source(role: str) -> str:
    if role == "judge":
        return """from impl.core.judge_protocol import ProjectJudge\nclass DemoJudge(ProjectJudge):\n    def build_context(self, trace):\n        return {\"contract_consumed\": True}\n"""
    return """from impl.core.mock_protocol import ProjectMock\nfrom impl.core.schema import MockIntentOutput\nclass DemoMock(ProjectMock):\n    def build_user_intent(self, scenario):\n        return MockIntentOutput(user_intent=\"筛选目标客户\", query=\"帮我筛选一些客户\", user_context={\"scenario\": scenario})\n    def build_initial_request(self, intent):\n        return {\"query\": intent.query}\n"""


def _judge_boundary_sha256() -> str:
    boundary = _judge_contract()["live_boundary"]
    return hashlib.sha256(
        json.dumps(
            boundary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _context_asset_id(role: str) -> str:
    return "judge_business_contract" if role == "judge" else "mock_context"


def _project(tmp_path: Path, role: str, *, with_investigation: bool = True) -> ProjectSpec:
    verifier_root = tmp_path / "repo"
    project_root = verifier_root / "impl" / "projects" / "demo"
    package = project_root / "draft" / "investigation" / role
    docs = package / "docs"
    docs.mkdir(parents=True)
    (project_root / "adapter.py").write_text(
        "class Adapter:\n    def __init__(self, spec): self.spec = spec\n",
        encoding="utf-8",
    )
    (project_root / "draft").mkdir(exist_ok=True)
    (project_root / "draft" / f"{role}.py").write_text(
        _candidate_source(role), encoding="utf-8"
    )
    (project_root / "draft" / "context.md").write_text(
        "contract-derived context\n", encoding="utf-8"
    )
    smoke_path = project_root / "draft" / "probes" / f"{role}-solidify-smoke.json"
    smoke_path.parent.mkdir(parents=True)
    smoke_path.write_text('{"status":"succeeded"}\n', encoding="utf-8")
    (package / "overview.md").write_text("# overview\n", encoding="utf-8")
    (docs / "source.md").write_text("business source\n", encoding="utf-8")
    contract = _judge_contract() if role == "judge" else _mock_contract()
    contract_name = f"{role}-investigation-contract.json"
    (docs / contract_name).write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=2,
            project_id="demo",
            role=role,
            source_revision="rev-1",
            evidence_refs=[EvidenceRef(
                ref_id="business-contract",
                kind="document",
                location_ref=LogicalPathRef(
                    PathScope.ARTIFACT_PACKAGE,
                    "docs/source.md",
                ),
                metadata={"source_revision": "rev-1"},
            )],
            artifact_refs=[InvestigationArtifactRef(
                location=LogicalPathRef(
                    PathScope.ARTIFACT_PACKAGE,
                    f"docs/{contract_name}",
                ),
                purpose="role investigation contract",
            )],
        ),
        package / "manifest.json",
    )
    roots = PathRoots(
        verifier_repo=verifier_root.resolve(),
        project_package=project_root.resolve(),
        knowledge_route=project_root.resolve(),
        artifact_package=project_root.resolve(),
    )
    metadata = {}
    if role == "judge":
        metadata = {
            "product_expectation_ids": ["qualified-client-set"],
            "dimensions": ["intent-completeness"],
            "dimension_expectation_ids": {
                "intent-completeness": ["qualified-client-set"],
            },
            "product_use_scenarios": {
                "qualified-client-set": "按自然语言组合条件筛选客户",
            },
            "live_boundary_sha256": _judge_boundary_sha256(),
            "judgment_kinds": ["explicit_condition"],
        }
    assets = [{
        "asset_id": _context_asset_id(role),
        "kind": "context",
        "enabled": True,
        "roles": [role],
        "production_path": "project://context.md",
        "candidate_path": "project://draft/context.md",
        "replace": True,
        "metadata": metadata,
    }]
    if with_investigation:
        assets.insert(0, {
            "asset_id": f"{role}_investigation",
            "kind": "investigation",
            "enabled": True,
            "roles": [role],
            "production_path": f"project://investigation/{role}",
            "candidate_path": f"project://draft/investigation/{role}",
            "replace": True,
        })
    return ProjectSpec(
        project_id="demo",
        name="demo",
        verifier={
            "roles": {role: {"draft": {
                "enabled": True,
                "module": f"project://draft/{role}.py",
            }}},
            "assets": assets,
        },
        path_roots=roots,
        path_resolver=PathResolver(roots),
    )


def _mappings(role: str) -> list[dict]:
    if role == "judge":
        source_ids = [
            "live_boundary",
            "expectation:qualified-client-set",
            "dimension:intent-completeness",
        ]
    else:
        source_ids = [
            "business_value:target-client-analysis",
            "dimension:intent-completeness",
            "demand_space:multi-condition-search",
        ]
    return [{
        "mapping_id": f"{role}-contract-to-context",
        "source_ids": source_ids,
        "asset_ids": [_context_asset_id(role), "candidate_role"],
        "runtime_observables": [f"{role}-smoke"],
    }]


def _observables(role: str) -> list[dict]:
    return [{
        "observable_id": f"{role}-smoke",
        "status": "succeeded",
        "evidence": f"draft/probes/{role}-solidify-smoke.json#status",
        "observed_asset_ids": [_context_asset_id(role), "candidate_role"],
    }]


@pytest.mark.parametrize("role", ["judge", "mock"])
def test_solidify_receipt_round_trip_uses_real_role_loader(
    tmp_path: Path, monkeypatch, role: str
):
    spec = _project(tmp_path, role)
    monkeypatch.setattr(
        solidify, "require_investigation_validation_receipt", lambda spec, role, **kwargs: {}
    )

    path = solidify.write_solidify_receipt(
        spec, role, mappings=_mappings(role), runtime_observables=_observables(role)
    )

    assert path.is_file()
    receipt = solidify.require_solidify_receipt(spec, role)
    assert receipt is not None
    assert receipt["required_source_ids"] == sorted(_mappings(role)[0]["source_ids"])


@pytest.mark.parametrize("role", ["judge", "mock"])
def test_solidify_rejects_missing_contract_mapping(tmp_path: Path, monkeypatch, role: str):
    spec = _project(tmp_path, role)
    monkeypatch.setattr(
        solidify, "require_investigation_validation_receipt", lambda spec, role, **kwargs: {}
    )
    mappings = _mappings(role)
    mappings[0]["source_ids"] = mappings[0]["source_ids"][:-1]

    with pytest.raises(ValueError, match="do not cover required contract IDs"):
        solidify.write_solidify_receipt(
            spec, role, mappings=mappings, runtime_observables=_observables(role)
        )


def test_solidify_rejects_unavailable_or_unobserved_assets(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path, "judge")
    monkeypatch.setattr(
        solidify, "require_investigation_validation_receipt", lambda spec, role, **kwargs: {}
    )
    unavailable = _mappings("judge")
    unavailable[0]["asset_ids"] = ["missing"]
    with pytest.raises(ValueError, match="unavailable asset ID"):
        solidify.write_solidify_receipt(
            spec,
            "judge",
            mappings=unavailable,
            runtime_observables=_observables("judge"),
        )

    unobserved = _observables("judge")
    unobserved[0]["observed_asset_ids"] = ["candidate_role"]
    with pytest.raises(ValueError, match="absent from its runtime observables"):
        solidify.write_solidify_receipt(
            spec,
            "judge",
            mappings=_mappings("judge"),
            runtime_observables=unobserved,
        )


def test_solidify_receipt_becomes_stale_after_candidate_change(tmp_path: Path, monkeypatch):
    spec = _project(tmp_path, "mock")
    monkeypatch.setattr(
        solidify, "require_investigation_validation_receipt", lambda spec, role, **kwargs: {}
    )
    solidify.write_solidify_receipt(
        spec,
        "mock",
        mappings=_mappings("mock"),
        runtime_observables=_observables("mock"),
    )
    spec.role_draft_path("mock").write_text(_candidate_source("mock") + "\n# changed\n")

    with pytest.raises(ValueError, match="candidate_role_sha256 changed"):
        solidify.require_solidify_receipt(spec, "mock")
    with pytest.raises(ValueError, match="candidate_role_sha256 changed"):
        solidify.require_solidify_receipt(
            spec,
            "mock",
            business_source_staleness_policy="warn",
        )


def test_no_investigation_asset_is_contextunit_empty_compatibility(tmp_path: Path):
    spec = _project(tmp_path, "judge", with_investigation=False)
    assert solidify.require_solidify_receipt(spec, "judge") is None


def test_solidify_rejects_business_contract_metadata_drift():
    spec = load_project("client_search")
    selected = resolve_role_assets(spec, "judge", use_candidate=True)
    drifted = []
    for item in selected:
        mapping = item["mapping"]
        if mapping.asset_id == "judge_business_contract":
            mapping = replace(
                mapping,
                metadata={
                    **dict(mapping.metadata or {}),
                    "product_use_scenarios": {
                        "find-target-customers": "任意请求均适用",
                    },
                },
            )
            item = {**item, "mapping": mapping}
        drifted.append(item)

    contract_path = (
        resolve_project_package_root(spec, must_exist=True)
        / "draft"
        / "investigation"
        / "judge"
        / "docs"
        / "judge-investigation-contract.json"
    )
    with pytest.raises(ValueError, match="use scenarios drifted"):
        solidify._validate_judge_business_contract_metadata(
            role="judge",
            contract_path=contract_path,
            selected_assets=drifted,
        )


def test_authority_source_ids_require_frozen_claim_gate():
    with pytest.raises(ValueError, match="validated authority claim gate"):
        solidify._required_authority_source_ids({"coverage_gaps": 1})

    source_ids = solidify._required_authority_source_ids({
        "coverage_gaps": 1,
        "authority_claim_gate": {
            "claims_sha256": "a" * 64,
            "probes": [{"probe_id": "probe-one"}],
        },
    })

    assert source_ids == [
        "authority-claim-index",
        "authority-coverage-gaps",
        "authority-investigation-report",
        "authority-search-load",
    ]


def test_authority_runtime_replay_rejects_simulated_smoke(tmp_path: Path):
    evidence = tmp_path / "draft" / "probes" / "smoke.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "checks": {
            "claim_gate": {"probes": [{"subject_id": "subject:one"}]},
            "authorities": {"gap": {"case_time": {"without_decisive_evidence": "not_evaluable"}}},
        }
    }), encoding="utf-8")
    probes = [{"subject_id": "subject:one", "expected_status": "unresolved"}]
    observables = [{"evidence": "draft/probes/smoke.json#status"}]

    with pytest.raises(ValueError, match="Authority Runtime Replay missing"):
        solidify._validate_authority_runtime_replay(
            observables, project_root=tmp_path, probes=probes
        )


def test_authority_runtime_replay_accepts_real_tool_audit_shape(tmp_path: Path):
    evidence = tmp_path / "draft" / "probes" / "smoke.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "checks": {"authority_runtime_replay": {"probe_results": [
            {
                "subject_id": "subject:resolved",
                "status": "resolved",
                "tool_call_id": "authority.demo.abc",
                "tool_audit_present": True,
                "environment_snapshot_sha256": "snapshot",
            },
            {
                "subject_id": "subject:unresolved",
                "status": "unresolved",
                "tool_call_id": "authority.demo.def",
                "tool_audit_present": True,
                "environment_snapshot_sha256": "snapshot",
            },
        ]}}
    }), encoding="utf-8")
    probes = [
        {"subject_id": "subject:resolved", "expected_status": "resolved"},
        {"subject_id": "subject:unresolved", "expected_status": "unresolved"},
    ]

    solidify._validate_authority_runtime_replay(
        [{"evidence": "draft/probes/smoke.json#status"}],
        project_root=tmp_path,
        probes=probes,
    )
