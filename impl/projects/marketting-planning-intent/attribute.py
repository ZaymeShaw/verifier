from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


STAGE_FILE_PREFIXES: Dict[str, tuple] = {
    "request_normalization": ("app/api/", "app/schemas/request", "app/main.py"),
    "intent_api_call": (
        "app/workflow/steps/intent_recognition.py",
        "app/workflow/prompts/intent_prompt.py",
        "app/schemas/intent.py",
        "app/config.py",
        "app/utils/llm_client.py",
    ),
    "adapter_extraction": (),
    "label_mapping": (
        "app/workflow/steps/intent_recognition.py",
        "app/schemas/intent.py",
        "app/config.py",
    ),
}

ATTRIBUTE_CATALOG_FILE_CAP = 8


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _intent_contract_probe(reference: dict[str, Any], actual: dict[str, Any], intent_evidence: dict[str, Any]) -> dict[str, Any]:
    expected_intent = _first_present(reference, ("intent", "user_intent", "label"))
    actual_intent = _first_present(actual, ("intent", "recognized_intent", "label", "raw_intent"))
    evidence_intent = _first_present(intent_evidence, ("intent", "recognized_intent", "label", "raw_intent"))
    expected_slots = reference.get("required_slots") or reference.get("slots") or []
    actual_slots = actual.get("slots") or actual.get("entities") or intent_evidence.get("slots") or intent_evidence.get("entities") or []
    expected_slot_set = set(expected_slots) if isinstance(expected_slots, list) else set()
    actual_slot_set = set(actual_slots) if isinstance(actual_slots, list) else set()
    expected_min_confidence = reference.get("min_confidence") or reference.get("confidence_threshold")
    actual_confidence = actual.get("confidence") if actual.get("confidence") is not None else intent_evidence.get("confidence")
    confidence_gap = None
    if isinstance(expected_min_confidence, (int, float)) and isinstance(actual_confidence, (int, float)):
        confidence_gap = round(float(actual_confidence) - float(expected_min_confidence), 4)
    return {
        "expected_intent": expected_intent,
        "actual_intent": actual_intent,
        "evidence_intent": evidence_intent,
        "intent_match": expected_intent is not None and expected_intent in (actual_intent, evidence_intent),
        "missing_required_slots": sorted(expected_slot_set - actual_slot_set),
        "actual_confidence": actual_confidence,
        "expected_min_confidence": expected_min_confidence,
        "confidence_gap": confidence_gap,
        "fallback_expected": bool(reference.get("fallback") or reference.get("allow_fallback")),
        "fallback_observed": bool(actual.get("fallback") or intent_evidence.get("fallback")),
        "evidence_gap": [
            name
            for name, missing in (
                ("expected_intent", expected_intent is None),
                ("actual_intent", actual_intent is None and evidence_intent is None),
                ("intent_evidence", not bool(intent_evidence)),
            )
            if missing
        ],
    }


def prioritized_ext_repo_files(ext_path: Path, limit: int = 100) -> List[Path]:
    priority_prefixes = (
        "app/workflow/steps/",
        "app/workflow/prompts/",
        "app/workflow/",
        "app/services/",
        "app/configs/",
        "app/schemas/",
        "app/api/",
        "app/analysis_func/",
        "app/fallback/",
        "app/utils/",
        "app/",
    )

    def rank(path: Path) -> tuple:
        rel = str(path.relative_to(ext_path))
        for i, prefix in enumerate(priority_prefixes):
            if rel.startswith(prefix):
                return (i, rel)
        return (len(priority_prefixes), rel)

    candidates = [
        path for path in ext_path.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    ]
    return sorted(candidates, key=rank)[:limit]


def trace_failure_stages(trace: RunTrace) -> List[str]:
    exec_trace = getattr(trace, "execution_trace", None) or []
    stages: List[str] = []
    for node in exec_trace:
        if not isinstance(node, dict):
            continue
        stage = node.get("stage") or node.get("node") or node.get("name")
        status = node.get("status")
        if stage and status in {"failed", "suspicious"} and stage not in stages:
            stages.append(stage)
    return stages


def select_ext_repo_files_by_stage(ext_path: Path, trace: RunTrace) -> List[Path]:
    implicated = trace_failure_stages(trace)
    if not implicated:
        chain = getattr(trace, "execution_trace", None) or []
        if chain and isinstance(chain[-1], dict):
            last_stage = chain[-1].get("stage") or chain[-1].get("node")
            if last_stage:
                implicated = [last_stage]
    if not implicated:
        implicated = ["intent_api_call"]

    prefix_union: List[str] = []
    for stage in implicated:
        for prefix in STAGE_FILE_PREFIXES.get(stage, ()):  # type: ignore[arg-type]
            if prefix not in prefix_union:
                prefix_union.append(prefix)

    if not prefix_union:
        return prioritized_ext_repo_files(ext_path, limit=3)

    candidates = [
        path for path in ext_path.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    ]

    def matches_prefix(rel: str) -> int | None:
        for i, prefix in enumerate(prefix_union):
            if rel.startswith(prefix):
                return i
        return None

    scored: List[tuple[int, str, Path]] = []
    for path in candidates:
        rel = str(path.relative_to(ext_path))
        idx = matches_prefix(rel)
        if idx is None:
            continue
        scored.append((idx, rel, path))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [path for _, _, path in scored[:ATTRIBUTE_CATALOG_FILE_CAP]]


