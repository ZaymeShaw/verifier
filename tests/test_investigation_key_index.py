from __future__ import annotations

from dataclasses import replace

import pytest

from impl.core.investigation_key_index import (
    InvestigationKeyIndexRegistry,
    create_key_index_tools,
)
from impl.core.schema import (
    InvestigationKeyEntry,
    InvestigationKeyIndex,
    InvestigationManifest,
    validate_investigation_manifest,
)


def _index() -> InvestigationKeyIndex:
    return InvestigationKeyIndex(
        index_key="demo.fields",
        collection_ref="field-definitions",
        target_kind="field_definition",
        entry_granularity="field",
        entries=(
            InvestigationKeyEntry(
                key="age",
                name="年龄",
                search_text="年龄 周岁 出生日期",
                target_ref="field://age",
            ),
            InvestigationKeyEntry(
                key="city",
                name="城市",
                search_text="城市 地区 地址",
                target_ref="field://city",
            ),
        ),
    )


def _strategy(query, entries, limit):
    ranked = [
        (entry, float(len(set(query) & set(entry.search_text))))
        for entry in entries
        if set(query) & set(entry.search_text)
    ]
    return sorted(ranked, key=lambda item: (-item[1], item[0].key))[:limit]


def _registry() -> InvestigationKeyIndexRegistry:
    targets = {
        "field://age": {
            "content": {"field": "age", "operators": ["GTE", "LTE"]},
            "locator": "fields.yaml#age",
            "provenance": {"evidence_ref_id": "field-definitions"},
        },
        "field://city": {
            "content": {"field": "city", "operators": ["MATCH"]},
            "locator": "fields.yaml#city",
            "provenance": {"evidence_ref_id": "field-definitions"},
        },
    }
    registry = InvestigationKeyIndexRegistry()
    registry.register(
        _index(),
        resolver=lambda target_ref: targets[target_ref],
        search_strategy=_strategy,
        target_validator=lambda target_ref: targets[target_ref] and None,
    )
    return registry


def test_key_index_search_load_and_receipts_trace_real_target():
    registry = _registry()

    hits, search_receipt = registry.search("demo.fields", "17周岁", limit=1)
    assert [hit.key for hit in hits] == ["age"]
    assert hits[0].target_ref == "field://age"
    assert "search_text" not in hits[0].as_dict()
    assert search_receipt.as_dict() == {
        "operation": "search_index",
        "index_key": "demo.fields",
        "query": "17周岁",
        "target_refs": ["field://age"],
    }

    loaded, load_receipt = registry.load("demo.fields", "age")
    assert loaded["content"]["field"] == "age"
    assert loaded["target_ref"] == "field://age"
    assert loaded["locator"] == "fields.yaml#age"
    assert load_receipt.as_dict()["provenance"] == {
        "evidence_ref_id": "field-definitions"
    }


def test_key_index_rejects_duplicate_keys_conclusions_and_unresolved_targets():
    duplicate = replace(_index(), entries=(_index().entries[0], _index().entries[0]))
    with pytest.raises(ValueError, match="duplicate InvestigationKeyEntry"):
        InvestigationKeyIndexRegistry().register(
            duplicate,
            resolver=lambda target_ref: {"content": target_ref},
            search_strategy=_strategy,
        )

    with pytest.raises(ValueError, match="cannot carry business conclusions"):
        InvestigationKeyEntry.from_dict({
            "key": "age",
            "name": "年龄",
            "search_text": "年龄",
            "target_ref": "field://age",
            "verdict": "fulfilled",
        })

    with pytest.raises(KeyError, match="missing"):
        InvestigationKeyIndexRegistry().register(
            _index(),
            resolver=lambda target_ref: {"content": target_ref},
            search_strategy=_strategy,
            target_validator=lambda target_ref: (_ for _ in ()).throw(
                KeyError(f"missing {target_ref}")
            ),
        )


def test_key_index_tools_keep_search_and_load_contract_separate():
    search_tool, load_tool = create_key_index_tools(_registry())

    searched = search_tool.execute_fn(
        index_key="demo.fields", query="城市地址", limit=2
    )
    assert searched.status == "succeeded"
    assert searched.actual["candidates"][0]["key"] == "city"
    assert "content" not in searched.actual["candidates"][0]
    assert searched.runtime_metadata["receipt"]["operation"] == "search_index"

    loaded = load_tool.execute_fn(index_key="demo.fields", key="city")
    assert loaded.status == "succeeded"
    assert loaded.actual["content"]["field"] == "city"
    assert loaded.runtime_metadata["receipt"]["operation"] == "load_entry"

    wildcard = load_tool.execute_fn(index_key="demo.fields", key="*")
    assert wildcard.status == "failed"
    assert "explicit non-wildcard key" in wildcard.error


def test_index_catalog_exposes_only_structured_navigation_metadata():
    registry = _registry()

    assert registry.catalog() == ({
        "index_key": "demo.fields",
        "collection_ref": "field-definitions",
        "target_kind": "field_definition",
        "entry_granularity": "field",
    },)

    search_tool, load_tool = create_key_index_tools(registry)
    for tool in (search_tool, load_tool):
        index_parameter = tool.parameters["properties"]["index_key"]
        assert index_parameter["enum"] == ["demo.fields"]
        assert "collection_ref=field-definitions" in index_parameter["description"]
        assert "target_kind=field_definition" in index_parameter["description"]
        assert "entry_granularity=field" in index_parameter["description"]
        assert "年龄" not in index_parameter["description"]
        assert "出生日期" not in index_parameter["description"]


