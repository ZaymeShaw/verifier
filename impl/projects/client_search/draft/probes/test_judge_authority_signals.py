from __future__ import annotations

from impl.core.schema import RunTrace
from impl.projects.client_search.judge import (
    _enum_completeness_evidence,
    _unsupported_boundary_evidence,
)


def _enum_trace(query: str) -> RunTrace:
    return RunTrace(
        trace_id="synthetic-enum",
        project_id="client_search",
        input={"user_text": query},
        normalized_request={"user_text": query},
        extracted_output={
            "conditions": [
                {
                    "field": "productCode",
                    "operator": "NOT_CONTAINS",
                    "value": ["甲产品", "乙产品"],
                }
            ]
        },
        application_boundary={"result_set_verified": False},
    )


def test_category_expansion_without_closed_world_evidence_exposes_enum_gap() -> None:
    evidence = _enum_completeness_evidence(
        _enum_trace("剔除某类医疗产品"),
        {
            "productCode": {
                "value_types": ["enum"],
                "enum_refs": ["medicalProducts"],
                "enums": ["甲产品", "乙产品"],
            }
        },
    )

    assert len(evidence) == 1
    assert evidence[0]["category_expansion_from_request"] is True
    assert evidence[0]["actual_values_all_in_static_registry"] is True
    assert evidence[0]["enum_authority_candidate"] is True


def test_user_explicit_enum_list_does_not_require_completeness_authority() -> None:
    evidence = _enum_completeness_evidence(
        _enum_trace("剔除甲产品和乙产品"),
        {
            "productCode": {
                "value_types": ["enum"],
                "enum_refs": ["medicalProducts"],
                "enums": ["甲产品", "乙产品"],
            }
        },
    )

    assert evidence[0]["user_explicitly_enumerated_all_actual_values"] is True
    assert evidence[0]["enum_authority_candidate"] is False


def test_clear_unsupported_notice_preserves_boundary_acceptance_path() -> None:
    trace = RunTrace(
        trace_id="synthetic-boundary",
        project_id="client_search",
        input={"user_text": "查询李雷去年投保某产品的客户"},
        normalized_request={"user_text": "查询李雷去年投保某产品的客户"},
        extracted_output={
            "conditions": [
                {"field": "customerName", "operator": "MATCH", "value": "李雷"},
                {"field": "productCode", "operator": "MATCH", "value": "某产品"},
            ],
            "intent_summary": (
                "客户姓名为李雷并且产品为某产品。"
                "提示：投保日期暂不支持搜索，系统将按可支持字段搜索。"
            ),
        },
    )

    evidence = _unsupported_boundary_evidence(trace)

    assert evidence["acknowledges_requested_constraint"] is True
    assert evidence["supported_condition_count"] == 2
    assert evidence["graceful_degradation_candidate"] is True


def test_explicit_unsupported_field_is_loaded_from_top_key_index_hit() -> None:
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import (
        _enrich_unsupported_boundary_evidence,
    )

    trace = RunTrace(
        trace_id="synthetic-explicit-unsupported",
        project_id="client_search",
        input={"query": "7月盘客"},
        normalized_request={"query": "7月盘客"},
        extracted_output={
            "conditions": [],
            "robot_text": "提示：盘客暂不支持搜索，无法进行查询。",
        },
    )
    evidence = _enrich_unsupported_boundary_evidence(
        load_project("client_search"), trace, _unsupported_boundary_evidence(trace)
    )

    assert evidence["explicit_unsupported_capability"] is True
    assert [item["field"] for item in evidence["explicit_unsupported_fields"]] == [
        "customerReview"
    ]


def test_authority_disabled_evidence_requires_intent_based_fulfillment() -> None:
    """关闭 Authority 时，显式不支持仍按用户交付判断 NF，不自动转 NE。"""
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import (
        _enrich_unsupported_boundary_evidence,
        _unsupported_boundary_evidence,
    )

    trace = RunTrace(
        trace_id="synthetic-explicit-unsupported-gate",
        project_id="client_search",
        input={"query": "7月盘客"},
        normalized_request={"query": "7月盘客"},
        extracted_output={
            "conditions": [],
            "robot_text": "提示：盘客暂不支持搜索，无法进行查询。",
        },
    )

    evidence = _enrich_unsupported_boundary_evidence(
        load_project("client_search"), trace, _unsupported_boundary_evidence(trace)
    )
    decision_rule = evidence["decision_rule"]

    assert evidence["explicit_unsupported_capability"] is True
    assert "missing blocking result is not_fulfilled" in decision_rule
    assert "do not emit not_evaluable merely" in decision_rule


