from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set

from .llm_client import LlmClient, project_llm_client
from .project_loader import load_project_document, load_field_provider
from .schema import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeLLMOutput, JudgeReferenceOutput, JudgeResult, ProjectSpec, RunTrace, _non_empty_reference, normalize_business_expectation, normalize_fulfillment_assessment, normalize_gap_item, normalize_judge_result, to_dict, trace_application_boundary, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_raw_response
from .structured_output import StructuredOutputSpec
from .summary import summary_from_fulfillment

logger = logging.getLogger(__name__)


_FIELD_LIST_KEYS = frozenset(["conditions", "structured_output"])

# spec/struct_output.md：judge 输出形状定义迁移到 impl/core/schema/judge.py 的
# JudgeLLMOutput / JudgeReferenceOutput dataclass，由 StructuredOutputSpec 提取 JSON Schema。
# 旧占位符 dict（_JUDGE_OUTPUT_SCHEMA / _judge_reference_only_output_schema）已删除，避免双真相源。


def _extract_fields_from_trace(trace: RunTrace) -> Set[str]:
    """Extract all field names mentioned in trace input, output, and reference.

    只做通用的结构化字段提取（list-of-dict 且 entry 含 field key），
    项目特有的字段命名模式由 project_judge_context["field_extraction_patterns"]
    提供，核心 judge 不硬编码 Age/Sex/Num 这类业务字段。
    """
    fields = set()

    # Extract from output - RunTrace only has extracted_output, no 'output' attribute
    output = trace_extracted_output(trace) if trace_extracted_output(trace) else {}
    if isinstance(output, dict):
        for key in _FIELD_LIST_KEYS:
            if key in output and isinstance(output[key], list):
                for entry in output[key]:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])

    # Extract from reference contract.
    reference = trace.reference_contract or (trace.input.get("reference") if isinstance(trace.input, dict) else None)
    if isinstance(reference, dict):
        for key, value in reference.items():
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])

    # 项目特有的字段命名模式（如 "字段A.age" 这类带点的键、或自定义后缀）通过
    # project_judge_context 注入，不在这里硬编码。
    return fields





# 上下文工程（demand/context.md §2.2 L2）：judge 只需要 RunTrace 中 LLM 实际消费的字段。
# to_dict(trace) 会把整个 RunTrace（含 live_result）全量序列化，而 live_result 与顶层
# raw_response/extracted_output/normalized_request/execution_trace 完全重复（见 trace 量化：
# 150 条 judge trace 平均 37.5% 的 user prompt 是 live_result 冗余）。
# 这里只保留 judge 真正消费的字段：核心事实 + 边界 + 元信息，去掉 live_result/state_history/
# gate_decisions/transition_decisions/conversation_* 等 LLM 用不到的字段。

# raw_response 截断上限（字符）。marketting-planning 的 raw_response 是 51KB 的 SSE 事件流，
# judge 只需最终 extracted_output + 关键事件摘要，原始 SSE 流全量注入会让 judge prompt 撑爆
# 40k 预算。超过上限时截断并保留首尾，标注 truncated。
_JUDGE_RAW_RESPONSE_MAX_CHARS = 4000


def _compact_raw_response_for_judge(raw_response: Any) -> Any:
    """Compress raw_response for judge prompt.

    Judge only needs the final structured output (already in extracted_output) and
    a small sample of raw events for context. Full SSE streams / huge raw payloads
    are truncated to stay within budget. Dict/list structure is preserved so the
    judge can still navigate keys; only oversized string leaves are truncated.
    """
    if raw_response is None:
        return None
    if isinstance(raw_response, str):
        if len(raw_response) <= _JUDGE_RAW_RESPONSE_MAX_CHARS:
            return raw_response
        head = _JUDGE_RAW_RESPONSE_MAX_CHARS // 2
        return raw_response[:head] + f"...[truncated {len(raw_response) - _JUDGE_RAW_RESPONSE_MAX_CHARS:,} chars]..." + raw_response[-head:]
    if isinstance(raw_response, dict):
        # marketing-planning stores raw SSE under "raw" key — truncate that leaf only
        result = {}
        for k, v in raw_response.items():
            if k == "raw" and isinstance(v, str) and len(v) > _JUDGE_RAW_RESPONSE_MAX_CHARS:
                head = _JUDGE_RAW_RESPONSE_MAX_CHARS // 2
                result[k] = v[:head] + f"...[truncated {len(v) - _JUDGE_RAW_RESPONSE_MAX_CHARS:,} chars]..." + v[-head:]
            else:
                result[k] = v
        return result
    return raw_response


def _judge_run_trace_view(trace: RunTrace) -> Dict[str, Any]:
    """Compact RunTrace view for judge prompt: drops live_result (duplicates top-level
    fields) and other fields judge never consumes. Uses accessors so live_result is
    still the fallback when top-level fields are empty."""
    return {
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "case_id": trace.case_id,
        "input": trace_input(trace),
        "normalized_request": trace_normalized_request(trace),
        "raw_response": _compact_raw_response_for_judge(trace_raw_response(trace)),
        "extracted_output": trace_extracted_output(trace),
        "execution_trace": trace_execution_trace(trace),
        "evidence_refs": to_dict(getattr(trace, "evidence_refs", None) or []),
        "application_boundary": trace_application_boundary(trace),
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "scenario": trace.scenario,
        "status": trace.status,
        "error": trace.error,
    }


