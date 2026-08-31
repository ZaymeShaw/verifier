from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from impl.core.authority_gate import apply_authority_gate
from impl.core.judge import (
    _compact_raw_response_for_judge,
    _derive_overall_status,
    _dict_value,
    _has_input_reference,
    _judge_turn_view,
    _minimal_honest_judge_result,
    _trace_reference,
    load_judge_boundary_standard,
)
from impl.core.project_loader import load_project_document
from impl.core.schema import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeLLMOutput, JudgeReferenceOutput, JudgeResult, ProjectSpec, RunTrace, normalize_business_expectation, normalize_fulfillment_assessment, normalize_gap_item, normalize_judge_result, to_dict, trace_application_boundary, trace_conversation_summary, trace_conversation_transcript, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_raw_response, trace_stop_reason, trace_turn_records
from impl.core.structured_output import StructuredOutputSpec
from impl.core.summary import summary_from_fulfillment

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from impl.core.llm_client import LlmClient


_MISSING_CORE_DELIVERY_ID = "核心业务交付"
_ABORT_EVIDENCE_MARKERS = (
    "llm_call_failed",
    "LLM 调用失败",
    "tool_budget_exceeded",
    "tool_budget abort",
)


def _authority_enabled(spec: ProjectSpec) -> bool:
    from impl.core.authority_scopes import in_run_authority_enabled

    return in_run_authority_enabled(spec)


def _item_status(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("status") or "").strip().lower()
    return str(getattr(item, "status", "") or "").strip().lower()


def _set_item_status(item: Any, status: str) -> None:
    if isinstance(item, dict):
        item["status"] = status
    else:
        item.status = status


def _evidence_marks_judge_abort(result: JudgeResult) -> bool:
    chunks: list[str] = [str(result.reasoning_summary or "")]
    for item in result.evidence or []:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, dict):
            chunks.append(json.dumps(item, ensure_ascii=False))
        else:
            chunks.append(str(item))
    blob = " ".join(chunks)
    return any(marker in blob for marker in _ABORT_EVIDENCE_MARKERS)


def _attach_missing_core_delivery_nf(result: JudgeResult, *, reason: str) -> None:
    """Honest missing-core-delivery NF shape.

    finalize_judge_result re-derives overall from assessments; empty
    assessments become not_evaluable. Authority-off fail-closed therefore
    supplies one blocking NF assessment instead of leaving the RoleResult
    as not_evaluable.
    """
    if list(result.fulfillment_assessments or []):
        return
    expectation_id = _MISSING_CORE_DELIVERY_ID
    expectations = list(result.business_expectations or [])
    expectations.append(BusinessExpectation(
        expectation_id=expectation_id,
        blocking=True,
        downstream_consumer="用户请求的核心业务结果",
        user_intent="用户请求的核心业务交付",
        expected_outcome="交付用户请求的核心业务结果",
        acceptance_criteria=["存在可核验的核心业务交付"],
        priority="high",
    ))
    assessments = list(result.fulfillment_assessments or [])
    assessments.append(FulfillmentAssessment(
        expectation_id=expectation_id,
        status="not_fulfilled",
        actual_evidence=[reason],
        downstream_impact="缺失 blocking 核心交付",
    ))
    result.business_expectations = expectations
    result.fulfillment_assessments = assessments


_LEGAL_AUTHORITY_OFF_NE = ("输入坏", "完全无关")
_ILLEGAL_AUTHORITY_OFF_NE = ("职责外", "依据不充分")


def _assessment_evidence_text(assessment: Any) -> str:
    parts: list[str] = []
    evidence = (
        assessment.get("actual_evidence")
        if isinstance(assessment, dict)
        else getattr(assessment, "actual_evidence", None)
    )
    if isinstance(evidence, (list, tuple)):
        parts.extend(str(item) for item in evidence)
    elif evidence:
        parts.append(str(evidence))
    return "".join(parts)


def _legal_authority_off_ne(assessment: Any) -> bool:
    text = _assessment_evidence_text(assessment)
    if any(marker in text for marker in _ILLEGAL_AUTHORITY_OFF_NE):
        return False
    return any(marker in text for marker in _LEGAL_AUTHORITY_OFF_NE)


