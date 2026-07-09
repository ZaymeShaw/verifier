from __future__ import annotations

import logging
from typing import Optional

from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, normalize_judge_result

from .judge import judge_trace as core_judge_trace

logger = logging.getLogger(__name__)


def run_project_judge_protocol(
    spec: ProjectSpec,
    adapter,
    trace: RunTrace,
    expected_intent: Optional[str] = None,
    project_judge_context: dict | None = None,
) -> JudgeResult:
    pre_judge_result = adapter.pre_judge_result(trace, expected_intent=expected_intent)
    if pre_judge_result is not None:
        normalized_pre = normalize_judge_result(adapter.normalize_judge_result(trace, pre_judge_result)) or pre_judge_result
        return adapter.reconcile_judge_result(trace, normalized_pre)

    try:
        result = core_judge_trace(
            spec,
            trace,
            expected_intent=expected_intent,
            project_judge_context=project_judge_context or {},
        )
    except ValueError as exc:
        logger.error(f"[{spec.project_id}.judge] judge LLM 产出不合规，阻断: {exc}")
        result = JudgeResult(
            trace_id=trace.trace_id,
            project_id=spec.project_id,
            overall_fulfillment={"status": "not_evaluable"},
            reasoning_summary=str(exc)[:500],
            evidence=["llm_output_validation_failed"],
        )
    normalized = normalize_judge_result(adapter.normalize_judge_result(trace, result)) or result
    return adapter.reconcile_judge_result(trace, normalized)
