"""调查增量门禁测试（spec/alg/investigate.md §1.8「增量门禁」）。

Gate 1 baseline：范围型复制 + 排除规则 + 逐字节校验 + 基线回执。
Gate 2 increment：drift 出范围 → 人确认 → 机器重钉 → 闭合校验。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from impl.core import investigation_lifecycle as lifecycle
from impl.core.investigation_lifecycle import InvestigationLifecycleError
from impl.core.path_contract import LogicalPathRef, PathResolver, PathRoots, PathScope
from impl.core.schema import EvidenceRef, InvestigationManifest, ProjectSpec
from impl.core.schema.investigation import (
    InvestigationArtifactRef,
    dump_investigation_manifest,
)
from impl.core.portable_artifact import write_portable_export
from impl.core.source_staleness import compute_slice_hashes, file_sha256

_JUDGE_CONTRACT = {
    "schema_version": 1,
    "business_expectations": [
        {
            "expectation_id": "find-target-customers",
            "user_role": "需要寻找目标客户的业务人员",
            "use_scenario": "用户通过自然语言描述目标客户群体并使用客户搜索产品",
            "desired_outcome": "获得符合其已表达筛选要求的客户集合",
        }
    ],
    "live_boundary": {
        "live_role": "将自然语言客户搜索要求转换为下游搜索服务可消费的结构化查询",
        "in_scope_responsibilities": ["完整保留用户已经表达或确认的筛选要求"],
        "out_of_scope_responsibilities": ["保证数据库中存在符合条件的客户"],
        "external_constraints": ["下游数据库不存在目标客户记录"],
    },
    "evaluation_dimensions": [
        {
            "dimension_id": "search-intent-preservation",
            "expectation_ids": ["find-target-customers"],
            "name": "搜索意图承接",
            "evaluation_question": "Live 的查询语义是否完整保留用户描述的目标客户范围？",
            "fulfilled_when": ["所有会改变目标客户集合的已表达要求均被保留"],
            "not_fulfilled_when": ["遗漏、增加或改变了会影响目标客户集合的条件"],
            "not_evaluable_when": ["无法取得或确认 Live 的实际输出"],
        }
    ],
    "mandatory_reviews": {
        "honest_refusal_is_not_fulfilled": "如实拒绝不等于办成。",
        "three_states_exclusive": "三态互斥，不得用第四态逃逸。",
        "no_escape": "不允许逃逸。",
    },
}

_FIELD_YAML_V1 = """\
fields:
  - field: alpha
    note: a
  - field: beta
    note: b
"""

_FIELD_YAML_V2 = """\
fields:
  - field: alpha
    note: a
  - field: beta
    note: b-changed
