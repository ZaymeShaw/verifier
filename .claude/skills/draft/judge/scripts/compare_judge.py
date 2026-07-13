"""Judge current/draft 同数据运行器。

只负责在同一批 case 上运行 current 和 draft，保留原始 JudgeResult，
异常直接冒泡。是否能证明 objective 改善由 skill 结合 config.review 和真实实验判断。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


def _run_judge(impl: Any, case: Dict[str, Any]) -> JudgeResult:
    trace = case.get("trace")
    if not isinstance(trace, RunTrace):
        raise TypeError(f"judge case 缺 trace 或类型错: {type(trace)}")
    expected_intent: Optional[str] = case.get("expected_intent")
    return impl.judge_trace(trace, expected_intent=expected_intent)


def _as_dict(result: JudgeResult) -> Dict[str, Any]:
    if result is None:
        return {}
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"raw": str(result)}


def compare_judge_outputs(
    spec: ProjectSpec,
    adapter: Any,
    cases: List[Dict[str, Any]],
    current_impl: Any,
    draft_impl: Any,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_key = case.get("case_key") or index
        current_result = _run_judge(current_impl, case)
        draft_result = _run_judge(draft_impl, case)
        rows.append({
            "case_key": case_key,
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
