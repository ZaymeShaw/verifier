"""Evidence-driven Attribute executor and private LLM boundary."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from .llm_client import LlmClient, project_llm_client
from .schema import AttributeLLMOutput, AttributeResult, JudgeResult, ProjectSpec, RunTrace, judge_expected_actual_gaps, judge_primary_signal, to_dict, trace_execution_trace, trace_extracted_output, trace_normalized_request
from .structured_output import StructuredOutputSpec

logger = logging.getLogger(__name__)

ATTRIBUTE_TOOL_CALL_LIMIT = 8
_ATTRIBUTE_OUTPUT_SPEC = StructuredOutputSpec.from_dataclass(
    AttributeLLMOutput,
    description="Finalization 后的 Attribute 已验证结论或整体 unresolved 原因",
)


@dataclass
class _AttributeInvestigationOutput:
    investigation_summary: str = ""


_ATTRIBUTE_INVESTIGATION_SPEC = StructuredOutputSpec.from_dataclass(
    _AttributeInvestigationOutput,
    description="Attribute Investigation 阶段的材料收集摘要，不是最终归因",
)


def _compact_value(obj: Any, max_chars: int) -> Any:
    if isinstance(obj, str):
        return obj[:max_chars] + f"...[truncated {len(obj) - max_chars:,} chars]" if len(obj) > max_chars else obj
    if isinstance(obj, dict):
        return {key: _compact_value(value, max_chars) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_compact_value(value, max_chars) for value in obj[:20]]
    return obj


def _compact_trace(trace: RunTrace) -> dict:
    return {
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "case_id": str(trace.case_id or ""),
        "input": _compact_value(trace.input, 1200),
        "normalized_request": _compact_value(trace_normalized_request(trace), 1200),
        "extracted_output": _compact_value(trace_extracted_output(trace), 10000),
        "execution_trace": _compact_value(trace_execution_trace(trace), 2500),
        "status": trace.status,
        "error": _compact_value(trace.error, 1200),
    }


def _compact_judge(judge: JudgeResult) -> dict:
    primary = judge_primary_signal(judge)
    gaps = judge_expected_actual_gaps(judge)
    return {
        "trace_id": judge.trace_id,
        "project_id": judge.project_id,
        "business_expectations": _compact_value(primary.get("business_expectations"), 3000),
        "fulfillment_assessments": _compact_value(primary.get("fulfillment_assessments"), 4000),
        "overall_fulfillment": primary.get("overall_fulfillment"),
        "missing": _compact_value(gaps.get("missing"), 1500),
        "wrong": _compact_value(gaps.get("wrong"), 1500),
        "extra": _compact_value(gaps.get("extra"), 1500),
        "reasoning_summary": _compact_value(getattr(judge, "reasoning_summary", None), 2000),
    }


def failed_expectation_ids(judge: JudgeResult) -> list[str]:
    result = []
    for item in judge.fulfillment_assessments or []:
        expectation_id = getattr(item, "expectation_id", None) or (item.get("expectation_id") if isinstance(item, dict) else "")
        status = getattr(item, "status", None) or (item.get("status") if isinstance(item, dict) else "")
        if expectation_id and status == "not_fulfilled" and expectation_id not in result:
            result.append(str(expectation_id))
    return result


def judge_status(judge: JudgeResult) -> str:
    overall = judge.overall_fulfillment or {}
    return str(overall.get("status") or "not_evaluable") if isinstance(overall, dict) else "not_evaluable"


def _default_system_prompt(tool_call_limit: int) -> str:
    return f"""你是业务问题 Attribute 主执行者，是实施修复前的最后一个诊断环节。

只调查 Judge 中 status=not_fulfilled 的 expectation。按真实缺陷合并：同一缺陷可覆盖多条 expectation；不要逐条找理由。Judge 文本只是调查起点，不是根因证据。

当前调用只负责 Investigation。若 ContextUnit 目录提供业务调查链路、trace map 或 operational index，先 Search 并 Load 该材料，用当前 trace/Judge gap 选择最小决定性验证路径，再调用路径指向的业务 Tool；若没有此类材料，才直接从可用 Tool 选择。Search 的候选摘要不是证据；必须 Load 完整材料。Tool 返回的完整结果会自动注册并记为已调查，无需重复 Load。源码、配置、运行检查、probe、replay或模拟结果只有实际连接当前 gap 与结论时才有用。不要因为一个文件缺陷多就归因到它。

严格区分两种标识：source_file_catalog 中的 key 只能传给 source_list_symbols、source_read_functions 或 source_search_text，绝不是 ContextUnit ID，禁止传给 load_context_units/finalize_attribution。source Tool 返回成功后会产生新的 context_unit_id；只有这个 ID，或 search_context_units 返回的 selection_ref，才可用于 load_context_units，加载成功后才可交给 finalize_attribution。queries 和 unit_ids 参数必须直接传 JSON 数组，不要包成对象或自造字段名；一次 search 最多 4 条 query，一次 load 最多 8 个 ID。

