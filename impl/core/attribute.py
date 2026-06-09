from __future__ import annotations

import json
from typing import Optional

from .llm_client import LlmClient
from .project_loader import load_project_document
from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def attribute_failure(spec: ProjectSpec, trace: RunTrace, judge: JudgeResult, llm: Optional[LlmClient] = None) -> AttributeResult:
    if judge.verdict == "correct":
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            failure_category="none",
            failure_stage="none",
            evidence_chain=list(judge.evidence or [judge.reasoning_summary or "judge verdict is correct"]),
            trace_analysis=list(trace.execution_trace or []),
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
    system = "你是通用评估系统的 attribute agent。目标是形成能帮助开发解决问题的证据链、根因假设、验证步骤和修改方向。必须基于当前 RunTrace/JudgeResult，不继承历史 case；优先沿 execution_trace 标记正常、可疑、失败、未验证节点；不要编造路径、函数、行号、日志或测试结果；如果没有代码链路证据，要明确说明。分析文字尽量使用中文，输出 JSON。"
    user = json.dumps(
        {
            "attribution_spec": attribution,
            "run_trace": trace.__dict__,
            "judge_result": judge.__dict__,
            "required_output": {
                "failure_category": "string",
                "failure_stage": "string",
                "evidence_chain": [],
                "trace_analysis": [],
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
    if data.get("error"):
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            failure_category="未归因",
            failure_stage="不确定",
            evidence_chain=[data.get("raw_text") or data.get("error")],
            primary_error_type="needs_human_review",
            error_types=["needs_human_review"],
            severity="unknown",
            needs_human_review=True,
            scenario=str(trace.project_fields.get("scenario") or ""),
            quality_flags=["llm_call_failed"],
            raw_model_output=data,
        )
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        failure_category=str(data.get("failure_category") or "未归因"),
        failure_stage=str(data.get("failure_stage") or "不确定"),
        evidence_chain=list(data.get("evidence_chain") or []),
        trace_analysis=list(data.get("trace_analysis") or trace.execution_trace or []),
        suspected_locations=list(data.get("suspected_locations") or []),
        root_cause_hypothesis=str(data.get("root_cause_hypothesis") or ""),
        verification_steps=list(data.get("verification_steps") or []),
        patch_direction=list(data.get("patch_direction") or []),
        business_impact=str(data.get("business_impact") or ""),
        primary_error_type=str(data.get("primary_error_type") or data.get("failure_category") or "未归因"),
        error_types=list(data.get("error_types") or []),
        severity=str(data.get("severity") or ""),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.project_fields.get("scenario") or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
