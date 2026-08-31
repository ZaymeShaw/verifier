"""资料系统：槽位门禁、内容封口、binding 预算、material:// 引用、V1.5 物化导出。"""
from __future__ import annotations

import hashlib

import pytest

from impl.core import materials_store
from impl.core.materials_materialize import MaterializeError, materialize_evidence, materialize_project
from impl.core.path_contract import LogicalPathRef, PathScope
from impl.core.schema import EvidenceRef, InvestigationManifest


SLOTS_YAML = """
slots:
  - slot_id: glossary
    title: 口径表
    description: judge 依据
    required: true
    roles: [judge]
  - slot_id: notes
    title: 补充说明
    required: false
    roles: [judge]
"""


@pytest.fixture
def demo_project(tmp_path, monkeypatch):
    root = tmp_path / "impl"
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "projects" / "demo" / "materials.yaml").write_text(SLOTS_YAML, encoding="utf-8")
    monkeypatch.setattr(materials_store, "ROOT", root)
    return "demo"


def test_missing_required_slot_blocks(demo_project):
    with pytest.raises(ValueError, match="口径表"):
        materials_store.require_materials(demo_project)
    with pytest.raises(ValueError, match="必填资料槽位"):
        materials_store.binding_materials_for_role(demo_project, "judge")


def test_fill_slot_passes_gate_and_binds(demo_project):
    manifest = materials_store.save_material(
        demo_project, "glossary", content="字段A：含义A", title="口径表"
    )
    assert manifest["sha256"]
    materials_store.require_materials(demo_project)  # 不再抛错
    listing = materials_store.list_materials(demo_project)
    status = {slot["slot_id"]: slot["status"] for slot in listing["slots"]}
    assert status == {"glossary": "filled", "notes": "missing"}
    bound = materials_store.binding_materials_for_role(demo_project, "judge")
    assert len(bound) == 1
    assert bound[0]["content"] == "字段A：含义A"
    assert bound[0]["uri"] == "material://demo/glossary"


def test_binding_budget_enforced(demo_project):
    materials_store.save_material(demo_project, "glossary", content="x" * 20000)
    materials_store.save_material(demo_project, "notes", content="y" * 20000)
    with pytest.raises(ValueError, match="预算"):
        materials_store.binding_materials_for_role(demo_project, "judge")


def test_free_material_and_uri_resolution(demo_project):
    materials_store.save_material(demo_project, "doc-1", content="自由资料正文", title="文档一")
    listing = materials_store.list_materials(demo_project)
    assert [item["id"] for item in listing["free"]] == ["doc-1"]
    assert materials_store.resolve_material_uri("material://demo/doc-1") == "自由资料正文"
    materials_store.delete_material(demo_project, "doc-1")
    with pytest.raises(ValueError, match="不存在"):
        materials_store.resolve_material_uri("material://demo/doc-1")


def test_list_materials_exposes_insertable_references(demo_project):
    """资料页下拉用：references 只含已填充、合法的 material:// URI。"""
    materials_store.save_material(demo_project, "glossary", content="x")
    materials_store.save_material(demo_project, "doc-1", content="y", title="文档一")
    listing = materials_store.list_materials(demo_project)
    uris = {item["uri"] for item in listing["references"]}
    assert "material://demo/glossary" in uris
    assert "material://demo/doc-1" in uris
    by_uri = {item["uri"]: item for item in listing["references"]}
    assert by_uri["material://demo/doc-1"]["title"] == "文档一"
    # notes 槽位未填，不应进 references
    assert "material://demo/notes" not in uris


def test_expand_material_uris_inlines_embedded_reference(demo_project):
    """唯一合法记号是 {material://<project>/<id>}；定界符让前后可粘连。"""
    materials_store.save_material(demo_project, "api-spec", content="字段：姓名、手机号", title="口径")
    expanded = materials_store.expand_material_uris(
        "字段口径见 {material://demo/api-spec}。以上为准。"
    )
    assert "字段：姓名、手机号" in expanded
    assert "--- material://demo/api-spec ---" in expanded
    assert expanded.startswith("字段口径见")
    # 粘连也安全
    glued = materials_store.expand_material_uris("见{material://demo/api-spec}即可")
    assert "字段：姓名、手机号" in glued


