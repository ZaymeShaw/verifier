from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import run_project_attribute_protocol
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    """Draft template: replace probe construction with project-specific evidence checks."""
    adapter_context = {}
    build_attribute_context = getattr(adapter, "build_attribute_context", None)
    if callable(build_attribute_context):
        adapter_context = build_attribute_context(trace, judge_result) or {}
    return {
        "tool_call_limit": 4,
        "system_prompt_override": """你是 <project_id> 项目的 attribute agent。
只基于当前 RunTrace、JudgeResult、adapter/project probes/tools 和项目文档做归因。
优先使用项目已有 adapter comparison/runtime checks；新增 draft probe 只能补充证据上下文，不能覆盖项目 canonical 标准。
如果 judge 已 fulfilled，不要强行制造失败根因；证据不足时 evidence_strength 必须为 none 或 weak，并说明缺失证据。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["<stage_1>", "<stage_2>", "<stage_3>"],
                "root_cause_policy": "Use current adapter/project probes/tools before LLM inference; do not reuse historical cases or invent a second semantic standard.",
                "evidence_contract": ["run_trace", "judge_result", "adapter_context", "project_probe", "runtime_checks"],
            },
            "adapter_attribute_context": adapter_context,
            "project_probe": _project_probe(trace, judge_result),
        },
    }


def _project_probe(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    actual = actual if isinstance(actual, dict) else {}
    return {
        "reference_present": bool(reference),
        "actual_present": bool(actual),
        "judge_status": (judge_result.overall_fulfillment or {}).get("status"),
        "evidence_gap": [
            name
            for name, missing in (
                ("reference_contract", not bool(reference)),
                ("actual_output", not bool(actual)),
                ("fulfillment_assessments", not bool(judge_result.fulfillment_assessments or [])),
            )
            if missing
        ],
    }


def attribute_failure(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    return run_project_attribute_protocol(
        spec,
        adapter,
        trace,
        judge_result,
        project_attribute_context=_build_project_attribute_context(spec, adapter, trace, judge_result),
    )
