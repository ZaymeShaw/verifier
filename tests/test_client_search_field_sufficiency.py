from __future__ import annotations

from impl.core.project_loader import load_project
from impl.core.schema import (
    BusinessExpectation,
    FulfillmentAssessment,
    JudgeResult,
    RunTrace,
)
from impl.projects.client_search.field_sufficiency import (
    decide,
    decide_from_trace,
    load_field_standards,
    result_if_speaks,
    sufficiency_hint,
)
from impl.projects.client_search.judge import ClientSearchJudge


def _trace(trace_id: str, query: str, pairs: list[tuple[str, str]]) -> RunTrace:
    return RunTrace(
        trace_id=trace_id,
        project_id="client_search",
        input={"user_text": query},
        normalized_request={"user_text": query},
        extracted_output={
            "conditions": [
                {"field": field, "operator": "MATCH", "value": value}
                for field, value in pairs
            ]
        },
    )


def _llm_result(trace: RunTrace, status: str) -> JudgeResult:
    return JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        business_expectations=[
            BusinessExpectation(
                expectation_id="llm-core",
                blocking=True,
                expected_outcome="leftover",
            )
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="llm-core", status=status)
        ],
        overall_fulfillment={"status": status},
        reasoning_summary="leftover llm",
    )


def test_field_sufficiency_needles_use_business_name_standard() -> None:
    spec = load_project("client_search")
    standards = load_field_standards(spec)

    assert decide("杨杰", [("searchClientName", "杨杰")], standards).status == "fulfilled"
    assert decide("王坤林", [("searchClientName", "王坤林")], standards).status == "fulfilled"
    assert decide("共展", [("searchClientName", "共展")], standards).status == "not_fulfilled"
    assert decide("豆芽", [("searchClientName", "豆芽")], standards).status == "not_fulfilled"
    assert decide("昊轩", [("searchClientName", "昊轩")], standards).status == "not_fulfilled"
    assert decide("金凤", [("searchClientName", "金凤")], standards).status == "not_fulfilled"

    silent = [
        decide("红莲保单", [("searchClientName", "红莲")], standards),
        decide("唐诗颖的生存金有没有领取？", [("searchClientName", "唐诗颖")], standards),
        decide("李明的重疾险", [("searchClientName", "李明"), ("pCategorys", "疾病保险")], standards),
        decide("李明重疾险", [("searchClientName", "李明"), ("pCategorys", "疾病保险")], standards),
        decide("金凤", [("polNoInfo.plancodeinfo.abbrname", "金凤")], standards),
        decide("李明的重疾险", [("pCategorys", "疾病保险")], standards),
    ]
    assert all(item.status is None for item in silent)


def test_judge_speaks_only_when_sufficiency_hits() -> None:
    spec = load_project("client_search")
    judge = ClientSearchJudge(spec)

    yang = _trace("needle-yang", "杨杰", [("searchClientName", "杨杰")])
    fake = _trace("needle-fake", "共展", [("searchClientName", "共展")])
    extra = _trace("needle-honglian", "红莲保单", [("searchClientName", "红莲")])

    assert judge.pre_judge(yang) is None
    assert result_if_speaks(spec, yang) is None
    assert decide_from_trace(spec, yang).reason == "sufficient_name"

    assert judge.pre_judge(fake) is None
    assert judge.pre_judge(extra) is None
    assert result_if_speaks(spec, extra) is None
    hint = sufficiency_hint(spec, yang)
    assert hint is not None
    assert hint["suggested_status"] == "fulfilled"
    assert hint["source"] == "field_sufficiency.hint"


def test_last_word_replaces_leftover_llm_contract() -> None:
    spec = load_project("client_search")
    judge = ClientSearchJudge(spec)
    yang = _trace("needle-yang-reconcile", "杨杰", [("searchClientName", "杨杰")])
    incoming = _llm_result(yang, "not_fulfilled")
    reconciled = judge.reconcile_result(yang, incoming)
    assert reconciled.overall_fulfillment["status"] == "not_fulfilled"
    assert [item.expectation_id for item in reconciled.business_expectations] == ["llm-core"]


def test_inherit_keeps_existing_judge_result() -> None:
    spec = load_project("client_search")
    judge = ClientSearchJudge(spec)
    extra = _trace("needle-honglian-reconcile", "红莲保单", [("searchClientName", "红莲")])
    incoming = _llm_result(extra, "not_fulfilled")
    reconciled = judge.reconcile_result(extra, incoming)
    assert reconciled.overall_fulfillment["status"] == "not_fulfilled"
    assert [item.expectation_id for item in reconciled.business_expectations] == ["llm-core"]