def test_expand_material_uris_rejects_malformed_identifier(demo_project):
    """疑似引用但不是 {material://} 记号时报错，不再静默当普通文本。"""
    for bad in (
        "见 material://demo/NoSuch",
        "见 material://demo/a/b",
        "见 material://demo/中文",
        "见 material://demo/api-spec 。以上为准。",   # 裸写也拦
        "见material://demo/api-spec即可",
    ):
        with pytest.raises(ValueError, match="不是合法记号"):
            materials_store.expand_material_uris(bad)


def test_expand_material_uris_passes_plain_text(demo_project):
    assert materials_store.expand_material_uris("见说明书，按姓名检索") == "见说明书，按姓名检索"
    assert materials_store.expand_material_uris("字段口径见附件 material 文档") == "字段口径见附件 material 文档"


def test_expand_material_uris_rejects_over_budget(demo_project):
    materials_store.save_material(demo_project, "huge", content="x" * 200, title="大资料")
    with pytest.raises(ValueError, match="上限"):
        materials_store.expand_material_uris(
            "见 {material://demo/huge}",
            budget=50,
        )


def test_content_tamper_detected(demo_project):
    materials_store.save_material(demo_project, "glossary", content="原始内容")
    content_path = (
        materials_store.materials_root(demo_project) / "glossary" / materials_store.CONTENT_FILENAME
    )
    content_path.write_text("被绕过 API 手改的内容", encoding="utf-8")
    with pytest.raises(ValueError, match="哈希"):
        materials_store.read_content(demo_project, "glossary")
    with pytest.raises(ValueError, match="哈希"):
        materials_store.binding_materials_for_role(demo_project, "judge")


def test_path_traversal_rejected(demo_project):
    with pytest.raises(ValueError, match="非法"):
        materials_store.save_material("../evil", "x", content="c")
    with pytest.raises(ValueError, match="非法"):
        materials_store.delete_material(demo_project, "../evil")
    with pytest.raises(ValueError, match="格式"):
        materials_store.resolve_material_uri("material://demo/a/b")


def test_slot_declaration_validated(demo_project, monkeypatch):
    path = materials_store.ROOT / "projects" / "demo" / "materials.yaml"
    path.write_text("slots:\n  - slot_id: bad\n    fill: [teleport]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fill 不支持"):
        materials_store.load_slots(demo_project)


def test_capability_material_reference(demo_project):
    materials_store.save_material(demo_project, "cap-doc", content="能力口径全文……")
    from impl.projects.llm_probe.capability import resolve_capability

    text = resolve_capability({"capability": "{material://demo/cap-doc}"})
    assert text == "能力口径全文……"


def test_get_material_returns_body(demo_project):
    materials_store.save_material(demo_project, "glossary", content="字段A：含义A", title="口径表")
    loaded = materials_store.get_material(demo_project, "glossary")
    assert loaded["content"] == "字段A：含义A"
    assert loaded["id"] == "glossary"
    assert loaded["sha256"]
    with pytest.raises(ValueError, match="不存在"):
        materials_store.get_material(demo_project, "notes")


def test_batch_run_requires_materials(demo_project):
    from impl.core import pipeline

    with pytest.raises(ValueError, match="口径表"):
        pipeline.batch_run(demo_project, [{"id": "c1"}])
    empty = pipeline.batch_run("llm_probe", [])
    assert empty.total == 0


