"""Independent, evidence-skeptical review used inside the Attribute protocol."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List

from .attribute import _compact_judge, _compact_trace, _compact_value
from .llm_client import project_llm_client
from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace, to_dict
from .structured_output import StructuredOutputSpec


@dataclass
class AttributeReviewIssue:
    target: str
    problem: str


@dataclass
class AttributeReviewOutput:
    passed: bool
    issues: List[AttributeReviewIssue] = field(default_factory=list)


_ATTRIBUTE_REVIEW_OUTPUT_SPEC = StructuredOutputSpec.from_dataclass(
    AttributeReviewOutput,
    description="Attribute 独立证据审查结果",
)


_REVIEW_SYSTEM_PROMPT = """你是 Attribute 的独立、挑剔证据审查者。你不是主执行者的延续，不接受其自我解释为事实。

你的唯一职责是判断当前归因的关键结论是否由真实、可核查、能说明该结论的证据支持。主 Attribute 引用 EvidenceRef 对应的 ContextUnit 完整信息已经提供给你；你不调用工具、不自行探索。

重点拒绝：
- 引用不存在、无法加载或只是模型总结；
- 证据只证明现象，却宣称业务内部位置或机制；
- 未区分会导致不同修复的强竞争解释；
- 存在反证、重放/模拟矛盾，或当前系统责任边界不支持落点；
- 把 Judge 推理、verifier trace、stage 名称、Search 候选摘要或 Tool 被调用这件事本身当成根因证据；
- 只引用计算、probe、replay、对照等派生 Tool 结果，却没有引用能够认证该 Tool 输入来自当前 case 的原始业务材料；Tool 参数和由模型转写的 source_quote 不是原始证据。若 Tool 的 boundary_limits 明示还需另行加载上游材料，而 finding 未引用该材料，必须拒绝；
- 结论超出 expected/actual 和实际验证所能支持的范围。
- finding 只把偏差收缩到两个接口之间，却仍有多个会导向不同修复位置的业务机制未区分，同时 unresolved_reason 为空、结果声称完整；边界定位可以保留，但必须要求主 Attribute 明确未解决路径，不能把“知道在哪段”冒充“知道该改哪里”。
- findings 已声称完整覆盖 gap，却把“无未解决问题”“所有证据一致”等完成声明写入 unresolved_reason；该字段非空时必须是真实、具体、会限制当前结论范围的遗留问题。

尤其注意“缺少规则/示例/配置，因此导致本次失败”这类常见因果跃迁：静态材料能证明某项内容不存在，当前 trace 能证明失败发生，但两者相加仍不能证明前者就是原因。除非已有对照重放、局部修改、稳定复现或其他能区分竞争解释的验证，否则必须指出 conclusion 只能收缩到已证明的故障发生层级，不能把建议补充的内容写成已实锤根因。

你还会看到当前权限范围内所有可用 ContextUnit、Tool 和源码资源的 name/description 目录。目录本身不是证据，也没有向你开放正文或执行权限；它只用于帮助你要求主 Attribute 从现有但尚未取用的材料中补证。现有目录仍不足时，可以指出业务上还需要构建哪类额外 evidence、probe、重放或对照验证，由主 Attribute 下一轮完成。

只输出 passed 和 issues。每个 issue 只包含 target 和 problem：target 使用 finding_id，无法归属单个 finding 时使用 attribute_result；problem 指出现有 evidence 为什么不能证明 conclusion、哪项引用无效，或主 Attribute 还需确认什么材料/验证。不要增加 evidence、next_action、修复方案、调查计划或 strength ceiling。纯措辞、格式偏好或“还可以更好”不是 issue。

如果没有找到有证据的实质问题，输出 passed=true, issues=[]。
"""


def _review_failure_issue(problem: str) -> dict[str, Any]:
    return {
        "target": "attribute_result",
        "problem": problem,
    }


def review_attribute_result(
    *,
    spec: ProjectSpec,
    trace: RunTrace,
    judge: JudgeResult,
    result: AttributeResult,
    project_context: dict[str, Any],
    round_number: int,
) -> dict[str, Any]:
    """Run one isolated review. The returned dict is protocol-internal only."""
    if not result.findings:
        return {"passed": True, "issues": []}

    bundle_builder = project_context.get("_attribute_review_bundle")
    if not callable(bundle_builder):
        return {
            "passed": False,
            "issues": [],
            "infrastructure_error": "Reviewer 缺少确定性 EvidenceRef 材料装载能力",
        }
    try:
        review_bundle = bundle_builder(result)
    except Exception as exc:
        return {
            "passed": False,
            "issues": [],
            "infrastructure_error": f"Reviewer 无法装载被引用 ContextUnit：{type(exc).__name__}: {exc}",
        }
    visible_context = {
        key: value
        for key, value in project_context.items()
        if key not in {"tools", "system_prompt_override"} and not str(key).startswith("_attribute_")
    }
    user = json.dumps(
        to_dict({
            "run_trace": _compact_trace(trace),
            "judge_result": _compact_judge(judge),
            "attribute_result_under_review": _compact_value(to_dict(result), 12_000),
            # The bundle is already policy-authorized: cited units contain the
            # exact evidence under review, while the remaining lists are
            # metadata-only catalogs.  Generic compaction silently kept only
            # the first 20 list entries, hiding possible counter-evidence and
            # supplementation options from the reviewer.
            "evidence_review_bundle": review_bundle,
            "project_attribute_context": _compact_value(visible_context, 4_000),
        }),
        ensure_ascii=False,
    )
    prompt_char_budget = int(project_context.get("review_prompt_char_budget") or 180_000)
    prompt_chars = len(_REVIEW_SYSTEM_PROMPT) + len(user)
    if prompt_chars > prompt_char_budget:
        return {
            "passed": False,
            "issues": [],
            "infrastructure_error": (
                f"Reviewer prompt size {prompt_chars} exceeds policy budget {prompt_char_budget}; "
                "目录和证据未被静默截断"
            ),
        }
    client = project_llm_client(
        spec,
        role="attribute-review",
        knowledge=None,
        tools=[],
    )
    try:
        data = client.complete_json(
            _REVIEW_SYSTEM_PROMPT,
            user,
            trace_id=f"{trace.trace_id}:attribute-review:{round_number}",
            output_spec=_ATTRIBUTE_REVIEW_OUTPUT_SPEC,
        )
    except Exception as exc:
        return {
            "passed": False,
            "issues": [],
            "infrastructure_error": f"独立 Reviewer 未完成结构化审查：{type(exc).__name__}: {exc}",
        }
    if data.get("_tool_call_log"):
        project_context.setdefault("_attribute_review_audit", []).extend(data["_tool_call_log"])
    if data.get("error"):
        return {
            "passed": False,
            "issues": [],
            "infrastructure_error": f"独立 Reviewer 调用失败：{data.get('raw_text') or data['error']}",
        }

    issues = []
    for item in list(data.get("issues") or []):
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "").strip()
        problem = str(item.get("problem") or "").strip()
        if target and problem:
            issues.append({
                "target": target,
                "problem": problem,
            })
    passed = bool(data.get("passed"))
    if passed and issues:
        passed = False
    if not passed and not issues:
        issues = [_review_failure_issue("Reviewer 返回 passed=false 但没有提供具体问题")]
    return {"passed": passed, "issues": issues}
