"""llm_probe 作为 G 的供给方（judge.md §5 / provider-contract §4.2）。

覆盖三件事：
- 探针观察 → 已戳记断言：provenance=该次探测、缺省档 current_behavior、
  staleness=探测时刻；档位越界 / 结论载荷 / 不可回溯即拒；
- overlay 入 G：只叠加不覆盖，既有断言字节不变，同名降级为注意力提示；
- 端到端归位：探针自认 is_supported=false 支撑"做不了"，citations 带
  current_behavior 档；探针断言也可独立构成 G（恒等路径）。
"""
from __future__ import annotations

import pytest

from impl.core.capability_carrier import (
    CARRY_NO,
    CARRY_YES,
    PLACEMENT_CANNOT,
    RECOG_UNSUPPORTED,
    TIER_CALLER_STATED,
    TIER_CURRENT_BEHAVIOR,
    TIER_INLIVE_BOUNDARY,
    TIER_NORMATIVE_RULE,
    ProbeClaimsRejected,
    carrier_from_claims,
    overlay_probe_claims,
    probe_provenance,
    validate_claim_stamps,
)
from impl.core.capability_structured import CarrierReading, evaluate_reading
from impl.projects.llm_probe.claims import probe_claims, probe_claims_from_trace


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
        },
        "revision": "rev-1",
    }


def _observed(**extra) -> dict:
    return {
        "licensePlateNo": {
            "operators": ["MATCH"],
            "is_supported": False,
            "governed": True,
            "description": "探测返回 4xx 明确拒绝该维度",
            **extra,
        },
    }


_REQUEST = {"method": "post", "url": "https://svc.example/api/search"}


# ------------------------------------------------------------------ builder


def test_probe_claims_carry_three_piece_stamps() -> None:
    claims = probe_claims(
        _observed(), run_id="run-42", request=_REQUEST, probed_at="2026-08-25T06:00:00Z",
    )
    entry = claims["licensePlateNo"]
    assert entry["provenance"] == "llm_probe:run-42"
    assert entry["trust_tier"] == TIER_CURRENT_BEHAVIOR
    assert entry["staleness"] == "2026-08-25T06:00:00Z"
    assert entry["warrant"] == "llm_probe:run-42@POST https://svc.example/api/search"
    assert entry["source"] == entry["warrant"]
    assert entry["is_supported"] is False
    assert validate_claim_stamps({"fields": claims}) == []


def test_probe_claims_staleness_falls_back_to_run_id() -> None:
    claims = probe_claims(_observed(), run_id="run-42")
    assert claims["licensePlateNo"]["staleness"] == "run-42"
    assert claims["licensePlateNo"]["warrant"] == "llm_probe:run-42"


def test_probe_claims_require_traceable_run() -> None:
    with pytest.raises(ProbeClaimsRejected):
        probe_claims(_observed(), run_id="  ")
    with pytest.raises(ProbeClaimsRejected):
        probe_provenance("")


def test_probe_never_normative_rule() -> None:
    with pytest.raises(ProbeClaimsRejected) as exc:
        probe_claims(_observed(trust_tier=TIER_NORMATIVE_RULE), run_id="run-1")
    assert "normative_rule" in str(exc.value)
    with pytest.raises(ProbeClaimsRejected):
        probe_claims(_observed(trust_tier=TIER_CALLER_STATED), run_id="run-1")


def test_inlive_boundary_needs_registered_warrant() -> None:
    with pytest.raises(ProbeClaimsRejected) as exc:
        probe_claims(_observed(trust_tier=TIER_INLIVE_BOUNDARY), run_id="run-1")
    assert "warrant" in str(exc.value)
    claims = probe_claims(
        _observed(trust_tier=TIER_INLIVE_BOUNDARY, warrant="trust_model:reg-7"),
        run_id="run-1",
        request=_REQUEST,
    )
    entry = claims["licensePlateNo"]
    assert entry["trust_tier"] == TIER_INLIVE_BOUNDARY
    assert entry["warrant"] == "trust_model:reg-7"
    assert entry["source"] == "trust_model:reg-7"


def test_probe_rejects_axis1_and_verdict_payload() -> None:
    with pytest.raises(ProbeClaimsRejected):
        probe_claims(_observed(expected_outcome="按车牌筛选"), run_id="run-1")
    with pytest.raises(ProbeClaimsRejected) as exc:
        probe_claims(_observed(placement="做不了"), run_id="run-1")
    assert "结论" in str(exc.value)
    with pytest.raises(ProbeClaimsRejected):
        probe_claims(_observed(carry=CARRY_NO), run_id="run-1")


