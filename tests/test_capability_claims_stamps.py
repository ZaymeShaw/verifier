"""G = 可问责断言集（spec/math-abstract/judge.md §1/§4/§6）。

覆盖三件事：
- 戳记 schema：每条快照断言带出处/信任档位/新鲜度，缺省映射零迁移；
- g 的恒等下界：capability_provider 可直接交出已戳记断言集，校验后恒等；
- citations 透传档位；担保暂缺落低档而非硬拒，且归位三态不变。
"""
from __future__ import annotations

import pytest

from impl.core.capability_carrier import (
    CARRY_NO,
    CARRY_YES,
    DEFAULT_TRUST_TIER,
    LOW_TRUST_TIER,
    PLACEMENT_CANNOT,
    PLACEMENT_WRONG,
    RECOG_UNSUPPORTED,
    STAMP_KEYS,
    TIER_CALLER_STATED,
    TIER_CURRENT_BEHAVIOR,
    TIER_NORMATIVE_RULE,
    TRUST_TIERS,
    CapabilityCarrierBase,
    CapabilityClaimsUnstamped,
    _instantiate_provider,
    assertion_tier,
    carrier_from_claims,
    stamp_claims,
    validate_claim_stamps,
)
from impl.core.capability_structured import (
    CarrierReading,
    StructuredCarrier,
    evaluate_reading,
    snapshot_from_capability_manifest,
)


def _stamped_claims() -> dict:
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


def _nf(expectation_id: str, **expectation) -> dict:
    payload = {"expectation_id": expectation_id, "blocking": True, **expectation}
    return {
        "overall_fulfillment": {"status": "not_fulfilled"},
        "business_expectations": [payload],
        "fulfillment_assessments": [
            {"expectation_id": expectation_id, "status": "not_fulfilled"}
        ],
    }


# ---------------------------------------------------------------- stamp schema


def test_manifest_snapshot_assertions_carry_three_piece_stamps() -> None:
    snapshot = snapshot_from_capability_manifest({
        "clientAge": {"operators": ["GTE"], "enums": []},
        "deadField": {"operators": ["EQ"], "is_supported": False},
    })
    assert validate_claim_stamps(snapshot) == []
    for entry in snapshot["fields"].values():
        for key in STAMP_KEYS:
            assert str(entry.get(key) or "").strip(), key
        assert entry["trust_tier"] == DEFAULT_TRUST_TIER
        assert entry["provenance"] == "capability_manifest"
        assert entry["staleness"] == snapshot["revision"]


def test_manifest_declared_stamps_pass_through() -> None:
    snapshot = snapshot_from_capability_manifest({
        "probeField": {
            "operators": ["MATCH"],
            "trust_tier": TIER_CURRENT_BEHAVIOR,
            "provenance": "llm_probe:run-42",
            "staleness": "probe-rev-9",
        },
    })
    entry = snapshot["fields"]["probeField"]
    assert entry["trust_tier"] == TIER_CURRENT_BEHAVIOR
    assert entry["provenance"] == "llm_probe:run-42"
    assert entry["staleness"] == "probe-rev-9"


def test_stamping_is_idempotent_and_order_stable() -> None:
    from impl.core.capability_carrier import snapshot_id

    first = snapshot_from_capability_manifest({
        "a": {"operators": ["EQ"]},
        "b": {"operators": ["MATCH"]},
    })
    second = snapshot_from_capability_manifest({
        "b": {"operators": ["MATCH"]},
        "a": {"operators": ["EQ"]},
    })
    assert snapshot_id(first) == snapshot_id(second)
    assert snapshot_id(stamp_claims(first)) == snapshot_id(first)


def test_load_time_fail_fast_on_invalid_tier() -> None:
    with pytest.raises(CapabilityClaimsUnstamped) as exc:
        StructuredCarrier({
            "fields": {
                "x": {"operators": ["EQ"], "trust_tier": "banana"},
            },
        })
    assert "banana" in str(exc.value)


def test_unavailable_snapshot_still_flows_to_placement_error() -> None:
    report = StructuredCarrier(
        {"fields": None},
        mapper=_fixed_mapper({"process_only": True, "alternatives": [], "unmapped": []}),
    ).place(_nf("x", expected_outcome="按车牌号筛选"))
    assert report["errors"][0]["stage"] == "snapshot"


def test_missing_warrant_falls_to_low_tier_not_reject() -> None:
    assert assertion_tier({}) == LOW_TRUST_TIER
    assert LOW_TRUST_TIER == TIER_CALLER_STATED
    assert set(TRUST_TIERS) >= {DEFAULT_TRUST_TIER, LOW_TRUST_TIER}
    carrier = StructuredCarrier({
        "fields": {
            "bareClaim": {"operators": ["MATCH"], "is_supported": True, "governed": True},
        },
    })
    entry = carrier.snapshot["fields"]["bareClaim"]
    assert entry["trust_tier"] == LOW_TRUST_TIER
    verdict = evaluate_reading(CarrierReading(field="bareClaim", operator="MATCH"), carrier.snapshot)
    assert verdict.carry == CARRY_YES
    assert verdict.citations[0]["tier"] == LOW_TRUST_TIER