def test_material_content_resolver(demo_project):
    from impl.core.context.models import ContextUnitRecord
    from impl.core.context.resolvers import standard_content_resolver

    materials_store.save_material(demo_project, "glossary", content="resolver-body")
    record = ContextUnitRecord(
        id="u1",
        name="glossary",
        description="slot",
        content=None,
        content_ref="material://demo/glossary",
        project_id="demo",
        scope="project",
        roles=("judge",),
        unit_type="document",
        source_type="material",
    )
    text = standard_content_resolver().resolve("material://demo/glossary", record)
    assert text == "resolver-body"


def test_client_search_required_slot_is_filled():
    materials_store.require_materials("client_search")
    bound = materials_store.binding_materials_for_role("client_search", "judge")
    assert bound and bound[0]["id"] == "field_glossary"
    assert "clientAge" in bound[0]["content"]


def test_llm_probe_has_no_required_slots():
    assert materials_store.load_slots("llm_probe") == []
    materials_store.require_materials("llm_probe")


def test_edit_downgrades_investigation_provenance(demo_project):
    materials_store.save_material(
        demo_project, "glossary", content="调查原样内容",
        provenance={"source": "investigation", "detail": "rev abc123"},
    )
    # 同内容重存：provenance 原样保留
    kept = materials_store.save_material(demo_project, "glossary", content="调查原样内容")
    assert kept["provenance"] == {"source": "investigation", "detail": "rev abc123"}
    # 改内容：降级 derived + edited，出处保留
    edited = materials_store.save_material(demo_project, "glossary", content="人手改过的内容")
    assert edited["provenance"]["source"] == "derived"
    assert edited["provenance"]["edited"] is True
    assert edited["provenance"]["derived_from"] == "investigation"
    assert edited["provenance"]["detail"] == "rev abc123"
    # 纯上传资料改内容：不降级
    materials_store.save_material(demo_project, "notes", content="v1")
    plain = materials_store.save_material(demo_project, "notes", content="v2")
    assert plain["provenance"] == {"source": "user_upload"}


def test_stores_declaration(demo_project):
    path = materials_store.ROOT / "projects" / "demo" / "materials.yaml"
    assert materials_store.load_stores(demo_project) == []
    path.write_text("stores:\n  - capability_map\n", encoding="utf-8")
    assert materials_store.load_stores(demo_project) == ["capability_map"]
    assert materials_store.load_slots(demo_project) == []  # slots 变为可选
    path.write_text("stores:\n  - unknown_store\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stores 不支持"):
        materials_store.load_stores(demo_project)


def test_overview_sections_declaration_driven():
    from impl.core.materials_overview import project_overview

    cs = project_overview("client_search")
    cs_kinds = [section["kind"] for section in cs["sections"]]
    assert "investigation" in cs_kinds
    assert "system_assets" in cs_kinds
    assert "capability_map" not in cs_kinds  # client_search 未声明 stores
    investigation = next(s for s in cs["sections"] if s["kind"] == "investigation")
    assert not investigation["editable"]
    judge_pkg = next(i for i in investigation["items"] if i["asset_id"] == "judge_investigation")
    assert judge_pkg["production_exists"] is True
    assert judge_pkg["manifest"] and judge_pkg["manifest"].get("source_revision")

    lp = project_overview("llm_probe")
    lp_kinds = [section["kind"] for section in lp["sections"]]
    assert "capability_map" in lp_kinds  # llm_probe 声明了 stores
    slots_section = next(s for s in lp["sections"] if s["kind"] == "slots")
    assert slots_section["slots"] == []
    sample_uris = {item["uri"] for item in lp.get("references") or []}
    assert "material://llm_probe/client-search-match-rule" in sample_uris


def test_asset_view_readonly_projection():
    from impl.core.materials_overview import asset_view

    view = asset_view("client_search", "judge_investigation")
    assert view["asset_kind"] == "investigation"
    assert view["manifest"].get("source_revision")
    assert view["files"], "调查包应展示文件清单"
    assert "content" in view  # overview.md
    with pytest.raises(ValueError, match="没有资产"):
        asset_view("client_search", "no-such-asset")