"""

_FIELD_SLICE_SPEC = {"mode": "field", "list_key": "fields", "field_key": "field"}


def _ref(business_file: Path, location: str, ref_id: str, revision: str) -> EvidenceRef:
    digest = file_sha256(business_file)
    return EvidenceRef(
        ref_id=ref_id,
        kind="source",
        location_ref=LogicalPathRef(PathScope.BUSINESS_SOURCE, location, sha256=digest),
        metadata={
            "sha256": digest,
            "source_revision": revision,
            "consumption": [{"consumer": "demo_tools", "mode": "key_live"}],
            "slice": _FIELD_SLICE_SPEC,
            "slice_hashes": compute_slice_hashes(business_file, _FIELD_SLICE_SPEC),
            "slice_hashes_source_sha256": digest,
            "key_index": {"entry_granularity": "field"},
        },
    )


def _business_manifest(file_a: Path, file_b: Path, boundary: Path, revision: str) -> InvestigationManifest:
    return InvestigationManifest(
        schema_version=2,
        project_id="demo",
        role="judge",
        source_revision=revision,
        evidence_refs=[
            _ref(file_a, "src/alpha.yaml", "business-alpha", revision),
            _ref(file_b, "src/beta.yaml", "business-beta", revision),
            EvidenceRef(
                ref_id="project-judge-boundary",
                kind="document",
                location_ref=LogicalPathRef(
                    PathScope.PROJECT_PACKAGE,
                    "judge_boundary_protocals.md",
                    sha256=file_sha256(boundary),
                ),
                metadata={"sha256": file_sha256(boundary), "source_revision": revision},
            ),
        ],
    )


@pytest.fixture
def gate_project(tmp_path, monkeypatch):
    verifier_root = tmp_path / "repo"
    project_root = verifier_root / "impl" / "projects" / "demo"
    business = tmp_path / "business"
    business_src = business / "src"
    business_src.mkdir(parents=True)
    file_a = business_src / "alpha.yaml"
    file_b = business_src / "beta.yaml"
    file_a.write_text(_FIELD_YAML_V1, encoding="utf-8")
    file_b.write_text(_FIELD_YAML_V1, encoding="utf-8")

    project_root.mkdir(parents=True)
    (project_root / "project.yaml").write_text("project_id: demo\n", encoding="utf-8")
    (project_root / "judge.py").write_text(
        "from impl.core.judge_protocol import ProjectJudge\n"
        "\n"
        "\n"
        "class ClientSearchJudge(ProjectJudge):\n"
        "    pass\n",
        encoding="utf-8",
    )
    boundary = project_root / "judge_boundary_protocals.md"
    boundary.write_text("judge boundary v1\n", encoding="utf-8")
    production = project_root / "investigation" / "judge"
    (production / "docs").mkdir(parents=True)
    manifest = _business_manifest(file_a, file_b, boundary, "rev-1")
    manifest.artifact_refs = [
        InvestigationArtifactRef(
            location=LogicalPathRef(
                PathScope.ARTIFACT_PACKAGE, "docs/judge-investigation-contract.json"
            ),
            purpose="judge contract",
        )
    ]
    # production 包不是 active artifact（registry 只拥有 */draft/investigation/*），
    # 用 portable export 写入。
    write_portable_export(production / "manifest.json", manifest.as_dict())
    (production / "overview.md").write_text("demo judge investigation\n", encoding="utf-8")
    (production / "docs" / "judge-investigation-contract.json").write_text(
        json.dumps(_JUDGE_CONTRACT, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    roots = PathRoots(
        verifier_repo=verifier_root.resolve(),
        project_package=project_root.resolve(),
        knowledge_route=project_root.resolve(),
        artifact_package=project_root.resolve(),
        business_source=business.resolve(),
    )
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        verifier={"assets": []},
        path_roots=roots,
        path_resolver=PathResolver(roots),
    )
    monkeypatch.setattr(lifecycle, "resolve_project_source_root", lambda _spec: business)
    return {
        "spec": spec,
        "project_root": project_root,
        "file_a": file_a,
        "file_b": file_b,
    }


def _draft_manifest(project_root: Path) -> dict:
    return json.loads(
        (project_root / "draft" / "investigation" / "judge" / "manifest.json")
        .read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Gate 1: baseline
# ---------------------------------------------------------------------------


def test_baseline_copies_byte_for_byte_and_writes_receipt(gate_project):
    spec = gate_project["spec"]
    receipt = lifecycle.create_baseline(spec, "judge")

    draft = gate_project["project_root"] / "draft" / "investigation" / "judge"
    assert receipt["gate"] == "baseline"
    assert receipt["source_revision"] == "rev-1"
    assert (draft / "manifest.json").is_file()
    assert receipt["files"] == {
        "manifest.json": file_sha256(draft / "manifest.json"),
        "overview.md": file_sha256(draft / "overview.md"),
        "docs/judge-investigation-contract.json": file_sha256(
            draft / "docs" / "judge-investigation-contract.json"
        ),
    }
    receipt_path = (
        gate_project["project_root"] / "draft" / ".state" / "judge" / "staleness"
        / "investigation-baseline.json"
    )
    assert receipt_path.is_file()


def test_baseline_excludes_backups_and_pycache(gate_project):
    spec = gate_project["spec"]
    production = gate_project["project_root"] / "investigation" / "judge"
    (production / "manifest.json.bak-reinvestigate").write_text("old", encoding="utf-8")
    cache_dir = production / "experiments" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "x.cpython-311.pyc").write_bytes(b"\x00")

    receipt = lifecycle.create_baseline(spec, "judge")

    draft = gate_project["project_root"] / "draft" / "investigation" / "judge"
    assert not (draft / "manifest.json.bak-reinvestigate").exists()
    assert not (draft / "experiments").exists()
    assert "manifest.json.bak-reinvestigate" in receipt["excluded"]
    assert "experiments/__pycache__/x.cpython-311.pyc" in receipt["excluded"]


def test_baseline_refuses_overwrite_without_force(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    with pytest.raises(InvestigationLifecycleError, match="已存在"):
        lifecycle.create_baseline(spec, "judge")
    receipt = lifecycle.create_baseline(spec, "judge", overwrite=True)
    assert receipt["gate"] == "baseline"


# ---------------------------------------------------------------------------
# Gate 2: drift（机器算范围）
# ---------------------------------------------------------------------------


def test_drift_requires_baseline_receipt(gate_project):
    with pytest.raises(InvestigationLifecycleError, match="Gate 1"):
        lifecycle.drift_report(gate_project["spec"], "judge")


def test_drift_reports_changed_slices_and_clean_refs(gate_project, capsys):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    gate_project["file_a"].write_text(_FIELD_YAML_V2, encoding="utf-8")

    payload = lifecycle.drift_report(spec, "judge")

    assert payload["needs_confirmation"] == ["business-alpha"]
    assert payload["clean"] == ["business-beta"]
    drifted = payload["drifted"][0]
    assert drifted["ref_id"] == "business-alpha"
    assert drifted["file_changed"] is True
    assert [change["slice_key"] for change in drifted["slice_changes"]] == ["field:beta"]
    out = capsys.readouterr().out
    assert "business-alpha" in out
    assert "field:beta" in out


def test_drift_no_change_reports_nothing_to_confirm(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    payload = lifecycle.drift_report(spec, "judge")
    assert payload["drifted"] == []
    assert payload["needs_confirmation"] == []
    assert payload["clean"] == ["business-alpha", "business-beta"]


# ---------------------------------------------------------------------------
# Gate 2: increment（机器执行确认范围 + 闭合校验）
# ---------------------------------------------------------------------------


def test_increment_repins_confirmed_refs_and_closes(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    gate_project["file_a"].write_text(_FIELD_YAML_V2, encoding="utf-8")
    payload = lifecycle.drift_report(spec, "judge")

    receipt = lifecycle.apply_increment(
        spec, "judge", payload["needs_confirmation"], source_revision="rev-2"
    )

    assert receipt["closure"]["passed"] is True
    assert receipt["updated"][0]["changed"] is True
    assert receipt["deferred_drift"] == []
    manifest = _draft_manifest(gate_project["project_root"])
    assert manifest["source_revision"] == "rev-2"
    alpha = next(ref for ref in manifest["evidence_refs"] if ref["ref_id"] == "business-alpha")
    beta = next(ref for ref in manifest["evidence_refs"] if ref["ref_id"] == "business-beta")
    assert alpha["location"]["sha256"] == file_sha256(gate_project["file_a"])
    assert alpha["metadata"]["sha256"] == file_sha256(gate_project["file_a"])
    assert alpha["metadata"]["source_revision"] == "rev-2"
    assert alpha["metadata"]["slice_hashes"] == compute_slice_hashes(
        gate_project["file_a"], _FIELD_SLICE_SPEC
    )
    # 未漂移的兄弟证据哈希不变，但 revision pin 同步
    assert beta["location"]["sha256"] == file_sha256(gate_project["file_b"])
    assert beta["metadata"]["source_revision"] == "rev-2"
    assert receipt["revision_pin_synced"] == ["business-beta"]


def test_increment_requires_nonempty_confirmed_scope(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    with pytest.raises(InvestigationLifecycleError, match="确认范围"):
        lifecycle.apply_increment(spec, "judge", [], source_revision="rev-2")


def test_increment_rejects_unknown_ref(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    with pytest.raises(InvestigationLifecycleError, match="未知"):
        lifecycle.apply_increment(spec, "judge", ["not-a-ref"], source_revision="rev-2")


def test_partial_confirmation_blocks_closure_until_remaining_refs_reconfirmed(gate_project):
    """只确认部分漂移时：拒绝落盘（带遗留漂移的 manifest 不允许写入），
    补齐确认后整包闭合。"""
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    gate_project["file_a"].write_text(_FIELD_YAML_V2, encoding="utf-8")
    gate_project["file_b"].write_text(_FIELD_YAML_V2, encoding="utf-8")

    with pytest.raises(InvestigationLifecycleError, match="确认范围不完整") as excinfo:
        lifecycle.apply_increment(spec, "judge", ["business-alpha"], source_revision="rev-2")
    assert "business-beta" in str(excinfo.value)

    # manifest 保持基线状态，未被部分确认污染：仍是旧哈希，与已变更的磁盘不符
    manifest = _draft_manifest(gate_project["project_root"])
    assert manifest["source_revision"] == "rev-1"
    beta = next(ref for ref in manifest["evidence_refs"] if ref["ref_id"] == "business-beta")
    assert beta["metadata"]["sha256"] != file_sha256(gate_project["file_b"])
    # 补齐确认范围后整包闭合
    receipt = lifecycle.apply_increment(
        spec, "judge", ["business-alpha", "business-beta"], source_revision="rev-2"
    )
    assert receipt["closure"]["passed"] is True
    manifest = _draft_manifest(gate_project["project_root"])
    assert manifest["source_revision"] == "rev-2"


# ---------------------------------------------------------------------------
# 物化 --candidate 的门禁挂接
# ---------------------------------------------------------------------------


def test_require_increment_closed_gate_sequence(gate_project):
    spec = gate_project["spec"]
    with pytest.raises(InvestigationLifecycleError, match="Gate 1"):
        lifecycle.require_increment_closed(spec, "judge")

    lifecycle.create_baseline(spec, "judge")
    with pytest.raises(InvestigationLifecycleError, match="Gate 2"):
        lifecycle.require_increment_closed(spec, "judge")

    gate_project["file_a"].write_text(_FIELD_YAML_V2, encoding="utf-8")
    payload = lifecycle.drift_report(spec, "judge")
    lifecycle.apply_increment(spec, "judge", payload["needs_confirmation"], source_revision="rev-2")
    lifecycle.require_increment_closed(spec, "judge")


# ---------------------------------------------------------------------------
# baseline 扩范围：薄 wrapper + candidate 资产完整性
# ---------------------------------------------------------------------------


def test_baseline_copies_production_role_impl_when_missing(gate_project):
    spec = gate_project["spec"]
    receipt = lifecycle.create_baseline(spec, "judge")
    draft_role = gate_project["project_root"] / "draft" / "judge.py"
    production_role = gate_project["project_root"] / "judge.py"
    assert draft_role.is_file()
    assert receipt["draft_role_impl"] == "copied"
    assert draft_role.read_bytes() == production_role.read_bytes()


def test_baseline_keeps_existing_draft_role_implementation(gate_project):
    spec = gate_project["spec"]
    wrapper = gate_project["project_root"] / "draft" / "judge.py"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("# real draft implementation\n", encoding="utf-8")
    receipt = lifecycle.create_baseline(spec, "judge")
    assert receipt["draft_role_impl"] == "existing"
    assert wrapper.read_text(encoding="utf-8") == "# real draft implementation\n"


def test_baseline_fails_closed_on_missing_candidate_asset(gate_project, monkeypatch):
    spec = gate_project["spec"]
    # 伪造一个声明了 candidate_path 但文件不存在的资产
    verifier = dict(spec.verifier)
    verifier["assets"] = (verifier.get("assets") or []) + [{
        "asset_id": "judge_extra",
        "kind": "context",
        "enabled": True,
        "roles": ["judge"],
        "production_path": "project://context/x.md",
        "candidate_path": "project://draft/context/x.md",
        "replace": True,
    }]
    spec.verifier = verifier
    with pytest.raises(InvestigationLifecycleError, match="candidate 资产缺失"):
        lifecycle.create_baseline(spec, "judge")


# ---------------------------------------------------------------------------
# drift 逻辑型漂移：只报不钉
# ---------------------------------------------------------------------------


def test_drift_reports_logic_drift_without_repinning(gate_project):
    spec = gate_project["spec"]
    lifecycle.create_baseline(spec, "judge")
    # 逻辑型资产（project_package 证据）内容变化：改业务文件无意义，改 manifest 登记的项目文件
    project_root = gate_project["project_root"]
    boundary = project_root / "judge_boundary_protocals.md"
    boundary.write_text("changed boundary\n", encoding="utf-8")

    payload = lifecycle.drift_report(spec, "judge")

    logic = [item for item in payload["logic_drift"] if item["ref_id"] == "project-judge-boundary"]
    assert logic, "逻辑型漂移必须被报告"
    assert logic[0]["reason"].startswith("content changed")
    # 逻辑型漂移不进待确认重钉范围
    assert "project-judge-boundary" not in payload["needs_confirmation"]