def build_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    source_config_paths = {}
    ext_repo = spec.application.get("external_repo") if isinstance(spec.application, dict) else None
    if ext_repo:
        ext_path = Path(ext_repo)
        if ext_path.exists():
            for py_file in select_ext_repo_files_by_stage(ext_path, trace):
                try:
                    source_config_paths[f"ext_repo:{py_file.relative_to(ext_path)}"] = str(py_file)
                except Exception:
                    pass
    for doc_key, doc_rel in (spec.documents or {}).items():
        if doc_key.startswith("source_"):
            path = Path(spec.root) / str(doc_rel)
            if path.exists():
                source_config_paths[f"project_doc:{doc_key}"] = str(path)
    return {
        "chain_nodes_to_check": list(trace.execution_trace or []),
        "earliest_stage_order": ["request_normalization", "intent_api_call", "adapter_extraction", "label_mapping"],
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "source_config_paths": source_config_paths,
        "attribute_standard": "Only attribute current single-turn intent-recognition failures; do not attribute planning/SSE generation gaps here. Use source_code_evidence to locate exact config/code/prompt responsible for the error.",
    }


def build_default_consumer_contract(trace: RunTrace) -> Dict[str, Any]:
    from importlib import import_module
    context = import_module("impl.projects.marketting-planning-intent.judge").build_judge_context(trace)
    return {
        "consumer": "marketing intent router",
        "contract": "single-turn query must resolve to the expected intent, required slots/entities, confidence threshold, and fallback policy before planning starts",
        "reference_contract": context.get("reference_contract") or {},
        "application_boundary": context.get("application_boundary") or {},
    }


