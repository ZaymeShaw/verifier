"""六轴过程评测的 ToolLoop 版（spec/adapter/tool-loop-plan-20260922.md §5/§6），独立于 eval_axes 的 runner。

Evaluation（父 loop，实例 B）把 Analysis（子 loop，实例 A，案卷整理）当一个 tool；两者只读复用 eval_axes 与
business_trace 的判定材料。入口 run_case：trace → dossier → 一个 case 的报告。
"""
from __future__ import annotations

from typing import Any

from .analysis import Analysis
from .evaluation import Evaluation, criteria_for

__all__ = ["Analysis", "Evaluation", "run_case"]


def run_case(spec: Any, trace: Any, *, client: Any = None) -> dict[str, Any]:
    """对一个 trace 跑整理 + 六轴。没有过程记录直接 failed（不对着空案卷判）；loop 失败同样 failed、无部分结果。"""
    import json

    from impl.projects.llm_probe.business_trace.dossier import build_dossier
    from impl.projects.llm_probe.eval_axes import _capability_ref

    fields = trace.project_fields or {}
    dossier = build_dossier(trace, fields.get("business_trace"))
    if not dossier["records"]:
        return {"status": "failed", "reason": "业务 Trace 缺失或采集失败，没有可整理的过程记录："
                                              + json.dumps(dossier["coverage"], ensure_ascii=False)[:300]}
    criteria, entry = criteria_for(spec.project_id, _capability_ref(trace))
    if client is None:
        from impl.core.llm_client import project_llm_client
        from impl.projects.llm_probe.eval_axes.llm import ENDPOINT_WAIT_SECONDS

        client = project_llm_client(spec, role="judge")
        # 离线评测宁可等端点恢复（与 AxisLlm 同口径）。
        client.endpoint_wait_seconds = ENDPOINT_WAIT_SECONDS
    return Evaluation(dossier, client, trace_id=trace.trace_id, criteria=criteria, entry=entry).run()
