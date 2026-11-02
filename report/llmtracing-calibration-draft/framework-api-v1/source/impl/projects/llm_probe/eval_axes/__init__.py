"""llm_probe 场景扩展评估轴（试验体系）。

设计文档：spec/adapter/axe-v4.md。
- 轴类型（AxisType）：开发者在 adapters/ 下写一次，定义枚举、依赖、筛选、取数、流程。
- 场景轴（ScenarioAxis）：capability 预设条目的 axes[] 里的一个框：type / enabled / description。
- 运行器（runner）：对一个 RunTrace 按依赖发动启用的轴，每轴独立落一条 AxisResult。

两个入口：
- ``run_for_trace(spec, trace)``：判后 pass 的项目钩子，由 core（impl/core/eval_axes.py）按项目名声明式装载，
  批量 / 全链路走到 ``_run_payload`` 时调用。预设没有启用的框 → 返回 None，生产零变化。
- ``build_report(spec, trace)``：/api/eval_axes/run 用，同一份报告形状。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from impl.core.capability_store import load_capability_map


def _capability_ref(trace: Any) -> str:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) and trace.normalized_request else (trace.input or {})
    return str((request or {}).get("capability_ref") or "").strip()


def build_report(spec: Any, trace: Any, *, run_id: str = "") -> dict[str, Any]:
    """对一个 trace 跑该预设的全部框。预设不存在或配置无效直接抛（调用方决定怎么呈现）。"""
    from .runner import new_run_id, run_axes
    from .validate import load_scenario_axes

    scenario_id = _capability_ref(trace)
    axes, report = load_scenario_axes(spec.project_id, scenario_id)
    from impl.projects.llm_probe.capability import capability_business_trace
    business_trace = capability_business_trace(scenario_id)
    if business_trace:
        from .types import ScenarioAxis
        from .adapters.process_common import PROCESS_SPECS
        configured = {a.type_id: a for a in axes}
        axes = [ScenarioAxis("trace_analysis", True, "完整整理过程案卷")]
        axes += [ScenarioAxis(key, True, configured[key].description if key in configured else value.question)
                 for key, value in PROCESS_SPECS.items()]
    run_id = str(run_id or "").strip() or new_run_id()
    from .adapters.transcript_axes import transcript_snapshot

    if business_trace and transcript_snapshot(
        trace, (trace.project_fields or {}).get("business_trace")
    ):
        from impl.projects.llm_probe.process_loop.llmtracing_report import build_loop_results

        results = build_loop_results(spec, trace, axes, scenario_id=scenario_id, run_id=run_id)
    else:
        results = [item.as_dict() for item in run_axes(
            spec, trace, axes, scenario_id=scenario_id, run_id=run_id,
        )]
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "trace_id": str(trace.trace_id or ""),
        "case_id": str(trace.case_id or ""),
        "axes": [axis.as_dict() for axis in axes],
        "results": results,
        "warnings": list(report.warnings),
    }


def run_for_trace(spec: Any, trace: Any) -> Optional[dict[str, Any]]:
    """判后 pass：框是开关。预设里没有启用的框就什么都不做（None），有就跑并返回报告。"""
    from .validate import parse_axes

    pending = getattr(trace, "_pending_process_report", None)
    if pending is not None:
        delattr(trace, "_pending_process_report")
        return pending
    from impl.projects.llm_probe.capability import capability_business_trace
    if capability_business_trace(_capability_ref(trace)):
        return None  # Trace evaluation belongs before main Judge, never a second post-pass.

    scenario_id = _capability_ref(trace)
    if not scenario_id:
        return None
    entry = load_capability_map(spec.project_id).get(scenario_id)
    if not isinstance(entry, Mapping):
        # 预设不存在：旧链路在 judge 阶段已经报过，这里不重复制造第二个错误。
        return None
    if not any(axis.enabled for axis in parse_axes(entry.get("axes"), owner=f"{scenario_id}.axes")):
        return None
    return build_report(spec, trace)


__all__ = ["build_report", "run_for_trace"]
