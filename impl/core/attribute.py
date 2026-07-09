"""spec/info-volume.md：通用层 attribute 协议入口 + agno 桥接调用。

通用层职责：
1. 提供 attribute agent 的协议入口（attribute_failure）
2. 通过 ToolOrchestrator + agno 桥接调用项目层定义的 tool
3. 产出 AttributeResult（只含通用最小字段）

项目层职责（impl/projects/<project>/attribute.py）：
- 提供 build_attribute_context / build_attribute_system_prompt / build_attribute_user_prompt
- 选择 tool 集合
- 产出项目特有归因字段（已下沉，不进通用 schema）

通用层不调用项目层方法（避免循环）；项目层通过 protocol_entry 调用通用能力。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .llm_client import LlmClient, project_llm_client
from .schema import AttributeLLMOutput, AttributeResult, ExpectationAttribution, JudgeResult, ProjectSpec, RunTrace, judge_expected_actual_gaps, judge_primary_signal, normalize_attribute_result, normalize_expectation_attribution, to_dict, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request
from .structured_output import StructuredOutputSpec
from .summary import summary_from_attribution

logger = logging.getLogger(__name__)

ATTRIBUTE_TOOL_CALL_LIMIT = 6

_ATTRIBUTE_OUTPUT_SPEC = StructuredOutputSpec.from_dataclass(
    AttributeLLMOutput,
    required_nonempty=["expectation_attributions", "root_cause_hypothesis"],
    description="attribute 归因分析输出",
)


def _compact_value(obj: Any, max_chars: int) -> Any:
    if isinstance(obj, str):
        return obj[:max_chars] + f"...[truncated {len(obj) - max_chars:,} chars]" if len(obj) > max_chars else obj
    if isinstance(obj, dict):
        return {k: _compact_value(v, max_chars) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_compact_value(v, max_chars) for v in obj[:20]]
    return obj


def _compact_trace(trace: RunTrace) -> dict:
    return {
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "input": _compact_value(trace.input, 1200),
        "normalized_request": _compact_value(trace_normalized_request(trace), 1200),
        "extracted_output": _compact_value(trace_extracted_output(trace), 10000),
        "runtime_logs": _compact_value(trace.runtime_logs, 1200),
        "evidence_refs": _compact_value(trace.evidence_refs, 1200),
        "execution_trace": _compact_value(trace_execution_trace(trace), 2500),
        "status": trace.status,
        "error": _compact_value(trace.error, 1200),
    }


def _compact_judge(judge: JudgeResult) -> dict:
    primary_signal = judge_primary_signal(judge)
    gaps = judge_expected_actual_gaps(judge)
    return {
        "trace_id": judge.trace_id,
        "project_id": judge.project_id,
        "business_expectations": _compact_value(primary_signal.get("business_expectations"), 2500),
        "fulfillment_assessments": _compact_value(primary_signal.get("fulfillment_assessments"), 2500),
        "overall_fulfillment": _compact_value(primary_signal.get("overall_fulfillment"), 1200),
        "missing": _compact_value(gaps.get("missing"), 1200),
        "wrong": _compact_value(gaps.get("wrong"), 1200),
        "extra": _compact_value(gaps.get("extra"), 1200),
        "evidence": _compact_value(getattr(judge, "evidence", None), 1200),
        "reasoning_summary": _compact_value(getattr(judge, "reasoning_summary", None), 2500),
    }


def _attribution_targets(judge: JudgeResult) -> list[dict]:
    expectations = {}
    for item in judge.business_expectations or []:
        expectation_id = item.expectation_id if hasattr(item, "expectation_id") else item.get("expectation_id") if isinstance(item, dict) else ""
        if expectation_id:
            expectations[expectation_id] = item
    targets = []
    failing_statuses = {"not_fulfilled", "not_evaluable"}
    for assessment in judge.fulfillment_assessments or []:
        expectation_id = assessment.expectation_id if hasattr(assessment, "expectation_id") else assessment.get("expectation_id") if isinstance(assessment, dict) else ""
        status = assessment.status if hasattr(assessment, "status") else assessment.get("status") if isinstance(assessment, dict) else ""
        if expectation_id and str(status) in failing_statuses:
            expectation = expectations.get(expectation_id, {})
            targets.append({
                "expectation_id": expectation_id,
                "fulfillment_status": str(status),
                "expected": getattr(expectation, "expected_outcome", None) or (expectation.get("expected_outcome") if isinstance(expectation, dict) else ""),
                "assessment": assessment if isinstance(assessment, dict) else to_dict(assessment),
                "expectation": expectation if isinstance(expectation, dict) else to_dict(expectation),
            })
    if targets:
        return targets
    for item in judge.business_expectations or []:
        expectation_id = item.expectation_id if hasattr(item, "expectation_id") else item.get("expectation_id") if isinstance(item, dict) else ""
        if expectation_id:
            targets.append({
                "expectation_id": expectation_id,
                "fulfillment_status": _judge_fulfillment_status(judge),
                "expected": getattr(item, "expected_outcome", None) or (item.get("expected_outcome") if isinstance(item, dict) else ""),
                "expectation": item if isinstance(item, dict) else to_dict(item),
            })
    return targets


def _judge_fulfillment_status(judge: JudgeResult) -> str:
    overall = judge.overall_fulfillment or {}
    if isinstance(overall, dict):
        status = overall.get("status")
        if status:
            return str(status)
    statuses = []
    for item in judge.fulfillment_assessments or []:
        if hasattr(item, "status"):
            statuses.append(str(item.status or ""))
        elif isinstance(item, dict):
            statuses.append(str(item.get("status") or ""))
    if not statuses:
        return "not_evaluable"
    if any(s == "not_fulfilled" for s in statuses):
        return "not_fulfilled"
    if any(s == "not_evaluable" for s in statuses):
        return "not_evaluable"
    return "fulfilled"


def _default_system_prompt(tool_call_limit: int) -> str:
    return f"""你是通用评估系统的 attribute agent。