def fail_closed_authority_off_judge_result(
    spec: ProjectSpec, result: JudgeResult
) -> JudgeResult:
    """Authority-off: remap illegal NE (职责外/依据不充分) to NF.

    fulfilled.md §3.1 still allows 输入坏 / 完全无关 / actual-trace 不可得.
    """
    if _authority_enabled(spec):
        return result

    abort = _evidence_marks_judge_abort(result)
    if not abort:
        for assessment in result.fulfillment_assessments or []:
            if _item_status(assessment) == "not_evaluable" and not _legal_authority_off_ne(assessment):
                _set_item_status(assessment, "not_fulfilled")

    empty = not list(result.fulfillment_assessments or [])
    overall = dict(result.overall_fulfillment or {})
    derived = _derive_overall_status(
        list(result.business_expectations or []),
        list(result.fulfillment_assessments or []),
    )
    has_legal_ne = any(
        _item_status(item) == "not_evaluable" and _legal_authority_off_ne(item)
        for item in (result.fulfillment_assessments or [])
    )
    # LLM/tool abort is not a business NF. Empty assessments stay not_evaluable.
    if abort:
        derived = _derive_overall_status(
            list(result.business_expectations or []),
            list(result.fulfillment_assessments or []),
        )
        if derived == "not_fulfilled":
            derived = "not_evaluable"
    elif empty:
        _attach_missing_core_delivery_nf(result, reason="missing blocking core delivery")
        derived = _derive_overall_status(
            list(result.business_expectations or []),
            list(result.fulfillment_assessments or []),
        )
    elif derived == "not_evaluable" and not has_legal_ne:
        _attach_missing_core_delivery_nf(
            result, reason="missing blocking core delivery"
        )
        derived = _derive_overall_status(
            list(result.business_expectations or []),
            list(result.fulfillment_assessments or []),
        )
        if derived == "not_evaluable":
            derived = "not_fulfilled"

    overall["status"] = derived
    overall["assessment_count"] = len(result.fulfillment_assessments or [])
    overall["blocking_expectations"] = [
        str(item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", "") or "")
        for item in (result.business_expectations or [])
        if bool(item.get("blocking") if isinstance(item, dict) else getattr(item, "blocking", False))
    ]
    result.overall_fulfillment = overall
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def build_judge_evidence_view(trace: RunTrace) -> Dict[str, Any]:
    """把完整 RunTrace 确定性投影为 Judge 可消费的业务事实。

    Judge 的事实源是 RunTrace，但不直接解释 adapter 私有路径或状态机内部结构。
    raw_response 只在输出缺失或执行失败时作为补充证据暴露。
    """
    raw_extracted_output = getattr(trace, "extracted_output", None)
    final_output = trace_extracted_output(trace)
    actual_state = (
        "unavailable"
        if raw_extracted_output is None
        else "empty"
        if final_output in ({}, [], "")
        else "available"
    )
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
        "actual_state": actual_state,
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


_FULFILLMENT_STATUS_VOCAB = {"fulfilled", "not_fulfilled", "not_evaluable"}


def _judge_self_check(
    data: Dict[str, Any],
    business_expectations: list,
    *,
    require_expected: bool = False,
    capability_fields: Optional[Set[str]] = None,
    status_vocab: Optional[Set[str]] = None,
) -> list[Dict[str, Any]]:
    """Detect fulfillment inconsistencies before constructing JudgeResult."""
    vocab = set(status_vocab) if status_vocab is not None else set(_FULFILLMENT_STATUS_VOCAB)
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
        if status and status not in vocab:
            inconsistencies.append({
                "kind": "status_off_vocabulary",
                "where": f"fulfillment_assessments[{index}].status",
                "value": status,
                "expected": "|".join(sorted(vocab)),
            })
        call_ids = [
            str(call_id)
            for call_id in item.get("authority_tool_call_ids") or []
        ]
        if any(not call_id.strip() for call_id in call_ids):
            inconsistencies.append({
                "kind": "empty_authority_tool_call_id",
                "where": (
                    f"fulfillment_assessments[{index}].authority_tool_call_ids"
                ),
                "value": call_ids,
                "expected": (
                    "authority_tool_call_ids entries must be non-empty "
                    "tool_call_id strings; Core 后处理会校验引用存在与 resolution"
                ),
            })
    for expectation_id in sorted(valid_ids - assessment_ids):
        inconsistencies.append({
            "kind": "missing_fulfillment_assessment",
            "where": "fulfillment_assessments",
            "expectation_id": expectation_id,
        })
    if require_expected and business_expectations and not data.get("expected"):
        inconsistencies.append({
            "kind": "missing_expected_reference",
            "where": "expected",
            "detail": (
                "business_expectations 非空时必须提供 expected（自产 reference），"
                "否则无法比对 actual。"
            ),
        })
    if capability_fields:
        expected = data.get("expected")
        if isinstance(expected, dict):
            expected_conditions = expected.get("conditions") or expected.get("structured_output") or []
            if isinstance(expected_conditions, list):
                for index, condition in enumerate(expected_conditions):
                    if not isinstance(condition, dict):
                        continue
                    field = str(condition.get("field") or "").strip()
                    if field and field not in capability_fields:
                        inconsistencies.append({
                            "kind": "expected_field_outside_capability_manifest",
                            "where": f"expected.conditions[{index}].field",
                            "value": field,
                            "expected": (
                                (
                                    "expected 只能引用 capability_manifest 内的字段；"
                                    "清单外维度的能力/职责归属必须先经 authority.resolve 裁决"
                                    "（authority.md §8.1/§8.2），不得用清单外伪字段构造期望，"
                                    "也不得自行断定“职责外→not_evaluable”"
                                )
                                if "not_evaluable" in vocab
                                else (
                                    "expected 只能引用 capability_manifest 内的字段；"
                                    "不得用清单外伪字段构造期望"
                                )
                            ),
                        })
    return inconsistencies


def judge_trace(
    spec: ProjectSpec,
    trace: RunTrace,
    user_intent: Optional[str] = None,
    llm: Optional[LlmClient] = None,
    project_judge_context: Optional[Dict[str, Any]] = None,
    has_actual: bool = True,
    has_reference: bool = False,
) -> JudgeResult:
    """judge 判定入口（Draft 单次 agentic 会话，方案 i）。

    authority.md §8：`authority.resolve` 是 Judge Tool，调用记录进 Tool audit；
    Core 后处理按 assessment 的 `authority_tool_call_ids` 校验引用并消费 resolution
    （unresolved → not_evaluable；引用不存在 → needs_human_review；resolved → 不覆盖）。
    spec/info-volume.md 后只产 fulfillment + expected/actual + gaps，不再产 verdict。
    """
    from impl.core.context.project import load_role_mandatory_context

    authority_enabled = _authority_enabled(spec)
    status_vocab = set(_FULFILLMENT_STATUS_VOCAB)

    mandatory_context = load_role_mandatory_context(
        spec,
        role="judge",
        operation="judge",
        trace_id=str(trace.trace_id or ""),
        run_id="judge-main",
        case_id=str(getattr(trace, "case_id", "") or ""),
        phase="planning",
    )
    migrated_context = mandatory_context is not None
    evaluation = "" if migrated_context else load_project_document(spec, "evaluation")
    boundary_standard = load_judge_boundary_standard(spec)
    judge_boundary = "" if migrated_context else load_project_document(spec, "judge_boundary")
    judge_standard = "" if migrated_context else load_project_document(spec, "judge_standard")
    governance_config = dict(
        (project_judge_context or {}).get("context_governance") or {}
    )
    if not governance_config:
        from impl.core.context_governance import role_governance_config
        governance_config = role_governance_config(
            spec,
            role="judge",
            stage="judge",
            trace_id=str(trace.trace_id or ""),
            case_id=str(getattr(trace, "case_id", "") or ""),
            compiler_source="impl/projects/client_search/judge_execution.py#judge_trace",
            user_source="trace://judge-evidence-view",
        )
    else:
        governance_config.setdefault("trace_id", str(trace.trace_id or ""))
        governance_config.setdefault("case_id", str(getattr(trace, "case_id", "") or ""))
    excluded_markers = list(governance_config.get("excluded_clause_markers") or [])
    if excluded_markers:
        from impl.core.context_governance import slice_context_clauses
        excluded_segments = list(governance_config.get("excluded_segments") or [])
        evaluation, excluded = slice_context_clauses(
            evaluation,
            source="project://evaluation",
            excluded_markers=excluded_markers,
        )
        excluded_segments.extend(excluded)
        judge_boundary, excluded = slice_context_clauses(
            judge_boundary,
            source="project://judge_boundary",
            excluded_markers=excluded_markers,
        )
        excluded_segments.extend(excluded)
        judge_standard, excluded = slice_context_clauses(
            judge_standard,
            source="project://judge_standard",
            excluded_markers=excluded_markers,
        )
        excluded_segments.extend(excluded)
        if mandatory_context is not None:
            mandatory_source = "contextunit://" + ",".join(
                mandatory_context.get("unit_ids") or []
            )
            projected_content, excluded = slice_context_clauses(
                mandatory_context["content"],
                source=mandatory_source,
                excluded_markers=excluded_markers,
            )
            mandatory_context = {
                **mandatory_context,
                "content": projected_content,
            }
            excluded_segments.extend(excluded)
        governance_config["excluded_segments"] = excluded_segments

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
        if authority_enabled:
            system += (
                "## 输出词表\n"
                "`fulfillment_assessments[*].status` 必须从以下 3 个值中选择：\n"
                "  - fulfilled：该 expectation 完全满足\n"
                "  - not_fulfilled：该 expectation 未满足\n"
                "  - not_evaluable：当前无法评估\n"
                "禁用 failed/passed/incorrect/wrong/met/unmet/partially_fulfilled/partial/success/fail/ok/unknown 等同义词。\n"
                "`actual_state=empty` 表示 Live 成功返回但没有交付明确业务结果；"
                "对本应交付的 expectation 通常判定 not_fulfilled。"
                "`actual_state=unavailable` 表示无法取得或确认 Live actual；通常判定 not_evaluable。\n"
                "`fulfillment_assessments[*].expected_evidence` 与 `actual_evidence` **必须是数组**（JSON array / list），"
                "即使只有一条证据也要用 `[...]` 包裹，不可直接用字符串或对象。\n\n"
                "不要输出 overall_fulfillment；公共层会在项目契约补充完成后根据 blocking expectations 确定性派生整体状态。\n\n"
            )
        else:
            system += (
                "## 输出词表\n"
                "`fulfillment_assessments[*].status` 必须从以下 2 个值中选择：\n"
                "  - fulfilled：该 expectation 完全满足\n"
                "  - not_fulfilled：该 expectation 未满足\n"
                "禁用 failed/passed/incorrect/wrong/met/unmet/partially_fulfilled/partial/success/fail/ok/unknown 等同义词。\n"
                "`actual_state=empty` 表示 Live 成功返回但没有交付明确业务结果；"
                "对本应交付的 expectation 通常判定 not_fulfilled。"
                "`actual_state=unavailable` 表示无法取得或确认 Live actual；不得标 fulfilled；"
                "若用户要的是一个结果，按 not_fulfilled 处理。\n"
                "`fulfillment_assessments[*].expected_evidence` 与 `actual_evidence` **必须是数组**（JSON array / list），"
                "即使只有一条证据也要用 `[...]` 包裹，不可直接用字符串或对象。\n\n"
                "不要输出 overall_fulfillment；公共层会在项目契约补充完成后根据 blocking expectations 确定性派生整体状态。\n\n"
            )
    system += (
        f"## 评估规范\n{evaluation}\n\n"
        f"## 评估边界\n{judge_boundary}\n\n"
        f"## 判断标准\n{judge_standard}\n\n"
    )
    if mandatory_context is not None:
        system += (
            "## 项目 ContextUnit（按 Role policy 在运行前确定性装载）\n"
            f"{mandatory_context['content']}\n\n"
        )

    system_extras = []
    if project_judge_context:
        raw_extras = project_judge_context.get("system_prompt_extras")
        if isinstance(raw_extras, str) and raw_extras.strip():
            system_extras.append(raw_extras.strip())
        elif isinstance(raw_extras, list):
            system_extras.extend(str(item).strip() for item in raw_extras if str(item).strip())
    system_extras_appendix = ""
    if system_extras:
        system_extras_appendix = "\n\n" + "\n\n".join(system_extras) + "\n"
        system += system_extras_appendix

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
        )

    system += (
        "## 工具使用原则\n"
        "工具如何调用以 Agno tool schema 为准。"
        "user prompt 中塞入的 capability_manifest / value_mappings / semantic_equivalence_rules / enhanced_rules 只是导航线索，不是 Evidence。"
        "口语别名、枚举归属、is_supported 必须经 investigation.search_index 后再 investigation.load_entry 取得；"
        "SearchHit 不是 Evidence，也不是同义证明。"
        "用户请求能在 Catalog 中导航时，先 Search→Load；未命中则保持沉默，依据用户意图与 Live 交付及已 Load 事实判断。\n\n"
        "## 禁止事项\n"
        "- 不要把 reference answer 当作默认主目标（除非 case 明确指定）\n"
        "- 不要把 HTTP 状态、run_status、attribute/cluster 结论当作满足依据\n"
        "- 不要归因内部代码、配置或 prompt 原因（属于 attribute agent）\n"
        "- Authority 的唯一运行时引用字段是 fulfillment_assessments[].authority_tool_call_ids；"
        "其中每个 ID 都必须来自本次 trace 中真实完成的 authority.resolve 调用，禁止自造。\n"
        "- 只输出结构化 schema 中声明的字段；不要自行增加未声明的历史/元数据字段。\n"
        "- 分析文字必须使用中文，包括 reasoning_summary 等所有文本字段。\n"
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
        from impl.core.llm_client import project_llm_client
        client = project_llm_client(
            spec,
            role="judge",
            knowledge=None,
            tools=tools,
            tool_call_limit=(project_judge_context or {}).get(
                "tool_call_limit"
            ),
        )
    else:
        client = llm
    client._caller = "judge"

    has_reference = _has_input_reference(trace)
    output_spec = _build_judge_output_spec(has_actual, project_id=spec.project_id, has_reference=has_reference)

    if governance_config:
        governance_config["base_user_char_count"] = len(user)
        governance_segments = list(governance_config.get("segments") or [])
        for segment_id, source, content in (
            ("project-evaluation", "project://evaluation", evaluation),
            ("project-judge-boundary", "project://judge_boundary", judge_boundary),
            ("project-judge-standard", "project://judge_standard", judge_standard),
        ):
            if content:
                governance_segments.append({
                    "segment_id": segment_id,
                    "source": source,
                    "content": content,
                })
        if mandatory_context is not None:
            governance_segments.append({
                "segment_id": "mandatory-context-units",
                "source": "contextunit://" + ",".join(mandatory_context.get("unit_ids") or []),
                "content": mandatory_context["content"],
            })
        governance_config["segments"] = governance_segments
        from impl.core.context_governance import (
            ContextGovernanceBlocked,
            configure_context_governance,
        )
        try:
            governance_report = configure_context_governance(
                client,
                config=governance_config,
                project_id=spec.project_id,
                system=system,
                user=user,
                output_spec=output_spec,
                tools=tools,
            )
        except ContextGovernanceBlocked as exc:
            if project_judge_context is not None:
                project_judge_context["context_governance_report"] = exc.report
            raise
        if project_judge_context is not None:
            project_judge_context["context_governance_report"] = governance_report

    try:
        data = client.complete_json(
            system,
            user,
            trace_id=trace.trace_id,
            output_spec=output_spec,
            stage="judge",
        )
    except ValueError as exc:
        logger.warning(f"[judge] enforce 阻断，触发 reprompt: {exc}")
        reprompt_inconsistencies = [{"kind": "enforce_blocked", "where": "structured_output", "detail": str(exc)}]
        data = _reprompt_judge(client, system, user, {}, reprompt_inconsistencies, trace.trace_id, output_spec=output_spec)
        if data.get("error"):
            return fail_closed_authority_off_judge_result(
                spec, _minimal_honest_judge_result(spec, trace, data)
            )
    if data.get("error"):
        return fail_closed_authority_off_judge_result(
            spec, _minimal_honest_judge_result(spec, trace, data)
        )

    from impl.projects.client_search.live import capability_manifest as _capability_manifest

    capability_fields = set()
    manifest_data = _capability_manifest(spec)
    if isinstance(manifest_data, dict):
        capability_fields = set(str(key) for key in manifest_data.keys())
    business_expectations = list(data.get("business_expectations") or [])
    inconsistencies = _judge_self_check(
        data,
        business_expectations,
        require_expected=not _has_input_reference(trace),
        capability_fields=capability_fields,
        status_vocab=status_vocab,
    )
    if inconsistencies:
        data = _reprompt_judge(client, system, user, data, inconsistencies, trace.trace_id, output_spec=output_spec)
        business_expectations = list(data.get("business_expectations") or [])
        inconsistencies = _judge_self_check(
            data,
            business_expectations,
            require_expected=not _has_input_reference(trace),
            capability_fields=capability_fields,
            status_vocab=status_vocab,
        )
        if inconsistencies:
            data["reasoning_summary"] = (data.get("reasoning_summary") or "") + f" [self_check_failed: {json.dumps(inconsistencies, ensure_ascii=False)}]"

    # 适用性判断交回单次 Judge LLM：空 business_expectations 是"业务不适用"的
    # 显式声明（reasoning_summary 须写明不适用原因），不再由确定性投影短路。
    if not business_expectations:
        if _trace_has_parsed_conditions(trace):
            # 兜底：actual 已成功解析出客户搜索条件，却声明"业务不适用"，
            # 属于适用性误拒。reprompt 一次让其基于 actual 重新派生评估点。
            applicability_conflict = [{
                "kind": "applicability_misjudged_with_parsed_conditions",
                "where": "business_expectations",
                "detail": (
                    "RunTrace actual 已成功解析出客户搜索条件，当前请求明显属于 "
                    "find-target-customers 场景；不得声明业务不适用或输出空数组。"
                    "请基于 actual 重新派生非空 business_expectations 与 "
                    "fulfillment_assessments。"
                ),
            }]
            data = _reprompt_judge(
                client,
                system,
                user,
                data,
                applicability_conflict,
                trace.trace_id,
                output_spec=output_spec,
            )
            business_expectations = list(data.get("business_expectations") or [])
            if not business_expectations:
                return fail_closed_authority_off_judge_result(
                    spec, _applicability_conflict_judge_result(spec, trace, data)
                )
            inconsistencies = _judge_self_check(
                data,
                business_expectations,
                require_expected=not _has_input_reference(trace),
                capability_fields=capability_fields,
                status_vocab=status_vocab,
            )
            if inconsistencies:
                data["reasoning_summary"] = (
                    str(data.get("reasoning_summary") or "")
                    + f" [self_check_failed: {json.dumps(inconsistencies, ensure_ascii=False)}]"
                )
        else:
            return fail_closed_authority_off_judge_result(
                spec,
                _not_applicable_judge_result(
                    spec,
                    trace,
                    reason=str(data.get("reasoning_summary") or ""),
                ),
            )

    result = _build_judge_result_from_data(spec, trace, data, user_intent, boundary_standard)

    # §8：消费 authority.resolve Tool audit —— 校验引用、按 resolution 改写状态。
    # audit 为空也要跑 gate：assessment 引用 audit 之外的 tool_call_id 必须
    # needs_human_review，不能因为"没有调用记录"而静默放行。
    authority_tool = (project_judge_context or {}).get("authority_tool")
    if authority_tool is not None:
        tool_audit = dict(getattr(authority_tool, "audit", None) or {})
        result = apply_authority_gate(result, tool_audit)
        authority_env = getattr(authority_tool, "_env", None)
        # 审计证据：tool_call_ids=现场 authority.resolve 调用（唯一可审计引用形态）。
        result.evidence = list(result.evidence or []) + [{
            "source": "authority_runtime",
            "environment_snapshot_sha256": (
                getattr(authority_env, "environment_snapshot_sha256", "")
                if authority_env is not None
                else ""
            ),
            "tool_call_ids": sorted(authority_tool.audit.keys()),
        }]
    return fail_closed_authority_off_judge_result(spec, result)


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
    from impl.core.project_loader import load_adapter
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
    from impl.core.context_governance import compact_reprompt_previous_values
    previous_values = compact_reprompt_previous_values(data, inconsistencies)
    appendix = (
        "\n\n## 上次输出存在不一致\n"
        + json.dumps(inconsistencies, ensure_ascii=False)
        + "\n## 仅供修复的上次字段值\n"
        + json.dumps(previous_values, ensure_ascii=False)
        + "\n请仅按错误路径修正，并重新输出符合唯一 schema 的完整 JSON；"
        "未列出的字段按原任务重新生成，不要复述上次输出。"
    )
    reprompt_user = user + appendix
    governance_config = dict(
        getattr(client, "_context_governance_config", {}) or {}
    )
    if governance_config and output_spec is not None:
        from impl.core.context_governance import configure_context_governance
        configure_context_governance(
            client,
            config=governance_config,
            project_id=str(getattr(client, "_project_id", "") or ""),
            system=system,
            user=reprompt_user,
            output_spec=output_spec,
            tools=list(
                getattr(client, "_context_governance_tools", None)
                or getattr(client, "tools", [])
                or []
            ),
            reprompt=True,
        )
    return client.complete_json(
        system,
        reprompt_user,
        trace_id=trace_id,
        output_spec=output_spec,
        stage="judge-reprompt",
    )


def _build_judge_output_spec(has_actual: bool, project_id: str = "", has_reference: bool = False) -> StructuredOutputSpec:
    """构造 judge 调用的结构化输出约束。spec/info-volume.md 后只约束通用字段。

    project_override: 项目级 schema 覆写，支持项目扩展 FulfillmentAssessment 字段。
    """
    nested: Dict[str, StructuredOutputSpec] = {}
    require_expected = not (has_actual and has_reference)
    if project_id and require_expected:
        try:
            from impl.core.mock_agent import load_live_schema
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

    # business_expectations 允许为空数组：空数组是 judge LLM 对"当前请求不属于
    # 本产品 use_scenario"的显式声明；适用性判断已交回单次 Judge LLM。
    # expected 在 business_expectations 非空时由 _judge_self_check 强制非空。
    required_nonempty = ["reasoning_summary"]
    if has_reference:
        description = "judge 判定输出（reference 已固化，仅产 fulfillment 判定）"
    else:
        description = "judge 判定输出（自产 reference + fulfillment 判定）"
    return StructuredOutputSpec.from_dataclass(
        JudgeLLMOutput,
        required_nonempty=required_nonempty,
        description=description,
        nested_schemas=nested,
    )


def _not_applicable_judge_result(
    spec: ProjectSpec, trace: RunTrace, *, reason: str = ""
) -> JudgeResult:
    """Return the public result for a request outside this product's scenario."""
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
        reasoning_summary=reason.strip() or (
            "当前请求不属于本项目已配置的 BusinessExpectation.use_scenario；"
            "因此没有生成评估点，本次业务不适用。"
        ),
        evidence=[{
            "source": "business_expectation_applicability",
            "status": "not_applicable",
            "cause": "完全无关",
            "trace_id": trace.trace_id,
        }],
    )
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def _trace_has_parsed_conditions(trace: RunTrace) -> bool:
    """True when the Live output already parsed customer-search conditions."""
    output = trace_extracted_output(trace) or {}
    if not isinstance(output, dict):
        return False
    for key in ("conditions", "structured_output"):
        value = output.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _applicability_conflict_judge_result(
    spec: ProjectSpec, trace: RunTrace, data: Dict[str, Any]
) -> JudgeResult:
    """确定性兜底：LLM 两次未派生评估点，但 actual 已解析出搜索条件。

    请求明显属于 find-target-customers 场景，不能以“业务不适用”零评估点判定；
    但也不能整体 not_evaluable 抹掉已可确认的部分。按第一性原理拆两层：
      1. 已解析条件（actual 真实产出的 conditions/structured_output）→ 每个
         条件派生一个 blocking 期望，actual 包含该条件即有证据判 fulfilled；
      2. 请求其余维度（LLM 未能评估的部分）→ blocking not_evaluable，理由写清
         “差在哪儿”（缺料清单），路由回调查层补证，而不是在判定层反复 NE。
    整体由 _derive_overall_status 按 blocking 期望确定性聚合：已解析部分 fulfilled
    + 其余维度 NE → 整体 not_evaluable。这是通用机制，不写死任何 case。
    """
    output = trace_extracted_output(trace)
    if not isinstance(output, dict):
        output = {}
    conditions: List[Dict[str, Any]] = []
    for key in ("conditions", "structured_output"):
        value = output.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and str(entry.get("field") or "").strip():
                    conditions.append(entry)

    business_expectations: List[BusinessExpectation] = []
    fulfillment_assessments: List[FulfillmentAssessment] = []
    evidence: List[Dict[str, Any]] = [{
        "source": "business_expectation_applicability",
        "status": "conflict_with_parsed_conditions",
        "trace_id": trace.trace_id,
        "judge_reasoning": str(data.get("reasoning_summary") or ""),
    }]
    for cond in conditions:
        field = str(cond.get("field") or "").strip()
        value = cond.get("value")
        operator = str(cond.get("operator") or "MATCH")
        expectation_id = f"正确提取{field}"
        business_expectations.append(BusinessExpectation(
            expectation_id=expectation_id,
            blocking=True,
            downstream_consumer="下游ES客户搜索",
            user_intent=f"用户请求中指定了 {field}={value} 的检索条件",
            expected_outcome=f"parser 应提取 {field} 字段，值为 {value}，操作符为 {operator}",
            acceptance_criteria=[
                f"actual conditions 包含 {field} 字段",
                f"值为 {value}",
                f"操作符为 {operator}",
            ],
            priority="high",
        ))
        fulfillment_assessments.append(FulfillmentAssessment(
            expectation_id=expectation_id,
            status="fulfilled",
            actual_evidence=[f"actual conditions: {json.dumps(cond, ensure_ascii=False)}"],
            downstream_impact="已解析条件可由下游搜索执行，该维度用户要的事已确认办成",
        ))

    residual_id = "请求其余维度评估"
    business_expectations.append(BusinessExpectation(
        expectation_id=residual_id,
        blocking=True,
        downstream_consumer="完整请求意图",
        user_intent="请求中除已解析条件外的其余维度",
        expected_outcome="请求中除已解析条件外的其余维度得到可核验的评估",
        acceptance_criteria=["存在对请求其余维度的可核验评估"],
        priority="high",
    ))
    fulfillment_assessments.append(FulfillmentAssessment(
        expectation_id=residual_id,
        status="not_evaluable",
        actual_evidence=[
            f"judge_reasoning: {str(data.get('reasoning_summary') or '').strip() or '（空）'}",
            "缺料：请求其余维度的职责边界/能力证据（authority 调查未登记 resolved 裁决，"
            "需按 spec/alg/investigate-authority-judge.md 补证后回填）",
        ],
        downstream_impact=(
            "LLM 两次未能派生评估点，除已解析条件外的其余请求维度未评估；"
            "属于“依据不充分”类说不清，缺料清单已记录，路由回调查层补证，"
            "不允许在判定层反复 not_evaluable"
        ),
    ))

    blocking_expectation_ids = [
        str(item.expectation_id)
        for item in business_expectations
        if item.blocking
    ]
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        business_expectations=business_expectations,
        fulfillment_assessments=fulfillment_assessments,
        overall_fulfillment={
            "status": "not_evaluable",
            "assessment_count": len(fulfillment_assessments),
            "blocking_expectations": blocking_expectation_ids,
        },
        actual=output,
        reasoning_summary=(
            "适用性判定冲突：actual 已成功解析出客户搜索条件，但 Judge 声明业务不适用"
            "并输出空评估点。确定性兜底：已解析条件按实际产出逐项评估为 fulfilled；"
            "请求其余维度保持 not_evaluable（依据不充分，缺料清单见 evidence），"
            "整体不置为业务不适用，也不整体抹成说不清。"
        ),
        evidence=evidence,
    )
    result.overall_fulfillment["status"] = _derive_overall_status(
        business_expectations, fulfillment_assessments
    )
    result.summary = summary_from_fulfillment(to_dict(result))
    return normalize_judge_result(result) or result

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
    raw_extracted = getattr(trace, "extracted_output", None)
    actual = raw_extracted if raw_extracted is not None else data.get("actual")

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
