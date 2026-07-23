from __future__ import annotations

import importlib.util
from pathlib import Path

from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


_PRODUCTION_PATH = Path(__file__).resolve().parents[1] / "attribute.py"
_PRODUCTION_SPEC = importlib.util.spec_from_file_location(
    "marketing_intent_production_attribute_for_draft",
    _PRODUCTION_PATH,
)
if _PRODUCTION_SPEC is None or _PRODUCTION_SPEC.loader is None:
    raise ImportError(f"cannot load production Attribute: {_PRODUCTION_PATH}")
_PRODUCTION = importlib.util.module_from_spec(_PRODUCTION_SPEC)
_PRODUCTION_SPEC.loader.exec_module(_PRODUCTION)
_ProductionMarketingIntentAttribute = _PRODUCTION.MarketingIntentAttribute


class MarketingIntentDraftAttribute(_ProductionMarketingIntentAttribute):
    """Evidence-driven candidate that adds the reusable business investigation assets."""

    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        from impl.core.project_loader import load_project_role_tools

        context = dict(super().build_context(trace, judge_result) or {})
        context.update({
            "tools": list(load_project_role_tools(self.spec, "attribute") or []),
            "system_prompt_override": """你是 marketting-planning-intent 项目的 Draft Attribute 主执行者。
只 Search 一次 `marketing intent business flow`，并只 Load 同名的文字 ContextUnit；Mermaid graph 和 overview 只是目录辅助，不要同时加载。使用 Operational index 把当前 RunTrace 的真实 API 输出、adapter 提取结果和 Judge gap 对齐，再沿一个有证据的分支向下验证。Judge 的 not_fulfilled 只是调查入口，不是业务缺陷已经成立的证据。当前 trace 已提供 raw response 与 adapter output，不要为重复读取它们调用 context_store。
先比较 raw response 与 adapter output：二者不一致才定位 adapter。若二者一致，再以同一个 query 和原始 contexts 调用 rule_stage_replay。若 replay 返回 `active_branch=homepage_rule`、具体 `homepage_match`，并且结果与公共输出相同，该结果已经区分了确定性 homepage rule 与 LLM/adapter；不要再调用 resolver_replay，也不要遍历无关源码。只有 replay no-match、non_homepage_rule 或与公共输出不一致时，才调用 resolver_replay 或最小源码读取。rule no-match 只说明进入 LLM fallback，禁止据此宣称规则覆盖不足。
源码、prompt、调查文档只能解释已经由当前 case 观察到的活跃机制，不能单独证明它造成问题。`homepage_match` 的 rule_index、pattern、matched_text 和 match_span 来自当前业务模块实际 `_HOMEPAGE_RULES`；可用于说明本次命中机制，但修复措辞不得扩张到 replay 未验证的其他表达。若 replay 与原调用不一致且没有原调用内部记录，或 expectation 超出单轮 IntentResult 合同，输出 unresolved_reason，不输出猜测性 finding。
只调查 not_fulfilled expectation，按同一真实缺陷合并 findings。最终只输出 findings、unresolved_reason；finding 中的证据必须引用 Finalization 重载的 ContextUnit。全部已证实问题都被 findings 覆盖时 unresolved_reason 必须为空字符串。""",
        })
        extras = dict(context.get("user_prompt_extras") or {})
        strategy = dict(extras.get("project_attribute_strategy") or {})
        strategy.update({
            "investigation_entry": "marketing intent business flow ContextUnit / Operational index",
            "branch_policy": (
                "raw response vs adapter first; then same-query rule replay; resolver replay only when "
                "needed to distinguish rule, LLM fallback, or supplementation"
            ),
            "anti_overfit_policy": (
                "No historical query, expected label, replacement regex, or static source presence may be "
                "used as proof of the current cause."
            ),
        })
        extras["project_attribute_strategy"] = strategy
        context["user_prompt_extras"] = extras
        return context
