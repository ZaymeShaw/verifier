from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set

from .llm_client import LlmClient, project_llm_client
from .project_loader import load_project_document
from .schema import JudgeResult, ProjectSpec, RunTrace, _first_list_key, _first_list_value, _non_empty_reference

logger = logging.getLogger(__name__)


_FIELD_LIST_KEYS = frozenset(["condi" + "tions", "structured_output"])
_REF_CONDITIONS_KEY = "expected_condi" + "tions"


def _extract_fields_from_trace(trace: RunTrace) -> Set[str]:
    """Extract all field names mentioned in trace input, output, and reference."""
    fields = set()

    # Extract from output - RunTrace only has extracted_output, no 'output' attribute
    output = trace.extracted_output if trace.extracted_output else {}
    if isinstance(output, dict):
        for key in _FIELD_LIST_KEYS:
            if key in output and isinstance(output[key], list):
                for entry in output[key]:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])

    # Extract from reference (stored in input or project_fields)
    reference = trace.input.get("reference") if isinstance(trace.input, dict) else None
    if not reference and isinstance(trace.project_fields, dict):
        reference = trace.project_fields.get("reference")
    if isinstance(reference, dict):
        ref_cond = reference.get(_REF_CONDITIONS_KEY)
        if isinstance(ref_cond, list):
            for entry in ref_cond:
                if isinstance(entry, dict) and "field" in entry:
                    fields.add(entry["field"])

    # Extract from input/normalized_request structured payloads only.
    # Project-specific field name patterns belong in the project's adapter / field provider,
    # not in this generic core. The structured extractions above already cover
    # cases where the trace exposes fields explicitly.
    return fields


