from __future__ import annotations

import json
from typing import Optional

from .llm_client import LlmClient
from .project_loader import load_project_document
from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _taxonomy(spec: ProjectSpec) -> set[str]:
    taxonomy = spec.frontend_extensions.get("error_taxonomy") if spec.frontend_extensions else None
    return set(taxonomy or [])


def _normalize_incomplete_reason(data: dict) -> str:
    reason = str(data.get("incomplete_reason") or "")
    quality = data.get("analysis_quality") or {}
    if reason or not isinstance(quality, dict) or quality.get("passed") is not False:
        return reason
    missing = quality.get("missing") or []
    if missing:
        return "归因质量门未通过，缺少证据：" + "、".join(str(item) for item in missing)
    return "归因质量门未通过，当前证据不足以支撑正式根因。"


def attribute_failure(
    spec: ProjectSpec,
    trace: RunTrace,
    judge: JudgeResult,
    llm: Optional[LlmClient] = None,
    project_attribute_context: Optional[dict] = None,
) -> AttributeResult:
    if judge.verdict == "correct":
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            failure_category="none",
            failure_stage="none",
            analysis_method="judge_correct_no_failure",
            evidence_chain=list(judge.evidence or [judge.reasoning_summary or "judge verdict is correct"]),
            trace_analysis=list(trace.execution_trace or []),
            chain_nodes=[],
            local_verifications=[],
            earliest_divergence={},
            evidence_coverage={"judge_evidence": bool(judge.evidence or judge.reasoning_summary)},
            analysis_quality={"passed": True, "missing": []},
            incomplete_reason="",
            suspected_locations=[],
            root_cause_hypothesis="未发现失败；当前输出满足项目评估标准。",
            verification_steps=["除非用户质疑 judge 结果，否则不需要失败专项验证。"],
            patch_direction=["本次运行不建议修改。"],
            business_impact="本次运行未发现负面业务影响。",
            primary_error_type="none",
            error_types=[],
            severity="none",
            needs_human_review=False,
            scenario=str(trace.project_fields.get("scenario") or ""),
            quality_flags=[],
        )
    attribution = load_project_document(spec, "attribution")
    system = "你是通用评估系统的 attribute agent。目标是形成能帮助开发解决问题的证据链、根因假设、验证步骤和修改方向。必须基于当前 RunTrace/JudgeResult，不继承历史 case；如果 judge_method/quality_flags 表明 judge 调用不可用或 verdict 不是可解释的 incorrect/uncertain，不得产出正式根因，必须用 incomplete_reason 阻断。归因中提到的字段、期望条件和修复方向必须能从当前 query、actual、expected、execution_trace、project_attribute_context.chain_nodes_to_check 或项目文档中找到证据，不能把其他历史 case 的字段带入当前问题。先重建当前 expected-vs-actual gap，再按项目提供的 chain_nodes_to_check 或 RunTrace.execution_trace 逐段标记 normal/suspicious/failed/not_verified，指出 earliest_divergence；suspected_locations 只能在有代码/配置/文档证据时填写，没有同 query 链路证据时必须说明待验证而不是编造补丁。如果 project_attribute_context.application_boundary 已经把外部依赖排除在当前 judge_scope 外，不要把该外部依赖当作根因或反复要求验证，只把它作为范围约束并聚焦范围内的可控链路。能做本地验证就记录 local_verifications，不能做就写 incomplete_reason；analysis_quality 必须说明证据是否足够支撑开发修改。不要编造路径、函数、行号、日志或测试结果。分析文字尽量使用中文，输出 JSON。"
    user = json.dumps(
        {
            "attribution_spec": attribution,
            "run_trace": trace.__dict__,
            "judge_result": judge.__dict__,
            "project_attribute_context": project_attribute_context or {},
            "allowed_error_taxonomy": sorted(_taxonomy(spec)),
            "required_output": {
                "failure_category": "string",
                "failure_stage": "string",
                "analysis_method": "string",
                "evidence_chain": [],
                "trace_analysis": [],
                "chain_nodes": [
                    {"name": "string", "status": "normal|suspicious|failed|not_verified", "evidence": [], "reason": "string"}
                ],
                "local_verifications": [
                    {"method": "string", "target": "string", "result": "string", "evidence": []}
                ],
                "earliest_divergence": {
                    "node": "string",
                    "expected": "object|string|null",
                    "actual": "object|string|null",
                    "evidence": [],
                    "confidence": "high|medium|low|unknown"
                },
                "evidence_coverage": {
                    "query": "boolean",
                    "actual": "boolean",
                    "expected": "boolean",
                    "execution_trace": "boolean",
                    "project_docs": "boolean",
                    "code_or_config": "boolean",
                    "unsupported_claims": []
                },
                "analysis_quality": {
                    "passed": "boolean",
                    "missing": [],
                    "standard": "string"
                },
                "incomplete_reason": "string",
                "suspected_locations": [],
                "root_cause_hypothesis": "string",
                "verification_steps": [],
                "patch_direction": [],
                "business_impact": "string",
                "primary_error_type": "string",
                "error_types": [],
                "severity": "string",
                "needs_human_review": "boolean|null",
                "scenario": "string",
                "quality_flags": [],
            },
        },
        ensure_ascii=False,
    )
    data = (llm or LlmClient()).complete_json(system, user)
    if data.get("error") or "llm_call_failed" in (judge.quality_flags or []):
        error_text = data.get("raw_text") or data.get("error") or judge.reasoning_summary or "judge LLM call failed"
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            failure_category="未归因",
            failure_stage="llm_attribute_call" if data.get("error") else "judge_llm_call",
            analysis_method="llm_call_failed" if data.get("error") else "judge_llm_failed_blocked_attribute",
            evidence_chain=[error_text, *(judge.evidence or [])],
            trace_analysis=list(trace.execution_trace or []),
            chain_nodes=[{"name": "semantic judge or attribute LLM", "status": "failed", "evidence": [error_text], "reason": error_text}],
            local_verifications=[],
            earliest_divergence={"node": "semantic judge or attribute LLM", "evidence": [error_text], "confidence": "high"},
            evidence_coverage={"query": bool(trace.normalized_request or trace.input), "actual": bool(trace.extracted_output), "expected": bool(judge.expected), "execution_trace": bool(trace.execution_trace), "project_docs": False, "code_or_config": False, "unsupported_claims": []},
            analysis_quality={"passed": False, "missing": ["semantic judge result" if "llm_call_failed" in (judge.quality_flags or []) else "attribute LLM result"], "standard": "归因必须基于当前 case 的 judge、trace 和可验证链路证据。"},
            incomplete_reason="judge LLM 调用失败，不能产出正式根因。" if "llm_call_failed" in (judge.quality_flags or []) else "attribute agent LLM 调用失败。",
            suspected_locations=[],
            root_cause_hypothesis="语义 judge 或 attribute agent 调用失败，当前只能确认执行 trace，无法完成正式归因。",
            verification_steps=["检查 LLM API key、余额、网络和模型配置。", "恢复 LLM 后重新运行 judge 和 attribute agent。"],
            patch_direction=["修复 LLM 调用配置或费用问题；不要把该兜底结果当作最终业务根因。"],
            business_impact="当前 case 需要人工复核，不能进入正式失败根因聚簇。",
            primary_error_type="needs_human_review",
            error_types=["needs_human_review"],
            severity="unknown",
            needs_human_review=True,
            scenario=str(trace.project_fields.get("scenario") or ""),
            quality_flags=[*(judge.quality_flags or []), "attribute_blocked"],
            raw_model_output=data,
        )
    primary_error_type = str(data.get("primary_error_type") or data.get("failure_category") or "未归因")
    taxonomy = _taxonomy(spec)
    if taxonomy and primary_error_type not in taxonomy:
        primary_error_type = "needs_human_review" if "needs_human_review" in taxonomy else primary_error_type
    error_types = [str(item) for item in list(data.get("error_types") or [])]
    if taxonomy:
        error_types = [item for item in error_types if item in taxonomy]
    if primary_error_type and primary_error_type != "none" and primary_error_type not in error_types:
        error_types.append(primary_error_type)
    incomplete_reason = _normalize_incomplete_reason(data)
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        failure_category=str(data.get("failure_category") or "未归因"),
        failure_stage=str(data.get("failure_stage") or "不确定"),
        analysis_method=str(data.get("analysis_method") or "current_case_llm_attribute"),
        evidence_chain=list(data.get("evidence_chain") or []),
        trace_analysis=list(data.get("trace_analysis") or trace.execution_trace or []),
        chain_nodes=list(data.get("chain_nodes") or []),
        local_verifications=list(data.get("local_verifications") or []),
        earliest_divergence=dict(data.get("earliest_divergence") or {}),
        evidence_coverage=dict(data.get("evidence_coverage") or {}),
        analysis_quality=dict(data.get("analysis_quality") or {}),
        incomplete_reason=incomplete_reason,
        suspected_locations=list(data.get("suspected_locations") or []),
        root_cause_hypothesis=str(data.get("root_cause_hypothesis") or ""),
        verification_steps=list(data.get("verification_steps") or []),
        patch_direction=list(data.get("patch_direction") or []),
        business_impact=str(data.get("business_impact") or ""),
        primary_error_type=primary_error_type,
        error_types=error_types,
        severity=str(data.get("severity") or ""),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.project_fields.get("scenario") or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