调查工具预算最多 {tool_call_limit} 次。调查完成后只输出 investigation_summary；运行时会独立进入 Finalization。禁止输出 markdown。"""


def _finalization_system_prompt() -> str:
    return """你是业务问题 Attribute 主执行者，现已进入 Finalization 自审阶段。此阶段没有调查工具。

运行时已经重新加载 Investigation 中实际呈现过的全部 ContextUnit。基于这些完整材料自审：每个结论是否真被材料支持、是否能解释当前 gap、是否排除了会导向不同修复的主要竞争解释。若输入包含 investigation_output_error，它只表示上一步摘要违反结构协议，不是业务证据；忽略非法摘要，只审核 finalized_context_units。材料不足时不得给 hypothesis，应输出整体 unresolved_reason。派生验证结果（计算、probe、replay、对照等）不能自行证明其输入来自当前业务事实；若结论依赖这类结果，evidence 必须同时引用承载原始业务事实的 ContextUnit 和承载验证结果的 ContextUnit。Tool 参数或 Tool 结果中由模型转写的 source_quote 不能替代原始材料引用。只证明“偏差发生在接口 A 与接口 B 之间”可以作为有限 finding，但如果该区间仍包含会导向不同修改位置的多个业务机制，必须在 unresolved_reason 中明确保留这些未区分路径，不得把结果标成完整归因。`unresolved_reason` 只能描述仍未归因的 expectation、竞争解释或证据边界；若 findings 已完整覆盖所有 not_fulfilled expectation 且没有真实遗留问题，必须输出空字符串，禁止填写“无”“没有未解决问题”“所有证据一致”等完成声明。