# --------------------------------------------------------- citations pass tier


def test_citations_pass_through_assertion_tier() -> None:
    carrier = StructuredCarrier(_stamped_claims())
    yes = evaluate_reading(CarrierReading(field="searchClientName", operator="MATCH"), carrier.snapshot)
    assert yes.carry == CARRY_YES
    assert yes.citations[0]["tier"] == TIER_NORMATIVE_RULE
    assert yes.citations[0]["source"] == "capability_manifest"

    no = evaluate_reading(CarrierReading(field="licensePlateNo"), carrier.snapshot)
    assert no.carry == CARRY_NO
    assert no.citations[0]["tier"] == TIER_NORMATIVE_RULE


def test_process_and_unmapped_citations_carry_tier() -> None:
    from impl.core.capability_structured import PROCESS_FIELD, unmapped_verdict

    carrier = StructuredCarrier(_stamped_claims())
    process = evaluate_reading(
        CarrierReading(field=PROCESS_FIELD, kind="process"), carrier.snapshot,
    )
    assert process.citations[0]["tier"] == DEFAULT_TRUST_TIER

    verdict = unmapped_verdict(
        [{
            "surface": "天气",
            "nearest": [{"field": "searchClientName", "why": "姓名不是天气"}],
        }],
        carrier.snapshot,
    )
    tiers = {cite["tier"] for cite in verdict.citations}
    assert tiers == {DEFAULT_TRUST_TIER, TIER_NORMATIVE_RULE}


# --------------------------------------------------------------- identity path


def test_provider_may_return_stamped_claims_identity() -> None:
    carrier = _instantiate_provider(lambda _spec: _stamped_claims(), None, "demo")
    assert isinstance(carrier, CapabilityCarrierBase)
    assert set(carrier.citation_space()) == {"searchClientName", "licensePlateNo"}
    carrier.mapper = _fixed_mapper({
        "process_only": False,
        "alternatives": [{"readings": [{"field": "licensePlateNo"}]}],
        "unmapped": [],
    })
    carrier.replicate = False
    report = carrier.place(_nf("plate", expected_outcome="按车牌号筛选"))
    item = report["placements"][0]
    assert item["placement"] == PLACEMENT_CANNOT
    assert item["recognition"] == RECOG_UNSUPPORTED
    assert item["citations"][0]["tier"] == TIER_NORMATIVE_RULE


def test_provider_bare_claims_mapping_is_wrapped() -> None:
    claims = _stamped_claims()["fields"]
    carrier = carrier_from_claims(claims, owner="demo")
    assert set(carrier.citation_space()) == {"searchClientName", "licensePlateNo"}


def test_identity_path_rejects_unstamped_claims() -> None:
    unstamped = {
        "fields": {
            "searchClientName": {"operators": ["MATCH"], "source": "capability_manifest"},
        },
    }
    with pytest.raises(CapabilityClaimsUnstamped) as exc:
        _instantiate_provider(lambda _spec: unstamped, None, "demo")
    assert "demo" in str(exc.value)
    assert "trust_tier" in str(exc.value)


def test_identity_path_rejects_claims_without_fields() -> None:
    with pytest.raises(CapabilityClaimsUnstamped):
        carrier_from_claims({"fields": None}, owner="demo")


def test_provider_bad_return_type_still_not_bound() -> None:
    from impl.core.capability_carrier import CapabilityCarrierNotBound

    with pytest.raises(CapabilityCarrierNotBound):
        _instantiate_provider(lambda _spec: 42, None, "demo")


# ------------------------------------------------- no placement drift on legacy


def test_legacy_unstamped_snapshot_keeps_identical_placements() -> None:
    legacy = {
        "fields": {
            "searchClientName": {
                "operators": ["MATCH", "EQ"],
                "enums": [],
                "is_supported": True,
                "governed": True,
                "source": "capability_manifest",
            },
            "deadField": {
                "operators": ["EQ"],
                "enums": ["A"],
                "is_supported": False,
                "governed": True,
                "source": "capability_manifest",
            },
        }
    }
    scenarios = [
        (
            {"process_only": False, "alternatives": [{"readings": [{"field": "searchClientName", "operator": "MATCH"}]}], "unmapped": []},
            PLACEMENT_WRONG,
            "",
        ),
        (
            {"process_only": False, "alternatives": [{"readings": [{"field": "deadField", "value": "A"}]}], "unmapped": []},
            PLACEMENT_CANNOT,
            RECOG_UNSUPPORTED,
        ),
    ]
    for payload, placement, recognition in scenarios:
        report = StructuredCarrier(legacy, mapper=_fixed_mapper(payload)).place(
            _nf("x", expected_outcome="目标客户")
        )
        item = report["placements"][0]
        assert item["placement"] == placement
        assert item.get("recognition", "") == recognition
        assert item["citations"][0]["tier"] == DEFAULT_TRUST_TIER
