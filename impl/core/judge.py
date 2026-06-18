from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from .knowledge_base import load_knowledge_base
from .llm_client import LlmClient, project_llm_client
from .project_loader import load_project_document
from .schema import JudgeResult, ProjectSpec, RunTrace, _first_list_key, _first_list_value, _non_empty_reference

logger = logging.getLogger(__name__)


def _extract_fields_from_trace(trace: RunTrace) -> Set[str]:
    """Extract all field names mentioned in trace input, output, and reference."""
    fields = set()

    # Extract from output - RunTrace only has extracted_output, no 'output' attribute
    output = trace.extracted_output if trace.extracted_output else {}
    if isinstance(output, dict):
        # Look for conditions/structured_output in client_search style
        for key in ["conditions", "structured_output"]:
            if key in output and isinstance(output[key], list):
                for condition in output[key]:
                    if isinstance(condition, dict) and "field" in condition:
                        fields.add(condition["field"])
        # Look for any field-like keys
        for key in output:
            if "." in key or key.endswith("Age") or key.endswith("Sex") or key.endswith("Num"):
                fields.add(key)

    # Extract from reference (stored in input or project_fields)
    reference = trace.input.get("reference") if isinstance(trace.input, dict) else None
    if not reference and isinstance(trace.project_fields, dict):
        reference = trace.project_fields.get("reference")
    if isinstance(reference, dict):
        if "expected_conditions" in reference and isinstance(reference["expected_conditions"], list):
            for condition in reference["expected_conditions"]:
                if isinstance(condition, dict) and "field" in condition:
                    fields.add(condition["field"])
        for key in reference:
            if "." in key or key.endswith("Age") or key.endswith("Sex") or key.endswith("Num"):
                fields.add(key)

    # Extract from input (look for field names in query text)
    input_text = str(trace.normalized_request or trace.input or "")
    # Common field patterns in queries
    field_patterns = [
        r"clientAge", r"clientSex", r"annPremSegNum", r"pCategorys", r"pTypes",
        r"polNoInfo\.\w+", r"familyInfo\.\w+", r"education", r"clientTemperature"
    ]
    for pattern in field_patterns:
        if re.search(pattern, input_text, re.IGNORECASE):
            fields.add(pattern.replace(r"\.", ".").replace(r"\w+", ""))

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



