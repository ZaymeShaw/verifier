from __future__ import annotations

from impl.core.authority_environment import AUTHORITY_RUNTIME_PROTOCOL_VERSION
from impl.core.authority_gate import apply_authority_gate
from impl.core.judge import finalize_judge_result
from impl.core.schema import (
    AuthorityResolution,
    BusinessExpectation,
    FulfillmentAssessment,
    JudgeResult,
    to_dict,
)
from impl.core.summary import summary_from_fulfillment
from impl.projects.client_search.judge_execution import (
    _judge_self_check,
)


def test_semantic_authority_blocks_downstream_decisive_overall_claim() -> None:
    result = JudgeResult(
        trace_id="trace-1",
        project_id="client_search",
        business_expectations=[
            BusinessExpectation(expectation_id="semantic-point", blocking=True),
            BusinessExpectation(expectation_id="downstream-point", blocking=True),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="semantic-point",
                status="fulfilled",
                authority_tool_call_ids=["tc-semantic"],
            ),
            FulfillmentAssessment(
                expectation_id="downstream-point",
                status="not_fulfilled",
            ),
        ],
    )
    apply_authority_gate(
        result,
        tool_audit={
            "tc-semantic": {
                "resolution": AuthorityResolution(
                    status="unresolved",
                    statement="",
                    reason="产品术语资料与历史案例来自不同治理链路，当前无法确认正式采用哪套定义。",
                    basis_evidence_ref_ids=("glossary", "history"),
                    required_evidence=("正式定义来源与生效版本",),
                ),
                "environment_snapshot_sha256": "snapshot-1",
            }
        },
    )
    finalized = finalize_judge_result(result)

    # authority.md §8：Authority 不单独参与 overall 聚合，先影响对应
    # assessment 状态，再由现有 blocking 规则聚合。依赖 unresolved 的
    # assessment 转 not_evaluable；独立的 decisive 失败仍按 blocking 规则
    # 决定整体状态（此处 downstream-point 独立 not_fulfilled → overall 失败）。
    assert finalized.fulfillment_assessments[0].status == "not_evaluable"
    assert finalized.fulfillment_assessments[1].status == "not_fulfilled"
    assert finalized.overall_fulfillment["status"] == "not_fulfilled"


def test_summary_prefers_structured_authority_limitation() -> None:
    result = JudgeResult(
        trace_id="trace-1",
        project_id="client_search",
        business_expectations=[
            BusinessExpectation(expectation_id="semantic-point", blocking=True),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="semantic-point",
                status="fulfilled",
                authority_tool_call_ids=["tc-semantic"],
            ),
        ],
    )
    result.reasoning_summary = "LLM 给出的笼统说明"
    apply_authority_gate(
        result,
        tool_audit={
            "tc-semantic": {
                "resolution": AuthorityResolution(
                    status="unresolved",
                    statement="",
                    reason="产品术语资料与历史案例来自不同治理链路，当前无法确认正式采用哪套定义。",
                    basis_evidence_ref_ids=("glossary", "history"),
                    required_evidence=("正式定义来源与生效版本",),
                ),
                "environment_snapshot_sha256": "snapshot-1",
            }
        },
    )
    finalized = finalize_judge_result(result)
    summary = summary_from_fulfillment(to_dict(finalized))

    assert "Authority" in summary["reason"]
    assert "未解决" in summary["reason"]
    assert "正式定义来源" in summary["reason"]
    assert "待澄清" in summary["reason"]
    assert "semantic-point" in summary["reason"]
    assert "LLM 给出的笼统说明" not in summary["reason"]
    assert summary["reason_source"] == "authority_limitation"


def test_judge_self_check_requests_correction_for_empty_authority_tool_call_id() -> None:
    data = {
        "fulfillment_assessments": [{
            "expectation_id": "point-1",
            "status": "fulfilled",
            "authority_tool_call_ids": ["  "],
        }]
    }
    expectations = [{"expectation_id": "point-1"}]

    inconsistencies = _judge_self_check(data, expectations)

    assert inconsistencies == [{
        "kind": "empty_authority_tool_call_id",
        "where": "fulfillment_assessments[0].authority_tool_call_ids",
        "value": ["  "],
        "expected": (
            "authority_tool_call_ids entries must be non-empty "
            "tool_call_id strings; Core 后处理会校验引用存在与 resolution"
        ),
    }]


def test_protocol_version_is_explicit() -> None:
    assert AUTHORITY_RUNTIME_PROTOCOL_VERSION == 2