def test_probe_claims_from_trace_pull_run_identity() -> None:
    trace = {
        "trace_id": "t-99",
        "created_at": "2026-08-25T05:00:00Z",
        "normalized_request": dict(_REQUEST),
    }
    claims = probe_claims_from_trace(trace, _observed())
    entry = claims["licensePlateNo"]
    assert entry["provenance"] == "llm_probe:t-99"
    assert entry["staleness"] == "2026-08-25T05:00:00Z"
    assert "POST https://svc.example/api/search" in entry["warrant"]


# ------------------------------------------------------------------ overlay


def test_overlay_adds_probe_assertion_without_touching_base() -> None:
    base = _base_claims()
    merged = overlay_probe_claims(base, probe_claims(_observed(), run_id="run-1"))
    assert merged["fields"]["searchClientName"] == base["fields"]["searchClientName"]
    assert merged["fields"]["licensePlateNo"]["trust_tier"] == TIER_CURRENT_BEHAVIOR
    assert validate_claim_stamps(merged) == []


def test_overlay_never_overwrites_same_name_assertion() -> None:
    base = _base_claims()
    probe = probe_claims(
        {"searchClientName": {"is_supported": False, "note": "探测 4xx"}},
        run_id="run-1",
    )
    merged = overlay_probe_claims(base, probe)
    assert merged["fields"]["searchClientName"] == base["fields"]["searchClientName"]
    notes = merged["attention"]
    assert notes[0]["field"] == "searchClientName"
    assert notes[0]["provenance"] == "llm_probe:run-1"
    assert notes[0]["tier"] == TIER_CURRENT_BEHAVIOR


def test_overlay_rejects_unstamped_or_forged_tier() -> None:
    base = _base_claims()
    with pytest.raises(ProbeClaimsRejected):
        overlay_probe_claims(base, {"x": {"operators": ["EQ"]}})
    forged = probe_claims(_observed(), run_id="run-1")
    forged["licensePlateNo"]["trust_tier"] = TIER_NORMATIVE_RULE
    with pytest.raises(ProbeClaimsRejected):
        overlay_probe_claims(base, forged)


def test_overlay_requires_base_snapshot() -> None:
    with pytest.raises(ProbeClaimsRejected):
        overlay_probe_claims({"fields": None}, probe_claims(_observed(), run_id="r"))


# ------------------------------------------------------------ end-to-end G


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


def test_probe_selfrecognition_supports_cannot_with_probe_tier_citation() -> None:
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        probe_claims=probe_claims(_observed(), run_id="run-1", request=_REQUEST),
    )
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
    cite = item["citations"][0]
    assert cite["tier"] == TIER_CURRENT_BEHAVIOR
    assert "llm_probe:run-1" in cite["source"]


def test_probe_claims_alone_can_constitute_g_identity_path() -> None:
    claims = probe_claims(
        {
            "searchClientName": {"operators": ["MATCH"], "is_supported": True, "governed": True},
            **_observed(),
        },
        run_id="run-7",
        request=_REQUEST,
    )
    carrier = carrier_from_claims(claims, owner="demo")
    assert set(carrier.citation_space()) == {"searchClientName", "licensePlateNo"}
    yes = evaluate_reading(CarrierReading(field="searchClientName", operator="MATCH"), carrier.snapshot)
    assert yes.carry == CARRY_YES
    assert yes.citations[0]["tier"] == TIER_CURRENT_BEHAVIOR


def test_probe_overlay_composes_with_caller_stated_overlay() -> None:
    carrier = carrier_from_claims(
        _base_claims(),
        owner="demo",
        probe_claims=probe_claims(_observed(), run_id="run-1"),
        caller_stated={"callerField": {"operators": ["EQ"], "is_supported": True}},
        caller="tenant-a",
    )
    fields = carrier.snapshot["fields"]
    assert fields["licensePlateNo"]["trust_tier"] == TIER_CURRENT_BEHAVIOR
    assert fields["callerField"]["trust_tier"] == TIER_CALLER_STATED
    assert fields["searchClientName"]["trust_tier"] == TIER_NORMATIVE_RULE


def test_llm_probe_axis1_judge_untouched() -> None:
    """供给方身份不触碰 llm_probe 自身的轴1判定入口。"""
    from impl.projects.llm_probe.judge import LlmProbeJudge

    assert not hasattr(LlmProbeJudge, "capability_provider")
    assert callable(getattr(LlmProbeJudge, "build_context"))
