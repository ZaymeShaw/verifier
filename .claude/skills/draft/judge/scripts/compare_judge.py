"""Judge 角色的 current vs draft 对比脚本（按 spec/draft/draft.md 阶段 5 写）。

spec/draft/draft.md 阶段 5 的对比逻辑骨架：

    def compare_<role>_outputs(spec, adapter, cases, current_impl, draft_impl):
        rows = []
        for case in cases:
            current_out = _result_summary(_run_<role>(current_impl, spec, adapter, case))
            draft_out = _result_summary(_run_<role>(draft_impl, spec, adapter, case))
            rows.append({...})
        return {"case_count": ..., "rows": ..., "decision_rule": ...}

三处角色特异函数（spec line 103）：
- _run_<role>：怎么从 case 取参喂给模板方法——judge 模板方法是
  judge_trace(self, trace: RunTrace, expected_intent: Optional[str]) -> JudgeResult。
- _result_summary：抽哪些字段——judge 抽 JudgeResult 的
  overall_fulfillment / fulfillment_assessments / business_expectations /
  missing / wrong / extra / evidence / reasoning_summary / summary。
- _case_status：从 case 取什么状态字段——judge case 不自带 judge_result
  （judge 自己产 JudgeResult），从 case.expected_check 取用户给的期望。

draft 机制不预判这三处，本文件是 judge 角色层填的具体实现。
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


def _run_judge(
    impl: Any,
    spec: ProjectSpec,
    adapter: Any,
    case: Dict[str, Any],
) -> JudgeResult:
    """从 case 取参喂给 judge 模板方法。

    当前 judge 模板方法签名（impl/core/judge_protocol.py）：
        judge_trace(self, trace: RunTrace, expected_intent: Optional[str]) -> JudgeResult

    case 必须包含的入参字段由这个签名派生：trace + expected_intent（可选）。
    """
    trace = case.get("trace")
    if not isinstance(trace, RunTrace):
        raise TypeError(f"judge case 缺 trace 或类型错: {type(trace)}")
    expected_intent = case.get("expected_intent")

    return impl.judge_trace(trace, expected_intent=expected_intent)


def _result_summary(result: JudgeResult) -> Dict[str, Any]:
    """抽 JudgeResult 的角色特异字段。

    字段从 impl/core/schema/judge.py 的 JudgeResult 派生：
    overall_fulfillment / fulfillment_assessments / business_expectations /
    missing / wrong / extra / evidence / reasoning_summary / summary。
    """
    if result is None:
        return {}
    if is_dataclass(result):
        data = asdict(result)
    elif isinstance(result, dict):
        data = result
    else:
        return {"raw": str(result)}

    return {
        "overall_fulfillment": data.get("overall_fulfillment") or {},
        "fulfillment_assessments": data.get("fulfillment_assessments") or [],
        "business_expectations": data.get("business_expectations") or [],
        "missing": data.get("missing") or [],
        "wrong": data.get("wrong") or [],
        "extra": data.get("extra") or [],
        "evidence": data.get("evidence") or [],
        "reasoning_summary": data.get("reasoning_summary") or "",
        "summary": data.get("summary") or {},
    }


def _case_status(case: Dict[str, Any]) -> str:
    """从 case 取状态字段——judge case 不自带 judge_result（judge 自己产），
    从 case.expected_check 取用户给的期望状态，没有则 'unknown'。
    """
    expected_check = case.get("expected_check") or {}
    if isinstance(expected_check, dict):
        return expected_check.get("expected_status") or "unknown"
    return "unknown"


def _matches_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _matches_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_matches_expected(candidate, item) for candidate in actual)
            for item in expected
        )
    return actual == expected


def _evaluate_expected(case: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
    expected = case.get("expected_check")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("judge case 缺非空 expected_check")
    normalized = dict(expected)
    expected_status = normalized.pop("expected_status", None)
    if expected_status is not None:
        normalized["overall_fulfillment"] = {"status": expected_status}
    unknown = set(normalized) - set(output)
    if unknown:
        raise ValueError(f"judge expected_check 含未知字段: {sorted(unknown)}")
    return {"matched": _matches_expected(output, normalized), "expected": expected}


def compare_judge_outputs(
    spec: ProjectSpec,
    adapter: Any,
    cases: List[Dict[str, Any]],
    current_impl: Any,
    draft_impl: Any,
) -> Dict[str, Any]:
    """对比 current vs draft judge 在同一批冻结 case 上的输出。

    按 spec/draft/draft.md 阶段 5：
    - 同一批冻结 case，current 和 draft 各跑一遍。
    - 比"证据质量 / 链路定位 / 不过拟合 / 不伪造"，不比刷分。
    - 异常直接冒泡并终止本次对比，不生成可用于 promotion 的报告。
    """
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_key = case.get("case_key") or index
        current_out = _result_summary(_run_judge(current_impl, spec, adapter, case))
        draft_out = _result_summary(_run_judge(draft_impl, spec, adapter, case))
        current_check = _evaluate_expected(case, current_out)
        draft_check = _evaluate_expected(case, draft_out)

        rows.append({
            "case_key": case_key,
            "case_status": _case_status(case),
            "current": current_out,
            "draft": draft_out,
            "current_check": current_check,
            "draft_check": draft_check,
            "comparison": (
                "draft_better" if draft_check["matched"] and not current_check["matched"]
                else "current_better" if current_check["matched"] and not draft_check["matched"]
                else "equivalent"
            ),
        })

    return {
        "case_count": len(rows),
        "rows": rows,
        "decision_rule": (
            "Promote only when at least one case changes from expected_check mismatch to match, "
            "no case regresses from match to mismatch, and role gates independently confirm "
            "no overfit or fabricated judgment."
        ),
    }
