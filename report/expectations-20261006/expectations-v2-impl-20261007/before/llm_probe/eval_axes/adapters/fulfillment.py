"""无过程 trace 场景的扩展能力兑现轴；trace 场景由主 Judge 统一裁决。"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, Mapping

from impl.core.judge import finalize_judge_result, judge_trace
from impl.core.judge_protocol import execution_failure_markers, is_terminal_judge_failure
from impl.core.live_transport import _redact_headers
from impl.core.materials_store import expand_material_uris
from impl.core.schema import JudgeResult, RunTrace, normalize_judge_result, to_dict, trace_application_boundary
from impl.projects.llm_probe.live import application_boundary_for

from ..llm import axis_llm
from ..types import (
    VERDICT_SCOPE_AXIS,
    AxisRuntime,
    AxisSummary,
    AxisType,
    ExecutionLimits,
    Dependency,
    Field,
    Input,
    RunOutcome,
    ScenarioAxis,
    Verdict,
)

# JudgeResult 的业务字段，与旧轴1同名，对照工具可直接 diff。trace_id / project_id 是记录簿字段，不进 output。
_OUTPUT_FIELDS = (
    "business_expectations",
    "fulfillment_assessments",
    "overall_fulfillment",
    "expected",
    "actual",
    "missing",
    "wrong",
    "extra",
    "evidence",
    "reasoning_summary",
    "summary",
)

FULFILLED = "fulfilled"
NOT_FULFILLED = "not_fulfilled"
NOT_EVALUABLE = "not_evaluable"

def _request_payload(trace: RunTrace) -> Dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    return dict(request)


def _parse_output_text(output_text: str) -> Any:
    text = str(output_text or "").strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def build_context(
    spec: Any,
    trace: RunTrace,
    capability: str,
    truth: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """复制自 ``LlmProbeJudge.build_context``：差别是 capability 由调用方给出（框里的描述），
    可附上游真实性结果。"""
    request = _request_payload(trace)
    show_schema = request.get("show_schema")
    output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    output_text = str(output.get("output_text") or "")
    output_text_parsed = _parse_output_text(output_text)
    system_extras = [
        "## 能力描述\n"
        "只根据能力描述判断 output_text 是否兑现了该能力。没有 gold output，不要编造参考答案。\n",
        "## not_evaluable 的边界\n"
        "not_evaluable 只在证据本身缺失时使用：output_text 为空、无法读取、或 HTTP 层失败。\n"
        "只要 output_text 有内容且可读，就必须对照能力描述和本次输入判 fulfilled 或 not_fulfilled。\n"
        "不要因为「不知道被测系统支不支持这种查询」而判 not_evaluable——系统能力边界是判后承载性裁决（轴2）的职责，不是本判定的输入。\n"
        "## 期望派生\n"
        "期望只来自两处：能力描述声明的职责，以及本次输入字面表达的语义。\n"
        "输入里明确表达的语义必须被输出忠实保留——等值/前缀/包含、范围与边界、数量与单位、逻辑关系；"
        "语义被放大、缩小或改写即 not_fulfilled（如输入说「姓名是张三」，输出却做前缀匹配）。\n"
        "不要发明两处都没有的要求：能力描述未声明「拒绝不支持的表述」时，不得要求输出必须拒绝。\n",
    ]
    if output_text_parsed is not None:
        system_extras.append(
            "## output_text_parsed\n"
            "output_text 是 JSON 字符串，user prompt 里附了解析后的 output_text_parsed。"
            "找证据以 output_text_parsed 为准，两者内容等价。\n"
        )
    if show_schema not in (None, "", {}, []):
        system_extras.append(
            "## show_schema\n"
            "下面指出输出里哪些部分重要。没提到的部分不要当成失败依据。\n"
        )
    context = {
        "intent_frame": {
            "project_id": spec.project_id,
            "downstream_consumer": request.get("capability_ref") or "probed HTTP service",
            "output_semantics": "output_text should fulfill the capability description",
            "capability": capability,
            "show_schema": show_schema,
            "critical_intent_dimensions": ["capability_fulfillment", "show_schema_focus"],
        },
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "capability": capability,
            "show_schema": show_schema,
            "request": {
                "url": request.get("url") or "",
                "method": request.get("method"),
                "headers": _redact_headers(request.get("headers") or {}),
                "body": request.get("body") or {},
                "capability_ref": request.get("capability_ref") or "",
            },
            "output_text": output_text,
            "output_text_parsed": output_text_parsed,
            "application_boundary": trace_application_boundary(trace)
            or application_boundary_for(str(request.get("response_mode") or "json")),
        }),
    }
    # 复制自 LlmProbeJudge.build_intent_frame
    frame = dict(context["intent_frame"])
    frame.setdefault("request_candidates", [
        {"source": "normalized_request.body", "value": (request.get("body") or {})},
    ])
    context["intent_frame"] = frame
    if truth:
        context["user_prompt_extras"]["truthfulness"] = {
            "claims": [{key: claim.get(key) for key in ("claim_id", "text", "context", "verdict", "reason", "citations")}
                       for claim in truth.get("claims", [])]
        }
        context["system_prompt_extras"].append(
            "## 真实性核验结果\n"
            "上游已对回答中的事实断言逐条核验。`refuted` 的断言视为事实错误，据此判相关期望 not_fulfilled；"
            "`unverifiable` 不构成失败依据；不要重复核验，也不要发明核验结果里没有的断言。"
        )
    return context


def _normalize_result(trace: RunTrace, result: JudgeResult) -> JudgeResult:
    """复制自 ``LlmProbeJudge.normalize_result``。"""
    judge_result = normalize_judge_result(result) or result
    actual = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    judge_result.actual = actual if actual else (judge_result.actual or {"output_text": ""})
    if judge_result.expected is None:
        judge_result.expected = {}
    return judge_result


def _output(result: JudgeResult) -> dict[str, Any]:
    data = to_dict(result)
    return {key: data.get(key) for key in _OUTPUT_FIELDS}


def _evidence_text(assessment: Mapping[str, Any]) -> str:
    """与 summary.aggregate_failure_dimensions 同一取证口径：证据字段 → downstream_impact。"""
    parts: list[str] = []
    for key in ("actual_evidence", "expected_evidence", "evidence_refs"):
        evidence = assessment.get(key)
        if isinstance(evidence, list):
            for entry in evidence:
                if isinstance(entry, str) and entry:
                    parts.append(entry)
                elif isinstance(entry, Mapping):
                    text = entry.get("summary") or entry.get("value") or entry.get("ref") or entry.get("reason")
                    if text:
                        parts.append(str(text))
        elif isinstance(evidence, str) and evidence:
            parts.append(evidence)
    if not parts and assessment.get("downstream_impact"):
        parts.append(str(assessment.get("downstream_impact")))
    return " | ".join(parts)


def _summary(output: Mapping[str, Any]) -> AxisSummary:
    """复制旧轴1的解释：一句话 = summary_from_fulfillment 的 reason（finalize_judge_result 已算好），
    逐格 = 每条期望的 status + 证据。不另调模型。"""
    summary = output.get("summary") if isinstance(output.get("summary"), Mapping) else {}
    text = str(summary.get("reason") or output.get("reasoning_summary") or "").strip()
    assessments = {
        str(item.get("expectation_id") or ""): item
        for item in (output.get("fulfillment_assessments") or [])
        if isinstance(item, Mapping)
    }
    items: list[dict[str, Any]] = []
    for expectation in output.get("business_expectations") or []:
        if not isinstance(expectation, Mapping):
            continue
        expectation_id = str(expectation.get("expectation_id") or "")
        assessment = assessments.get(expectation_id) or {}
        # 缺 assessment 的期望在整体派生里按 not_evaluable 计，这里同口径。
        status = str(assessment.get("status") or "not_evaluable").strip().lower()
        items.append({
            "key": expectation_id,
            "value": status,
            "reason": _evidence_text(assessment),
            "blocking": bool(expectation.get("blocking")),
        })
    return AxisSummary(text=text, items=items)


def run_fulfillment(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: AxisRuntime) -> RunOutcome:
    trace: RunTrace = inputs["trace"]
    # 与 resolve_capability 同一条展开路径：prompt-load，超预算即拒。
    capability = expand_material_uris(axis.description)
    # LLM 调用记录挂到本次试验的 trace_id 下（axe-v4 D9），不污染生产 trace 的记录。
    judged = replace(trace, trace_id=runtime.trace_id)
    context = build_context(runtime.spec, judged, capability, inputs.get("truth"))
    tools = list(context.get("tools") or [])
    # 与 core judge_trace 自建客户端的参数一致；外壳只做记账和模型策略（axe-v4 D12）。
    client = axis_llm(runtime.spec, role="judge", knowledge=None, tools=tools)
    try:
        raw = judge_trace(runtime.spec, judged, user_intent=None, llm=client, project_judge_context=context)
    except ValueError as exc:
        # 复制自 ProjectJudge.judge_trace：LLM 产出不合规阻断。旧链路落 not_evaluable + 标记，这里落 failed。
        return RunOutcome(
            output={key: None for key in _OUTPUT_FIELDS} | {"reasoning_summary": str(exc)[:500], "evidence": ["llm_output_validation_failed"]},
            summary=AxisSummary("能力兑现判定失败"),
            failed=True,
            failure_reason=f"llm_output_validation_failed: {str(exc)[:200]}",
            usage={**client.usage(), "tool_calls": 0},
        )
    usage = {**client.usage(), "tool_calls": 0}
    if is_terminal_judge_failure(raw):
        finalized = finalize_judge_result(raw)
        markers = sorted(execution_failure_markers(finalized))
        return RunOutcome(
            output=_output(finalized),
            summary=AxisSummary("能力兑现判定失败"),
            failed=True,
            failure_reason="; ".join(markers) or "judge execution failed",
            usage=usage,
        )
    normalized = _normalize_result(judged, raw)
    if is_terminal_judge_failure(normalized):
        finalized = finalize_judge_result(normalized)
        return RunOutcome(
            output=_output(finalized),
            summary=AxisSummary("能力兑现判定失败"),
            failed=True,
            failure_reason="; ".join(sorted(execution_failure_markers(finalized))),
            usage=usage,
        )
    final = finalize_judge_result(normalized)
    output = _output(final)
    return RunOutcome(output=output, summary=_summary(output), usage=usage)


AXIS_TYPE = AxisType(
    type_id="fulfillment",
    title="能力兑现",
    summary="按场景描述派生期望，逐条判 output_text 是否兑现；整体状态由 blocking 期望程序派生",
    verdict_scope=VERDICT_SCOPE_AXIS,
    verdict_enum=(
        Verdict(FULFILLED, "所有 blocking 期望都兑现"),
        Verdict(NOT_FULFILLED, "至少一条 blocking 期望未兑现（含数据源没给数据、原因说错、数据源已给的信息没传达）"),
        Verdict(NOT_EVALUABLE, "证据缺失（output_text 为空/不可读/HTTP 失败）或没有 blocking 期望，无法判"),
    ),
    depend_on=(Dependency("truthfulness", optional=True),),
    trigger_when=None,
    inputs=(
        Input("trace", source="sample.trace"),
        Input("truth", source="axis.truthfulness.output", fields=("claims", "coverage"), required=False),
    ),
    output_fields=_OUTPUT_FIELDS,
    verdict_path="overall_fulfillment.status",
    scenario_fields=(Field("description", required=True, expand="prompt_load"),),
    # 1 次判定 + 至多 1 次 reprompt；llm_probe 轴1不给工具。
    # 单次 judge 调用（含一次 reprompt），墙钟实际由 llm.request_timeout_seconds 兜底；seconds 只作声明与对照口径。
    limits=ExecutionLimits(llm_calls=2, tool_calls=0, seconds=600),
    run=run_fulfillment,
    implementation_files=(
        "impl/projects/llm_probe/eval_axes/adapters/fulfillment.py",
        "impl/core/judge.py",
        "impl/core/judge_protocol.py",
    ),
)
