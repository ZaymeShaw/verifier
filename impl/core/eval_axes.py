"""扩展评估轴的判后 pass（spec/adapter/axe-v4.md）。

与轴2的 ``capability_provider`` 同一装载方式：core 只按项目名找声明式符号
``impl.projects.<project_id>.eval_axes.run_for_trace``，不 import 任何项目代码。
项目没有这个模块 / 符号 → 什么都不发生。

隔离合同：扩展轴的任何失败只记在 ``run["eval_axes"]["error"]`` 里，
不碰 run_status、JudgeResult 或 capability_carrier；一个试验轴挂了不能把 case 标成失败。
例外（项目侧决定，core 不感知）：llm_probe 无 trace 且启用主轴框的预设，主结论就是扩展轴主轴的结论，
主轴及其依赖失败即主判失败；那时报告已在主判阶段跑过，这里只是取回（spec/adapter/main-axis-switch-plan-20261018.md）。
"""
from __future__ import annotations

import importlib
import importlib.util
from typing import Any, Optional

HOOK_MODULE = "impl.projects.{project_id}.eval_axes"
HOOK_SYMBOL = "run_for_trace"


def eval_axes_report(spec: Any, trace: Any, judge: Any) -> Optional[dict[str, Any]]:
    if judge is None or trace is None:
        return None
    project_id = str(getattr(spec, "project_id", "") or "").strip()
    if not project_id:
        return None
    module_name = HOOK_MODULE.format(project_id=project_id)
    try:
        found = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        found = None
    if found is None:
        return None
    try:
        hook = getattr(importlib.import_module(module_name), HOOK_SYMBOL, None)
        if not callable(hook):
            return None
        return hook(spec, trace)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
