"""证明力档位：担保档位优先，内容类型只是缺省映射（judge.md §6）。

覆盖四件事：
- 无显式担保元数据时，缺省映射与既有"conclusion_kind 即证明力"逐位一致（零迁移）；
- 显式 warrant_tier 覆盖内容类型；序列化零声明零变化；
- warrant_tier 档位非法在报告校验期即拒；
- warrant_tier 不得成为绕开 inlive_boundary 信任模型登记的旁路；
- 导航面暴露最终档位 proof_power，检索面含担保档位词。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from impl.core.authority_key_index import (
    MATERIAL_DECISION_INDEX_KEY,
    build_material_decision_key_index,
    build_material_decision_key_index_registry,
)
from impl.core.schema.investigation_judge import (
    AuthorityInvestigationReport,
    MaterialDecision,
    decision_proof_power,
    load_authority_investigation_report,
    render_authority_report_markdown,
    validate_authority_report,
)

_ALL_KINDS = ("current_behavior", "normative_rule", "external_fact", "inlive_boundary")
_LOCATION = "project_package:materials/field-catalog.yaml"
_EVIDENCE = {"field-catalog": _LOCATION}
_CLIENT_SEARCH_REPORT = Path(
    "impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json"
)


def _decision(**overrides) -> dict:
    base = {
        "conclusion_kind": "current_behavior",
        "governs": "字段目录当前口径",
        "statement": "字段目录列出当前可检索字段与操作符",
        "locator": "fields",
        "scenario": "承载性问答",
        "conditions": [],
    }
    base.update(overrides)
    return base


def _report(decisions: list[dict]) -> AuthorityInvestigationReport:
    return AuthorityInvestigationReport.from_dict({
        "schema_version": 2,
        "report_id": "warrant-tier-demo",
        "investigation_snapshot_id": "snap-1",
        "business_scope": "字段目录治理",
        "materials": [{
            "source_ref_id": "field-catalog",
            "source_location": _LOCATION,
            "decisions": decisions,
            "related_to": [],
            "connections": [],
            "limitations": [],
        }],
        "coverage_gaps": [],
    })


# ----------------------------------------------------- default mapping identity


def test_no_warrant_metadata_default_mapping_identical_to_today() -> None:
    for kind in _ALL_KINDS:
        decision = MaterialDecision.from_dict(_decision(conclusion_kind=kind))
        assert decision.warrant_tier == ""
        assert decision_proof_power(decision) == kind
        payload = decision.as_dict()
        assert "warrant_tier" not in payload
        assert MaterialDecision.from_dict(payload) == decision


def test_frozen_client_search_report_round_trips_unchanged() -> None:
    report = load_authority_investigation_report(_CLIENT_SEARCH_REPORT)
    assert AuthorityInvestigationReport.from_dict(report.as_dict()) == report
    for material in report.materials:
        for decision in material.decisions:
            assert decision.warrant_tier == ""
            assert decision_proof_power(decision) == decision.conclusion_kind


def test_frozen_report_navigation_proof_power_equals_content_type() -> None:
    report = load_authority_investigation_report(_CLIENT_SEARCH_REPORT)
    registry = build_material_decision_key_index_registry(report)
    index = build_material_decision_key_index(report)
    baseline = json.dumps(
        [entry.search_text for entry in index.entries], ensure_ascii=False,
    )
    assert "warrant_tier" not in baseline
    entry = next(
        item for item in index.entries
        if item.target_ref.startswith("material-decision://")
    )
    loaded, _ = registry.load(MATERIAL_DECISION_INDEX_KEY, entry.key)
    content = loaded["content"]
    assert content["proof_power"] == content["decision"]["conclusion_kind"]
    assert "warrant_tier" not in content["decision"]


# ------------------------------------------------------ explicit warrant wins


def test_declared_warrant_tier_overrides_content_type() -> None:
    decision = MaterialDecision.from_dict(
        _decision(warrant_tier="external_fact")
    )
    assert decision.conclusion_kind == "current_behavior"
    assert decision_proof_power(decision) == "external_fact"
    payload = decision.as_dict()
    assert payload["warrant_tier"] == "external_fact"
    assert MaterialDecision.from_dict(payload) == decision


def test_markdown_renders_warrant_tier_only_when_declared() -> None:
    plain = render_authority_report_markdown(_report([_decision()]))
    assert "warrant_tier" not in plain
    warranted = render_authority_report_markdown(
        _report([_decision(warrant_tier="external_fact")])
    )
    assert "warrant_tier: `external_fact`" in warranted


def test_navigation_exposes_final_proof_power_and_searchable_warrant() -> None:
    report = _report([
        _decision(),
        _decision(
            governs="产品全称合法值空间",
            statement="产品全称枚举来自外部产品目录快照",
            locator="planfullname",
            warrant_tier="external_fact",
        ),
    ])
    registry = build_material_decision_key_index_registry(report)
    loaded_plain, _ = registry.load(
        MATERIAL_DECISION_INDEX_KEY, "field-catalog.decision-1"
    )
    assert loaded_plain["content"]["proof_power"] == "current_behavior"
    loaded_warranted, _ = registry.load(
        MATERIAL_DECISION_INDEX_KEY, "field-catalog.decision-2"
    )
    assert loaded_warranted["content"]["proof_power"] == "external_fact"
    assert loaded_warranted["content"]["decision"]["warrant_tier"] == "external_fact"
    hits, _ = registry.search(MATERIAL_DECISION_INDEX_KEY, "external_fact", limit=3)
    assert [hit.key for hit in hits] == ["field-catalog.decision-2"]


# ---------------------------------------------------------- validation guards


def test_invalid_warrant_tier_fails_report_validation() -> None:
    report = _report([_decision(warrant_tier="banana")])
    with pytest.raises(ValueError, match="warrant_tier is invalid"):
        validate_authority_report(
            report, evidence_locations=_EVIDENCE, dimension_ids=set(),
        )


def test_warrant_tier_cannot_dodge_inlive_trust_model_registration() -> None:
    # 内容类型是 inlive_boundary：担保升档也不解除登记回指要求。
    dodged_up = _report([
        _decision(conclusion_kind="inlive_boundary", warrant_tier="normative_rule"),
    ])
    with pytest.raises(ValueError, match="inlive_boundary but no condition"):
        validate_authority_report(
            dodged_up, evidence_locations=_EVIDENCE, dimension_ids=set(),
        )
    # 担保档位声明为 inlive_boundary：同样必须回指登记。
    warranted_inlive = _report([
        _decision(warrant_tier="inlive_boundary"),
    ])
    with pytest.raises(ValueError, match="inlive_boundary but no condition"):
        validate_authority_report(
            warranted_inlive, evidence_locations=_EVIDENCE, dimension_ids=set(),
        )


def test_warranted_inlive_with_registration_passes() -> None:
    report = _report([
        _decision(
            warrant_tier="inlive_boundary",
            conditions=["trust_model: 引用输出空间信任模型登记"],
        ),
        _decision(
            conclusion_kind="normative_rule",
            governs="输出空间信任模型登记",
            statement="业务方同意以输出空间配置作为边界代理",
            locator="trust-model",
            scenario="信任模型登记",
        ),
    ])
    validate_authority_report(
        report, evidence_locations=_EVIDENCE, dimension_ids=set(),
    )


def test_legacy_report_without_warrant_metadata_validates_unchanged() -> None:
    report = _report([
        _decision(),
        _decision(
            conclusion_kind="normative_rule",
            governs="字段目录应然口径",
            statement="字段目录应覆盖业务方确认的检索维度",
            locator="fields",
            scenario="口径裁决",
        ),
    ])
    validate_authority_report(
        report, evidence_locations=_EVIDENCE, dimension_ids=set(),
    )