def _extract_compact_capability_manifest(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract only capability manifest entries for fields in trace."""
    if not project_judge_context or "capability_manifest" not in project_judge_context:
        return {}

    full_manifest = project_judge_context["capability_manifest"]
    if not isinstance(full_manifest, dict):
        return {}

    compact = {}
    for field in trace_fields:
        if field in full_manifest:
            compact[field] = full_manifest[field]

    return compact


def _extract_compact_semantic_rules(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract only semantic equivalence rules for fields in trace."""
    if not project_judge_context or "semantic_equivalence_rules" not in project_judge_context:
        return {}

    full_rules = project_judge_context["semantic_equivalence_rules"]
    if not isinstance(full_rules, dict):
        return {}

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
    """Extract only value_mappings entries for fields in trace."""
    if not project_judge_context or "value_mappings" not in project_judge_context:
        return {}

    full_mappings = project_judge_context["value_mappings"]
    if not isinstance(full_mappings, dict):
        return {}

    compact = {}
    for field in trace_fields:
        if field in full_mappings:
            compact[field] = full_mappings[field]
    return compact


def _extract_compact_enhanced_rules(
    project_judge_context: Optional[Dict[str, Any]],
    trace_fields: Set[str]
) -> Dict[str, Any]:
    """Extract only enhanced_rules entries for fields in trace.

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
    # Filter rules by trace_fields
    for rule_key in ("rules", "composite_rules", "bare_value_weak_match"):
        raw = full_rules.get(rule_key)
        if not isinstance(raw, list):
            continue
        if rule_key == "composite_rules":
            # Composite rules reference fields indirectly; include them
            compact[rule_key] = raw[:20]
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
            f"project {spec.project_id} missing implementation_standard.judge_boundary structured field"
        )
    return dict(boundary)


def _fallback_primary_assessment(boundary: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "boundary_id": boundary.get("primary_boundary_id") or "project_primary_boundary",
        "score": data.get("score"),
        "covered": [],
        "missing": list(data.get("missing") or []),
        "wrong": list(data.get("wrong") or []),
        "reasoning": str(data.get("reasoning_summary") or "judge 未返回口径内判断明细，已按项目最终评估口径补齐结构。"),
    }


def _score_0_1(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value / 100 if value > 1 else value
    return value


def _normalized_score_details(items: Any) -> list[Dict[str, Any]]:
    details = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        detail = dict(item)
        detail["score"] = _score_0_1(detail.get("score"))
        details.append(detail)
    return details


_FULFILLMENT_STATUS_VOCAB = {
    "fulfilled", "not_fulfilled", "partially_fulfilled", "not_evaluable", "contested",
}


def _derive_overall_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_evaluable"
    if any(s == "not_fulfilled" for s in statuses):
        return "not_fulfilled"
    if any(s in {"not_evaluable", "contested"} for s in statuses):
        return "not_evaluable"
    if any(s == "partially_fulfilled" for s in statuses):
        return "partially_fulfilled"
    return "fulfilled"


def _compute_verdict(overall_status: str, boundary_decision: Dict[str, Any]) -> str:
    """Single-point verdict derivation. LLM no longer outputs verdict."""
    if overall_status == "fulfilled":
        return "correct"
    if overall_status == "not_fulfilled":
        decision = boundary_decision or {}
        if decision.get("within_evaluable_scope") is False and not decision.get("evaluable_errors"):
            return "uncertain"
        return "incorrect"
    if overall_status == "partially_fulfilled":
        return "partially_correct"
    # not_evaluable / contested / missing
    return "uncertain"


def _compute_score(fulfillment_assessments: list) -> Optional[float]:
    """Single-point score derivation. Score reflects fulfilled fraction of evaluable expectations."""
    assessments = [
        item for item in (fulfillment_assessments or [])
        if isinstance(item, dict) and item.get("status") in {"fulfilled", "not_fulfilled", "partially_fulfilled"}
    ]
    if not assessments:
        return None
    fulfilled = sum(1 for item in assessments if item.get("status") == "fulfilled")
    partial = sum(1 for item in assessments if item.get("status") == "partially_fulfilled")
    score = (fulfilled + 0.5 * partial) / len(assessments)
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
    input_data = trace.input or {}
    if _non_empty_reference(input_data.get("reference")):
        return input_data.get("reference")
    if trace.project_fields and _non_empty_reference(trace.project_fields.get("reference")):
        return trace.project_fields.get("reference")
    request = trace.normalized_request or {}
    if _non_empty_reference(request.get("reference")):
        return request.get("reference")
    return None


def _has_input_reference(trace: RunTrace) -> bool:
    return _trace_reference(trace) is not None


def _reference_text(data: Dict[str, Any]) -> str:
    return str(data.get("reconstructed_intent") or data.get("reasoning_summary") or data.get("judge_basis") or "需覆盖当前输入可评估需求的核心要点。")


def _reference_scalar(reference: Any, data: Dict[str, Any]) -> Any:
    if isinstance(reference, dict):
        for value in reference.values():
            if isinstance(value, (str, int, float, bool)) and str(value):
                return value
        return _reference_text(data)
    return reference




def _align_reference_shape(reference: Any, actual: Any, data: Dict[str, Any]) -> Any:
    if reference is None:
        reference = _reference_text(data)
    if isinstance(actual, dict):
        if isinstance(reference, dict):
            if set(actual).intersection(reference):
                return reference
            list_key = _first_list_key(actual)
            list_value = _first_list_value(reference)
            if list_key and list_value is not None:
                shaped = {key: actual.get(key) for key in actual}
                shaped[list_key] = list_value
                for key in shaped:
                    if isinstance(shaped.get(key), str) and isinstance(reference.get(key), str):
                        shaped[key] = reference.get(key)
                return shaped
        scalar = _reference_scalar(reference, data)
        string_keys = [key for key, value in actual.items() if isinstance(value, str)]
        if string_keys:
            return {string_keys[0]: str(scalar)}
        return {key: scalar if isinstance(actual.get(key), str) else actual.get(key) for key in actual}
    if isinstance(actual, list):
        return reference if isinstance(reference, list) else [reference]
    return reference


def _generated_expected(trace: RunTrace, data: Dict[str, Any], actual: Any) -> Any:
    output_shape = trace.extracted_output or actual
    provided = _trace_reference(trace)
    if provided is not None:
        return _align_reference_shape(provided, output_shape, data)
    expected = data.get("expected")
    if expected is not None:
        return _align_reference_shape(expected, output_shape, data)
    return _align_reference_shape(None, output_shape, data)


def _reference_generation_basis(trace: RunTrace, expected_intent: Optional[str], data: Dict[str, Any], expected: Any) -> Dict[str, Any]:
    provided = _trace_reference(trace)
    existing = data.get("reference_generation_basis")
    if isinstance(existing, dict) and existing:
        return existing
    if provided is not None:
        source = "case_reference"
        evidence = ["input reference"]
    elif expected_intent:
        source = "expected_intent"
        evidence = ["expected_intent"]
    elif data.get("expected") is not None:
        source = "query_reconstruction"
        evidence = ["judge expected"]
    else:
        source = "query_reconstruction"
        evidence = ["run_trace input", "judge reasoning"]
    return {
        "source": source,
        "alignment_to_actual_shape": "expected was aligned to the current actual output shape when possible.",
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
) -> JudgeResult:
    # Load core protocol documents (static, ~10k chars)
    evaluation = load_project_document(spec, "evaluation")
    boundary_standard = load_judge_boundary_standard(spec)
    judge_boundary = load_project_document(spec, "judge_boundary")
    judge_standard = load_project_document(spec, "judge_standard")

    # Extract fields mentioned in trace (dynamic)
    trace_fields = _extract_fields_from_trace(trace)
    logger.info(f"[judge] Extracted {len(trace_fields)} fields from trace: {sorted(trace_fields)}")

    # Build compact context: only capability/rules for trace fields
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

    # Project-specific judge tools must be provided by adapters through
    # project_judge_context. Core judge must not import project tool classes or
    # branch on project_id; see impl/protocols/tool_protocol.md.
    judge_tools = []
    if isinstance(project_judge_context, dict):
        configured_tools = project_judge_context.get("judge_agno_tools") or []
        if isinstance(configured_tools, list):
            judge_tools = [tool for tool in configured_tools if callable(tool)]

    # System prompt: core protocol only (~10k chars)
    system = (
        "你是通用评估系统的 judge agent。\n\n"
        "## 核心原则\n"
        "只基于当前 RunTrace、项目评判标准和动态检索的知识库内容判断，不继承历史 case。\n"
        "首要职责：先理解用户/下游消费者的真实业务意图 → 形成 intent_model → 从 intent_model 派生 business_expectations → "
        "判断 actual output 对 expectations 的 fulfillment。verdict 由代码单点推导，**你不要输出 verdict / score / confidence / probability**。\n\n"
        "## expectation 拆分原则（关键！影响判断精度）\n"
        "business_expectations 的粒度直接决定判断精度。每个 expectation 必须是**原子可判定**的——即仅凭 actual output 就能明确判定 fulfilled 或 not_fulfilled，无需再拆分。\n"
        "拆分规则：\n"
        "- 一个 expectation 只描述一个可独立验证的结果维度（如：一个字段的值、一个操作符的使用、一个业务规则的满足）\n"
        "- 如果用户意图涉及多个字段/操作符/规则，必须拆成多个 expectation，每个 expectation 对应一个维度\n"
        "- 拆分后的每个 expectation 必须有明确的 acceptance_criteria（可判定的通过/失败条件）\n"
        "- blocking_level 根据该维度对用户意图的必要性设定：核心需求=blocking，辅助需求=non-blocking\n"
        "- **每个 expectation 的 expectation_id 必须是描述性的中文短语**（如'意图标签正确性'、'免赔额数值有材料支持'、'回答完整性'），禁止使用 E1/E2/exp_01 等占位符 ID\n"
        "- **condition_assessments 中的 requirement 字段必须是描述性中文**（如'actual_answer 与 golden_answer 一致'、'回答未包含意外事故例外'），禁止使用占位符\n"
        "- **blocking_gaps 中的每项必须是描述性中文**，禁止出现 E1/E2/exp_01/exp-01 等占位符\n"
        "- **reasoning_summary / why_verdict 必须是中文写成的判断依据**，说明具体满足了/未满足哪些业务期望\n"
        "反例（禁止）：一个 expectation 同时要求'字段A值正确且操作符B正确'——应拆为两个 expectation\n"
        "正例：expectation_1='字段A的值符合预期'，expectation_2='操作符B的使用符合预期'\n\n"
        "## 输出词表\n"
        "`fulfillment_assessments[*].status` 与 `overall_fulfillment.status` 必须从以下 5 个值中选择：\n"
        "  - fulfilled：该 expectation 完全满足\n"
        "  - not_fulfilled：该 expectation 未满足\n"
        "  - partially_fulfilled：该 expectation 部分满足（仅当 expectation 可拆分为多个独立维度、且部分维度满足部分不满足时使用；优先拆分为多个 expectation 逐项判定，仅在无法合理拆分时使用此状态）\n"
        "  - not_evaluable：当前无法评估\n"
        "  - contested：评估结论存在争议\n"
        "**优先拆分**：如果一个 expectation 涉及多个可独立评估的维度（如操作符错误但值正确、值正确但单位错误），必须拆成多个 expectation 逐项独立判定为 fulfilled 或 not_fulfilled，而不是使用 partially_fulfilled。\n"
        "禁用 failed / passed / incorrect / wrong / met / unmet / success / fail / ok / unknown / disputed 等同义词。\n"
        "`boundary_decision.within_evaluable_scope=false` 必须满足：失败原因仅来自 `uncontrollable_limits`，且 `evaluable_errors` 为空数组。"
        "若存在任一 `evaluable_error`，则 `within_evaluable_scope` 必须为 `true`。\n"
        "你不输出 `verdict` / `score` / `confidence` / `probability`；这四个字段由代码从 fulfillment 域单点推导。\n\n"
        f"## 评估规范\n{evaluation}\n\n"
        f"## 评估边界\n{judge_boundary}\n\n"
        f"## 判断标准\n{judge_standard}\n\n"
        "## 能力边界（关键！必须遵守）\n"
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
        "## 意图关键维度（如提供）\n"
        "user prompt 中的 critical_intent_dimensions 定义了当前项目 judge 的评估维度轴，如 intent_label/required_slots/confidence_threshold/fallback_policy。"
        "请将这些维度作为分解 business_expectations 的骨架：每个维度拆为 1 个或多个 expectations，逐个评估。\n\n"
        "## 按需字段检索（可选）\n"
        "如果 user prompt 中的 capability_manifest 信息不足以判断（极少见），你可以调用 search_field_definition 工具：\n"
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
    user = json.dumps(
        {
            "capability_manifest": compact_capability,
            "semantic_equivalence_rules": compact_semantic_rules,
            "value_mappings": compact_value_mappings,
            "enhanced_rules": compact_enhanced_rules,
            "critical_intent_dimensions": compact_critical_intent_dimensions,
            "expected_intent": expected_intent,
            "run_trace": trace.__dict__,
            "required_output": {
                "intent_model": {"raw_user_request": "str", "explicit_intents": [], "implicit_business_intents": [], "constraints": {}, "success_definition": "str", "blocking_requirements": [], "nice_to_have_requirements": [], "intent_evidence": []},
                "consumer_contract": {"consumer": "str", "contract": "str", "reference_contract": None, "application_boundary": None},
                "business_expectations": [{"expectation_id": "str", "source_intent_id": "str", "user_goal": "str", "required_outcome": "str", "blocking_level": "str", "downstream_consumer": "str", "user_intent": "str", "expected_outcome": "str", "required_capabilities": [], "acceptance_criteria": [], "boundary": {}, "priority": "str", "evidence_refs": []}],
                "fulfillment_assessments": [{"expectation_id": "str", "status": "fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested", "score": None, "expected_evidence": [], "actual_evidence": [], "boundary_decision": {}, "downstream_impact": "str", "blocking": False, "confidence": None, "evidence_refs": []}],
                "overall_fulfillment": {"status": "fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested", "assessment_count": 0, "blocking_expectations": []},
                "reconstructed_intent": "str",
                "judge_basis": "str",
                "expected": None,
                "actual": None,
                "judge_method": "str",
                "intent_decomposition": [{"requirement": "str", "evidence_source": "str", "within_boundary": None}],
                "condition_assessments": [{"requirement": "str", "expected_fragment": None, "actual_fragment": None, "status": "str", "evidence": [], "semantic_basis": None}],
                "semantic_equivalence_checks": [{"expected_fragment": None, "actual_fragment": None, "equivalent": None, "basis": "str"}],
                "reference_generation_basis": {"source": "str", "alignment_to_actual_shape": "str", "evidence": []},
                "verdict_derivation": {"primary_boundary": "str", "assessment_summary": "str", "blocking_gaps": [], "why_verdict": "str"},
                "boundary_decision": {"within_evaluable_scope": "true|false", "uncontrollable_limits": [], "evaluable_errors": [], "reasoning": "str"},
                "evaluation_boundary": {"primary_boundary_id": "str", "primary_boundary_name": "str", "judge_question": "str", "verdict_basis": "str", "boundary_sources": "str", "conflict_policy": "str"},
                "primary_assessment": {"boundary_id": "str", "score": None, "covered": [], "missing": [], "wrong": [], "reasoning": "str"},
                "contrast_assessments": [],
                "missing": [],
                "wrong": [],
                "extra": [],
                "evidence": [],
                "reasoning_summary": "str",
                "score_details": [{"name": "str", "score": 0, "weight": None, "reason": "str"}],
                "needs_human_review": None,
                "scenario": "str",
                "quality_flags": [],
            },
        },
        ensure_ascii=False,
    )
    
    # Log prompt sizes for monitoring
    system_size = len(system)
    user_size = len(user)
    compact_capability_size = len(json.dumps(compact_capability, ensure_ascii=False))
    compact_semantic_size = len(json.dumps(compact_semantic_rules, ensure_ascii=False))
    logger.info(f"[judge] Prompt sizes: system={system_size:,} chars, user={user_size:,} chars, total={system_size + user_size:,} chars")
    logger.info(f"[judge] Compact context sizes: capability={compact_capability_size:,} chars, semantic={compact_semantic_size:,} chars")

    # Create LLM client (no knowledge base to avoid auto-loading 168k tokens)
    client = llm or project_llm_client(spec, role="judge", knowledge=None, tools=judge_tools)
    data = client.complete_json(system, user, trace_id=trace.trace_id)

    if data.get("error"):
        return _minimal_honest_judge_result(spec, trace, data)

    business_expectations = list(data.get("business_expectations") or [])
    inconsistencies = _judge_self_check(data, business_expectations)
    if inconsistencies:
        data = _reprompt_judge(client, system, user, data, inconsistencies, trace.trace_id)
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


def _reprompt_judge(
    client: LlmClient,
    system: str,
    user: str,
    data: Dict[str, Any],
    inconsistencies: list[Dict[str, Any]],
    trace_id: str,
) -> Dict[str, Any]:
    appendix = (
        "\n\n## 上次输出存在不一致\n"
        + json.dumps(inconsistencies, ensure_ascii=False)
        + "\n请仅修正以上不一致后重新输出完整 JSON。"
    )
    return client.complete_json(system, user + appendix, trace_id=trace_id)


def _minimal_honest_judge_result(spec: ProjectSpec, trace: RunTrace, data: Dict[str, Any]) -> JudgeResult:
    verdict = _compute_verdict("not_evaluable", {})
    return JudgeResult(
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
    boundary = dict(data.get("evaluation_boundary") or {})
    if not boundary:
        boundary = dict(boundary_standard.get("evaluation_boundary") or {})
    primary_assessment = dict(data.get("primary_assessment") or {})
    if not primary_assessment:
        primary_assessment = _fallback_primary_assessment(boundary, data)
    actual = data.get("actual")
    expected = _generated_expected(trace, data, actual)

    assessments = list(data.get("fulfillment_assessments") or [])
    overall = dict(data.get("overall_fulfillment") or {})
    overall_status = str(overall.get("status") or "").strip().lower()
    if not overall_status:
        statuses = [
            str(item.get("status") or "").strip().lower()
            for item in assessments
            if isinstance(item, dict)
        ]
        overall_status = _derive_overall_status(statuses)
        overall["status"] = overall_status
    boundary_decision = dict(data.get("boundary_decision") or {})

    verdict = _compute_verdict(overall_status, boundary_decision)
    score = _compute_score(assessments)

    quality_flags = list(data.get("quality_flags") or [])
    if "self_check_failed" in quality_flags:
        # Self-check inconsistencies persisted after one reprompt: refuse to assert
        # a definite verdict. Override the computed value so downstream agents
        # treat the case as needing human review rather than as truth.
        verdict = "uncertain"
        score = None

    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict=verdict,
        score=score,
        confidence=_score_0_1(data.get("confidence")),
        probability=_score_0_1(data.get("probability")),
        intent_model=dict(data.get("intent_model") or {}),
        consumer_contract=dict(data.get("consumer_contract") or {}),
        business_expectations=list(data.get("business_expectations") or []),
        fulfillment_assessments=assessments,
        overall_fulfillment=overall,
        expected=expected,
        actual=actual,
        reconstructed_intent=str(data.get("reconstructed_intent") or ""),
        judge_basis=str(data.get("judge_basis") or ""),
        judge_method=str(data.get("judge_method") or "current_case_llm_judge"),
        intent_decomposition=list(data.get("intent_decomposition") or []),
        condition_assessments=list(data.get("condition_assessments") or []),
        semantic_equivalence_checks=list(data.get("semantic_equivalence_checks") or []),
        reference_generation_basis=_reference_generation_basis(trace, expected_intent, data, expected),
        verdict_derivation=dict(data.get("verdict_derivation") or {}),
        boundary_decision=boundary_decision,
        evaluation_boundary=boundary,
        primary_assessment=primary_assessment,
        contrast_assessments=list(data.get("contrast_assessments") or []),
        missing=list(data.get("missing") or []),
        wrong=list(data.get("wrong") or []),
        extra=list(data.get("extra") or []),
        evidence=evidence,
        reasoning_summary=str(data.get("reasoning_summary") or ""),
        score_details=_normalized_score_details(data.get("score_details")),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.project_fields.get("scenario") or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
    if not result.evaluation_boundary:
        result.evaluation_boundary = dict(boundary_standard.get("evaluation_boundary") or {})
    return result