def test_asset_view_reports_actually_active_package():
    """asset_view 展示的必须是 runtime 真正读的那个包（role draft.enabled → candidate）。"""
    from impl.core.materials_overview import asset_view, project_overview

    # client_search judge draft.enabled=true 且有 candidate_path：生效 draft 候选包
    judge = asset_view("client_search", "judge_investigation")
    assert judge["active_source"] == "candidate"
    assert judge["active_path"] == judge["candidate_path"]
    assert judge["candidate_path"].startswith("project://draft/")

    # client_search attribute draft.enabled=true 且有 candidate_path：生效 draft 候选包
    attribute = asset_view("client_search", "attribute_investigation")
    assert attribute["active_source"] == "candidate"
    assert attribute["active_path"] == attribute["candidate_path"]
    assert attribute["candidate_path"].startswith("project://draft/")

    # overview 列表两个 exists 都保留，并标注 active_source
    overview = project_overview("client_search")
    investigation = next(s for s in overview["sections"] if s["kind"] == "investigation")
    items = {item["asset_id"]: item for item in investigation["items"]}
    assert items["judge_investigation"]["active_source"] == "candidate"
    assert items["attribute_investigation"]["active_source"] == "candidate"
    assert "production_exists" in items["attribute_investigation"]
    assert "candidate_exists" in items["attribute_investigation"]


def test_asset_view_expands_business_source_evidence():
    """调查对象清单必须把被调查的业务源码文件逐份列出，不能只给计数。"""
    from impl.core.materials_overview import asset_view

    view = asset_view("client_search", "judge_investigation")
    evidence = view["evidence_refs"]
    business = [ref for ref in evidence if ref["scope"] == "business_source"]
    assert len(business) >= 10
    paths = {ref["path"] for ref in business}
    assert any("field_definitions_args.yaml" in path for path in paths)
    assert all(ref["source_revision"] for ref in business)
    assert evidence[0]["scope"] == "business_source", "业务源码证据应排在最前"
    assert "materialize" in (view.get("materialize_hint") or "")
    assert "client_search" in view["materialize_hint"]
    artifacts = view["artifact_refs"]
    assert any("experiments/" in (ref["path"] or "") for ref in artifacts), \
        "冻结的 key-index 实验产物是包的一部分，必须出现在清单里"


def test_asset_file_opens_package_and_rejects_traversal():
    from impl.core.materials_overview import asset_file

    opened = asset_file("client_search", "judge_investigation", "artifact_package", "overview.md")
    assert "Judge investigation" in opened["content"]
    doc = asset_file("client_search", "judge_investigation", "project_package", "judge_boundary_protocals.md")
    assert doc["content"].strip()
    with pytest.raises(ValueError, match="越界"):
        asset_file("client_search", "judge_investigation", "artifact_package", "../../evaluation.md")
    with pytest.raises(ValueError, match="scope"):
        asset_file("client_search", "judge_investigation", "elsewhere", "overview.md")
    with pytest.raises(ValueError, match="不可达"):
        asset_file("client_search", "judge_investigation", "artifact_package", "no-such-file.md")


def _business_tree(tmp_path, *, body="foo: 1\n", relative="src/config.yaml", ref_id="business-config"):
    source_root = tmp_path / "biz"
    path = source_root / relative
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = EvidenceRef(
        ref_id=ref_id,
        source="biz",
        kind="source",
        summary="config snapshot",
        location_ref=LogicalPathRef(PathScope.BUSINESS_SOURCE, relative, sha256=digest),
        metadata={"source_revision": "abc123", "sha256": digest},
    )
    manifest = InvestigationManifest(
        schema_version=2,
        project_id="demo",
        role="judge",
        source_revision="abc123",
        evidence_refs=[evidence],
    )
    return source_root, manifest, digest, body


