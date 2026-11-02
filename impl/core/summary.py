from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


_FAILURE_DIMENSION_STATUSES = {"not_fulfilled"}


def aggregate_failure_dimensions(judge: dict) -> list[dict]:
    assessments = judge.get("fulfillment_assessments") or []
    blocking_by_id = {
        str(item.get("expectation_id") or ""): bool(item.get("blocking"))
        for item in (judge.get("business_expectations") or [])
        if isinstance(item, dict)
    }
    reasoning = judge.get("reasoning_summary") or ""
    dimensions: list[dict] = []
    for item in assessments:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _FAILURE_DIMENSION_STATUSES:
            continue
        evidence_parts: list[str] = []
        for key in ("actual_evidence", "expected_evidence", "evidence_refs"):
            ev = item.get(key)
            if isinstance(ev, list):
                for entry in ev:
                    if isinstance(entry, str) and entry:
                        evidence_parts.append(entry)
                    elif isinstance(entry, dict):
                        text = entry.get("summary") or entry.get("value") or entry.get("ref") or entry.get("reason")
                        if text:
                            evidence_parts.append(str(text))
            elif isinstance(ev, str) and ev:
                evidence_parts.append(ev)
        if not evidence_parts and (item.get("downstream_impact")):
            evidence_parts.append(str(item.get("downstream_impact")))
        if not evidence_parts and reasoning:
            evidence_parts.append(reasoning)
        dimensions.append({
            "expectation_id": item.get("expectation_id") or "",
            "status": status,
            "blocking": blocking_by_id.get(str(item.get("expectation_id") or ""), False),
            "downstream_impact": item.get("downstream_impact") or "",
            "evidence": " | ".join(evidence_parts) if evidence_parts else "",
        })
    dimensions.sort(key=lambda dim: (not dim["blocking"], dim["expectation_id"]))
    return dimensions


BUSINESS_CALL_FAILED = "business_call_failed"
# 展示状态：被测系统以非 2xx 报错。判定协议里仍是 not_fulfilled（用户没拿到答复），
# 展示单列为 fail，免得读成"业务答得不好"；统计、筛选、导出都读这个字段。
DISPLAY_FAIL = "fail"


