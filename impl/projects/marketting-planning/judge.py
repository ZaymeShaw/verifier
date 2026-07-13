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
            "## marketing-planning 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕业务指标、目标值与单位、时间范围、拆解维度、stage 路由、planning 可执行性和 SSE 完整性交付判断 fulfillment。\n"
        )
    return {
        "expected_intent": context.get("expected_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "output_summary": context.get("output_summary") or {},
            "application_boundary": context.get("application_boundary") or {},
            "expected_stage": context.get("expected_stage"),
            "expected_path_types": context.get("expected_path_types") or [],
            "expected_cards": context.get("expected_cards") or [],
            "stage_rules": context.get("stage_rules") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


# spec/info-volume.md：marketing-planning 的 judge 策略属于项目层；core.judge 只保留通用 fulfillment 协议。
def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(adapter, trace),
    )


from impl.core.judge_protocol import ProjectJudge


class MarketingPlanningJudge(ProjectJudge):
    """marketting-planning 项目 Judge 实现（新协议）。

    迁移过渡期：扩展点委托 adapter 现有方法。
    """

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(self._adapter, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return self._adapter.build_intent_frame(trace)

    def pre_judge(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return self._adapter.pre_judge_result(trace, expected_intent=expected_intent)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        from impl.core.schema import normalize_judge_result
        return normalize_judge_result(self._adapter.normalize_judge_result(trace, result)) or result

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return self._adapter.reconcile_judge_result(trace, result)
