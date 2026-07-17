"""deerflow 项目的 Judge 实现

实现 ProjectJudge 协议：多轮营销规划对话的判定逻辑。
判定关键维度：stage 路由、维度累积、NBEV 脚本调用、fallback 边界。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from impl.core.judge_protocol import ProjectJudge
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, normalize_judge_result, to_dict


def _list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _application_boundary_from_trace(trace: RunTrace) -> Dict[str, Any]:
    from impl.core.schema import trace_application_boundary
    boundary = trace_application_boundary(trace)
    if boundary:
        return boundary
    project_fields = trace.project_fields or {} if isinstance(trace.project_fields, dict) else {}
    return dict(project_fields.get("application_boundary") or {})


def _reference_contract(trace: RunTrace) -> Dict[str, Any]:
    return trace.reference_contract if isinstance(trace.reference_contract, dict) else {}


def _planning_summary(trace: RunTrace) -> Dict[str, Any]:
    project_fields = trace.project_fields or {} if isinstance(trace.project_fields, dict) else {}
    summary = project_fields.get("planning_summary") if isinstance(project_fields, dict) else None
    return summary if isinstance(summary, dict) else {}


def build_judge_context(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    """构建 Judge 判定上下文（项目业务语义）。"""
    application_boundary = _application_boundary_from_trace(trace)
    reference = _reference_contract(trace)
    planning_summary = _planning_summary(trace)
    return {
        "project_type": "multi_turn_deerflow_marketing_planning",
        "current_case_only": True,
        "reference_contract": reference,
        "output_summary": planning_summary or trace.extracted_output,
        "application_boundary": application_boundary,
        "expected_stage": reference.get("expected_stage"),
        "expected_dimensions": _list(reference.get("required_dimensions")),
        "stage_rules": {
            "clarification": "缺字段时澄清是正确方向，规划脚本通常是可疑证据。",
            "planning": "规划场景必须检查 dimensions、scripts、fallback 和 multi-turn accumulation。",
            "non_agent": "非营销规划意图（如闲聊），应被正确路由到 non_agent stage。",
            "fallback": "fallback 是否正确取决于当前 boundary 是否允许。",
        },
    }


def build_intent_frame(spec: ProjectSpec, trace: RunTrace, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构建意图框架：下游消费者是谁、用户意图在哪、边界提示。"""
    context = context if context is not None else build_judge_context(spec, trace)
    request_candidates = []
    for source_name, source_value in (("normalized_request", trace.normalized_request or {}), ("input", trace.input or {})):
        if isinstance(source_value, dict):
            for key in ("query", "user_intent", "question", "input"):
                value = source_value.get(key)
                if value:
                    request_candidates.append({"source": f"{source_name}.{key}", "value": value})
        elif source_value:
            request_candidates.append({"source": source_name, "value": source_value})
    return {
        "project_id": spec.project_id,
        "downstream_consumer": "deer-flow marketing planning user",
        "request_candidates": request_candidates,
        "boundary_hints": context.get("application_boundary") or {},
        "output_semantics": "route the current marketing demand to the proper stage, accumulate required dimensions, and invoke NBEV scripts within the project boundary",
        "business_task_type": "multi_turn_deerflow_marketing_planning",
        "critical_intent_dimensions": [
            "business_metric",
            "target_value_and_unit",
            "decomposition_dimensions",
            "stage_routing",
            "nbev_script_invocation",
            "multi_turn_accumulation",
        ],
        "boundary_rules": context.get("application_boundary") or {},
        "expected_stage": context.get("expected_stage"),
        "expected_dimensions": context.get("expected_dimensions") or [],
    }