def summary_from_fulfillment(judge: dict) -> dict:
    """从 judge 结果中提取前端展示用的摘要。

    spec/info-volume.md：verdict 已删除，改用 overall_fulfillment.status 驱动。
    输出字段不变，前端兼容。
    """
    dimensions = aggregate_failure_dimensions(judge)
    if BUSINESS_CALL_FAILED in (judge.get("evidence") or []):
        detail = str(judge.get("reasoning_summary") or "").removeprefix("被测系统调用失败：")
        return {
            "reason": f"fail · 被测系统报错：{detail}",
            "primary_failure_dimensions": dimensions,
            "reason_source": BUSINESS_CALL_FAILED,
            "fulfillment_status": DISPLAY_FAIL,
            "assessment_count": len(judge.get("fulfillment_assessments") or []),
            "blocking_count": 1,
            "is_formal_attribution": False,
        }
    reasoning_summary = judge.get("reasoning_summary") or ""
    overall = judge.get("overall_fulfillment") or {}
    fulfillment_status = overall.get("status") or ""
    assessments = judge.get("fulfillment_assessments") or []
    assessment_count = len(assessments)
    expectations = judge.get("business_expectations") or []
    blocking_count = len([item for item in expectations if isinstance(item, dict) and item.get("blocking")])
    nonblocking_failures = len([dim for dim in dimensions if not dim["blocking"]])
    authority_limitations = []
    for assessment in assessments:
        if not (
            isinstance(assessment, dict)
            and assessment.get("status") == "not_evaluable"
        ):
            continue
        expectation_id = str(assessment.get("expectation_id") or "")
        for evidence in assessment.get("actual_evidence") or []:
            if (
                isinstance(evidence, dict)
                and evidence.get("kind") == "authority_limitation"
            ):
                authority_limitations.append({
                    "analysis_id": str(evidence.get("analysis_id") or ""),
                    "judgment_point": str(
                        evidence.get("judgment_point") or ""
                    ),
                    "conflicting_sources": (
                        evidence.get("conflicting_sources") or []
                    ),
                    "causal_reasoning": str(
                        evidence.get("causal_reasoning") or ""
                    ),
                    "unresolved_question": str(
                        evidence.get("unresolved_question") or ""
                    ),
                    "point_id": str(evidence.get("point_id") or expectation_id),
                })
        for evidence in assessment.get("evidence_refs") or []:
            if (
                isinstance(evidence, dict)
                and evidence.get("kind") == "authority_unresolved"
            ):
                required = list(evidence.get("required_evidence") or [])
                authority_limitations.append({
                    "analysis_id": str(
                        evidence.get("tool_call_id") or ""
                    ),
                    "judgment_point": "",
                    "conflicting_sources": [],
                    "causal_reasoning": str(evidence.get("reason") or ""),
                    "unresolved_question": "；".join(
                        str(item) for item in required
                    ),
                    "point_id": expectation_id,
                })

    if authority_limitations:
        parts = []
        for limitation in authority_limitations:
            source_text = "；".join(
                f"{item.get('source_label') or item.get('source_id')}：{item.get('claim')}"
                for item in limitation.get("conflicting_sources") or []
                if isinstance(item, dict)
            )
            parts.append(
                "Authority "
                f"{limitation.get('analysis_id') or ''}"
                f"（{limitation.get('judgment_point') or ''}）未解决；"
                f"冲突来源：{source_text or '未提供'}；"
                f"原因：{limitation.get('causal_reasoning') or '当前调查无法确定'}；"
                f"待澄清：{limitation.get('unresolved_question') or '未提供'}；"
                f"受影响验收点：{limitation.get('point_id') or ''}"
            )
        reason = "not_evaluable · " + " | ".join(parts)
        reason_source = "authority_limitation"
    elif fulfillment_status == "fulfilled":
        tail = f" · {reasoning_summary}" if reasoning_summary else ""
        incomplete = f" · {nonblocking_failures} non-blocking gaps" if nonblocking_failures else ""
        reason = f"fulfilled · {blocking_count} blocking expectations all met{incomplete}{tail}"
        reason_source = "aggregated_fulfillment"
    elif fulfillment_status == "not_fulfilled":
        blocking_ids = [dim["expectation_id"] for dim in dimensions if dim["blocking"] and dim["expectation_id"]]
        ids_text = ",".join(blocking_ids) if blocking_ids else "(none)"
        primary_impact = next((dim["downstream_impact"] for dim in dimensions if dim["downstream_impact"]), "")
        tail = f" · {reasoning_summary}" if reasoning_summary else (" · " + primary_impact if primary_impact else "")
        reason = f"not_fulfilled · blocking=[{ids_text}]{tail}"
        reason_source = "aggregated_fulfillment"
    elif fulfillment_status == "not_evaluable" and expectations and not blocking_count:
        reason = (
            "not_evaluable · 缺少覆盖用户核心诉求的 blocking 必办验收项；"
            "无法证明用户真正要办的事已经完成，需要补齐验收项或人工复核"
        )
        reason_source = "aggregated_fulfillment"
    elif fulfillment_status == "not_evaluable" and expectations and not assessments:
        reason = "not_evaluable · 已声明业务期望，但没有 fulfillment assessment 证据"
        reason_source = "aggregated_fulfillment"
    else:
        tail = reasoning_summary or "unclear"
        reason = f"not_evaluable · {tail}"
        reason_source = "reasoning_summary"

    return {
        "reason": reason,
        "primary_failure_dimensions": dimensions,
        "reason_source": reason_source,
        "fulfillment_status": fulfillment_status,
        "assessment_count": assessment_count,
        "blocking_count": blocking_count,
        "is_formal_attribution": reason_source == "aggregated_fulfillment",
    }


def summary_from_attribution(
    attribute: dict,
    failed_expectation_ids: Optional[Iterable[str]] = None,
    *,
    judge_status: str = "",
) -> dict:
    """Deterministically derive the display summary from reviewed findings."""
    if not attribute:
        return {}
    findings = list(attribute.get("findings") or [])
    unresolved_reason = str(attribute.get("unresolved_reason") or "").strip()
    failed_ids = list(dict.fromkeys(str(item) for item in (failed_expectation_ids or []) if str(item)))
    covered_ids = list(dict.fromkeys(
        str(expectation_id)
        for finding in findings
        for expectation_id in (finding.get("affected_expectation_ids") or [])
        if str(expectation_id)
    ))
    unresolved_ids = [item for item in failed_ids if item not in set(covered_ids)]
    if judge_status == "fulfilled" and not failed_ids:
        status = "not_applicable"
        summary_text = "Judge 未发现需要归因的 not_fulfilled business gap。"
    elif findings and not unresolved_ids and not unresolved_reason:
        status = "complete"
        lines = [str(item.get("conclusion") or "").strip() for item in findings]
        summary_text = "\n".join(item for item in lines if item)
    elif findings:
        status = "partial"
        lines = [str(item.get("conclusion") or "").strip() for item in findings]
        summary_text = "\n".join(item for item in [*lines, unresolved_reason] if item)
    else:
        status = "unresolved"
        summary_text = unresolved_reason
    is_formal = bool(findings)
    return {
        "summary_text": summary_text,
        "finding_count": len(findings),
        "covered_expectation_ids": covered_ids,
        "unresolved_expectation_ids": unresolved_ids,
        "attribution_status": status,
        "is_complete": status == "complete",
        "is_formal_attribution": is_formal,
    }
