from __future__ import annotations

from typing import Optional

from impl.core.judge_protocol import run_project_judge_protocol
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, to_dict


def _build_core_context(adapter, trace: RunTrace) -> dict:
    context = adapter.build_judge_context(trace) or {}
    intent_frame = adapter.build_intent_frame(trace)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")
    system_extras = []
    if critical_dimensions:
        system_extras.append(
            "## QA 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕当前问题、上下文/参考答案依赖、事实性、忠实性、矛盾风险和答案可用性判断 fulfillment。\n"
        )
    return {
        "expected_intent": context.get("expected_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "score_dimensions": context.get("score_dimensions") or [],
            "error_taxonomy": context.get("error_taxonomy") or [],
            "application_boundary": context.get("application_boundary") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


# spec/info-volume.md：QA 的 judge 策略属于项目层；core.judge 只保留通用 fulfillment 协议。
def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(adapter, trace),
    )
