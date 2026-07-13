"""Attribute current/draft 同数据运行器。

只负责在同一批 case 上运行 current 和 draft，保留原始 AttributeResult，
异常直接冒泡。是否能证明 objective 改善由 skill 结合 config.review 和真实实验判断。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _run_attribute(impl: Any, case: Dict[str, Any]) -> AttributeResult:
    trace = case.get("trace")
    judge_result = case.get("judge_result")
    if not isinstance(trace, RunTrace):
        raise TypeError(f"attribute case 缺 trace 或类型错: {type(trace)}")
    if not isinstance(judge_result, JudgeResult):
        raise TypeError(f"attribute case 缺 judge_result 或类型错: {type(judge_result)}")
    return impl.attribute_failure(trace, judge_result)


def _as_dict(result: AttributeResult) -> Dict[str, Any]:
    if result is None:
        return {}
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"raw": str(result)}


def compare_attribute_outputs(
    spec: ProjectSpec,
    adapter: Any,
    cases: List[Dict[str, Any]],
    current_impl: Any,
    draft_impl: Any,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_key = case.get("case_key") or index
        judge_result = case.get("judge_result")
        case_status = (
            (judge_result.overall_fulfillment or {}).get("status") or "unknown"
            if isinstance(judge_result, JudgeResult)
            else "unknown"
        )
        current_result = _run_attribute(current_impl, case)
        draft_result = _run_attribute(draft_impl, case)
        rows.append({
            "case_key": case_key,
            "case_status": case_status,
            "current": _as_dict(current_result),
            "draft": _as_dict(draft_result),
        })
    return {
        "case_count": len(rows),
        "rows": rows,
        "note": (
            "Raw current/draft outputs on the same frozen cases. "
            "Whether they prove objective improvement must be decided against config.review "
            "and real experiments, not by this runner."
        ),
    }