def test_index_schema_rejects_missing_catalog_metadata_and_routing_hints():
    base = _index().as_dict()
    del base["collection_ref"]
    with pytest.raises(ValueError, match="collection_ref is required"):
        InvestigationKeyIndex.from_dict(base)

    routed = _index().as_dict()
    routed["next_index"] = "demo.values"
    with pytest.raises(ValueError, match="cannot carry runtime routing hints"):
        InvestigationKeyIndex.from_dict(routed)


def test_load_entry_exposes_runtime_load_targets_at_protocol_level():
    registry = InvestigationKeyIndexRegistry()
    registry.register(
        _index(),
        resolver=lambda target_ref: {
            "content": {"target": target_ref},
            "locator": "fields.city",
            "load_targets": ["C1", "C1", "C2"],
            "target_resolution": {"status": "resolved", "strategy": "fixture"},
        },
        search_strategy=_strategy,
    )

    loaded, receipt = registry.load("demo.fields", "city")

    assert loaded["load_targets"] == ["C1", "C2"]
    assert loaded["target_resolution"] == {
        "status": "resolved",
        "strategy": "fixture",
    }
    assert "load_targets" not in loaded["content"]
    assert receipt.load_targets == ("C1", "C2")
    assert receipt.as_dict()["target_resolution"]["status"] == "resolved"


def test_investigation_manifest_registers_key_indexes():
    manifest = InvestigationManifest(
        schema_version=2,
        project_id="demo",
        role="judge",
        source_revision="abc",
        key_indexes=[_index()],
    )
    validate_investigation_manifest(manifest)
    restored = InvestigationManifest.from_dict(manifest.as_dict())
    assert restored.key_indexes == [_index()]


def test_material_decision_index_is_navigation_not_evidence():
    from pathlib import Path

    from impl.core.authority_key_index import (
        MATERIAL_DECISION_INDEX_KEY,
        build_material_decision_key_index_registry,
    )
    from impl.core.schema.investigation_judge import load_authority_investigation_report

    report = load_authority_investigation_report(Path(
        "impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json"
    ))
    registry = build_material_decision_key_index_registry(report)
    hits, _ = registry.search(MATERIAL_DECISION_INDEX_KEY, "客户搜索是否支持按年龄查询", limit=5)
    assert hits
    loaded, _ = registry.load(MATERIAL_DECISION_INDEX_KEY, hits[0].key)
    content = loaded["content"]
    assert content["navigation_only"] is True
    assert content["source_ref_id"]
    assert content["evidence_search_hint"]
    assert "status" not in content
    assert "resolved" not in content
    assert "verdict" not in content


def test_authority_application_rejects_catalog_metadata_mismatch():
    from pathlib import Path

    from impl.core.authority_key_index import (
        build_material_decision_key_index,
        build_material_decision_key_index_registry,
    )
    from impl.core.schema.investigation_judge import load_authority_investigation_report

    report = load_authority_investigation_report(Path(
        "impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json"
    ))
    invalid = replace(
        build_material_decision_key_index(report),
        target_kind="evidence_locator",
    )
    with pytest.raises(ValueError, match="target_kind must be material_decision"):
        build_material_decision_key_index_registry(report, index=invalid)


def test_material_decision_index_miss_has_no_unresolved_semantics():
    from pathlib import Path

    from impl.core.authority_key_index import (
        MATERIAL_DECISION_INDEX_KEY,
        build_material_decision_key_index_registry,
    )
    from impl.core.schema.investigation_judge import load_authority_investigation_report

    report = load_authority_investigation_report(Path(
        "impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json"
    ))
    registry = build_material_decision_key_index_registry(report)
    hits, receipt = registry.search(
        MATERIAL_DECISION_INDEX_KEY, "量子航海许可证折射率", limit=5
    )
    assert hits == []
    assert receipt.target_refs == ()


def test_coverage_gap_trigger_hit_requires_top_hit_gap():
    from pathlib import Path

    from impl.core.authority_key_index import coverage_gap_trigger_hit
    from impl.core.schema.investigation_judge import load_authority_investigation_report

    report = load_authority_investigation_report(Path(
        "impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json"
    ))
    # 请求命中调查层覆盖缺口且无更相关的 MaterialDecision：返回 gap_id（确定性触发面）。
    assert coverage_gap_trigger_hit(
        report, "陈金秀在别的业务员的投保的平安产品"
    ) == "silently-dropped-request-dimension"
    assert coverage_gap_trigger_hit(
        report, "东莞何叶玩具制品有限公司"
    ) == "responsibility-boundary-entity-name-query"
    # 请求有更相关的已登记 MaterialDecision 覆盖（增强规则/字段定义）时不触发。
    assert coverage_gap_trigger_hit(report, "在职单") is None
    assert coverage_gap_trigger_hit(report, "17周岁以下少儿客户名单") is None
    # 空请求文本不触发。
    assert coverage_gap_trigger_hit(report, "") is None


def test_client_search_large_value_index_is_complete_and_collection_index_has_no_samples():
    from impl.core.project_loader import load_project
    from impl.projects.client_search.draft.build_authority_key_index import build_indexes

    indexes = {item["index_key"]: item for item in build_indexes(load_project("client_search"))}
    collection = indexes["authority.material-decisions"]
    plan_entry = next(
        item for item in collection["entries"]
        if item["key"] == "business-planfullname-enums.decision-1"
    )
    assert "住院医疗保险" not in plan_entry["search_text"]
    assert "阖家团圆康" not in plan_entry["search_text"]

    internal = indexes["material.business-planfullname-enums.values"]
    projected = " ".join(item["search_text"] for item in internal["entries"])
    assert len(internal["entries"]) == 74
    assert "住院医疗保险" in projected
    assert "阖家团圆康" in projected