最终只输出 JSON：findings 和 unresolved_reason。每个 finding 只能是已验证的真实缺陷，包含 finding_id、affected_expectation_ids、conclusion、evidence。evidence 每项只填 finalized_context_units 中的 context_unit_id 和 reason；reason 指明材料中什么事实证明结论。不得生成 ref_id/hash/location。禁止输出 markdown。"""


def fulfilled_attribute_result(trace: RunTrace) -> AttributeResult:
    return AttributeResult(trace_id=trace.trace_id, project_id=trace.project_id, case_id=str(trace.case_id or ""))


def _fulfilled_attribute_result(_spec: ProjectSpec, trace: RunTrace, _judge: JudgeResult) -> AttributeResult:
    """Temporary callable compatibility; the returned schema is the new protocol."""
    return fulfilled_attribute_result(trace)


def unresolved_attribute_result(trace: RunTrace, reason: str) -> AttributeResult:
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.case_id or ""),
        unresolved_reason=reason,
    )


def _registration_failure_text(context: dict[str, Any]) -> str:
    failures = list(context.get("evidence_registration_errors") or [])
    if not failures:
        return ""
    details = []
    for item in failures:
        if not isinstance(item, dict):
            continue
        details.append(
            f"{item.get('material') or 'material'} 在 {item.get('stage') or 'registration'} 失败"
            f"（{item.get('error_type') or 'Error'}，尝试 {item.get('attempts') or '1'} 次）：{item.get('reason') or 'unknown error'}"
        )
    return "；".join(details)


def attribute_failure(
    spec: ProjectSpec,
    trace: RunTrace,
    judge: JudgeResult,
    llm: Optional[LlmClient] = None,
    project_attribute_context: Optional[dict] = None,
) -> AttributeResult:
    if judge_status(judge) == "fulfilled":
        return fulfilled_attribute_result(trace)
    failed_ids = failed_expectation_ids(judge)
    if not failed_ids:
        return unresolved_attribute_result(trace, "Judge 未提供可归因的 not_fulfilled expectation。")

    context = project_attribute_context or {}
    tool_call_limit = int(context.get("tool_call_limit") or ATTRIBUTE_TOOL_CALL_LIMIT)
    investigation_system = _default_system_prompt(tool_call_limit)
    if context.get("system_prompt_override"):
        investigation_system += "\n\n项目补充约束：\n" + str(context["system_prompt_override"])
        investigation_system += "\n\n当前是 Investigation 阶段，项目补充约束中的最终输出要求暂不适用；本次只输出 investigation_summary。"
    visible_context = {
        key: value for key, value in context.items()
        if key not in {
            "system_prompt_override", "tools", "tool_call_limit", "targets_override",
            "finalization_prompt_char_budget", "review_prompt_char_budget",
        }
        and not str(key).startswith("_attribute_")
    }
    user_data = {
        "run_trace": _compact_trace(trace),
        "judge_result": _compact_judge(judge),
        "failed_expectation_ids": failed_ids,
        "project_attribute_context": visible_context,
    }
    if context.get("review_issues"):
        user_data["review_issues"] = context["review_issues"]
    if context.get("user_prompt_extras"):
        user_data.update(context["user_prompt_extras"])

    investigation_client = llm or project_llm_client(
        spec,
        role="attribute",
        knowledge=None,
        tools=list(context.get("tools") or []),
        tool_call_limit=tool_call_limit,
        compress_tool_results=True,
        max_tool_calls_from_history=4,
    )
    investigation_output_error = ""
    try:
        investigation = investigation_client.complete_json(
            investigation_system,
            json.dumps(to_dict(user_data), ensure_ascii=False),
            trace_id=f"{trace.trace_id}:attribute-investigation:{context.get('_attribute_round', 1)}",
            output_spec=_ATTRIBUTE_INVESTIGATION_SPEC,
        )
    except ValueError as exc:
        # Investigation 的自然语言摘要不是证据。只要 Tool/Context 已经成功注册了
        # 原始材料，结构化摘要失败也不应把材料一并丢弃；Finalization 会在无 Tool
        # 的独立调用中仅依据重新加载的 ContextUnit 形成或拒绝结论。
        logger.warning("[attribute] Investigation 输出不符合结构协议，转入材料自审：%s", exc)
        investigation_output_error = str(exc)
        investigation = {}
    except Exception as exc:
        logger.exception("[attribute] LLM call failed")
        return unresolved_attribute_result(trace, f"Attribute 主执行失败，无法形成已验证归因：{exc}")
    if investigation.get("_tool_call_log"):
        context.setdefault("_attribute_tool_audit", []).extend(investigation["_tool_call_log"])
    if investigation.get("error"):
        return unresolved_attribute_result(trace, f"Attribute Investigation 失败：{investigation.get('raw_text') or investigation['error']}")

    finalize = context.get("_attribute_finalize")
    if not callable(finalize):
        return unresolved_attribute_result(trace, "当前 Attribute 环境未提供 Finalization 能力。")
    try:
        finalized_units = finalize()
    except Exception as exc:
        return unresolved_attribute_result(trace, f"Evidence Finalization 未通过：{exc}")

    finalization_user = {
        "run_trace": _compact_trace(trace),
        "judge_result": _compact_judge(judge),
        "failed_expectation_ids": failed_ids,
        "investigation_summary": investigation.get("investigation_summary") or "",
        "finalized_context_units": finalized_units,
    }
    if investigation_output_error:
        finalization_user["investigation_output_error"] = investigation_output_error[:2_000]
    if context.get("review_issues"):
        finalization_user["review_issues"] = context["review_issues"]
    finalization_client = llm or project_llm_client(spec, role="attribute-finalization", knowledge=None, tools=[])
    try:
        finalization_system = _finalization_system_prompt()
        if context.get("system_prompt_override"):
            finalization_system += "\n\n项目补充约束：\n" + str(context["system_prompt_override"])
        serialized_finalization_user = json.dumps(to_dict(finalization_user), ensure_ascii=False)
        prompt_char_budget = int(context.get("finalization_prompt_char_budget") or 160_000)
        prompt_chars = len(finalization_system) + len(serialized_finalization_user)
        if prompt_chars > prompt_char_budget:
            return unresolved_attribute_result(
                trace,
                f"Attribute Finalization prompt size {prompt_chars} exceeds policy budget {prompt_char_budget}",
            )
        data = finalization_client.complete_json(
            finalization_system,
            serialized_finalization_user,
            trace_id=f"{trace.trace_id}:attribute-finalization:{context.get('_attribute_round', 1)}",
            output_spec=_ATTRIBUTE_OUTPUT_SPEC,
        )
    except Exception as exc:
        logger.exception("[attribute] Finalization LLM call failed")
        return unresolved_attribute_result(trace, f"Attribute Finalization 自审失败：{exc}")
    if data.get("error"):
        return unresolved_attribute_result(trace, f"Attribute Finalization 自审失败：{data.get('raw_text') or data['error']}")

    materialize = context.get("_attribute_materialize_findings")
    if not callable(materialize):
        return unresolved_attribute_result(trace, "当前 Attribute 环境未提供 EvidenceRef Finalization 能力。")
    try:
        findings = materialize(data.get("findings") or [], failed_ids)
    except Exception as exc:
        registration_failure = _registration_failure_text(context)
        suffix = f" ContextUnit 注册诊断：{registration_failure}" if registration_failure else ""
        return unresolved_attribute_result(trace, f"Evidence Finalization 未通过：{exc}.{suffix}")
    unresolved_reason = str(data.get("unresolved_reason") or "").strip()
    covered = {item for finding in findings for item in finding.affected_expectation_ids}
    registration_failure = _registration_failure_text(context)
    if registration_failure and set(failed_ids) - covered:
        notice = f"部分调查材料未能进入证据链：{registration_failure}"
        unresolved_reason = " ".join(item for item in (unresolved_reason, notice) if item)
    if not findings and not unresolved_reason:
        unresolved_reason = "当前调查未形成经 Finalization 验证的业务缺陷。"
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.case_id or ""),
        findings=findings,
        unresolved_reason=unresolved_reason,
    )
