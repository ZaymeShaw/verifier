from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .project_loader import load_project_document
from .schema import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeLLMOutput, JudgeReferenceOutput, JudgeResult, ProjectSpec, RunTrace, _non_empty_reference, normalize_business_expectation, normalize_fulfillment_assessment, normalize_gap_item, normalize_judge_result, to_dict, trace_application_boundary, trace_conversation_summary, trace_conversation_transcript, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_raw_response, trace_stop_reason, trace_turn_records
from .structured_output import StructuredOutputSpec
from .summary import summary_from_fulfillment

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .llm_client import LlmClient

_FIELD_LIST_KEYS = frozenset(["conditions", "structured_output"])
_JUDGE_RAW_RESPONSE_MAX_CHARS = 4000


def _extract_fields_from_trace(trace: RunTrace) -> Set[str]:
    """Extract all field names mentioned in trace input, output, and reference."""
    fields = set()
    output = trace_extracted_output(trace) if trace_extracted_output(trace) else {}
    if isinstance(output, dict):
        for key in _FIELD_LIST_KEYS:
            if key in output and isinstance(output[key], list):
                for entry in output[key]:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])
    reference = trace.reference_contract or (trace.input.get("reference") if isinstance(trace.input, dict) else None)
    if isinstance(reference, dict):
        for key, value in reference.items():
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])
    return fields


def _compact_raw_response_for_judge(raw_response: Any) -> Any:
    if raw_response is None:
        return None
    if isinstance(raw_response, str):
        if len(raw_response) <= _JUDGE_RAW_RESPONSE_MAX_CHARS:
            return raw_response
        head = _JUDGE_RAW_RESPONSE_MAX_CHARS // 2
        return raw_response[:head] + f"...[truncated {len(raw_response) - _JUDGE_RAW_RESPONSE_MAX_CHARS:,} chars]..." + raw_response[-head:]
    if isinstance(raw_response, dict):
        result = {}
        for k, v in raw_response.items():
            if k == "raw" and isinstance(v, str) and len(v) > _JUDGE_RAW_RESPONSE_MAX_CHARS:
                head = _JUDGE_RAW_RESPONSE_MAX_CHARS // 2
                result[k] = v[:head] + f"...[truncated {len(v) - _JUDGE_RAW_RESPONSE_MAX_CHARS:,} chars]..." + v[-head:]
            else:
                result[k] = v
        return result
    return raw_response


def _judge_turn_view(turn: Any) -> Dict[str, Any]:
    """Project one trace turn into judge evidence without transport-private raw payloads."""
    if not isinstance(turn, dict):
        return {}
    allowed = (
        "turn_index",
        "request",
        "extracted_output",
        "call_status",
        "runtime_ms",
        "error",
        "fallbacks",
        "validation",
        "execution_trace",
        "application_boundary",
        "project_fields",
    )
    return {key: turn.get(key) for key in allowed if key in turn}


def build_judge_evidence_view(trace: RunTrace) -> Dict[str, Any]:
    """把完整 RunTrace 确定性投影为 Judge 可消费的业务事实。

    Judge 的事实源是 RunTrace，但不直接解释 adapter 私有路径或状态机内部结构。
    raw_response 只在输出缺失或执行失败时作为补充证据暴露。
    """
    final_output = trace_extracted_output(trace)
    turns = [_judge_turn_view(turn) for turn in trace_turn_records(trace)]
    raw_response_evidence = None
    if not final_output or str(trace.status or "") != "ok":
        raw_response_evidence = _compact_raw_response_for_judge(trace_raw_response(trace))
    missing_evidence = []
    if not final_output:
        missing_evidence.append("final_output")
    if str(trace.status or "") != "ok":
        missing_evidence.append("successful_execution")
    return {
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "case_id": trace.case_id,
        "intent_input": trace_input(trace),
        "normalized_request": trace_normalized_request(trace),
        "final_output": final_output,
        "final_output_turn": trace.final_output_turn,
        "turns": turns,
        "conversation_transcript": trace_conversation_transcript(trace),
        "conversation_summary": trace_conversation_summary(trace),
        "stop_reason": trace_stop_reason(trace),
        "completion_status": str(trace.completion_status or ""),
        "execution_trace": trace_execution_trace(trace),
        "evidence_refs": to_dict(getattr(trace, "evidence_refs", None) or []),
        "raw_response_evidence": raw_response_evidence,
        "evidence_completeness": {
            "complete": not missing_evidence,
            "missing_evidence": missing_evidence,
        },
        "application_boundary": trace_application_boundary(trace),
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "scenario": trace.scenario,
        "status": trace.status,
        "error": trace.error if str(trace.status or "") != "ok" else None,
    }