def _extract_compact_capability_manifest(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract capability manifest entries for fields in trace.

    trace_fields 为空（reference 模式无 actual）时退化为全量 manifest，
    让 reference 模式与判定模式共享同一套上下文来源。
    """
    if not project_judge_context or "capability_manifest" not in project_judge_context:
        return {}

    full_manifest = project_judge_context["capability_manifest"]
    if not isinstance(full_manifest, dict):
        return {}

    if not trace_fields:
        # reference 模式（无 actual）：全量 manifest，对齐判定模式可用的字段契约来源
        return dict(full_manifest)

    compact = {}
    for field in trace_fields:
        if field in full_manifest:
            compact[field] = full_manifest[field]

    return compact


def _extract_compact_semantic_rules(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract semantic equivalence rules for fields in trace.

    trace_fields 为空（reference 模式）时退化为全量规则。
    """
    if not project_judge_context or "semantic_equivalence_rules" not in project_judge_context:
        return {}

    full_rules = project_judge_context["semantic_equivalence_rules"]
    if not isinstance(full_rules, dict):
        return {}

    if not trace_fields:
        return dict(full_rules)

    compact = {}

    # Filter equivalent_condition_forms
    if "equivalent_condition_forms" in full_rules:
        compact["equivalent_condition_forms"] = [
            rule for rule in full_rules["equivalent_condition_forms"]
            if isinstance(rule, dict) and rule.get("field") in trace_fields
        ]

    # Filter operator_compatibility
    if "operator_compatibility" in full_rules:
        compact["operator_compatibility"] = [
            rule for rule in full_rules["operator_compatibility"]
            if isinstance(rule, dict) and rule.get("field") in trace_fields
        ]

    # Filter equivalent_fields
    if "equivalent_fields" in full_rules:
        compact["equivalent_fields"] = [
            rule for rule in full_rules["equivalent_fields"]
            if isinstance(rule, dict) and (
                rule.get("field") in trace_fields or
                rule.get("equivalent_field") in trace_fields
            )
        ]

    return compact


def _extract_compact_value_mappings(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract value_mappings entries for fields in trace.

    trace_fields 为空（reference 模式）时退化为全量映射。
    """
    if not project_judge_context or "value_mappings" not in project_judge_context:
        return {}

    full_mappings = project_judge_context["value_mappings"]
    if not isinstance(full_mappings, dict):
        return {}

    if not trace_fields:
        return dict(full_mappings)

    compact = {}
    for field in trace_fields:
        if field in full_mappings:
            compact[field] = full_mappings[field]
    return compact


def _extract_compact_enhanced_rules(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract enhanced_rules entries for fields in trace.

    trace_fields 为空（reference 模式）时退化为全量规则（仍受每字段 20 条上限约束，
    避免超大规则集撑爆 prompt）。

    Returns the full rule list for matching fields. For very large rule sets
    (e.g., 330KB source), this aggressively limits per-field rules to the first
    20 entries to stay within prompt budget. Composite rules (no field key) are
    included as-is since they represent cross-field patterns.
    """
    if not project_judge_context or "enhanced_rules" not in project_judge_context:
        return {}

    full_rules = project_judge_context["enhanced_rules"]
    if not isinstance(full_rules, dict):
        return {}

    compact = {}
    # Filter rules by trace_fields; trace_fields 为空时退化为全量
    for rule_key in ("rules", "composite_rules", "bare_value_weak_match"):
        raw = full_rules.get(rule_key)
        if not isinstance(raw, list):
            continue
        if rule_key == "composite_rules":
            compact[rule_key] = raw[:20]
            if len(raw) > 20:
                compact[f"{rule_key}_truncated"] = True
        elif not trace_fields:
            compact[rule_key] = raw[:20] if len(raw) > 20 else raw
            if len(raw) > 20:
                compact[f"{rule_key}_truncated"] = True
        else:
            filtered = [r for r in raw if isinstance(r, dict) and r.get("field") in trace_fields]
            if filtered:
                if len(filtered) > 20:
                    compact[rule_key] = filtered[:20]
                    compact[f"{rule_key}_truncated"] = True
                else:
                    compact[rule_key] = filtered

    # Include negation_words (always useful, small)
    negation = full_rules.get("negation_words")
    if isinstance(negation, list):
        compact["negation_words"] = negation
    return compact


def _extract_compact_field(
    project_judge_context: Optional[Dict[str, Any]],
    field_name: str,
) -> Any:
    """Extract a top-level field from project_judge_context."""
    if not project_judge_context:
        return None
    value = project_judge_context.get(field_name)
    if value is not None:
        return value
    # Fallback: check inside intent_frame
    intent_frame = project_judge_context.get("intent_frame")
    if isinstance(intent_frame, dict):
        return intent_frame.get(field_name)
    return None



def load_judge_boundary_standard(spec: ProjectSpec) -> Dict[str, Any]:
    implementation_standard = spec.frontend_extensions.get("implementation_standard") if spec.frontend_extensions else None
    boundary = implementation_standard.get("judge_boundary") if isinstance(implementation_standard, dict) else None
    if not isinstance(boundary, dict) or not boundary:
        raise ValueError(
            f"project {spec.id} missing implementation_standard.judge_boundary structured field"
        )
    return dict(boundary)


def _score_0_1(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value / 100 if value > 1 else value
    return value


_FULFILLMENT_STATUS_VOCAB = {
    "fulfilled", "not_fulfilled", "not_evaluable",
}


def _derive_overall_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_evaluable"
    if any(s == "not_fulfilled" for s in statuses):
        return "not_fulfilled"
    if any(s == "not_evaluable" for s in statuses):
        return "not_evaluable"
    return "fulfilled"


def _dict_value(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compute_verdict(overall_status: str, boundary_decision: Dict[str, Any]) -> str:
    """Single-point verdict derivation. LLM no longer outputs verdict."""
    if overall_status == "fulfilled":
        return "correct"
    if overall_status == "not_fulfilled":
        decision = boundary_decision or {}
        if decision.get("within_evaluable_scope") is False and not decision.get("evaluable_errors"):
            return "uncertain"
        return "incorrect"
    # not_evaluable / missing
    return "uncertain"


def _compute_score(fulfillment_assessments: list) -> Optional[float]:
    """Single-point score derivation. Score reflects fulfilled fraction of evaluable expectations."""
    assessments = [
        item for item in (fulfillment_assessments or [])
        if isinstance(item, dict) and item.get("status") in {"fulfilled", "not_fulfilled"}
    ]
    if not assessments:
        return None
    fulfilled = sum(1 for item in assessments if item.get("status") == "fulfilled")
    score = fulfilled / len(assessments)
    return float(score)


def _judge_self_check(data: Dict[str, Any], business_expectations: list) -> list[Dict[str, Any]]:
    """Detect fulfillment inconsistencies before computing verdict.

    Returns a list of inconsistency records; empty list means consistent.
    """
    inconsistencies: list[Dict[str, Any]] = []

    assessments = data.get("fulfillment_assessments") or []
    valid_ids = {
        str(item.get("expectation_id"))
        for item in (business_expectations or [])
        if isinstance(item, dict) and item.get("expectation_id")
    }

    statuses: list[str] = []
    for index, item in enumerate(assessments):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        statuses.append(status)
        if status and status not in _FULFILLMENT_STATUS_VOCAB:
            inconsistencies.append({
                "kind": "status_off_vocabulary",
                "where": f"fulfillment_assessments[{index}].status",
                "value": status,
                "expected": "|".join(sorted(_FULFILLMENT_STATUS_VOCAB)),
            })
        exp_id = item.get("expectation_id")
        if exp_id and valid_ids and str(exp_id) not in valid_ids:
            inconsistencies.append({
                "kind": "orphan_expectation_id",
                "where": f"fulfillment_assessments[{index}].expectation_id",
                "value": exp_id,
            })

    overall = data.get("overall_fulfillment") or {}
    if isinstance(overall, dict):
        overall_status = str(overall.get("status") or "").strip().lower()
        if overall_status and overall_status not in _FULFILLMENT_STATUS_VOCAB:
            inconsistencies.append({
                "kind": "status_off_vocabulary",
                "where": "overall_fulfillment.status",
                "value": overall_status,
                "expected": "|".join(sorted(_FULFILLMENT_STATUS_VOCAB)),
            })
        if overall_status and statuses:
            derived = _derive_overall_status(statuses)
            if derived != overall_status:
                inconsistencies.append({
                    "kind": "overall_status_mismatch",
                    "where": "overall_fulfillment.status",
                    "value": overall_status,
                    "derived": derived,
                })

    boundary_decision = data.get("boundary_decision") or {}
    if isinstance(boundary_decision, dict):
        if boundary_decision.get("within_evaluable_scope") is False and boundary_decision.get("evaluable_errors"):
            inconsistencies.append({
                "kind": "boundary_decision_contradiction",
                "where": "boundary_decision",
                "detail": "within_evaluable_scope=false but evaluable_errors is non-empty",
            })

    return inconsistencies



def _trace_reference(trace: RunTrace) -> Any:
    # 协议层 ready 声明式：仅当 trace 携带的 ready 快照声明 reference 就绪时才采信 trace 携带的 reference，
    # 否则返回 None 让 judge 自己生成 reference（client_search/mpi/mp 的 mock reference 不可信）。
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
    # trace.ready 是所有 trace 的必填字段（由 pipeline 从 spec.common.ready 注入），
    # 不存在"旧 trace 兼容"——缺少 ready 字段的一律报错。
    ready = getattr(trace, "ready", None)
    if ready is None:
        raise ValueError(
            f"trace.ready 字段缺失: trace_id={trace.trace_id}, project_id={trace.project_id}。"
            "所有 trace 必须携带 ready 快照，请确认 trace 由 pipeline.live_run 正常构建。"
        )
    return "reference" in ready


def _check_judge_reference_with_live_schema(trace: RunTrace, expected: Any) -> None:
    """judge 自生成 expected 时，校验是否符合 EXTRACT_OUTPUT_SHAPE。

    强约束：校验失败抛 ValueError，触发上层阻断/重试。
    spec/struct_output.md 后，结构校验由 complete_json 内部的 enforce_output 统一执行，
    此函数保留作为旧路径兜底，新路径不再调用。"""
    from .mock_agent import load_live_schema
    ls = load_live_schema(trace.project_id)
    if ls is not None and hasattr(ls, "check"):
        if isinstance(expected, dict):
            if not ls.check.reference(expected):
                raise ValueError(
                    f"judge 自生成的 expected 不符合 EXTRACT_OUTPUT_SHAPE: "
                    f"project={trace.project_id}, expected={json.dumps(expected, ensure_ascii=False)[:200]}"
                )


def _has_input_reference(trace: RunTrace) -> bool:
    return _trace_reference(trace) is not None


def _reference_generation_basis(trace: RunTrace, expected_intent: Optional[str], data: Dict[str, Any], expected: Any) -> Dict[str, Any]:
    provided = _trace_reference(trace)
    existing = data.get("reference_generation_basis")
    if isinstance(existing, dict) and existing:
        return existing
    if provided is not None:
        source = "ready_固化"
        evidence = ["reference 已由 judge 在 mock build 阶段按 live_schema 固化"]
    elif expected_intent:
        source = "expected_intent"
        evidence = ["expected_intent"]
    elif data.get("expected") is not None:
        source = "judge_自生成"
        evidence = ["judge expected"]
    else:
        source = "judge_自生成"
        evidence = ["run_trace input", "judge reasoning"]
    return {
        "source": source,
        "alignment_to_live_schema": "reference 形状来源是 live_schema.EXTRACT_OUTPUT_SHAPE，不按 actual 整形。",
        "evidence": evidence,
        "expected_present": expected is not None,
    }


def _source_documents(spec: ProjectSpec) -> Dict[str, str]:
    return {
        key: load_project_document(spec, key)
        for key in sorted(spec.documents)
        if key.startswith("source_") and key != "source_field_definitions"
    }


def judge_trace(
    spec: ProjectSpec,
    trace: RunTrace,
    expected_intent: Optional[str] = None,
    llm: Optional[LlmClient] = None,
    project_judge_context: Optional[Dict[str, Any]] = None,
    has_actual: bool = True,
    has_reference: bool = False,
) -> JudgeResult:
    """judge 判定入口。同一套 prompt 模板 + 条件块控制三模式：
    - 有 actual + 有 reference（ready 判定）：跳过 expected 生成段落
    - 有 actual + 无 reference（非 ready 判定）：含 expected 生成段落
    - 无 actual + 有意图（仅生成 reference）：只渲染 expected 生成段落
    """
    # Load core protocol documents (static, ~10k chars)
    evaluation = load_project_document(spec, "evaluation")
    boundary_standard = load_judge_boundary_standard(spec)
    judge_boundary = load_project_document(spec, "judge_boundary")
    judge_standard = load_project_document(spec, "judge_standard")

    # 提取 trace 中涉及的字段（仅 has_actual 时可从 actual output 提取）。
    # reference 模式（!has_actual）没有 actual output，trace_fields 为空 →
    # compact_* 随之为空。两种模式走同一套 compact 逻辑，区别只在 trace_fields 来源。
    # 项目级字段契约由 adapter.build_judge_context 提供，judge 核心不做项目分支。
    trace_fields = _extract_fields_from_trace(trace) if has_actual else set()

    # Build compact context: 对齐纯 reference 模式 ——
    # reference 模式 trace_fields 为空时，compact 退化为"全量 manifest"（不按字段过滤）。
    # 非 reference 模式（has_actual）保持按 trace_fields compact 的原行为。
    # 两种模式都用同一组 _extract_compact_* 函数，由 trace_fields 是否为空决定 compact 粒度。
    compact_capability = _extract_compact_capability_manifest(project_judge_context, trace_fields)
    compact_semantic_rules = _extract_compact_semantic_rules(project_judge_context, trace_fields)
    compact_value_mappings = _extract_compact_value_mappings(project_judge_context, trace_fields)
    compact_enhanced_rules = _extract_compact_enhanced_rules(project_judge_context, trace_fields)
    compact_critical_intent_dimensions = _extract_compact_field(project_judge_context, "critical_intent_dimensions")

    # Fallback: if pipeline-extracted expected_intent is None, try project_judge_context
    if not expected_intent and project_judge_context:
        expected_intent = project_judge_context.get("expected_intent") or (
            project_judge_context.get("intent_frame", {}).get("expected_intent")
            if isinstance(project_judge_context.get("intent_frame"), dict)
            else None
        )

    logger.info(f"[judge] Compact capability_manifest: {len(compact_capability)} fields")
    logger.info(f"[judge] Compact semantic_rules: {sum(len(v) if isinstance(v, list) else 0 for v in compact_semantic_rules.values())} rules")
    logger.info(f"[judge] Compact value_mappings: {len(compact_value_mappings)} fields")
    logger.info(f"[judge] Compact enhanced_rules: {len(compact_enhanced_rules)} fields")

    # Create field definition search tool (项目专属 provider + 通用协议)
    from impl.tools.field_retrieval import create_field_search_tool

    # Load project-specific field provider (动态加载，核心代码不对 project_id 分支)
    field_provider = None
    try:
        field_provider = load_field_provider(spec)
    except Exception as e:
        logger.warning(f"[judge] Failed to load field provider for {spec.project_id}: {e}")

    # Create tool if provider available
    field_search_tool = create_field_search_tool(field_provider) if field_provider else None

    # System prompt: 核心协议部分（所有项目通用，只讲 intent→expectations→fulfillment）
    system = (
        "你是通用评估系统的 judge agent。\n\n"
        "## 核心原则\n"
        "只基于当前 RunTrace、项目评判标准和动态检索的知识库内容判断，不继承历史 case。\n"
        "首要职责：先理解用户/下游消费者的真实业务意图 → 形成 intent_model → 从 intent_model 派生 business_expectations → "
        "判断 actual output 对 expectations 的 fulfillment。verdict 由代码单点推导，**你不要输出 verdict / score / confidence / probability**。\n\n"
        "## expectation 拆分原则（关键！影响判断精度）\n"
        "business_expectations 的粒度直接决定判断精度。每个 expectation 必须是**原子可判定**的——即仅凭 actual output 就能明确判定 fulfilled 或 not_fulfilled，无需再拆分。\n"
        "拆分规则：\n"
        "- 一个 expectation 只描述一个可独立验证的结果维度\n"
        "- 如果用户意图涉及多个维度，必须拆成多个 expectation，每个 expectation 对应一个维度\n"
        "- 拆分后的每个 expectation 必须有明确的 acceptance_criteria（可判定的通过/失败条件）\n"
        "- blocking_level 根据该维度对用户意图的必要性设定：核心需求=blocking，辅助需求=non-blocking\n"
        "- **每个 expectation 的 expectation_id 必须是描述性的中文短语**，禁止使用 E1/E2/exp_01 等占位符 ID\n"
        "- **fulfillment_assessments 中的 expectation_id 必须引用 business_expectations 中的描述性 expectation_id**，禁止使用占位符\n"
        "- **blocking_gaps 中的每项必须是描述性中文**，禁止出现 E1/E2/exp_01/exp-01 等占位符\n"
        "- **reasoning_summary / why_verdict 必须是中文写成的判断依据**，说明具体满足了/未满足哪些业务期望\n"
    )
    if has_actual:
        system += (
            "## 输出词表\n"
            "`fulfillment_assessments[*].status` 与 `overall_fulfillment.status` 必须从以下 3 个值中选择：\n"
            "  - fulfilled：该 expectation 完全满足\n"
            "  - not_fulfilled：该 expectation 未满足\n"
            "  - not_evaluable：当前无法评估\n"
            "禁用 failed / passed / incorrect / wrong / met / unmet / partially_fulfilled / partial / success / fail / ok / unknown / disputed / contested 等同义词。\n"
            "`boundary_decision.within_evaluable_scope=false` 必须满足：失败原因仅来自 `uncontrollable_limits`，且 `evaluable_errors` 为空数组。"
            "若存在任一 `evaluable_error`，则 `within_evaluable_scope` 必须为 `true`。\n"
            "你不输出 `verdict` / `score` / `confidence` / `probability`；这四个字段由代码从 fulfillment 域单点推导。\n\n"
        )
    system += (
        f"## 评估规范\n{evaluation}\n\n"
        f"## 评估边界\n{judge_boundary}\n\n"
        f"## 判断标准\n{judge_standard}\n\n"
    )

    # 项目结构化字段判断范式：仅当项目实际提供 capability_manifest / 规则时才注入，
    # 非结构化项目（QA / marketing-planning 等问答类）不会看到字段-操作符-值核对语义，
    # 避免把一个项目的判断范式当成通用范式塞进所有项目。
    has_field_contract = compact_capability or compact_semantic_rules or compact_value_mappings or compact_enhanced_rules
    if has_actual and has_field_contract:
        system += (
            "## 结构化字段判断范式（仅适用于提供 capability_manifest 的项目）\n"
            "user prompt 中的 capability_manifest 包含当前 case 涉及字段的完整能力清单。每个字段的 operators 列表定义了该字段允许的操作符；"
            "value_types 定义了值类型。判断 actual output 时，必须逐字段核对 capability_manifest：\n"
            "- 如果 actual 中某字段使用了不在其 operators 列表中的操作符 → 标记为 wrong\n"
            "- 如果 actual 中某字段的值类型与其 value_types 不匹配 → 标记为 wrong\n"
            "- 如果用户意图中的字段在 capability_manifest 中存在但 actual 完全未输出 → 标记为 missing\n"
            "- 如果 actual 输出了 capability_manifest 中不存在的字段 → 标记为 extra 或 not_verified\n\n"
            "## 语义等价规则（强制约束）\n"
            "user prompt 中的 semantic_equivalence_rules 定义了下游可执行的语义等价关系。在判定任何条目前，必须先检查 semantic_equivalence_rules：\n"
            "- equivalent_condition_forms：不同表面形式但语义等价的字段-操作符-值组合\n"
            "- operator_compatibility：在某些条件下互相兼容的操作符\n"
            "- equivalent_fields：表示同一业务含义的不同字段名\n"
            "如果条件满足等价规则，必须在 semantic_equivalence_checks 中说明，且不应判定为 wrong/missing。\n\n"
            "## 口语映射规则（如提供）\n"
            "user prompt 中的 value_mappings 包含用户口语别名到系统标准枚举值的映射关系（如'男性'→'男'、'重疾险'→'疾病保险'）。"
            "如果 actual output 使用了标准枚举值而非用户的口语表达，应视为正确映射，不应判 wrong 或 missing。\n\n"
            "## 增强正则规则（如提供）\n"
            "user prompt 中的 enhanced_rules 包含当前字段的 L2 正则匹配规则定义。如果 actual output 的条件符合 enhanced_rules 中的某个 pattern/operator/value_type 绑定，应视为与项目规则一致。\n\n"
        )

    # 意图关键维度（仅当项目提供时注入）
    if has_actual and compact_critical_intent_dimensions:
        system += (
            "## 意图关键维度（如提供）\n"
            "user prompt 中的 critical_intent_dimensions 定义了当前项目 judge 的评估维度轴，如 intent_label/required_slots/confidence_threshold/fallback_policy。"
            "请将这些维度作为分解 business_expectations 的骨架：每个维度拆为 1 个或多个 expectations，逐个评估。\n\n"
        )

    # 条件块：仅生成 reference 模式（无 actual）只渲染 expected 生成指令，不做 fulfillment 判定
    if not has_actual:
        # spec/struct_output.md：expected 的形状约束由 StructuredOutputSpec（JudgeReferenceOutput）统一承担，
        # 这里只保留语义指引，不再用 render_shape_constraint 拼占位符文案。
        system += (
            "## 仅生成 reference（expected）模式\n"
            "本次调用没有 actual output，你**只产 expected**（参考答案），不做 fulfillment 判定。\n"
            "你的 expected 是该输入下系统应当产出什么的标准答案，由你（评估侧，掌握全量系统信息）产出。\n\n"
            "### expected 的产出步骤\n"
            "1. 理解用户意图（run_trace.input / expected_intent / scenario）\n"
            "2. 结合项目评估文档（evaluation/judge_standard/judge_boundary）确定该场景下的标准答案应满足什么\n"
            "3. 派生 business_expectations，每条 expectation 的 expected_outcome 描述该输入下系统应当产出什么\n"
            "4. 把所有 expected_outcome 汇总成 expected 字段，按结构化输出约束的 JSON Schema 填入真实内容\n\n"
            "### 强约束\n"
            "- expected 字段必须非空——即使意图信息不完整，也要基于现有信息给出最合理的标准答案\n"
            "- 不要输出 fulfillment_assessments / overall_fulfillment / missing / wrong / extra / verdict 等判定域字段\n"
            "- 输出 JSON，只含 expected、business_expectations、reconstructed_intent、judge_basis、reference_generation_basis\n"
        )

    system += (
        "## 按需字段检索（可选）\n"
        "如果 user prompt 中的 capability_manifest 信息不足以判断，你可以调用 search_field_definition 工具：\n"
        "- 输入：字段名（如项目文档中的字段标识）\n"
        "- 返回：该字段的完整定义、操作符、值类型、示例\n"
        "- 注意：user prompt 中已提供当前 case 涉及字段的完整能力清单，优先使用！\n\n"
        "## 禁止事项\n"
        "- 不要输出 verdict / score / confidence / probability 字段（由代码单点推导）\n"
        "- 不要把 reference answer 当作默认主目标（除非 case 明确指定）\n"
        "- 不要把 HTTP 状态、run_status、review_verdict、attribute/cluster 结论当作满足依据\n"
        "- 不要归因内部代码、配置或 prompt 原因（属于 attribute agent）\n"
        "- 分析文字必须使用中文，包括 reasoning_summary、why_verdict、blocking_gaps 等所有文本字段。禁止使用英文撰写分析内容。\n"
        "- 输出 JSON。"
    )
    user_payload = to_dict({
        "capability_manifest": compact_capability,
        "semantic_equivalence_rules": compact_semantic_rules,
        "value_mappings": compact_value_mappings,
        "enhanced_rules": compact_enhanced_rules,
        "critical_intent_dimensions": compact_critical_intent_dimensions,
        "expected_intent": expected_intent,
        "run_trace": _judge_run_trace_view(trace) if has_actual else None,
    })
    if not has_actual:
        user_payload["run_trace"] = _judge_run_trace_view(trace)  # 保留 trace 中的 input 信息
        # spec/struct_output.md：expected 形状约束由 StructuredOutputSpec（JudgeReferenceOutput）承担。
        # 字段契约（capability_manifest 等）由项目 adapter 通过 project_judge_context 注入
        # 到 intent_frame / reference_generation_guidance 中，judge 核心不做项目分支。
        # 如果项目没有提供字段契约，reference 模式仍可基于 evaluation/judge_standard 文档
        # 和 expected 的 JSON Schema 约束产出合理的 expected。更精确的字段级指引由
        # search_field_definition 工具按需补充。
    user = json.dumps(user_payload, ensure_ascii=False)
    
    # Log prompt sizes for monitoring
    system_size = len(system)
    user_size = len(user)
    compact_capability_size = len(json.dumps(compact_capability, ensure_ascii=False))
    compact_semantic_size = len(json.dumps(compact_semantic_rules, ensure_ascii=False))
    logger.info(f"[judge] Prompt sizes: system={system_size:,} chars, user={user_size:,} chars, total={system_size + user_size:,} chars")
    logger.info(f"[judge] Compact context sizes: capability={compact_capability_size:,} chars, semantic={compact_semantic_size:,} chars")

    # Create LLM client (no knowledge base to avoid auto-loading 168k tokens)
    tools = [field_search_tool] if field_search_tool else []
    client = llm or project_llm_client(spec, role="judge", knowledge=None, tools=tools)
    client._caller = "judge"

    # has_reference 从 trace.ready 推断：ready 含 reference 且 trace 携带可采信 reference 时，judge 不需自产 expected。
    has_reference = _has_input_reference(trace)
    output_spec = _build_judge_output_spec(has_actual, project_id=spec.project_id, has_reference=has_reference)
    try:
        data = client.complete_json(system, user, trace_id=trace.trace_id, output_spec=output_spec)
    except ValueError as exc:
        # enforce_output 阻断（reference 形状/必填字段不合规）：reprompt 一次，仍失败返回兜底
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
            quality_flags = list(data.get("quality_flags") or [])
            if "self_check_failed" not in quality_flags:
                quality_flags.append("self_check_failed")
            data["quality_flags"] = quality_flags
            data["needs_human_review"] = True
            derivation = dict(data.get("verdict_derivation") or {})
            derivation["why_verdict"] = (
                "judge self-check failed; specific inconsistencies: "
                + json.dumps(inconsistencies, ensure_ascii=False)
            )
            data["verdict_derivation"] = derivation

    return _build_judge_result_from_data(spec, trace, data, expected_intent, boundary_standard)


def generate_reference(
    spec: ProjectSpec,
    intent: Dict[str, Any],
    project_id: Optional[str] = None,
    llm: Optional[LlmClient] = None,
) -> Optional[Dict[str, Any]]:
    """仅生成 reference（expected）模式：无 actual + 有意图，只产 expected 相关字段。
    用于 mock build 阶段 ready 含 reference 时，由 judge 评估侧固化 reference。
    reference 拥有全量系统信息（evaluation/judge_standard/judge_boundary 文档完整注入）。
    """
    project_id_val = project_id or spec.project_id
    # 构造一个最小 trace，只含意图信息，无 actual
    trace = RunTrace(
        trace_id=f"judge-ref-gen-{project_id_val}",
        project_id=project_id_val,
        case_id="",
        input=intent.get("input", {}),
        status="pending",
        scenario=intent.get("scenario", ""),
    )
    expected_intent = intent.get("expected_intent")
    # 构建 judge context：注入完整项目上下文（evaluation/judge_standard/judge_boundary）
    from .project_loader import load_adapter
    project_judge_context = None
    try:
        adapter = load_adapter(spec)
        project_judge_context = adapter.build_judge_context(trace)
        project_judge_context = {**(project_judge_context or {}), "intent_frame": adapter.build_intent_frame(trace)}
    except Exception:
        # 如果 adapter 不可用（如 QA 的抽象类），降级用空 context
        pass
    result = judge_trace(spec, trace, expected_intent=expected_intent, llm=llm,
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
        + "\n请仅修正以上不一致后重新输出完整 JSON。"
    )
    return client.complete_json(system, user + appendix, trace_id=trace_id, output_spec=output_spec)


def _build_judge_output_spec(has_actual: bool, project_id: str = "", has_reference: bool = False) -> StructuredOutputSpec:
    """spec/struct_output.md / spec/reference.md：构造 judge 调用的结构化输出约束。

    同一份 JudgeLLMOutput dataclass，按三阶段差异化 required_nonempty/nested_schemas：
    - 仅生成 reference（has_actual=False）：JudgeReferenceOutput，expected+business_expectations 必填且非空，
      expected 子结构按项目 ExtractOutput 约束。
    - reference+fulfilled 判定（has_actual=True, has_reference=False）：JudgeLLMOutput，
      expected+business_expectations+overall_fulfillment+reasoning_summary 必填非空，expected 子结构按项目 ExtractOutput 约束。
    - 已有 reference 仅出 fulfilled（has_actual=True, has_reference=True）：JudgeLLMOutput，
      business_expectations+overall_fulfillment+reasoning_summary 必填非空，expected 不强制 LLM 产（采信 trace.reference），
      不注入 expected 的 nested_schemas 子约束。

    has_reference 语义：trace.ready 含 reference 且 trace 携带可采信 reference → judge 不需自产 expected。
    """
    # 加载项目 ExtractOutput dataclass 作为 expected 子结构约束（没有则跳过，不阻断）
    # 仅当本阶段要求 LLM 自产 expected 时注入；ready 已有 reference 的阶段不注入（避免约束一个不要求的字段）。
    nested: Dict[str, StructuredOutputSpec] = {}
    require_expected = not (has_actual and has_reference)
    if project_id and require_expected:
        try:
            from .mock_agent import get_extract_output_dataclass
            extract_cls = get_extract_output_dataclass(project_id)
            if extract_cls is not None:
                nested["expected"] = StructuredOutputSpec.from_dataclass(
                    extract_cls,
                    description=f"项目 {project_id} 的 expected/live output 结构",
                )
        except Exception:
            pass  # 项目无 dataclass → expected 仍按 Any 不约束

    # 仅生成 reference 阶段：用 JudgeReferenceOutput（schema 子集，只含 expected 相关字段）
    if not has_actual:
        return StructuredOutputSpec.from_dataclass(
            JudgeReferenceOutput,
            required_nonempty=["expected", "business_expectations"],
            description="judge 仅生成 reference（expected）模式",
            nested_schemas=nested,
        )

    # 判定阶段：JudgeLLMOutput。has_reference 区分 expected 是否强制 LLM 产。
    if has_reference:
        # ready 已有 reference：expected 不强制 LLM 产，采信 trace.reference（_build_judge_result_from_data 里走 ready 分支）
        required_nonempty = ["business_expectations", "overall_fulfillment", "reasoning_summary"]
        description = "judge 判定输出（reference 已固化，仅产 fulfillment 判定）"
    else:
        # reference+fulfilled 判定：expected 必须由 LLM 自产且非空，子结构按 live_schema 约束
        required_nonempty = ["expected", "business_expectations", "overall_fulfillment", "reasoning_summary"]
        description = "judge 判定输出（自产 reference + fulfillment 判定）"
    return StructuredOutputSpec.from_dataclass(
        JudgeLLMOutput,
        required_nonempty=required_nonempty,
        description=description,
        nested_schemas=nested,
    )


def _minimal_honest_judge_result(spec: ProjectSpec, trace: RunTrace, data: Dict[str, Any]) -> JudgeResult:
    verdict = _compute_verdict("not_evaluable", {})
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict=verdict,
        score=None,
        intent_model={},
        business_expectations=[],
        fulfillment_assessments=[],
        overall_fulfillment={
            "status": "not_evaluable",
            "assessment_count": 0,
            "blocking_expectations": [],
        },
        boundary_decision={},
        verdict_derivation={"why_verdict": "LLM 调用失败，未做出算法判断"},
        needs_human_review=True,
        quality_flags=["llm_call_failed"],
        judge_method="llm_call_failed",
        wrong=[],
        missing=[],
        extra=[],
        raw_model_output=data,
    )
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def _build_judge_result_from_data(
    spec: ProjectSpec,
    trace: RunTrace,
    data: Dict[str, Any],
    expected_intent: Optional[str],
    boundary_standard: Dict[str, Any],
) -> JudgeResult:
    evidence = list(data.get("evidence") or [])
    if not evidence and data.get("reasoning_summary"):
        evidence = [str(data.get("reasoning_summary"))]
    boundary = _dict_value(data.get("evaluation_boundary"))
    if not boundary:
        boundary = _dict_value(boundary_standard.get("evaluation_boundary"))
    # actual 是 live 系统真实输出（adapter.extract_output），不能由 judge LLM 或项目后处理改成摘要/比较中间态。
    actual = trace_extracted_output(trace) or data.get("actual")

    # expected 取值：ready 路径直接用 trace.reference（已由 judge 在 mock build 阶段按 live_schema 固化），
    # 不整形；非 ready 路径 judge 自生成，过 live_schema 强校验。
    expected: Any = None
    if _has_input_reference(trace):
        expected = _trace_reference(trace)
    else:
        expected = data.get("expected")
        # spec/struct_output.md：结构校验由 complete_json 内部的 enforce_output 统一执行，
        # 不再需要事后 _check_judge_reference_with_live_schema 重复校验。

    raw_assessments = list(data.get("fulfillment_assessments") or [])
    assessments = [item for item in (normalize_fulfillment_assessment(item) for item in raw_assessments) if item is not None]
    assessment_payloads = [to_dict(item) for item in assessments]
    overall = _dict_value(data.get("overall_fulfillment"))
    overall_status = str(overall.get("status") or "").strip().lower()
    if not overall_status:
        statuses = [str(item.status or "").strip().lower() for item in assessments]
        overall_status = _derive_overall_status(statuses)
        overall["status"] = overall_status
    boundary_decision = _dict_value(data.get("boundary_decision"))

    verdict = _compute_verdict(overall_status, boundary_decision)
    score = _compute_score(assessment_payloads)

    quality_flags = list(data.get("quality_flags") or [])
    if "self_check_failed" in quality_flags:
        # Self-check inconsistencies persisted after one reprompt: refuse to assert
        # a definite verdict. Override the computed value so downstream agents
        # treat the case as needing human review rather than as truth.
        verdict = "uncertain"
        score = None

    business_expectations: List[BusinessExpectation] = [item for item in (normalize_business_expectation(item) for item in list(data.get("business_expectations") or [])) if item is not None]
    fulfillment_assessments: List[FulfillmentAssessment] = assessments
    missing_items: List[GapItem] = [normalize_gap_item(item, "missing") for item in list(data.get("missing") or [])]
    wrong_items: List[GapItem] = [normalize_gap_item(item, "wrong") for item in list(data.get("wrong") or [])]
    extra_items: List[GapItem] = [normalize_gap_item(item, "extra") for item in list(data.get("extra") or [])]

    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict=verdict,
        score=score,
        confidence=_score_0_1(data.get("confidence")),
        probability=_score_0_1(data.get("probability")),
        intent_model=_dict_value(data.get("intent_model")),
        consumer_contract=_dict_value(data.get("consumer_contract")),
        business_expectations=business_expectations,
        fulfillment_assessments=fulfillment_assessments,
        overall_fulfillment=overall,
        expected=expected,
        actual=actual,
        reconstructed_intent=str(data.get("reconstructed_intent") or ""),
        judge_basis=str(data.get("judge_basis") or ""),
        judge_method=str(data.get("judge_method") or "current_case_llm_judge"),
        semantic_equivalence_checks=list(data.get("semantic_equivalence_checks") or []),
        reference_generation_basis=_reference_generation_basis(trace, expected_intent, data, expected),
        verdict_derivation=_dict_value(data.get("verdict_derivation")),
        boundary_decision=boundary_decision,
        evaluation_boundary=boundary,
        missing=missing_items,
        wrong=wrong_items,
        extra=extra_items,
        evidence=evidence,
        reasoning_summary=str(data.get("reasoning_summary") or ""),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.scenario or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
    if not result.evaluation_boundary:
        result.evaluation_boundary = _dict_value(boundary_standard.get("evaluation_boundary"))
    result.summary = summary_from_fulfillment(to_dict(result))
    return normalize_judge_result(result) or result