def test_materialize_apply_writes_free_materials_not_bound_to_judge(demo_project, tmp_path):
    source_root, manifest, digest, body = _business_tree(tmp_path)
    materials_store.save_material(demo_project, "glossary", content="字段A：含义A")
    result = materialize_evidence(
        project_id=demo_project,
        role="judge",
        manifest=manifest,
        source_root=source_root,
        apply=True,
    )
    assert result["applied"] is True
    material_id = result["snapshots"][0]["id"]
    assert material_id == "judge-business-config"
    loaded = materials_store.get_material(demo_project, material_id)
    assert body.strip() in loaded["content"]
    assert digest in loaded["content"]
    assert loaded["provenance"]["source"] == "investigation"
    assert loaded["provenance"]["execution"] == "local"
    assert loaded["provenance"]["source_ref"]["sha256"] == digest
    assert loaded["provenance"]["source_ref"]["location"] == "src/config.yaml"
    index = materials_store.get_material(demo_project, result["index_id"])
    assert "material://demo/judge-business-config" in index["content"]
    free_ids = [item["id"] for item in materials_store.list_materials(demo_project)["free"]]
    assert material_id in free_ids
    assert result["index_id"] in free_ids
    bound = materials_store.binding_materials_for_role(demo_project, "judge")
    assert [item["id"] for item in bound] == ["glossary"]


def test_materialize_candidate_ids_coexist_with_production(demo_project, tmp_path):
    """candidate 来源带 -draft- 中缀，不覆盖 production 物化结果。"""
    source_root, manifest, digest, body = _business_tree(tmp_path)
    prod = materialize_evidence(
        project_id=demo_project,
        role="judge",
        manifest=manifest,
        source_root=source_root,
        apply=True,
    )
    draft = materialize_evidence(
        project_id=demo_project,
        role="judge",
        manifest=manifest,
        source_root=source_root,
        apply=True,
        package_source="candidate",
    )
    assert prod["package_source"] == "production"
    assert draft["package_source"] == "candidate"
    assert prod["snapshots"][0]["id"] == "judge-business-config"
    assert draft["snapshots"][0]["id"] == "judge-draft-business-config"
    assert draft["index_id"] == "judge-draft-investigation-snapshot"
    free_ids = [item["id"] for item in materials_store.list_materials(demo_project)["free"]]
    assert "judge-business-config" in free_ids
    assert "judge-draft-business-config" in free_ids
    loaded = materials_store.get_material(demo_project, "judge-draft-business-config")
    assert loaded["provenance"]["package_source"] == "candidate"
    kept = materials_store.get_material(demo_project, "judge-business-config")
    assert kept["provenance"]["package_source"] == "production"


def test_materialize_source_selection_follows_runtime():
    """auto 跟随 role draft.enabled（与 runtime 一致）；candidate/production 强制。"""
    from impl.core.materials_materialize import _use_candidate_for_source

    class Spec:
        def role_draft(self, role):
            return {"enabled": True} if role == "attribute" else {}

    spec = Spec()
    assert _use_candidate_for_source(spec, "attribute", "auto") is True
    assert _use_candidate_for_source(spec, "judge", "auto") is False
    assert _use_candidate_for_source(spec, "judge", "candidate") is True
    assert _use_candidate_for_source(spec, "attribute", "production") is False
    with pytest.raises(MaterializeError, match="source"):
        _use_candidate_for_source(spec, "judge", "bogus")


def test_materialize_dry_run_does_not_write(demo_project, tmp_path):
    source_root, manifest, _, _ = _business_tree(tmp_path)
    result = materialize_evidence(
        project_id=demo_project,
        role="judge",
        manifest=manifest,
        source_root=source_root,
        apply=False,
    )
    assert result["applied"] is False
    assert result["written"] == []
    assert materials_store.load_manifest(demo_project, result["snapshots"][0]["id"]) is None


