"""llm_probe_loop 的评测轴：一个 case 一个主 loop（spec/alg/axis_loop.md）。

入口与 llm_probe 的 eval_axes 同名同形（core/eval_axes.py 按项目名装载 run_for_trace；service、judge 调 build_report）：
- ``build_report(spec, trace)``：跑场景启用的全部轴，报告形状同 llm_probe（results[] + main_verdict），另带 loop 记录；
- ``run_for_trace(spec, trace)``：判后 pass；主判阶段已跑过就直接取回。
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any, Optional

from impl.core.axis_loop.definitions import AxisDef
from impl.core.axis_loop.loop import AxisLoop, LoopReport, Settings
from impl.core.axis_loop.materials import MaterialTable
from impl.core.capability_store import load_capability_map
from impl.core.config import get_runtime_config
from impl.core.tool_loop import LoopContext

from . import business_failure
from .common import FAILURE_AXIS, STATUS_FAILED, STATUS_NOT_APPLICABLE, STATUS_SUCCEEDED
from .llm import axis_llm
from .materials import Case, registry as material_registry
from .registry import PROJECT, definitions
from .sources import ProbeSources
from .validate import load_scenario_axes, parse_axes

MAIN_AXIS = "fulfillment"
MAIN_VERDICT = "main_verdict"


def settings() -> Settings:
    """全局预算与上下文上限，取自运行配置 eval_axes.loop_*（spec/alg/axis_loop.md §9、§10）。"""
    c = get_runtime_config().eval_axes
    return Settings(llm_calls=c.loop_llm_calls, tool_calls=c.loop_tool_calls, seconds=c.loop_seconds,
                    context_limit_tokens=c.loop_context_limit_tokens, archive_ratio=c.loop_archive_ratio,
                    material_inline_chars=c.loop_material_inline_chars)


def new_run_id() -> str:
    return f"axes-{uuid.uuid4().hex[:12]}"


def _capability_ref(trace: Any) -> str:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) and trace.normalized_request else (trace.input or {})
    return str((request or {}).get("capability_ref") or "").strip()


def _result(axis: AxisDef, status: str, output: Optional[Mapping[str, Any]], *, error: str = "") -> dict[str, Any]:
    output = dict(output or {})
    text = str(output.get("reason") or output.get("verdict") or error or "")
    return {"type_id": axis.id, "axis_id": axis.id, "title": axis.title, "display": axis.display, "status": status, "verdict": output.get("verdict"),
            "output": output, "summary": {"text": text, "items": []}, "error": error, "usage": {}}


def _report_main(results: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    main = next((r for r in results if r["type_id"] == MAIN_VERDICT and r["status"] == STATUS_SUCCEEDED), None)
    if not main:
        return None
    out = main["output"]
    return {"verdict": out["verdict"], "basis": out["reason"], "composition": out["composition"]}


def _loop_results(report: LoopReport, enabled: list[str], axes: Mapping[str, AxisDef]) -> list[dict[str, Any]]:
    results = []
    for key in enabled:
        state = report.states.get(key)
        if report.status != "complete":
            # 不出部分结论：没跑成时各轴都不带输出，过程只留在 loop 记录里（spec/alg/axis_loop.md §5.5）。
            results.append(_result(axes[key], STATUS_FAILED, None, error=f"{FAILURE_AXIS} axis loop 没跑成：{report.reason}"))
        elif state == "absent":
            results.append(_result(axes[key], STATUS_NOT_APPLICABLE, None, error="触发条件未满足"))
        else:
            results.append(_result(axes[key], STATUS_SUCCEEDED, report.results.get(key)))
    return results


def build_report(spec: Any, trace: Any, *, run_id: str = "", scenario_id: str = "") -> dict[str, Any]:
    """scenario_id 缺省取 trace 请求里的 capability_ref；评测集重放时按样本登记的场景跑（同 llm_probe run_axes）。"""
    scenario_id = scenario_id or _capability_ref(trace)
    axes = load_scenario_axes(scenario_id)
    if not axes.enabled:
        raise ValueError(f"场景预设 {scenario_id!r} 没有启用的评测轴")
    entry = load_capability_map(PROJECT)[scenario_id]
    defs = definitions()
    run_id = str(run_id or "").strip() or new_run_id()
    case = Case(trace, scenario_id, entry, axes.notes)
    started = time.monotonic()
    report: dict[str, Any] = {"run_id": run_id, "scenario_id": scenario_id, "trace_id": str(trace.trace_id or ""),
                              "case_id": str(trace.case_id or ""), "route": "loop",
                              "axes": [{"type": k, "enabled": True, "description": axes.notes.get(k, "")} for k in axes.enabled],
                              "warnings": list(axes.warnings)}
    failure = business_failure.matched(trace, entry)
    if failure:
        # 命中场景登记的错误码：运行失败，不出结论、不启动 loop（demand/main_axis.md §3.6）。
        results = [_result(defs.axes[k], STATUS_FAILED, None, error=f"被测系统调用失败：{failure}") for k in axes.enabled]
        report.update(results=results, main_verdict=None, business_failure=failure,
                      loop={"status": "skipped", "reason": failure, "seconds": 0})
        return report
    notes = {k: axes.notes.get(k, "") for k in axes.enabled}
    request = (trace.normalized_request or {}).get("body") or {}
    sources = ProbeSources(notes, request)
    client = axis_llm(spec, role="judge")
    loop = AxisLoop(defs, axes.enabled, MaterialTable(material_registry(), case), sources, client, settings(),
                    axis_sources=sources.axis_instances())
    turns = len(getattr(trace, "turn_records", None) or []) or 1
    # 不给用例名：用例名常带预期（如 neg-unknown-policy），会把答案透给评测
    header = f"场景 {scenario_id}，共 {turns} 轮。下面是第一批任务。"
    outcome = loop.run(header, LoopContext(trace_id=run_id, stage="axis_loop"))
    results = _loop_results(outcome, axes.enabled, defs.axes)
    report.update(results=results, main_verdict=_report_main(results), loop={
        "status": outcome.status, "reason": outcome.reason, "llm_calls": outcome.llm_calls, "tool_calls": outcome.tool_calls,
        "seconds": round(time.monotonic() - started, 1), "archived": outcome.archived, "states": dict(outcome.states),
        "events": [e.__dict__ for e in outcome.events], "messages": outcome.messages, "usage": client.usage()},
        loops=outcome.loops)
    return report


def main_axis_enabled(spec: Any, trace: Any) -> bool:
    """场景启用了兑现框 → 主结论由 axis loop 出（同 llm_probe 无 trace 预设的主轴切换）。"""
    scenario_id = _capability_ref(trace)
    entry = load_capability_map(spec.project_id).get(scenario_id) if scenario_id else None
    if not isinstance(entry, Mapping):
        return False
    return any(b["enabled"] and b["type"] == MAIN_AXIS for b in parse_axes(entry.get("axes"), owner=f"{scenario_id}.axes"))


def main_axis_upstream() -> set[str]:
    """兑现的依赖链（含软依赖）：启用了的上游没跑成，主结论就不成立。"""
    defs = definitions()
    seen: set[str] = set()
    pending = [MAIN_AXIS]
    while pending:
        for dep in defs.axes[pending.pop()].depends:
            if dep.axis not in seen:
                seen.add(dep.axis)
                pending.append(dep.axis)
    return seen


def run_for_trace(spec: Any, trace: Any) -> Optional[dict[str, Any]]:
    """判后 pass：主判阶段已跑过就取回；预设没有启用的框就什么都不做。"""
    pending = getattr(trace, "_pending_process_report", None)
    if pending is not None:
        delattr(trace, "_pending_process_report")
        return pending
    scenario_id = _capability_ref(trace)
    entry = load_capability_map(spec.project_id).get(scenario_id) if scenario_id else None
    if not isinstance(entry, Mapping) or not any(b["enabled"] for b in parse_axes(entry.get("axes"), owner=f"{scenario_id}.axes")):
        return None
    return build_report(spec, trace)


__all__ = ["MAIN_AXIS", "build_report", "main_axis_enabled", "main_axis_upstream", "run_for_trace"]