## 核心目标
围绕 judge 中未达成、部分达成、不可评估的 business_expectations，基于当前可观测证据解释 fulfillment 状态背后的根因。

## 推理框架
1. 基于 trace + judge 结果，识别哪些 expectation 未达成
2. 基于当前信息缺口选择合适工具填补证据
3. 用工具返回的证据推导最可能的根因假设
4. 给出证据强度标注：strong / medium / weak / none

## 输出格式
- 最终输出必须是单个合法 JSON 对象
- 禁止 markdown 散文、章节标题
- 分析文字必须使用中文

## 关键约束
- suspected_locations 只能基于真实证据，不能编造路径或函数名
- 如果证据不足以支撑根因，evidence_strength 设为 weak 或 none，root_cause_hypothesis 给出"最可能"的假设而非编造确定结论
- 工具调用预算有限（最多 {tool_call_limit} 次），每次调用都必须服务于当前未满足的信息缺口
"""


def _fulfilled_attribute_result(spec: ProjectSpec, trace: RunTrace, judge: JudgeResult) -> AttributeResult:
    """整体 fulfilled 时的快速归因。"""
    expectation_ids = [item.expectation_id if hasattr(item, "expectation_id") else item.get("expectation_id") if isinstance(item, dict) else ""
                       for item in (judge.business_expectations or judge.fulfillment_assessments or [])]
    expectation_ids = [eid for eid in expectation_ids if eid]
    if not expectation_ids:
        expectation_ids = ["primary_business_expectation"]
    evidence = list(getattr(judge, "evidence", None) or [getattr(judge, "reasoning_summary", None) or "business expectations are fulfilled"])
    attributions: list[ExpectationAttribution] = [
        ExpectationAttribution(
            expectation_id=eid,
            fulfillment_status="fulfilled",
            root_cause_hypothesis="业务预期已达成，无根因。",
            evidence=evidence,
        )
        for eid in expectation_ids
    ]
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or "") if isinstance(trace.input, dict) else "",
        expectation_attributions=attributions,
        root_cause_hypothesis="业务预期已达成，无根因。",
        evidence=evidence,
        evidence_strength="strong",
    )
    result.summary = summary_from_attribution(to_dict(result))
    return result


def _llm_call_failed_attribute_result(spec: ProjectSpec, trace: RunTrace, judge: JudgeResult, error_text: str) -> AttributeResult:
    """LLM 调用失败时的兜底归因。"""
    expectation_ids = [item.expectation_id if hasattr(item, "expectation_id") else item.get("expectation_id") if isinstance(item, dict) else ""
                       for item in (judge.fulfillment_assessments or [])]
    attributions = [
        ExpectationAttribution(
            expectation_id=eid,
            fulfillment_status="not_evaluable",
            root_cause_hypothesis=f"attribute agent LLM 调用失败: {error_text}",
            evidence=[error_text],
        )
        for eid in expectation_ids
    ]
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or "") if isinstance(trace.input, dict) else "",
        expectation_attributions=attributions,
        root_cause_hypothesis=f"attribute agent LLM 调用失败，无法完成正式归因: {error_text}",
        evidence=[error_text],
        evidence_strength="none",
    )
    result.summary = summary_from_attribution(to_dict(result))
    return result


def attribute_failure(
    spec: ProjectSpec,
    trace: RunTrace,
    judge: JudgeResult,
    llm: Optional[LlmClient] = None,
    project_attribute_context: Optional[dict] = None,
) -> AttributeResult:
    """通用层归因协议入口。

    项目层可通过 project_attribute_context 注入：
    - system_prompt_override: 自定义 system prompt
    - user_prompt_extras: 自定义 user prompt 附加内容（项目特有上下文）
    - tools: 项目自定义 tool 集合
    - tool_call_limit: 工具调用预算
    - targets_override: 自定义归因目标列表
    """
    if _judge_fulfillment_status(judge) == "fulfilled":
        return _fulfilled_attribute_result(spec, trace, judge)

    context = project_attribute_context or {}
    tool_call_limit = context.get("tool_call_limit") or ATTRIBUTE_TOOL_CALL_LIMIT

    # 归因目标
    attribution_targets = context.get("targets_override") or _attribution_targets(judge)

    # Tool 集合：项目层提供
    tools = context.get("tools") or []

    # Build prompts
    system = context.get("system_prompt_override") or _default_system_prompt(tool_call_limit)
    user_data = {
        "run_trace": _compact_trace(trace),
        "judge_result": _compact_judge(judge),
        "attribution_targets": attribution_targets,
        "project_attribute_context": {k: v for k, v in context.items() if k not in ("system_prompt_override", "tools", "tool_call_limit", "targets_override")},
    }
    # 项目层可注入额外字段
    if context.get("user_prompt_extras"):
        user_data.update(context["user_prompt_extras"])
    user = json.dumps(to_dict(user_data), ensure_ascii=False)

    # LLM call
    client = llm or project_llm_client(
        spec, role="attribute", knowledge=None, tools=tools,
        tool_call_limit=tool_call_limit,
        compress_tool_results=True,
        max_tool_calls_from_history=3,
    )
    try:
        data = client.complete_json(system, user, trace_id=trace.trace_id, output_spec=_ATTRIBUTE_OUTPUT_SPEC)
    except Exception as e:
        logger.error(f"[attribute] LLM call failed: {e}")
        return _llm_call_failed_attribute_result(spec, trace, judge, str(e))

    if data.get("error"):
        return _llm_call_failed_attribute_result(spec, trace, judge, data.get("raw_text") or data.get("error") or "llm request failed")

    # Build AttributeResult
    expectation_attributions: list[ExpectationAttribution] = [
        item for item in (normalize_expectation_attribution(item) for item in list(data.get("expectation_attributions") or []))
        if item is not None
    ]
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or "") if isinstance(trace.input, dict) else "",
        expectation_attributions=expectation_attributions,
        suspected_locations=list(data.get("suspected_locations") or []),
        root_cause_hypothesis=str(data.get("root_cause_hypothesis") or ""),
        evidence=list(data.get("evidence") or []),
        evidence_strength=str(data.get("evidence_strength") or "weak"),
    )
    result.summary = summary_from_attribution(to_dict(result))
    return normalize_attribute_result(result) or result