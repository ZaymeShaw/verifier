"""Attribute 角色的 current vs draft 对比脚本（按 spec/draft/draft.md 阶段 5 写）。

spec/draft/draft.md 阶段 5 的对比逻辑骨架：

    def compare_<role>_outputs(spec, adapter, cases, current_impl, draft_impl):
        rows = []
        for case in cases:
            current_out = _result_summary(_run_<role>(current_impl, spec, adapter, case))
            draft_out = _result_summary(_run_<role>(draft_impl, spec, adapter, case))
            rows.append({...})
        return {"case_count": ..., "rows": ..., "decision_rule": ...}

三处角色特异函数（spec line 103）：
- _run_<role>：怎么从 case 取参喂给模板方法——attribute 模板方法是
  attribute_failure(self, trace, judge_result) -> AttributeResult。
- _result_summary：抽哪些字段——attribute 抽 AttributeResult 的
  expectation_attributions / suspected_locations / root_cause_hypothesis /
  evidence / evidence_strength。
- _case_status：从 case 取什么状态字段——attribute case 携带 judge_result，
  从 judge_result.overall_fulfillment.status 取。

draft 机制不预判这三处，本文件是 attribute 角色层填的具体实现。
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _run_attribute(
    impl: Any,
    spec: ProjectSpec,
    adapter: Any,
    case: Dict[str, Any],
) -> AttributeResult:
    """从 case 取参喂给 attribute 模板方法。

    当前 attribute 模板方法签名（impl/core/attribute_protocol.py）：
        attribute_failure(self, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult

    case 必须包含的入参字段由这个签名派生：trace + judge_result。
    """
    trace = case.get("trace")
    judge_result = case.get("judge_result")
    if not isinstance(trace, RunTrace):
        raise TypeError(f"attribute case 缺 trace 或类型错: {type(trace)}")
    if not isinstance(judge_result, JudgeResult):
        raise TypeError(f"attribute case 缺 judge_result 或类型错: {type(judge_result)}")

    return impl.attribute_failure(trace, judge_result)


def _result_summary(result: AttributeResult) -> Dict[str, Any]:
    """抽 AttributeResult 的角色特异字段。

    字段从 impl/core/schema/attribute.py 的 AttributeResult 派生：
    expectation_attributions / suspected_locations / root_cause_hypothesis /
    evidence / evidence_strength。
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
        "expectation_attributions": data.get("expectation_attributions") or [],
        "suspected_locations": data.get("suspected_locations") or [],
        "root_cause_hypothesis": data.get("root_cause_hypothesis") or "",
        "evidence": data.get("evidence") or [],
        "evidence_strength": data.get("evidence_strength"),
    }


def _case_status(case: Dict[str, Any]) -> str:
    """从 case 取状态字段——attribute case 携带 judge_result，取其 status。"""
    judge_result = case.get("judge_result")
    if isinstance(judge_result, JudgeResult):
        return (judge_result.overall_fulfillment or {}).get("status") or "unknown"
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
        raise ValueError("attribute case 缺非空 expected_check")
    unknown = set(expected) - set(output)
    if unknown:
        raise ValueError(f"attribute expected_check 含未知字段: {sorted(unknown)}")
    return {"matched": _matches_expected(output, expected), "expected": expected}


def compare_attribute_outputs(
    spec: ProjectSpec,
    adapter: Any,
    cases: List[Dict[str, Any]],
    current_impl: Any,
    draft_impl: Any,
) -> Dict[str, Any]:
    """对比 current vs draft attribute 在同一批冻结 case 上的输出。

    按 spec/draft/draft.md 阶段 5：
    - 同一批冻结 case，current 和 draft 各跑一遍。
    - 比"证据质量 / 链路定位 / 不过拟合 / 不伪造"，不比刷分。
    - 异常直接冒泡并终止本次对比，不生成可用于 promotion 的报告。
    """
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_key = case.get("case_key") or index
        current_out = _result_summary(_run_attribute(current_impl, spec, adapter, case))
        draft_out = _result_summary(_run_attribute(draft_impl, spec, adapter, case))
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
            "no overfit or inflated evidence strength."
        ),
    }