def test_authority_disabled_zero_condition_no_overlap_preserves_effect_verdict() -> None:
    """093 类：请求是具体值、提示是字段标签（无词法重叠），实际零条件交付。

    Key-Index 已确认 is_supported=false 时，all_conditions_unsupported 因重叠为空
    仍为 False，但显式不支持只作为当前交付证据；Authority 关闭时按用户意图判 NF。
    """
    from impl.core.project_loader import load_project
    from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult
    from impl.projects.client_search.judge import (
        ClientSearchJudge,
        _enrich_unsupported_boundary_evidence,
        _unsupported_boundary_evidence,
    )

    trace = RunTrace(
        trace_id="synthetic-093-license-plate-gate",
        project_id="client_search",
        input={"query": "贵C826N1"},
        normalized_request={"query": "贵C826N1"},
        extracted_output={
            "conditions": [],
            "intent_summary": "提示：车牌号暂不支持搜索，无法进行查询。",
            "robot_text": "提示：车牌号暂不支持搜索，无法进行查询。",
        },
    )
    evidence = _enrich_unsupported_boundary_evidence(
        load_project("client_search"), trace, _unsupported_boundary_evidence(trace)
    )
    assert evidence["explicit_unsupported_capability"] is True
    assert evidence["all_conditions_unsupported"] is False

    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id="client_search",
        business_expectations=[
            BusinessExpectation(expectation_id="core", blocking=True),
            BusinessExpectation(expectation_id="notice", blocking=False),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="core", status="not_fulfilled"),
            FulfillmentAssessment(expectation_id="notice", status="fulfilled"),
        ],
    )
    reconciled = ClientSearchJudge(load_project("client_search")).reconcile_result(
        trace, result
    )

    assert reconciled.fulfillment_assessments[0].status == "not_fulfilled"
    assert reconciled.fulfillment_assessments[1].status == "fulfilled"
    assert reconciled.overall_fulfillment["status"] == "not_fulfilled"


def test_authority_disabled_empty_semantic_carrier_preserves_not_fulfilled() -> None:
    from impl.core.project_loader import load_project
    from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult
    from impl.projects.client_search.judge import ClientSearchJudge

    trace = RunTrace(
        trace_id="synthetic-empty-carrier",
        project_id="client_search",
        input={"query": "中银保信"},
        normalized_request={"query": "中银保信"},
        extracted_output={
            "conditions": [],
            "robot_text": "未识别到明确查询条件",
        },
    )
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id="client_search",
        business_expectations=[
            BusinessExpectation(expectation_id="core", blocking=True),
            BusinessExpectation(expectation_id="notice", blocking=False),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="core", status="not_fulfilled"),
            FulfillmentAssessment(expectation_id="notice", status="fulfilled"),
        ],
        overall_fulfillment={"status": "not_fulfilled"},
    )

    reconciled = ClientSearchJudge(load_project("client_search")).reconcile_result(
        trace, result
    )

    assert reconciled.fulfillment_assessments[0].status == "not_fulfilled"
    assert reconciled.fulfillment_assessments[1].status == "fulfilled"
    assert reconciled.overall_fulfillment["status"] == "not_fulfilled"
    assert reconciled.summary["fulfillment_status"] == "not_fulfilled"


def test_authority_disabled_reconcile_preserves_partial_delivery_failure() -> None:
    from impl.core.project_loader import load_project
    from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult
    from impl.projects.client_search.judge import ClientSearchJudge

    trace = RunTrace(
        trace_id="synthetic-partial-delivery",
        project_id="client_search",
        input={"query": "2025年6月份投保的新客户名单"},
        normalized_request={"query": "2025年6月份投保的新客户名单"},
        extracted_output={
            "conditions": [
                {"field": "isBuyInsurance", "operator": "CONTAINS", "value": ["客户", "准客"]},
            ],
            "robot_text": "提示：投保日期暂不支持搜索，系统将按可支持字段搜索。",
        },
    )
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id="client_search",
        business_expectations=[BusinessExpectation(expectation_id="core", blocking=True)],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="core", status="not_fulfilled")
        ],
    )

    reconciled = ClientSearchJudge(load_project("client_search")).reconcile_result(
        trace, result
    )

    assert reconciled.fulfillment_assessments[0].status == "not_fulfilled"
    assert reconciled.fulfillment_assessments[0].evidence_refs == []


