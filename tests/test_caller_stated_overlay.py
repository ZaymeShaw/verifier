"""caller-stated 低档叠加层（spec/math-abstract/judge.md §5/§7.3）。

覆盖四条硬约束：
- 只落最低信任档：调用方声明不能自我担保出更高档位（担保键一律改写）；
- 只叠加不覆盖：G 已有断言字节不变，同名声明降级为注意力提示；
- 不进 e：声明携带期望/轴1载荷键在装载期即拒（结构保证）；
- 不洗轴1分：叠加层只影响轴2归位与注意力提示，轴1 JudgeResult 原样不动。
"""
from __future__ import annotations

import copy

import pytest

from impl.core.capability_carrier import (
    AXIS1_PAYLOAD_KEYS,
    CARRY_NO,
    CARRY_YES,
    CallerStatedOverlayRejected,
    PLACEMENT_CANNOT,
    PLACEMENT_WRONG,
    TIER_CALLER_STATED,
    TIER_NORMATIVE_RULE,
    attach_row_placements,
    caller_stated_provenance,
    carrier_from_claims,
    overlay_caller_stated,
    validate_claim_stamps,
)
from impl.core.capability_structured import (
    CarrierReading,
    StructuredCarrier,
    attention_prompt,
    catalog_prompt,
    evaluate_reading,
)


def _base_claims() -> dict:
    return {
        "fields": {
            "searchClientName": {
                "operators": ["MATCH"],
                "enums": [],
                "is_supported": True,
                "governed": True,
                "source": "capability_manifest",
                "provenance": "capability_manifest",
                "trust_tier": TIER_NORMATIVE_RULE,
                "staleness": "rev-1",
            },
            "licensePlateNo": {
                "operators": ["MATCH"],
                "enums": [],
                "is_supported": False,
                "governed": True,
                "source": "capability_manifest",
                "provenance": "capability_manifest",
                "trust_tier": TIER_NORMATIVE_RULE,
                "staleness": "rev-1",
            },
        },
        "revision": "rev-1",
    }


def _fixed_mapper(payload: dict):
    def mapper(_expectation, _snapshot):
        return payload
    return mapper


def _nf_row(expectation_id: str) -> dict:
    side = {
        "overall_fulfillment": {"status": "not_fulfilled"},
        "business_expectations": [
            {"expectation_id": expectation_id, "blocking": True}
        ],
        "fulfillment_assessments": [
            {"expectation_id": expectation_id, "status": "not_fulfilled"}
        ],
    }
    return {"current": copy.deepcopy(side), "draft": copy.deepcopy(side)}


# ------------------------------------------------------------- lowest tier only


def test_overlay_forces_lowest_tier_despite_declared_warrant() -> None:
    overlaid = overlay_caller_stated(
        _base_claims(),
        {
            "callerField": {
                "operators": ["EQ"],
                "trust_tier": TIER_NORMATIVE_RULE,
                "warrant": "docs/self-endorsed.md",
                "source": "capability_manifest",
                "provenance": "capability_manifest",
            },
        },
        caller="crm",
    )
    entry = overlaid["fields"]["callerField"]
    assert entry["trust_tier"] == TIER_CALLER_STATED
    assert entry["provenance"] == "caller_stated:crm"
    assert entry["source"] == "caller_stated:crm"
    assert "warrant" not in entry
    assert entry["staleness"] == "rev-1"
    assert validate_claim_stamps(overlaid) == []
    assert caller_stated_provenance() == "caller_stated"


def test_overlay_citations_carry_caller_stated_tier() -> None:
    overlaid = overlay_caller_stated(
        _base_claims(),
        {"callerField": {"operators": ["EQ"], "governed": True}},
        caller="crm",
    )
    verdict = evaluate_reading(CarrierReading(field="callerField", operator="EQ"), overlaid)
    assert verdict.carry == CARRY_YES
    assert verdict.citations[0]["tier"] == TIER_CALLER_STATED
    assert verdict.citations[0]["source"] == "caller_stated:crm"


# ------------------------------------------------------- additive, no override


def test_overlay_never_overrides_existing_assertions() -> None:
    base = _base_claims()
    before = copy.deepcopy(base["fields"]["licensePlateNo"])
    overlaid = overlay_caller_stated(
        base,
        {"licensePlateNo": {"is_supported": True, "note": "调用方称车牌可查"}},
        caller="crm",
    )
    assert overlaid["fields"]["licensePlateNo"] == before
    notes = overlaid["attention"]
    assert notes[0]["field"] == "licensePlateNo"
    assert notes[0]["tier"] == TIER_CALLER_STATED
    verdict = evaluate_reading(CarrierReading(field="licensePlateNo"), overlaid)
    assert verdict.carry == CARRY_NO
    assert verdict.citations[0]["tier"] == TIER_NORMATIVE_RULE


def test_overlay_requires_available_snapshot_base() -> None:
    with pytest.raises(CallerStatedOverlayRejected):
        overlay_caller_stated({"fields": None}, {"x": {"operators": ["EQ"]}})


