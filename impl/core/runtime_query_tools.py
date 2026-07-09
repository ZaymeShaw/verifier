"""通用分歧分析工具：编排 trace、expected/actual 与项目 runtime checks。

核心设计理念（来自 Issue #3 / Issue #6）：
- 共享工具只做通用编排，不导入项目代码、不写项目名分支。
- 项目特有的“直接引用系统原函数/配置”由 adapter.get_runtime_checks 提供。
- attribute agent 获取结构化答案后，优先基于 system_check/root_cause 归因，
  不再为了已闭合根因去读取 prompt 猜测。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .schema import ExecutionTraceEvent

__all__ = ["analyze_divergence", "extract_runtime_values"]


def _trace_step_data(step: Any) -> Dict[str, Any]:
    if isinstance(step, ExecutionTraceEvent):
        data = {"stage": step.stage, "status": step.status, "evidence": step.evidence, "error": step.error}
        data.update(step.outputs or {})
        data.update(step.metadata or {})
        return data
    return step if isinstance(step, dict) else {}


def extract_runtime_values(trace: list, actual: Any = None) -> dict:
    """从 trace steps 与 actual 输出中提取运行时实际值。"""
    values: dict[str, Any] = {}
    for step in trace or []:
        step = _trace_step_data(step)
        if not step:
            continue
        output = step.get("output") or step.get("evidence") or step.get("result") or step.get("actual")
        if isinstance(output, dict):
            _merge_first(values, output)
            data = output.get("data")
            if isinstance(data, dict):
                _merge_first(values, data)
    if isinstance(actual, dict):
        _merge_first(values, actual)
    return values


def _merge_first(target: dict, source: dict) -> None:
    for key, value in source.items():
        if key not in target and value is not None:
            target[key] = value


def _find_first_failed(trace: list) -> Optional[dict]:
    """找到 trace 中第一个失败/可疑/分歧节点。"""
    for step in trace or []:
        step = _trace_step_data(step)
        if not step:
            continue
        status = str(step.get("status", "")).lower()
        if status in ("failed", "diverged", "error", "rejected", "suspicious"):
            return step
        evidence = str(step.get("evidence", step.get("reason", "")))
        if any(kw in evidence for kw in ["失败", "错误", "error", "不符合", "缺失", "differs"]):
            return step
    return None


def _compare_values(expected: Any, actual: Any) -> dict:
    """比较 expected vs actual，找出不一致字段。"""
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        if expected != actual:
            return {"$value": {"expected": expected, "actual": actual}}
        return {}
    gaps = {}
    all_keys = set(expected.keys()) | set(actual.keys())
    for key in all_keys:
        exp_val = expected.get(key)
        act_val = actual.get(key)
        if exp_val != act_val:
            gaps[key] = {"expected": exp_val, "actual": act_val}
    return gaps


def _normalize_runtime_checks(runtime_checks: Any) -> dict:
    if isinstance(runtime_checks, dict):
        return runtime_checks
    if isinstance(runtime_checks, list):
        return {"checks": runtime_checks}
    if runtime_checks:
        return {"value": runtime_checks}
    return {}


def _evidence_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _root_cause_from_system_check(system_check: dict) -> Optional[dict]:
    """从标准化 runtime check 输出中提取根因，不理解项目语义。"""
    if not system_check:
        return None

    direct = system_check.get("root_cause")
    if isinstance(direct, dict):
        return {
            "category": direct.get("category") or system_check.get("root_cause_category") or "implementation_bug",
            "summary": direct.get("summary") or direct.get("reason") or direct.get("root_cause") or str(direct),
            "evidence": _evidence_list(direct.get("evidence") or system_check.get("evidence")),
            "confidence": direct.get("confidence") or system_check.get("confidence") or "high",
            "fix_suggestion": direct.get("fix_suggestion") or system_check.get("fix_suggestion") or "",
        }
    if isinstance(direct, str) and direct.strip():
        return {
            "category": system_check.get("root_cause_category") or "implementation_bug",
            "summary": direct,
            "evidence": _evidence_list(system_check.get("evidence")),
            "confidence": system_check.get("confidence") or "high",
            "fix_suggestion": system_check.get("fix_suggestion") or "",
        }

    checks = system_check.get("checks") if isinstance(system_check.get("checks"), list) else []
    for item in checks:
        if not isinstance(item, dict):
            continue
        cause = _root_cause_from_system_check(item)
        if cause:
            return cause

    if str(system_check.get("status") or "").lower() == "failed":
        evidence = _evidence_list(system_check.get("evidence"))
        summary = system_check.get("summary") or system_check.get("reason") or "; ".join(str(x) for x in evidence) or "runtime check failed"
        return {
            "category": system_check.get("root_cause_category") or "implementation_bug",
            "summary": str(summary),
            "evidence": evidence,
            "confidence": system_check.get("confidence") or "high",
            "fix_suggestion": system_check.get("fix_suggestion") or "",
        }
    return None


def _infer_generic_root_cause(gaps: dict, runtime_values: dict, failed_step: Optional[dict]) -> Optional[dict]:
    if gaps:
        evidence = [
            f"{key}: expected={value.get('expected')} actual={value.get('actual')}"
            for key, value in gaps.items()
            if isinstance(value, dict)
        ]
        return {
            "category": "implementation_bug",
            "summary": "当前运行输出与期望存在字段级差异，需结合项目 runtime check 或源码证据确认根因。",
            "evidence": evidence,
            "confidence": "medium" if failed_step else "low",
            "fix_suggestion": "检查最早分歧节点对应的实现、配置或映射规则。",
        }
    if failed_step:
        stage = failed_step.get("stage") or failed_step.get("name") or failed_step.get("node") or "unknown"
        return {
            "category": "implementation_bug",
            "summary": f"调用链路中 {stage} 阶段出现失败或可疑状态。",
            "evidence": _evidence_list(failed_step.get("evidence") or failed_step.get("reason")),
            "confidence": "medium",
            "fix_suggestion": f"检查 {stage} 阶段的项目实现或运行时配置。",
        }
    return None


def analyze_divergence(
    trace: list,
    expected: Any,
    actual: Any,
    project_name: Optional[str] = None,
    runtime_checks: Any = None,
) -> Dict[str, Any]:
    """通用分歧分析：核心层编排，不包含项目特定逻辑。"""
    runtime_values = extract_runtime_values(trace, actual)
    first_failed = _find_first_failed(trace)
    gaps = _compare_values(expected or {}, actual or {})
    system_check = _normalize_runtime_checks(runtime_checks)

    root_cause = _root_cause_from_system_check(system_check) or _infer_generic_root_cause(gaps, runtime_values, first_failed)
    root_cause_category = (root_cause or {}).get("category") or "unknown"
    root_cause_hypothesis = (root_cause or {}).get("summary") or ""
    fix_suggestion = (root_cause or {}).get("fix_suggestion") or ""

    result = {
        "divergence_point": {
            "stage": first_failed.get("stage", first_failed.get("name", first_failed.get("node", "unknown"))) if first_failed else "unknown",
            "status": first_failed.get("status", "unknown") if first_failed else "unknown",
            "evidence": first_failed.get("evidence") if first_failed else None,
            "runtime_values_at_divergence": runtime_values,
        },
        "gaps": gaps,
        "system_check": system_check,
        "root_cause": root_cause,
        "root_cause_hypothesis": root_cause_hypothesis,
        "fix_suggestion": fix_suggestion,
        "root_cause_category": root_cause_category,
        "root_cause_reasoning": root_cause_hypothesis,
        "analysis_method": "trace_runtime_analysis_with_project_checks" if system_check else "trace_runtime_analysis",
        "evidence_source": "execution_trace + adapter_runtime_checks" if system_check else "execution_trace runtime data",
        "project_name": project_name,
        "note": "共享工具仅编排通用 trace/gap/runtime_check；项目特有检查由 adapter 提供。",
    }
    return result