def test_authority_disabled_partial_dimensions_keep_fulfilled_and_not_fulfilled() -> None:
    from impl.core.project_loader import load_project
    from impl.core.schema import BusinessExpectation, FulfillmentAssessment, JudgeResult
    from impl.projects.client_search.judge import ClientSearchJudge

    trace = RunTrace(
        trace_id="synthetic-enum-search-boundary",
        project_id="client_search",
        input={"query": "查一下徐晓燕名下是否有住院医疗保险"},
        normalized_request={"query": "查一下徐晓燕名下是否有住院医疗保险"},
        extracted_output={
            "conditions": [
                {"field": "searchClientName", "operator": "MATCH", "value": "徐晓燕"},
            ],
            "robot_text": "客户姓名为徐晓燕的客户",
        },
    )
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id="client_search",
        business_expectations=[
            BusinessExpectation(expectation_id="name", blocking=True),
            BusinessExpectation(expectation_id="insurance", blocking=True),
            BusinessExpectation(expectation_id="notice", blocking=False),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(expectation_id="name", status="fulfilled"),
            FulfillmentAssessment(expectation_id="insurance", status="not_fulfilled"),
            FulfillmentAssessment(expectation_id="notice", status="fulfilled"),
        ],
    )

    reconciled = ClientSearchJudge(load_project("client_search")).reconcile_result(
        trace, result
    )

    assert reconciled.fulfillment_assessments[0].status == "fulfilled"
    assert reconciled.fulfillment_assessments[1].status == "not_fulfilled"
    assert reconciled.fulfillment_assessments[2].status == "fulfilled"
    assert reconciled.overall_fulfillment["status"] == "not_fulfilled"


def test_material_mapping_conflict_opens_authority_without_choosing_precedence() -> None:
    from impl.projects.client_search.judge import _material_conflict_reasons

    trace = RunTrace(
        trace_id="synthetic-material-conflict",
        project_id="client_search",
        input={"user_text": "孤儿单"},
        normalized_request={"user_text": "孤儿单"},
        extracted_output={"conditions": []},
    )
    reasons = _material_conflict_reasons(
        trace,
        {"orphanType": {"notes": "当前口径：孤儿单=在职有效客户；有存续单=纯存续单客户。"}},
        {"orphanType": {"孤儿单": "纯存续单客户"}},
    )

    assert reasons == ["conflicting_materials:value_mapping:orphanType:孤儿单"]


def test_empty_actual_opens_missing_carrier_authority_but_explicit_unsupported_does_not() -> None:
    from impl.projects.client_search.judge import _authority_candidate_reasons
    from impl.core.project_loader import load_project

    trace = RunTrace(
        trace_id="synthetic-missing-carrier",
        project_id="client_search",
        input={"user_text": "某机构名称"},
        normalized_request={"user_text": "某机构名称"},
        extracted_output={"conditions": []},
    )
    reasons = _authority_candidate_reasons(
        load_project("client_search"),
        trace,
        enum_completeness_evidence=[],
        unsupported_boundary_evidence={},
    )
    unsupported = _authority_candidate_reasons(
        load_project("client_search"),
        trace,
        enum_completeness_evidence=[],
        unsupported_boundary_evidence={
            "explicit_unsupported_capability": True,
            "all_conditions_unsupported": False,
        },
    )

    assert "missing_semantic_carrier:empty_actual_conditions" in reasons
    assert "missing_semantic_carrier:empty_actual_conditions" not in unsupported


def test_pre_authority_obligations_are_material_decision_guidance_not_key_index() -> None:
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import _authority_pre_obligations

    obligations = _authority_pre_obligations(
        load_project("client_search"),
        trace_fields={"orphanType"},
        compact_manifest={
            "orphanType": {"field": "orphanType", "enums": ["在职有效客户"]}
        },
        mapping_values={"orphanType": {"孤儿单": "在职有效客户"}},
        enhanced_rules={},
        unsupported_boundary_evidence={},
        authority_available=False,
    )

    kinds = {item["obligation_kind"] for item in obligations}
    assert {"field_carrier_and_translation", "enum_space", "spoken_value_mapping"} <= kinds
    assert all(item["authority_availability"] == "unavailable" for item in obligations)
    refs = {
        ref["material_decision_ref"]
        for item in obligations
        for ref in item["governed_by"]
    }
    assert "business-field-definitions#decision-1" in refs
    assert "business-field-enums#decision-1" in refs
    assert all("key-index" not in ref for ref in refs)


def test_authority_disabled_context_does_not_inject_unusable_pre_obligations() -> None:
    from impl.core.project_loader import load_project
    from impl.core.schema import RunTrace
    from impl.projects.client_search.judge import _build_core_context

    context = _build_core_context(
        load_project("client_search"),
        RunTrace(
            trace_id="authority-disabled-context",
            project_id="client_search",
            input={"user_text": "查一下徐晓燕名下是否有住院医疗保险"},
            normalized_request={"user_text": "查一下徐晓燕名下是否有住院医疗保险"},
            extracted_output={
                "conditions": [
                    {
                        "field": "searchClientName",
                        "operator": "MATCH",
                        "value": "徐晓燕",
                    }
                ],
                "query_logic": "AND",
                "robot_text": "客户姓名为徐晓燕的客户",
            },
        ),
    )

    extras = context["user_prompt_extras"]
    assert extras["authority_mode"] == "disabled_with_candidates"
    assert "authority_candidate_reasons" not in extras
    assert "authority_obligation_contract" not in extras
    prompt = "\n".join(context["system_prompt_extras"])
    assert "不得仅因 Authority 关闭或存在边界候选而判 not_evaluable" in prompt