# ------------------------------------------------------------- cannot enter e


def test_overlay_rejects_expectation_payload_keys() -> None:
    for key in sorted(AXIS1_PAYLOAD_KEYS):
        with pytest.raises(CallerStatedOverlayRejected):
            overlay_caller_stated(_base_claims(), {key: {}})
        with pytest.raises(CallerStatedOverlayRejected):
            overlay_caller_stated(
                _base_claims(), {"callerField": {"operators": ["EQ"], key: "x"}},
            )


def test_overlay_rejects_non_mapping_entries() -> None:
    with pytest.raises(CallerStatedOverlayRejected):
        overlay_caller_stated(_base_claims(), {"callerField": "supported"})


def test_overlay_cannot_add_expectations_to_placement_scope() -> None:
    """归位只遍历 row 自己的 business_expectations：叠加层造不出新期望。"""
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        caller_stated={"callerField": {"operators": ["EQ"], "governed": True}},
    )
    carrier.mapper = _fixed_mapper({
        "process_only": False,
        "alternatives": [{"readings": [{"field": "callerField"}]}],
        "unmapped": [],
    })
    carrier.replicate = False
    row = _nf_row("only-one")
    attach_row_placements(_spec_on(), row, carrier=carrier)
    for side in ("current", "draft"):
        placed = {
            item["expectation_id"]
            for item in row["capability_carrier"][side]["placements"]
        }
        assert placed == {"only-one"}


# ------------------------------------------------- cannot wash axis-1 scoring


class _spec_on:
    project_id = "demo"
    verifier = {"authority": {"enabled_scopes": ["capability_carrier"]}}


def test_overlay_cannot_wash_axis1_scoring() -> None:
    """§7.3：caller 声明「承载得了」只改变轴2归位，不改轴1 not_fulfilled。"""
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        caller_stated={"callerField": {"operators": ["EQ"], "governed": True}},
        caller="crm",
    )
    carrier.mapper = _fixed_mapper({
        "process_only": False,
        "alternatives": [{"readings": [{"field": "callerField"}]}],
        "unmapped": [],
    })
    carrier.replicate = False
    row = _nf_row("exp-1")
    axis1_before = copy.deepcopy(row["current"]["overall_fulfillment"])
    assessments_before = copy.deepcopy(row["current"]["fulfillment_assessments"])
    attach_row_placements(_spec_on(), row, carrier=carrier)
    assert row["current"]["overall_fulfillment"] == axis1_before
    assert row["current"]["fulfillment_assessments"] == assessments_before
    item = row["capability_carrier"]["current"]["placements"][0]
    assert item["placement"] == PLACEMENT_WRONG
    assert item["citations"][0]["tier"] == TIER_CALLER_STATED


def test_overlay_does_not_apply_when_axis1_fulfilled() -> None:
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        caller_stated={"callerField": {"operators": ["EQ"], "governed": True}},
    )
    report = carrier.place({"overall_fulfillment": {"status": "fulfilled"}})
    assert report["applicable"] is False
    assert report["placements"] == []


def test_high_tier_no_still_wins_with_conflicting_caller_claim() -> None:
    """调用方对既有维度唱反调：既有 normative 断言照旧裁 做不了，档位不降。"""
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        caller_stated={"licensePlateNo": {"is_supported": True}},
        caller="crm",
    )
    carrier.mapper = _fixed_mapper({
        "process_only": False,
        "alternatives": [{"readings": [{"field": "licensePlateNo"}]}],
        "unmapped": [],
    })
    carrier.replicate = False
    row = _nf_row("plate")
    attach_row_placements(_spec_on(), row, carrier=carrier)
    item = row["capability_carrier"]["current"]["placements"][0]
    assert item["placement"] == PLACEMENT_CANNOT
    assert item["citations"][0]["tier"] == TIER_NORMATIVE_RULE


# ------------------------------------------------------------- attention lane


def test_attention_hints_enter_prompt_not_assertions() -> None:
    base = _base_claims()
    overlaid = overlay_caller_stated(
        base,
        None,
        caller="crm",
        attention=["近期车牌搜索投诉集中，注意车牌相关读法", ""],
    )
    assert overlaid["fields"] == base["fields"]
    prompt = catalog_prompt(overlaid)
    assert "调用方注意力提示" in prompt
    assert "车牌搜索投诉" in prompt
    assert "车牌搜索投诉" in attention_prompt(overlaid)
    assert catalog_prompt(base).find("调用方注意力提示") == -1


def test_structured_carrier_accepts_overlaid_snapshot() -> None:
    overlaid = overlay_caller_stated(
        _base_claims(),
        {"callerField": {"operators": ["EQ"], "governed": True}},
        caller="crm",
        attention=["注意 callerField 是调用方口头声明"],
    )
    carrier = StructuredCarrier(overlaid)
    assert "callerField" in carrier.citation_space()
    assert carrier.snapshot["fields"]["callerField"]["trust_tier"] == TIER_CALLER_STATED
    assert carrier.snapshot.get("attention")