# 兼容内部旧名称；所有新调用统一使用 build_judge_evidence_view。
_judge_run_trace_view = build_judge_evidence_view


def load_judge_boundary_standard(spec: ProjectSpec) -> Dict[str, Any]:
    implementation_standard = spec.frontend_extensions.get("implementation_standard") if spec.frontend_extensions else None
    boundary = implementation_standard.get("judge_boundary") if isinstance(implementation_standard, dict) else None
    if not isinstance(boundary, dict) or not boundary:
        raise ValueError(f"project {spec.id} missing implementation_standard.judge_boundary structured field")
    return dict(boundary)


_FULFILLMENT_STATUS_VOCAB = {"fulfilled", "not_fulfilled", "not_evaluable"}


def _derive_overall_status(business_expectations: list[Any], assessments: list[Any]) -> str:
    """Derive overall status only from expectations declared blocking before comparison."""
    blocking_ids = {
        str(item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", ""))
        for item in business_expectations or []
        if bool(item.get("blocking") if isinstance(item, dict) else getattr(item, "blocking", False))
    }
    if not business_expectations or not assessments:
        return "not_evaluable"
    if not blocking_ids:
        return "fulfilled"
    status_by_id = {
        str(item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", "")):
        str(item.get("status") if isinstance(item, dict) else getattr(item, "status", "")).strip().lower()
        for item in assessments or []
    }
    blocking_statuses = [status_by_id.get(expectation_id, "not_evaluable") for expectation_id in blocking_ids]
    if any(status == "not_fulfilled" for status in blocking_statuses):
        return "not_fulfilled"
    if any(status != "fulfilled" for status in blocking_statuses):
        return "not_evaluable"
    return "fulfilled"


def ensure_business_expectation(
    result: JudgeResult,
    expectation_id: str,
    *,
    blocking: bool,
    expected_outcome: str,
    acceptance_criteria: Optional[list[Any]] = None,
    downstream_consumer: str = "",
) -> None:
    """Add or update a project contract expectation without putting policy on its assessment."""
    expectations = list(result.business_expectations or [])
    for item in expectations:
        item_id = item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", "")
        if str(item_id or "") != expectation_id:
            continue
        if isinstance(item, dict):
            item["blocking"] = blocking
        else:
            item.blocking = blocking
        result.business_expectations = expectations
        return
    expectations.append(BusinessExpectation(
        expectation_id=expectation_id,
        downstream_consumer=downstream_consumer,
        expected_outcome=expected_outcome,
        acceptance_criteria=list(acceptance_criteria or []),
        priority="high" if blocking else "normal",
        blocking=blocking,
    ))
    result.business_expectations = expectations


def finalize_judge_result(result: JudgeResult) -> JudgeResult:
    """Apply the single public derivation after all project extensions have finished."""
    normalized = normalize_judge_result(result) or result
    overall = dict(normalized.overall_fulfillment or {})
    overall["status"] = _derive_overall_status(
        list(normalized.business_expectations or []),
        list(normalized.fulfillment_assessments or []),
    )
    overall["blocking_expectations"] = [
        item.expectation_id
        for item in normalized.business_expectations or []
        if bool(item.blocking)
    ]
    normalized.overall_fulfillment = overall
    normalized.summary = summary_from_fulfillment(to_dict(normalized))
    return normalized


def _dict_value(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _judge_self_check(data: Dict[str, Any], business_expectations: list) -> list[Dict[str, Any]]:
    """Detect fulfillment inconsistencies before constructing JudgeResult."""
    inconsistencies: list[Dict[str, Any]] = []
    assessments = data.get("fulfillment_assessments") or []
    valid_ids = {
        str(item.get("expectation_id"))
        for item in (business_expectations or [])
        if isinstance(item, dict) and item.get("expectation_id")
    }
    assessment_ids: set[str] = set()
    for index, item in enumerate(assessments):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        expectation_id = str(item.get("expectation_id") or "")
        assessment_ids.add(expectation_id)
        if expectation_id and expectation_id not in valid_ids:
            inconsistencies.append({
                "kind": "unknown_expectation_id",
                "where": f"fulfillment_assessments[{index}].expectation_id",
                "value": expectation_id,
            })
        if status and status not in _FULFILLMENT_STATUS_VOCAB:
            inconsistencies.append({
                "kind": "status_off_vocabulary",
                "where": f"fulfillment_assessments[{index}].status",
                "value": status,
                "expected": "|".join(sorted(_FULFILLMENT_STATUS_VOCAB)),
            })
    for expectation_id in sorted(valid_ids - assessment_ids):
        inconsistencies.append({
            "kind": "missing_fulfillment_assessment",
            "where": "fulfillment_assessments",
            "expectation_id": expectation_id,
        })
    return inconsistencies


def _trace_reference(trace: RunTrace) -> Any:
    if not _reference_ready_from_trace(trace):
        return None
    if _non_empty_reference(trace.reference_contract):
        return trace.reference_contract
    input_data = trace.input or {}
    if _non_empty_reference(input_data.get("reference")):
        return input_data.get("reference")
    request = trace_normalized_request(trace)
    if _non_empty_reference(request.get("reference")):
        return request.get("reference")
    return None


def _reference_ready_from_trace(trace: RunTrace) -> bool:
    ready = getattr(trace, "ready", None)
    if ready is None:
        raise ValueError(
            f"trace.ready 字段缺失: trace_id={trace.trace_id}, project_id={trace.project_id}。"
            "所有 trace 必须携带 ready 快照，请确认 trace 由 pipeline.live_run 正常构建。"
        )
    return "reference" in ready


def _has_input_reference(trace: RunTrace) -> bool:
    return _trace_reference(trace) is not None


def _source_documents(spec: ProjectSpec) -> Dict[str, str]:
    return {
        key: load_project_document(spec, key)
        for key in sorted(spec.documents)
        if key.startswith("source_") and key != "source_field_definitions"
    }


def judge_trace(
    spec: ProjectSpec,
    trace: RunTrace,
    user_intent: Optional[str] = None,
    llm: Optional[LlmClient] = None,
    project_judge_context: Optional[Dict[str, Any]] = None,
    has_actual: bool = True,
    has_reference: bool = False,
) -> JudgeResult:
    """judge 判定入口。spec/info-volume.md 后只产 fulfillment + expected/actual + gaps，不再产 verdict。"""
    evaluation = load_project_document(spec, "evaluation")
    boundary_standard = load_judge_boundary_standard(spec)
    judge_boundary = load_project_document(spec, "judge_boundary")
    judge_standard = load_project_document(spec, "judge_standard")

    if not user_intent and project_judge_context:
        user_intent = project_judge_context.get("user_intent") or (
            project_judge_context.get("intent_frame", {}).get("user_intent")
            if isinstance(project_judge_context.get("intent_frame"), dict)
            else None
        )

    system = (
        "你是通用评估系统的 judge agent。\n\n"
        "## 核心原则\n"
        "只基于当前 RunTrace、项目评判标准和动态检索的知识库内容判断，不继承历史 case。\n"
        "首要职责：理解用户/下游消费者的真实业务意图 → 派生 business_expectations → "
        "基于完整执行链路（每轮 output、最终 output、交互过程和停止事实）判断 expectations 的 fulfillment。\n\n"
        "## expectation 拆分原则\n"
        "business_expectations 的粒度直接决定判断精度。每个 expectation 必须是原子可判定的——"
            "仅凭当前 Judge evidence 中的业务事实就能明确判定 fulfilled 或 not_fulfilled。\n"
        "- 一个 expectation 只描述一个可独立验证的结果维度\n"
        "- 多维度意图必须拆成多个 expectation\n"
        "- 每个 expectation 必须有明确的 acceptance_criteria\n"
        "- 每个 expectation 必须在比较 actual 前确定 blocking：只有缺失后会阻断用户/下游核心目的、安全底线或项目强契约的 expectation 才设为 true\n"
        "- fulfillment_assessments 只判断对应 expectation 的 status 和证据，不得重新定义 blocking\n"
        "- expectation_id 必须是描述性的中文短语，禁止使用 E1/E2/exp_01 等占位符 ID\n"
        "- reasoning_summary 必须是中文写成的判断依据\n\n"
    )
    if has_actual:
        system += (
            "## 输出词表\n"
            "`fulfillment_assessments[*].status` 必须从以下 3 个值中选择：\n"
            "  - fulfilled：该 expectation 完全满足\n"
            "  - not_fulfilled：该 expectation 未满足\n"
            "  - not_evaluable：当前无法评估\n"
            "禁用 failed/passed/incorrect/wrong/met/unmet/partially_fulfilled/partial/success/fail/ok/unknown 等同义词。\n"
            "`fulfillment_assessments[*].expected_evidence` 与 `actual_evidence` **必须是数组**（JSON array / list），"
            "即使只有一条证据也要用 `[...]` 包裹，不可直接用字符串或对象。\n\n"
            "不要输出 overall_fulfillment；公共层会在项目契约补充完成后根据 blocking expectations 确定性派生整体状态。\n\n"
        )
    system += (
        f"## 评估规范\n{evaluation}\n\n"
        f"## 评估边界\n{judge_boundary}\n\n"
        f"## 判断标准\n{judge_standard}\n\n"
    )

    system_extras = []
    if project_judge_context:
        raw_extras = project_judge_context.get("system_prompt_extras")
        if isinstance(raw_extras, str) and raw_extras.strip():
            system_extras.append(raw_extras.strip())
        elif isinstance(raw_extras, list):
            system_extras.extend(str(item).strip() for item in raw_extras if str(item).strip())
    if system_extras:
        system += "\n\n" + "\n\n".join(system_extras) + "\n"

    if not has_actual:
        system += (
            "## 仅生成 reference（expected）模式\n"
            "本次调用没有 actual output，你**只产 expected**（参考答案），不做 fulfillment 判定。\n"
            "你的 expected 是该输入下系统应当产出什么的标准答案。\n\n"
            "### expected 的产出步骤\n"
            "1. 理解用户意图（run_trace.input / user_intent / scenario）\n"
            "2. 结合项目评估文档确定该场景下的标准答案应满足什么\n"
            "3. 派生 business_expectations，每条 expectation 的 expected_outcome 描述该输入下系统应当产出什么\n"
            "4. 把所有 expected_outcome 汇总成 expected 字段，按结构化输出约束的 JSON Schema 填入真实内容\n\n"
            "### 强约束\n"
            "- expected 字段必须非空\n"
            "- 不要输出 fulfillment_assessments / overall_fulfillment / missing / wrong / extra 等判定域字段\n"
            "- 输出 JSON，只含 expected、business_expectations\n"
        )

    system += (
        "## 工具使用原则\n"
        "所有工具的用途、调用时机和参数含义以 Agno tool schema 为准；"
        "user prompt 中已提供当前 case 涉及字段的完整能力清单时，优先使用 prompt 信息。\n\n"
        "## 禁止事项\n"
        "- 不要把 reference answer 当作默认主目标（除非 case 明确指定）\n"
        "- 不要把 HTTP 状态、run_status、attribute/cluster 结论当作满足依据\n"
        "- 不要归因内部代码、配置或 prompt 原因（属于 attribute agent）\n"
        "- 分析文字必须使用中文，包括 reasoning_summary 等所有文本字段。\n"
        "- 输出 JSON。"
    )
    user_payload = to_dict({
        "user_intent": user_intent,
        "run_trace": build_judge_evidence_view(trace),
    })
    if project_judge_context:
        user_extras = project_judge_context.get("user_prompt_extras")
        if isinstance(user_extras, dict):
            user_payload.update(to_dict(user_extras))
    user = json.dumps(user_payload, ensure_ascii=False)

    tools = project_judge_context.get("tools") if project_judge_context else None
    tools = list(tools or [])
    if llm is None:
        from .llm_client import project_llm_client
        client = project_llm_client(spec, role="judge", knowledge=None, tools=tools)
    else:
        client = llm
    client._caller = "judge"

    has_reference = _has_input_reference(trace)
    output_spec = _build_judge_output_spec(has_actual, project_id=spec.project_id, has_reference=has_reference)
    try:
        data = client.complete_json(system, user, trace_id=trace.trace_id, output_spec=output_spec)
    except ValueError as exc:
        logger.warning(f"[judge] enforce 阻断，触发 reprompt: {exc}")
        reprompt_inconsistencies = [{"kind": "enforce_blocked", "where": "structured_output", "detail": str(exc)}]
        data = _reprompt_judge(client, system, user, {}, reprompt_inconsistencies, trace.trace_id, output_spec=output_spec)
        if data.get("error"):
            return _minimal_honest_judge_result(spec, trace, data)

    business_expectations = list(data.get("business_expectations") or [])
    inconsistencies = _judge_self_check(data, business_expectations)
    if inconsistencies:
        data = _reprompt_judge(client, system, user, data, inconsistencies, trace.trace_id, output_spec=output_spec)
        business_expectations = list(data.get("business_expectations") or [])
        inconsistencies = _judge_self_check(data, business_expectations)
        if inconsistencies:
            data["reasoning_summary"] = (data.get("reasoning_summary") or "") + f" [self_check_failed: {json.dumps(inconsistencies, ensure_ascii=False)}]"

    return _build_judge_result_from_data(spec, trace, data, user_intent, boundary_standard)


def generate_reference(
    spec: ProjectSpec,
    intent: Dict[str, Any],
    project_id: Optional[str] = None,
    llm: Optional[LlmClient] = None,
) -> Optional[Dict[str, Any]]:
    """仅生成 reference（expected）模式。"""
    project_id_val = project_id or spec.project_id
    trace = RunTrace(
        trace_id=f"judge-ref-gen-{project_id_val}",
        project_id=project_id_val,
        case_id="",
        input=intent.get("input", {}),
        status="pending",
        scenario=intent.get("scenario", ""),
    )
    user_intent_value = intent.get("user_intent")
    from .project_loader import load_adapter
    project_judge_context = None
    try:
        adapter = load_adapter(spec)
        project_judge_context = adapter.build_judge_context(trace)
        project_judge_context = {**(project_judge_context or {}), "intent_frame": adapter.build_intent_frame(trace)}
    except Exception:
        pass
    result = judge_trace(spec, trace, user_intent=user_intent_value, llm=llm,
                         project_judge_context=project_judge_context,
                         has_actual=False, has_reference=False)
    if result.expected is not None:
        return result.expected if isinstance(result.expected, dict) else None
    return None


def _reprompt_judge(
    client: LlmClient,
    system: str,
    user: str,
    data: Dict[str, Any],
    inconsistencies: list[Dict[str, Any]],
    trace_id: str,
    output_spec: Optional[StructuredOutputSpec] = None,
) -> Dict[str, Any]:
    appendix = (
        "\n\n## 上次输出存在不一致\n"
        + json.dumps(inconsistencies, ensure_ascii=False)
        + "\n## 上次完整输出\n"
        + json.dumps(data, ensure_ascii=False)
        + "\n请保留未报错字段，只修正以上路径后重新输出完整 JSON。"
    )
    return client.complete_json(system, user + appendix, trace_id=trace_id, output_spec=output_spec)


def _build_judge_output_spec(has_actual: bool, project_id: str = "", has_reference: bool = False) -> StructuredOutputSpec:
    """构造 judge 调用的结构化输出约束。spec/info-volume.md 后只约束通用字段。

    project_override: 项目级 schema 覆写，支持项目扩展 FulfillmentAssessment 字段。
    """
    nested: Dict[str, StructuredOutputSpec] = {}
    require_expected = not (has_actual and has_reference)
    if project_id and require_expected:
        try:
            from .mock_agent import load_live_schema
            live_schema = load_live_schema(project_id)
            extract_cls = getattr(live_schema, "EXTRACT_OUTPUT_SCHEMA", None) if live_schema is not None else None
            if extract_cls is not None:
                nested["expected"] = StructuredOutputSpec.from_dataclass(
                    extract_cls,
                    description=f"项目 {project_id} 的 expected/live output 结构",
                )
        except Exception:
            pass

    if not has_actual:
        return StructuredOutputSpec.from_dataclass(
            JudgeReferenceOutput,
            required_nonempty=["expected", "business_expectations"],
            description="judge 仅生成 reference（expected）模式",
            nested_schemas=nested,
        )

    if has_reference:
        required_nonempty = ["business_expectations", "reasoning_summary"]
        description = "judge 判定输出（reference 已固化，仅产 fulfillment 判定）"
    else:
        required_nonempty = ["expected", "business_expectations", "reasoning_summary"]
        description = "judge 判定输出（自产 reference + fulfillment 判定）"
    return StructuredOutputSpec.from_dataclass(
        JudgeLLMOutput,
        required_nonempty=required_nonempty,
        description=description,
        nested_schemas=nested,
    )


def _minimal_honest_judge_result(spec: ProjectSpec, trace: RunTrace, data: Dict[str, Any]) -> JudgeResult:
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        business_expectations=[],
        fulfillment_assessments=[],
        overall_fulfillment={
            "status": "not_evaluable",
            "assessment_count": 0,
            "blocking_expectations": [],
        },
        reasoning_summary="LLM 调用失败，未做出算法判断" + (f": {data.get('raw_text', '')}" if data.get("raw_text") else ""),
        evidence=["llm_call_failed"],
    )
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def _build_judge_result_from_data(
    spec: ProjectSpec,
    trace: RunTrace,
    data: Dict[str, Any],
    user_intent: Optional[str],
    boundary_standard: Dict[str, Any],
) -> JudgeResult:
    evidence = list(data.get("evidence") or [])
    if not evidence and data.get("reasoning_summary"):
        evidence = [str(data.get("reasoning_summary"))]
    actual = trace_extracted_output(trace) or data.get("actual")

    expected: Any = None
    if _has_input_reference(trace):
        expected = _trace_reference(trace)
    else:
        expected = data.get("expected")

    raw_assessments = list(data.get("fulfillment_assessments") or [])
    assessments = [item for item in (normalize_fulfillment_assessment(item) for item in raw_assessments) if item is not None]
    business_expectations: List[BusinessExpectation] = [item for item in (normalize_business_expectation(item) for item in list(data.get("business_expectations") or [])) if item is not None]
    fulfillment_assessments: List[FulfillmentAssessment] = assessments
    overall = _dict_value(data.get("overall_fulfillment"))
    overall["status"] = _derive_overall_status(business_expectations, fulfillment_assessments)
    missing_items: List[GapItem] = [normalize_gap_item(item, "missing") for item in list(data.get("missing") or [])]
    wrong_items: List[GapItem] = [normalize_gap_item(item, "wrong") for item in list(data.get("wrong") or [])]
    extra_items: List[GapItem] = [normalize_gap_item(item, "extra") for item in list(data.get("extra") or [])]

    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        business_expectations=business_expectations,
        fulfillment_assessments=fulfillment_assessments,
        overall_fulfillment=overall,
        expected=expected,
        actual=actual,
        missing=missing_items,
        wrong=wrong_items,
        extra=extra_items,
        evidence=evidence,
        reasoning_summary=str(data.get("reasoning_summary") or ""),
    )
    result.summary = summary_from_fulfillment(to_dict(result))
    return normalize_judge_result(result) or result