def _extract_boundary_value(text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip('"\'')
    return ""


def _line_after_label(text: str, label: str) -> str:
    prefix = f"{label}："
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def _fallback_evaluation_boundary(judge_boundary: str) -> Dict[str, Any]:
    verdict_standard = _line_after_label(judge_boundary, "判题目标") or _line_after_label(judge_boundary, "最终评估口径")
    limitation = _line_after_label(judge_boundary, "限制")
    evaluation_scope = _line_after_label(judge_boundary, "评价范围")
    boundary_sources = _line_after_label(judge_boundary, "边界依据") or _line_after_label(judge_boundary, "能力边界依据") or _line_after_label(judge_boundary, "边界来源")
    out_of_boundary_policy = _line_after_label(judge_boundary, "出界处理")
    project_boundary_notes = _line_after_label(judge_boundary, "项目边界说明")
    explanation_parts = [part for part in [limitation, evaluation_scope, out_of_boundary_policy, project_boundary_notes] if part]
    explanation = "\n".join(explanation_parts) or _line_after_label(judge_boundary, "口径说明") or _line_after_label(judge_boundary, "冲突处理")
    conflict_policy = _line_after_label(judge_boundary, "冲突处理") or out_of_boundary_policy or evaluation_scope or project_boundary_notes
    return {
        "primary_boundary_id": _extract_boundary_value(judge_boundary, "id") or "project_verdict_standard",
        "primary_boundary_name": verdict_standard or _extract_boundary_value(judge_boundary, "name") or "项目最终评估口径",
        "judge_question": _extract_boundary_value(judge_boundary, "final_verdict_question") or _extract_boundary_value(judge_boundary, "judge_question") or explanation,
        "verdict_basis": explanation or "fallback_from_project_judge_boundary",
        "boundary_sources": boundary_sources,
        "conflict_policy": conflict_policy,
    }


def load_judge_boundary_standard(spec: ProjectSpec) -> Dict[str, Any]:
    implementation_standard = spec.frontend_extensions.get("implementation_standard") if spec.frontend_extensions else None
    configured = implementation_standard.get("judge_boundary") if isinstance(implementation_standard, dict) and isinstance(implementation_standard.get("judge_boundary"), dict) else {}
    text = load_project_document(spec, "judge_boundary")
    return {
        **configured,
        "text": text,
        "evaluation_boundary": _fallback_evaluation_boundary(text),
    }


def apply_boundary_reconciliation(trace: RunTrace, judge_result: JudgeResult, boundary_standard: Dict[str, Any]) -> JudgeResult:
    evaluation_boundary = boundary_standard.get("evaluation_boundary") if isinstance(boundary_standard, dict) else None
    if evaluation_boundary and not judge_result.evaluation_boundary:
        judge_result.evaluation_boundary = dict(evaluation_boundary)
    decision = judge_result.boundary_decision or {}
    if judge_result.verdict == "incorrect" and decision.get("within_evaluable_scope") is False and decision.get("uncontrollable_limits") and not decision.get("evaluable_errors"):
        judge_result.verdict = "uncertain"
        judge_result.score = None
        judge_result.confidence = None
        judge_result.probability = None
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.needs_human_review = False
        if "external_limitation_not_penalized" not in judge_result.quality_flags:
            judge_result.quality_flags.append("external_limitation_not_penalized")
        judge_result.verdict_derivation = {
            **(judge_result.verdict_derivation or {}),
            "boundary_gate": "excluded uncontrollable limits from incorrect verdict",
            "why_verdict": "unmet need is outside the project-controllable evaluation boundary",
        }
    return judge_result


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


def _score_from_verdict(verdict: Any, score: Any) -> Any:
    """When LLM omits score but verdict is decisive, derive score from verdict
    so the UI doesn't show '-' for clearly-decided cases."""
    if isinstance(score, (int, float)):
        return _score_0_1(score)
    v = str(verdict or "").strip().lower()
    if v == "correct":
        return 1
    if v == "incorrect":
        return 0
    return _score_0_1(score)


def _normalized_score_details(items: Any) -> list[Dict[str, Any]]:
    details = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        detail = dict(item)
        detail["score"] = _score_0_1(detail.get("score"))
        details.append(detail)
    return details


_FULFILLMENT_STATUS_CANON = {
    "fulfilled", "not_fulfilled", "partially_fulfilled", "not_evaluable", "contested",
}
_FULFILLMENT_STATUS_ALIASES = {
    "failed": "not_fulfilled",
    "fail": "not_fulfilled",
    "incorrect": "not_fulfilled",
    "wrong": "not_fulfilled",
    "violated": "not_fulfilled",
    "rejected": "not_fulfilled",
    "missed": "not_fulfilled",
    "unmet": "not_fulfilled",
    "unfulfilled": "not_fulfilled",
    "passed": "fulfilled",
    "pass": "fulfilled",
    "correct": "fulfilled",
    "ok": "fulfilled",
    "success": "fulfilled",
    "succeeded": "fulfilled",
    "met": "fulfilled",
    "satisfied": "fulfilled",
    "partial": "partially_fulfilled",
    "partially": "partially_fulfilled",
    "partial_fulfilled": "partially_fulfilled",
    "partial_pass": "partially_fulfilled",
    "unknown": "not_evaluable",
    "unverified": "not_evaluable",
    "not_verified": "not_evaluable",
    "indeterminate": "not_evaluable",
    "n/a": "not_evaluable",
    "disputed": "contested",
    "conflict": "contested",
    "conflicting": "contested",
}


def _canonicalize_fulfillment_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "not_evaluable"
    if text in _FULFILLMENT_STATUS_CANON:
        return text
    return _FULFILLMENT_STATUS_ALIASES.get(text, text)


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


def _normalize_fulfillment(data: Dict[str, Any]) -> None:
    """In-place: canonicalize assessment statuses and rebuild overall_fulfillment to match.

    Many LLM completions return non-canonical synonyms like 'failed'/'passed' for
    fulfillment_assessments[*].status. The state machine's
    derived_verdict_consistency gate compares those statuses against canonical
    expected values; non-canonical values cause spurious contradictions, retry
    exhaustion, and fallback to needs_human_review. Normalize here so downstream
    gates see consistent inputs.
    """
    assessments = data.get("fulfillment_assessments")
    if not isinstance(assessments, list) or not assessments:
        return

    failing = {"not_fulfilled", "partially_fulfilled", "not_evaluable", "contested"}
    statuses: list[str] = []
    blocking_ids: list[str] = []
    for item in assessments:
        if not isinstance(item, dict):
            continue
        canon = _canonicalize_fulfillment_status(item.get("status"))
        item["status"] = canon
        statuses.append(canon)
        if canon in failing:
            exp_id = item.get("expectation_id")
            if exp_id:
                blocking_ids.append(str(exp_id))

    overall = data.get("overall_fulfillment")
    if not isinstance(overall, dict):
        overall = {}
        data["overall_fulfillment"] = overall
    derived_status = _derive_overall_status(statuses)
    overall["status"] = derived_status
    overall["assessment_count"] = len(statuses)
    seen: set[str] = set()
    deduped = []
    for bid in blocking_ids:
        if bid in seen:
            continue
        seen.add(bid)
        deduped.append(bid)
    overall["blocking_expectations"] = deduped

    verdict = str(data.get("verdict") or "").strip().lower()
    if derived_status == "not_fulfilled" and verdict == "correct":
        data["verdict"] = "incorrect"
    elif derived_status == "fulfilled" and verdict == "incorrect":
        data["verdict"] = "correct"
    elif derived_status in {"not_evaluable", "partially_fulfilled"} and verdict not in {"uncertain", "correct", "incorrect"}:
        data["verdict"] = "uncertain"



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
    judge_boundary = boundary_standard.get("text") or ""
    judge_standard = load_project_document(spec, "judge_standard")

    # Extract fields mentioned in trace (dynamic)
    trace_fields = _extract_fields_from_trace(trace)
    logger.info(f"[judge] Extracted {len(trace_fields)} fields from trace: {sorted(trace_fields)}")

    # Build compact context: only capability/rules for trace fields
    compact_capability = _extract_compact_capability_manifest(project_judge_context, trace_fields)
    compact_semantic_rules = _extract_compact_semantic_rules(project_judge_context, trace_fields)

    logger.info(f"[judge] Compact capability_manifest: {len(compact_capability)} fields")
    logger.info(f"[judge] Compact semantic_rules: {sum(len(v) if isinstance(v, list) else 0 for v in compact_semantic_rules.values())} rules")

    # Create field definition search tool (项目专属 provider + 通用协议)
    from impl.tools.field_retrieval import create_field_search_tool

    # Load project-specific field provider
    field_provider = None
    try:
        if spec.project_id == 'client_search':
            from impl.projects.client_search.field_provider import ClientSearchFieldDefinitionProvider
            field_provider = ClientSearchFieldDefinitionProvider(spec)
        # Add other projects here as needed
        # elif spec.project_id == 'QA':
        #     from impl.projects.QA.field_provider import QAFieldDefinitionProvider
        #     field_provider = QAFieldDefinitionProvider(spec)
    except Exception as e:
        logger.warning(f"[judge] Failed to load field provider for {spec.project_id}: {e}")

    # Create tool if provider available
    field_search_tool = create_field_search_tool(field_provider) if field_provider else None

    # System prompt: core protocol only (~10k chars)
    system = (
        "你是通用评估系统的 judge agent。\n\n"
        "## 核心原则\n"
        "只基于当前 RunTrace、项目评判标准和动态检索的知识库内容判断，不继承历史 case。\n"
        "首要职责：先理解用户/下游消费者的真实业务意图 → 形成 intent_model → 从 intent_model 派生 business_expectations → "
        "判断 actual output 对 expectations 的 fulfillment。verdict 只是派生兼容摘要。\n\n"
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
        "## 按需字段检索（可选）\n"
        "如果 user prompt 中的 capability_manifest 信息不足以判断（极少见），你可以调用 search_field_definition 工具：\n"
        "- 输入：字段名（如 'clientAge'）\n"
        "- 返回：该字段的完整定义、操作符、值类型、示例\n"
        "- 注意：user prompt 中已提供当前 case 涉及字段的完整能力清单，优先使用！\n\n"
        "## 禁止事项\n"
        "- 不要把 reference answer 当作默认主目标（除非 case 明确指定）\n"
        "- 不要把 HTTP 状态、run_status、review_verdict、attribute/cluster 结论当作满足依据\n"
        "- 不要归因内部代码、配置或 prompt 原因（属于 attribute agent）\n"
        "- 分析文字尽量使用中文，输出 JSON。"
    )
    
    # User prompt: runtime data + compact context (~30k chars)
    user = json.dumps(
        {
            "capability_manifest": compact_capability,  # Only fields in trace
            "semantic_equivalence_rules": compact_semantic_rules,  # Only fields in trace
            "expected_intent": expected_intent,
            "run_trace": trace.__dict__,
            "required_output": {
                "intent_model": {"raw_user_request": "str", "explicit_intents": [], "implicit_business_intents": [], "constraints": {}, "success_definition": "str", "blocking_requirements": [], "nice_to_have_requirements": [], "intent_evidence": []},
                "consumer_contract": {"consumer": "str", "contract": "str", "reference_contract": None, "application_boundary": None},
                "business_expectations": [{"expectation_id": "str", "source_intent_id": "str", "user_goal": "str", "required_outcome": "str", "blocking_level": "str", "downstream_consumer": "str", "user_intent": "str", "expected_outcome": "str", "required_capabilities": [], "acceptance_criteria": [], "boundary": {}, "priority": "str", "evidence_refs": []}],
                "fulfillment_assessments": [{"expectation_id": "str", "status": "fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested", "score": None, "expected_evidence": [], "actual_evidence": [], "boundary_decision": {}, "downstream_impact": "str", "blocking": False, "confidence": None, "evidence_refs": []}],
                "overall_fulfillment": {"status": "fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested", "assessment_count": 0, "blocking_expectations": []},
                "verdict": "correct|incorrect|uncertain",
                "score": None,
                "confidence": None,
                "probability": None,
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
                "boundary_decision": {"within_evaluable_scope": None, "uncontrollable_limits": [], "evaluable_errors": [], "reasoning": "str"},
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
    tools = [field_search_tool] if field_search_tool else []
    client = llm or project_llm_client(spec, role="judge", knowledge=None, tools=tools)
    data = client.complete_json(system, user, trace_id=trace.trace_id)
    _normalize_fulfillment(data)

    if data.get("error") or not data.get("verdict"):
        boundary = _fallback_evaluation_boundary(judge_boundary)
        error_text = data.get("raw_text") or data.get("error") or "judge LLM returned no verdict"
        result = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="uncertain",
            intent_model={
                "raw_user_request": str(trace.normalized_request or trace.input or ""),
                "explicit_intents": [],
                "implicit_business_intents": [],
                "constraints": {},
                "success_definition": "judge LLM unavailable; intent cannot be confidently reconstructed",
                "blocking_requirements": [],
                "nice_to_have_requirements": [],
                "intent_evidence": [{"source": "run_trace", "text": str(trace.normalized_request or trace.input or "")}],
            },
            consumer_contract={"consumer": spec.project_id, "contract": "judge LLM unavailable; business expectation fulfillment not evaluable", "application_boundary": boundary},
            business_expectations=[{"expectation_id": f"{spec.project_id}:judge_unavailable", "downstream_consumer": spec.project_id, "user_intent": str(trace.normalized_request or trace.input or ""), "expected_outcome": "produce evaluable business output", "acceptance_criteria": [], "boundary": boundary, "priority": "blocking"}],
            fulfillment_assessments=[{"expectation_id": f"{spec.project_id}:judge_unavailable", "status": "not_evaluable", "score": None, "expected_evidence": [], "actual_evidence": [trace.extracted_output], "boundary_decision": {"within_evaluable_scope": None, "reasoning": error_text}, "downstream_impact": "fulfillment cannot be judged because judge call failed", "blocking": True, "confidence": None}],
            overall_fulfillment={"status": "not_evaluable", "assessment_count": 1, "blocking_expectations": [f"{spec.project_id}:judge_unavailable"]},
            expected=_generated_expected(trace, {"reasoning_summary": error_text}, trace.extracted_output),
            actual=trace.extracted_output,
            reconstructed_intent=str(trace.normalized_request or trace.input or ""),
            evaluation_boundary=boundary,
            primary_assessment=_fallback_primary_assessment(boundary, {"reasoning_summary": error_text}),
            judge_basis="llm_call_failed",
            intent_decomposition=[{"requirement": "current RunTrace semantic judgment", "evidence_source": "run_trace", "within_boundary": None}],
            condition_assessments=[{"requirement": "semantic judge result", "expected_fragment": None, "actual_fragment": trace.extracted_output, "status": "not_verified", "evidence": [error_text], "semantic_basis": "judge LLM call failed"}],
            reference_generation_basis=_reference_generation_basis(trace, expected_intent, {}, trace.extracted_output),
            boundary_decision={"within_evaluable_scope": None, "reasoning": error_text},
            judge_method="llm_call_failed",
            verdict_derivation={"why_verdict": "judge LLM call failed; verdict is uncertain", "blocking_gaps": [error_text]},
            evidence=[error_text],
            needs_human_review=True,
            quality_flags=["llm_call_failed"],
            raw_model_output=data,
        )
        return apply_boundary_reconciliation(trace, result, boundary_standard)
    evidence = list(data.get("evidence") or [])
    if not evidence and data.get("reasoning_summary"):
        evidence = [str(data.get("reasoning_summary"))]
    boundary = dict(data.get("evaluation_boundary") or {})
    if not boundary:
        boundary = _fallback_evaluation_boundary(judge_boundary)
    primary_assessment = dict(data.get("primary_assessment") or {})
    if not primary_assessment:
        primary_assessment = _fallback_primary_assessment(boundary, data)
    actual = data.get("actual")
    expected = _generated_expected(trace, data, actual)
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict=str(data.get("verdict") or "uncertain"),
        score=_score_from_verdict(data.get("verdict"), data.get("score")),
        confidence=_score_0_1(data.get("confidence")),
        probability=_score_0_1(data.get("probability")),
        intent_model=dict(data.get("intent_model") or {}),
        consumer_contract=dict(data.get("consumer_contract") or {}),
        business_expectations=list(data.get("business_expectations") or []),
        fulfillment_assessments=list(data.get("fulfillment_assessments") or []),
        overall_fulfillment=dict(data.get("overall_fulfillment") or {}),
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
        boundary_decision=dict(data.get("boundary_decision") or {}),
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
    return apply_boundary_reconciliation(trace, result, boundary_standard)
