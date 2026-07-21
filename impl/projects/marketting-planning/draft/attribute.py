from __future__ import annotations

import importlib.util
from pathlib import Path

from impl.core.schema import JudgeResult, RunTrace


_PRODUCTION_PATH = Path(__file__).resolve().parents[1] / "attribute.py"
_SPEC = importlib.util.spec_from_file_location("marketing_planning_production_attribute_for_draft", _PRODUCTION_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load production Attribute: {_PRODUCTION_PATH}")
_PRODUCTION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PRODUCTION)
_ProductionAttribute = _PRODUCTION.MarketingPlanningAttribute


class MarketingPlanningDraftAttribute(_ProductionAttribute):
    """Candidate that adds the reusable business-flow investigation assets."""

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        from impl.core.project_loader import load_project_role_tools

        context = dict(super().build_context(trace, judge_result) or {})
        context.update({
            "tools": list(load_project_role_tools(self.spec, "attribute") or []),
            "tool_call_limit": 7,
            "system_prompt_override": """你是 marketting-planning 项目的 Draft Attribute 主执行者。
先 Search 一次 `marketing planning business flow`，并只 Load 同名文字 ContextUnit。Mermaid 和 overview 只作目录辅助，不要重复加载。以 Operational index 对齐当前公共请求、raw SSE、adapter 输出和 Judge gap，然后只沿一个能被当前证据支持的分支深入。
先比较 raw SSE 与 adapter；只有不一致才归因 adapter。目标值或路径不一致时，使用当前 query 调用 field_extraction_replay；只有需要区分解析结果与 session/工作流传递时，才调用 workflow_handoff_replay。handoff receipt 的 observed_calls 是本次重放实际经过的 resolver、extractor、clarification 调用记录：当它显示确定性 extractor 产出、rule result、clarification result、PlanningStartedEvent 与公共 SSE 对齐，已足以排除 adapter、LLM fallback 和后置 planning 竞争解释；不要再读取 resolver 或 extractor 源码，也不要遍历规划函数。只有 observed_calls 缺失、出现 LLM 分支或与公共 trace 不一致时才补读最小源码。handoff 正确但卡片错误时，才沿实际 path 查 planning_function 和 result_assembly。
Judge gap、静态 probe、源码存在和 Mermaid 节点都只是调查入口，不能单独证明根因。工具不计算期望答案；期望来自当前 reference/Judge，实际行为来自当前公共 trace 和业务重放。若部署版本、query、contexts 或随机分支不能与 replay 对齐，输出 unresolved_reason，不给 hypothesis。
只调查 not_fulfilled expectation，按同一真实缺陷合并 findings。最终只输出 findings、unresolved_reason；finding 证据必须引用 Finalization 重载的 ContextUnit。""",
        })
        extras = dict(context.get("user_prompt_extras") or {})
        strategy = dict(extras.get("project_attribute_strategy") or {})
        strategy.update({
            "investigation_entry": "marketing planning business flow ContextUnit / Operational index",
            "branch_policy": "raw SSE vs adapter; then field replay; workflow handoff only when propagation is disputed; path/assembly only when handoff is correct",
            "anti_overfit_policy": "No expected-value calculator, historical query, static source presence or generic probe may prove the current cause.",
        })
        extras["project_attribute_strategy"] = strategy
        context["user_prompt_extras"] = extras
        return context