def _build_core_context(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    """构建 judge LLM 的完整上下文（含 system/user prompt extras）。"""
    context = build_judge_context(spec, trace) or {}
    intent_frame = build_intent_frame(spec, trace, context)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")
    system_extras: list[str] = []
    if critical_dimensions:
        system_extras.append(
            "## deerflow 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕业务指标、目标值与单位、拆解维度、stage 路由、NBEV 脚本调用和多轮累积交付判断 fulfillment。\n"
        )
    return {
        "user_intent": context.get("user_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "output_summary": context.get("output_summary") or {},
            "application_boundary": context.get("application_boundary") or {},
            "expected_stage": context.get("expected_stage"),
            "expected_dimensions": context.get("expected_dimensions") or [],
            "stage_rules": context.get("stage_rules") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


def normalize_judge_result_for_project(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    """项目侧 normalize_result：按 reference contract 校验契约是否满足。"""
    planning_summary = _planning_summary(trace)
    expected = _reference_contract(trace)
    expected_stage = expected.get("expected_stage")
    actual_stage = planning_summary.get("stage")
    expected_dimensions = _list(expected.get("required_dimensions"))
    actual_scripts = _list(planning_summary.get("scripts_called") or [])
    actual_reply_text = str(planning_summary.get("reply_text") or "")
    fallback = planning_summary.get("fallback") or {}
    application_boundary = _application_boundary_from_trace(trace)
    allow_fallback = bool(expected.get("allow_fallback") or application_boundary.get("allow_fallback"))

    failures: list[Dict[str, Any]] = []
    if expected_stage and actual_stage and expected_stage != actual_stage:
        failures.append({
            "requirement": "expected_stage",
            "expected_fragment": expected_stage,
            "actual_fragment": actual_stage,
            "status": "wrong",
            "evidence": ["stage routing mismatch between reference and actual output"],
        })
    # 检查 expected_dimensions 是否有对应脚本调用
    if expected_dimensions:
        dimension_to_script = {
            "product": "run_profile.py",
            "team": "run_profile.py",
            "customer": "run_profile.py",
            "activity": "run_playbook.py",
        }
        missing_dimensions = []
        for dimension in expected_dimensions:
            script = dimension_to_script.get(dimension)
            if script and script not in actual_scripts and dimension.lower() not in actual_reply_text.lower():
                missing_dimensions.append(dimension)
        if missing_dimensions:
            failures.append({
                "requirement": "expected_dimensions",
                "expected_fragment": expected_dimensions,
                "actual_fragment": {"scripts": actual_scripts, "reply_text": actual_reply_text[:200]},
                "status": "missing",
                "evidence": ["required dimensions not covered by scripts or reply"],
            })
    if fallback.get("used") and not allow_fallback:
        failures.append({
            "requirement": "allow_fallback",
            "expected_fragment": False,
            "actual_fragment": fallback,
            "status": "wrong",
            "evidence": ["fallback used but reference/boundary does not allow it"],
        })

    judge_result.actual = trace.extracted_output
    if not failures:
        return judge_result

    for failure in failures:
        requirement = failure.get("requirement") or "contract"
        evidence_text = "; ".join(failure.get("evidence") or []) or failure.get("status") or "mismatch"
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": f"deerflow_contract:{requirement}",
            "status": "not_fulfilled",
            "blocking": True,
            "evidence": evidence_text,
            "downstream_impact": failure_downstream_impact(requirement, failure),
        }]
    return judge_result


def failure_downstream_impact(requirement: str, failure: Dict[str, Any]) -> str:
    """不同契约失败的下游影响描述。"""
    impacts = {
        "expected_stage": "stage 路由错误，下游无法进入预期流程",
        "expected_dimensions": "规划的维度缺失，用户拿不到期望维度的营销规划结果",
        "allow_fallback": "fallback 在不允许的边界内触发，违反 boundary 契约",
    }
    return impacts.get(requirement, f"{requirement} 契约不满足")


class DeerflowJudge(ProjectJudge):
    """deerflow 项目 Judge 实现（新协议）。"""

    def build_context(self, trace: RunTrace) -> Dict[str, Any]:
        return _build_core_context(self.spec, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return build_intent_frame(self.spec, trace, context)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        judge_result = normalize_judge_result(result) or result
        return normalize_judge_result_for_project(self.spec, trace, judge_result)