def test_materialize_hash_mismatch_refuses_entire_export(demo_project, tmp_path):
    source_root, manifest, _, _ = _business_tree(tmp_path)
    (source_root / "src/config.yaml").write_text("changed: true\n", encoding="utf-8")
    with pytest.raises(MaterializeError, match="哈希"):
        materialize_evidence(
            project_id=demo_project,
            role="judge",
            manifest=manifest,
            source_root=source_root,
        )
    assert materials_store.list_materials(demo_project)["free"] == []


def test_materialize_missing_source_refuses(demo_project):
    manifest = InvestigationManifest(
        schema_version=2,
        project_id="demo",
        role="judge",
        source_revision="abc123",
        evidence_refs=[
            EvidenceRef(
                ref_id="business-config",
                kind="source",
                location_ref=LogicalPathRef(
                    PathScope.BUSINESS_SOURCE,
                    "src/config.yaml",
                    sha256="a" * 64,
                ),
            )
        ],
    )
    with pytest.raises(MaterializeError, match="业务源码根不可达"):
        materialize_evidence(
            project_id=demo_project,
            role="judge",
            manifest=manifest,
            source_root=None,
        )


def test_materialize_missing_file_refuses(demo_project, tmp_path):
    source_root, manifest, _, _ = _business_tree(tmp_path)
    (source_root / "src/config.yaml").unlink()
    with pytest.raises(MaterializeError, match="不存在"):
        materialize_evidence(
            project_id=demo_project,
            role="judge",
            manifest=manifest,
            source_root=source_root,
        )


def test_materialize_binding_slot_refuses_and_writes_nothing(demo_project, tmp_path):
    source_root, manifest, _, _ = _business_tree(tmp_path)
    with pytest.raises(MaterializeError, match="绑定"):
        materialize_evidence(
            project_id=demo_project,
            role="judge",
            manifest=manifest,
            source_root=source_root,
            apply=True,
            slot_id="glossary",
        )
    assert materials_store.load_manifest(demo_project, "glossary") is None
    assert materials_store.list_materials(demo_project)["free"] == []


def test_materialize_empty_roles_slot_ok(demo_project, tmp_path):
    path = materials_store.ROOT / "projects" / "demo" / "materials.yaml"
    path.write_text(
        SLOTS_YAML
        + """
  - slot_id: snapshot
    title: 调查快照
    required: false
    roles: []
""",
        encoding="utf-8",
    )
    source_root, manifest, _, body = _business_tree(tmp_path)
    materials_store.save_material(demo_project, "glossary", content="字段A：含义A")
    result = materialize_evidence(
        project_id=demo_project,
        role="judge",
        manifest=manifest,
        source_root=source_root,
        apply=True,
        slot_id="snapshot",
    )
    pack = materials_store.get_material(demo_project, "snapshot")
    assert body.strip() in pack["content"]
    assert pack["provenance"]["kind"] == "slot_pack"
    bound = materials_store.binding_materials_for_role(demo_project, "judge")
    assert [item["id"] for item in bound] == ["glossary"]
    assert result["slot_id"] == "snapshot"


def test_materialize_llm_probe_has_no_investigation():
    with pytest.raises(MaterializeError, match="investigation"):
        materialize_project("llm_probe", "judge")


def test_cli_materialize_llm_probe_exits(capsys):
    from impl.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["materialize", "--project", "llm_probe", "--role", "judge"])
    assert exc.value.code == 1
    assert "investigation" in capsys.readouterr().err


def test_cli_materialize_source_flags_mutually_exclusive(capsys):
    from impl.cli import main

    with pytest.raises(SystemExit) as exc:
        main([
            "materialize", "--project", "llm_probe", "--role", "judge",
            "--candidate", "--production",
        ])
    assert exc.value.code == 2  # argparse conflict


def test_cli_materialize_push_requires_apply(capsys):
    from impl.cli import main

    with pytest.raises(SystemExit) as exc:
        main([
            "materialize", "--project", "llm_probe", "--role", "judge",
            "--push", "user@host:/opt/verifier",
        ])
    assert exc.value.code == 1
    assert "--apply" in capsys.readouterr().err