def build_default_business_expectation(trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    from importlib import import_module
    expectation = {
        "expectation_id": "marketting-planning-intent:intent_contract",
        "downstream_consumer": "marketing intent router",
        "required_capabilities": ["intent_label", "slot_extraction", "confidence_threshold", "fallback_control"],
        "boundary": import_module("impl.projects.marketting-planning-intent.judge").build_judge_context(trace).get("application_boundary") or {},
    }
    expectation.update(
        {
            "user_intent": str((trace.normalized_request or {}).get("query") or trace.input or ""),
            "expected_outcome": "single-turn intent recognition should return the expected label, required slots/entities, acceptable confidence, and permitted fallback behavior",
            "acceptance_criteria": list(judge_result.missing or judge_result.wrong or []),
        }
    )
    return expectation


def build_default_fulfillment_assessment(trace: RunTrace, judge_result: JudgeResult, expectation: Dict[str, Any]) -> Dict[str, Any]:
    overall = judge_result.overall_fulfillment or {}
    status = overall.get("status") or "not_evaluable"
    return {
        "expectation_id": expectation.get("expectation_id"),
        "status": status,
        "expected_evidence": list(judge_result.missing or []) or [judge_result.expected or trace.reference_contract or {}],
        "actual_evidence": list(judge_result.wrong or []) or [judge_result.actual or trace.extracted_output],
        "downstream_impact": "intent router can safely dispatch to the next planning step" if status == "fulfilled" else (judge_result.reasoning_summary or "intent router cannot safely dispatch this query to the expected planning path"),
        "blocking": status in {"not_fulfilled", "not_evaluable"},
        "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
    }


def get_runtime_checks(runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = context or {}
    raw_intent = runtime_values.get("raw_intent") or runtime_values.get("raw_output")
    actual_intent = runtime_values.get("intent") or (context.get("actual") if isinstance(context.get("actual"), str) else None)
    actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
    expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
    reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
    actual_intent = actual_intent or actual.get("intent")
    expected_intent = expected.get("intent") or reference.get("intent") or context.get("user_intent")
    if not raw_intent and not actual_intent and not expected_intent:
        return {"tool_type": "runtime_check", "check_type": "intent_mapping", "status": "not_applicable", "evidence": ["当前 trace 未提供 intent 映射检查所需的 raw_intent/intent/reference。"]}

    if raw_intent is None:
        return {
            "tool_type": "runtime_check",
            "check_type": "intent_mapping",
            "status": "inconclusive",
            "raw_intent": None,
            "actual_intent": actual_intent,
            "expected_intent": expected_intent,
            "evidence": [
                "当前 trace 未提供业务系统映射前的 raw_intent，不能验证标签映射机制。",
                f"actual_intent={actual_intent}",
                f"expected_intent={expected_intent}",
            ],
            "root_cause": None,
            "fix_suggestion": "",
            "confidence": "low",
        }

    mapping, enum_values, source = _load_intent_mapping_source()
    actual_mapping = mapping.get(str(raw_intent))
    if actual_mapping is None:
        actual_mapping = actual_intent or "other"
    is_in_mapping = str(raw_intent) in mapping
    is_expected_mapping = bool(expected_intent) and actual_mapping == expected_intent
    status = "passed" if (not expected_intent or is_expected_mapping) else "failed"
    evidence = [
        f"raw_intent={raw_intent}",
        f"actual_mapping={actual_mapping}",
        f"actual_intent={actual_intent}",
        f"expected_intent={expected_intent}",
        f"mapping_source={source}",
    ]
    root_cause = None
    fix_suggestion = ""
    if status == "failed":
        root_cause = {
            "category": "label_mapping",
            "summary": f"运行时 raw_intent={raw_intent} 经项目映射得到 {actual_mapping}，但当前 reference contract 期望 {expected_intent}。",
            "evidence": evidence,
            "confidence": "high",
            "fix_suggestion": f"在项目意图映射源头校准 raw_intent={raw_intent} 的映射，或修正上游意图识别使其输出与 reference contract 一致的编码。",
        }
        fix_suggestion = root_cause["fix_suggestion"]
    return {
        "tool_type": "runtime_check",
        "check_type": "intent_mapping",
        "status": status,
        "raw_intent": raw_intent,
        "actual_mapping": actual_mapping,
        "actual_intent": actual_intent,
        "expected_intent": expected_intent,
        "is_in_mapping": is_in_mapping,
        "is_expected_mapping": is_expected_mapping,
        "available_mapping_count": len(mapping),
        "enum_values": enum_values,
        "evidence": evidence,
        "source": source,
        "root_cause": root_cause,
        "fix_suggestion": fix_suggestion,
        "confidence": "high" if status in {"passed", "failed"} else "low",
    }


def _load_intent_mapping_source() -> tuple[Dict[str, str], List[str], str]:
    source_path = Path(__file__).resolve().parents[3] / "projects" / "marketting-planning-intent" / "intent.py"
    source = "projects/marketting-planning-intent/intent.py:INTENT_MAPPING"
    spec = importlib.util.spec_from_file_location("marketting_planning_intent_runtime_source", source_path)
    if spec is None or spec.loader is None:
        return {}, [], source
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mapping = dict(getattr(module, "INTENT_MAPPING", {}) or {})
    intent_type = getattr(module, "IntentType", None)
    enum_values = [item.value for item in intent_type] if intent_type else []
    return mapping, enum_values, source


def _build_project_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    intent_evidence = (trace.project_fields or {}).get("intent_evidence", {}) if isinstance(trace.project_fields, dict) else {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    actual_payload = actual if isinstance(actual, dict) else {}
    intent_probe = _intent_contract_probe(reference, actual_payload, intent_evidence if isinstance(intent_evidence, dict) else {})
    return {
        "tool_call_limit": 4,
        "system_prompt_override": """你是 marketting-planning-intent 项目的 attribute agent。
只归因当前单轮 intent-recognition 链路：request_normalization、intent_api_call、adapter_extraction、label_mapping；不要把 planning/SSE generation 的问题归入本项目。
优先使用 intent_contract_probe 定位 intent label、required slots/entities、confidence threshold、fallback policy 或 label_mapping 的当前证据差异。
只调查 not_fulfilled expectation，按真实缺陷合并 findings。证据不足时不输出 hypothesis，只写一个 unresolved_reason。最终只输出 findings、unresolved_reason，evidence 仅引用 Finalization 重载的 ContextUnit。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["request_normalization", "intent_api_call", "adapter_extraction", "label_mapping"],
                "root_cause_policy": "先读取 intent_contract_probe 的 intent_match、missing_required_slots、confidence_gap、fallback 差异，再结合 runtime_checks 判断是否为映射或证据缺失。",
                "scope_boundary": "single-turn intent-recognition only; planning path output is out of scope",
                "evidence_contract": ["normalized_request.query", "reference_contract", "trace.project_fields.intent_evidence", "intent_contract_probe", "judge_result.fulfillment_assessments", "runtime_checks"],
            },
            "reference_contract": reference,
            "actual_intent_output": actual,
            "intent_evidence": intent_evidence,
            "intent_contract_probe": intent_probe,
        },
    }
from impl.core.attribute_protocol import ProjectAttribute
from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import normalize_attribute_result as normalize_core_attribute_result, trace_execution_trace, trace_extracted_output


class MarketingIntentAttribute(ProjectAttribute):
    """marketting-planning-intent 项目 Attribute 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        base_context = build_attribute_context(self.spec, trace, judge_result)
        extra_context = _build_project_attribute_context(self.spec, trace, judge_result)
        context = dict(base_context or {})
        context.update(extra_context)
        actual = judge_result.actual or trace_extracted_output(trace) or {}
        expected = judge_result.expected or trace.reference_contract or {}
        runtime_context = {
            "expected": expected,
            "actual": actual,
            "reference": trace.reference_contract or {},
            "trace_id": trace.trace_id,
            "project_id": trace.project_id,
        }
        runtime_values = extract_runtime_values(trace_execution_trace(trace), actual)
        context["runtime_checks"] = get_runtime_checks(runtime_values, runtime_context)
        return context

    def probes(self):
        return None

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        return normalize_core_attribute_result(result) or result
