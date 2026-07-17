from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import AttributeResult, ExecutionTraceEvent, JudgeResult, ProjectSpec, RunTrace, normalize_attribute_result, to_dict, trace_execution_trace, trace_extracted_output

_STAGE_ORDER = [
    "request_normalization",
    "intent_recognition",
    "field_clarification",
    "session_merge",
    "path_dispatch",
    "planning_function",
    "result_assembly",
    "sse_generation",
    "adapter_extraction",
]

STAGE_FILE_PREFIXES: Dict[str, tuple] = {
    "request_normalization": ("app/api/", "app/schemas/request", "app/main.py"),
    "intent_recognition": (
        "app/workflow/steps/intent_recognition",
        "app/workflow/prompts/intent_",
        "app/schemas/intent",
        "app/config.py",
    ),
    "field_clarification": (
        "app/workflow/steps/field_clarification",
        "app/workflow/prompts/clarification",
        "app/services/session_store",
        "app/schemas/session",
    ),
    "session_merge": (
        "app/services/session_store",
        "app/workflow/steps/field_clarification",
        "app/schemas/session",
    ),
    "path_dispatch": (
        "app/workflow/steps/path_planning",
        "app/workflow/path_types",
        "app/workflow/nbev_workflow",
    ),
    "planning_function": (
        "app/services/planning/",
        "app/analysis_func/",
        "app/workflow/steps/path_planning",
    ),
    "result_assembly": (
        "app/workflow/steps/result_assembly",
        "app/services/card_formatter",
        "app/services/next_step_recommendation",
        "app/schemas/events",
    ),
    "sse_generation": (
        "app/api/",
        "app/schemas/events",
        "app/schemas/response",
        "app/workflow/nbev_workflow",
    ),
    "adapter_extraction": (),
}

ATTRIBUTE_CATALOG_FILE_CAP = 8


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, ExecutionTraceEvent):
        return {
            "stage": event.stage,
            "status": event.status,
            "evidence": event.evidence,
            "error": event.error,
            "inputs": event.inputs,
            "outputs": event.outputs,
            "metadata": event.metadata,
        }
    return event if isinstance(event, dict) else {}


def _execution_stage_probe(trace: RunTrace) -> dict[str, Any]:
    events = [_event_payload(event) for event in (trace.execution_trace or [])]
    observed = []
    failed = []
    for event in events:
        stage = str(event.get("stage") or event.get("name") or "")
        status = str(event.get("status") or "")
        if stage:
            observed.append({"stage": stage, "status": status, "evidence": event.get("evidence"), "error": event.get("error") or ""})
        if status in {"failed", "error", "blocked"}:
            failed.append({"stage": stage, "status": status, "evidence": event.get("evidence"), "error": event.get("error") or ""})
    observed_stages = [item["stage"] for item in observed if item["stage"]]
    earliest_missing = next((stage for stage in _STAGE_ORDER if stage not in observed_stages), None)
    return {
        "observed_stages": observed,
        "failed_stages": failed,
        "earliest_missing_expected_stage": earliest_missing,
        "stage_order": _STAGE_ORDER,
    }


def _planning_output_probe(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    if not isinstance(actual, dict):
        actual = {}
    expected_stage = reference.get("stage") or reference.get("expected_stage")
    actual_stage = actual.get("stage") or actual.get("current_stage")
    expected_paths = reference.get("path_types") or reference.get("expected_path_types") or []
    actual_paths = actual.get("path_types") or actual.get("paths") or []
    expected_cards = reference.get("cards") or reference.get("expected_cards") or []
    actual_cards = actual.get("cards") or actual.get("card_summary") or []
    expected_path_set = set(expected_paths) if isinstance(expected_paths, list) else set()
    actual_path_set = set(actual_paths) if isinstance(actual_paths, list) else set()
    return {
        "expected_stage": expected_stage,
        "actual_stage": actual_stage,
        "stage_match": bool(expected_stage) and expected_stage == actual_stage,
        "missing_path_types": sorted(expected_path_set - actual_path_set),
        "unexpected_path_types": sorted(actual_path_set - expected_path_set),
        "expected_cards_count": len(expected_cards) if isinstance(expected_cards, list) else None,
        "actual_cards_count": len(actual_cards) if isinstance(actual_cards, list) else None,
        "fallback": actual.get("fallback"),
        "errors": actual.get("errors") or [],
        "evidence_gap": [
            name
            for name, missing in (
                ("reference_contract", not bool(reference)),
                ("actual_output", not bool(actual)),
                ("expected_stage", expected_stage is None),
                ("actual_stage", actual_stage is None),
            )
            if missing
        ],
    }


def _application_boundary_from_trace(trace: RunTrace) -> dict[str, Any]:
    from impl.core.schema import trace_application_boundary
    boundary = trace_application_boundary(trace)
    if boundary:
        return boundary
    empty_boundary: dict[str, Any] = {}
    return empty_boundary


def _reference_contract(trace: RunTrace) -> dict[str, Any]:
    return trace.reference_contract if isinstance(trace.reference_contract, dict) else {}


def build_attribute_context(trace: RunTrace, judge_result: JudgeResult, spec: ProjectSpec) -> dict[str, Any]:
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
            p = Path(spec.root) / str(doc_rel)
            if p.exists():
                source_config_paths[f"project_doc:{doc_key}"] = str(p)
    return {
        "application_boundary": _application_boundary_from_trace(trace),
        "chain_nodes_to_check": list(trace.execution_trace or []),
        "earliest_stage_order": list(_STAGE_ORDER),
        "reference_contract": _reference_contract(trace),
        "output_summary": (trace.project_fields or {}).get("planning_summary") if isinstance(trace.project_fields, dict) else trace.extracted_output,
        "source_config_paths": source_config_paths,
        "attribute_standard": "Only attribute failures grounded in current RunTrace/JudgeResult/project docs; no historical-case field carryover. Use source_code_evidence to locate exact code/config responsible for the error.",
    }


def get_runtime_checks(runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = context or {}
    expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
    actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
    checks: Dict[str, Any] = {}
    expected_stage = expected.get("expected_stage") or expected.get("stage")
    actual_stage = actual.get("stage") or actual.get("current_stage")
    if expected_stage or actual_stage:
        checks["stage_match"] = {
            "expected": expected_stage,
            "actual": actual_stage,
            "match": bool(expected_stage) and expected_stage == actual_stage,
        }
    if runtime_values:
        checks["runtime_values"] = runtime_values
    reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
    if reference:
        checks["reference_contract"] = reference
    return checks


def apply_attribution_probes(trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
    target_probe = target_value_unit_probe(trace, judge_result)
    if not target_probe:
        return attribute_result
    attribute_result.suspected_locations = [{
        "location": "request_normalization",
        "evidence": list(target_probe.get("evidence") or []),
        "findings": target_probe,
    }]
    attribute_result.evidence = list(target_probe.get("evidence") or [])
    attribute_result.evidence_strength = "strong"
    attribute_result.root_cause_hypothesis = f"当前 query 含目标值 {target_probe.get('source_amount')}，按项目内部单位应为 {target_probe.get('expected_target_nbev_wan')} 万，实际链路使用 {target_probe.get('actual_target_nbev_wan')} 万，最早差异位于请求归一化/目标值单位转换。"
    return attribute_result


def normalize_attribute_result_for_project(trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
    overall = judge_result.overall_fulfillment or {}
    if overall.get("status") == "fulfilled":
        if not attribute_result.expectation_attributions:
            expectation_id = "marketting-planning:planning_output_contract"
            if judge_result.business_expectations:
                first = judge_result.business_expectations[0]
                expectation_id = first.get("expectation_id", expectation_id) if isinstance(first, dict) else getattr(first, "expectation_id", expectation_id)
            evidence = list(judge_result.evidence or ["planning output contract fulfilled"])
            attribute_result.expectation_attributions = [{"expectation_id": expectation_id, "fulfillment_status": "fulfilled", "suspected_locations": [], "root_cause_hypothesis": "当前 planning 输出满足业务预期，归因结论为 no_issue。", "evidence": evidence}]
        attribute_result.suspected_locations = []
        attribute_result.root_cause_hypothesis = "当前 planning 输出满足业务预期，归因结论为 no_issue。"
        return attribute_result
    return apply_attribution_probes(trace, judge_result, attribute_result)


def attribution_probes(trace: RunTrace, judge_result: JudgeResult):
    target_probe = target_value_unit_probe(trace, judge_result)
    return [target_probe] if target_probe else []


def target_value_unit_probe(trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    evidence_text = _target_value_error_evidence(judge_result)
    if not evidence_text:
        return {}
    trace_input = trace.input or {}
    normalized_request = trace.normalized_request or {}
    turns = normalized_request.get("turns") if isinstance(normalized_request.get("turns"), list) else []
    query = str(
        normalized_request.get("query")
        or (turns[-1].get("content") if turns and isinstance(turns[-1], dict) else "")
        or normalized_request.get("user_intent")
        or trace_input.get("query")
        or ""
    )
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*亿", query)
    if not amount_match:
        return {}
    expected = int(float(amount_match.group(1)) * 10000)
    actual = _find_target_nbev_wan(judge_result.actual)
    if actual is None:
        actual = _find_target_nbev_wan(judge_result.wrong)
    if actual is None:
        actual = _find_target_nbev_wan(trace.extracted_output)
    if actual is None or actual == expected:
        return {}
    return {
        "method": "target_value_unit_probe",
        "source_amount": amount_match.group(0),
        "expected_target_nbev_wan": expected,
        "actual_target_nbev_wan": actual,
        "result": "mismatch reproduced",
        "evidence": [f"query contains {amount_match.group(0)}", f"expected {expected} 万", f"actual {actual} 万", evidence_text],
    }


def _target_value_error_evidence(judge_result: JudgeResult) -> str:
    evidence_text = json.dumps(to_dict([judge_result.expected, judge_result.wrong, judge_result.actual, judge_result.fulfillment_assessments]), ensure_ascii=False)
    has_target = any(token in evidence_text for token in ("targetNbev", "target_value", "target_value_wan", "目标值", "NBEV"))
    has_wrong_status = '"status": "wrong"' in evidence_text or "数值错误" in evidence_text or "误差" in evidence_text
    if has_target and (has_wrong_status or "target_value_wan" in evidence_text):
        return evidence_text[:500]
    return ""


def _find_target_nbev_wan(value: Any) -> Any:
    if isinstance(value, dict):
        if "actual_fragment" in value:
            found = _find_target_nbev_wan(value.get("actual_fragment"))
            if found is not None:
                return found
        for key in ("target_nbev_wan", "target_value_wan", "targetNbev", "forecast_value"):
            if key in value and isinstance(value.get(key), (int, float)):
                return int(value[key])
        for key, item in value.items():
            if key == "expected_fragment":
                continue
            found = _find_target_nbev_wan(item)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_target_nbev_wan(item)
            if found is not None:
                return found
    return None


def _build_project_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    application_boundary = _application_boundary_from_trace(trace)
    target_probe = target_value_unit_probe(trace, judge_result) or {}
    execution_probe = _execution_stage_probe(trace)
    planning_probe = _planning_output_probe(trace, judge_result)
    return {
        "tool_call_limit": 4,
        "system_prompt_override": """你是 marketting-planning 项目的 attribute agent。
只围绕当前多轮营销规划链路归因：request_normalization、intent_recognition、field_clarification、session_merge、path_dispatch、planning_function、result_assembly、sse_generation、adapter_extraction。
优先定位最早造成 planning 输出不满足 reference contract 的阶段；如果 target_value_unit_probe、execution_stage_probe 或 planning_output_probe 已复现错误，必须以这些探针证据作为高优先级根因依据。
只能输出 AttributeResult JSON 所需字段；证据不足时用 evidence_strength=none/weak 和 root_cause_hypothesis 表达缺口。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": _STAGE_ORDER,
                "root_cause_policy": "按 stage_order 读取 execution_stage_probe 和 planning_output_probe，查找当前 trace 中最早的失败、缺失阶段或 reference/actual 差异；不能把多轮上下文、shared_session 或外部仓库边界外问题混入当前可控链路。",
                "probe_priority": "target_value_unit_probe、execution_stage_probe、planning_output_probe 优先于 LLM 猜测；探针证据为空时再用 judge gaps 和 execution_trace 定位。",
                "evidence_contract": ["normalized_request.turns", "reference_contract", "planning_summary", "execution_trace", "runtime_checks", "target_value_unit_probe", "execution_stage_probe", "planning_output_probe"],
            },
            "application_boundary": application_boundary,
            "target_value_unit_probe": target_probe,
            "execution_stage_probe": execution_probe,
            "planning_output_probe": planning_probe,
        },
    }
class MarketingPlanningAttribute(ProjectAttribute):
    """marketting-planning 项目 Attribute 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        base_context = build_attribute_context(trace, judge_result, self.spec)
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
        return attribution_probes

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        result = normalize_attribute_result_for_project(trace, judge_result, result)
        return normalize_attribute_result(result) or result


# Shared helpers kept in this module for project-local attribute flow.

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

    def rank(p: Path) -> tuple:
        rel = str(p.relative_to(ext_path))
        for i, prefix in enumerate(priority_prefixes):
            if rel.startswith(prefix):
                return (i, rel)
        return (len(priority_prefixes), rel)

    candidates = [
        p for p in ext_path.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    ]
    return sorted(candidates, key=rank)[:limit]


def trace_failure_stages(trace) -> List[str]:
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


def select_ext_repo_files_by_stage(ext_path: Path, trace) -> List[Path]:
    implicated = trace_failure_stages(trace)
    if not implicated:
        chain = getattr(trace, "execution_trace", None) or []
        if chain and isinstance(chain[-1], dict):
            last_stage = chain[-1].get("stage") or chain[-1].get("node")
            if last_stage:
                implicated = [last_stage]
    if not implicated:
        implicated = ["intent_recognition"]

    prefix_union: List[str] = []
    for stage in implicated:
        for prefix in STAGE_FILE_PREFIXES.get(stage, ()):
            if prefix not in prefix_union:
                prefix_union.append(prefix)

    if not prefix_union:
        return prioritized_ext_repo_files(ext_path, limit=3)

    candidates = [
        p for p in ext_path.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    ]

    def matches_prefix(rel: str) -> Optional[int]:
        for i, prefix in enumerate(prefix_union):
            if rel.startswith(prefix):
                return i
        return None

    scored: List[tuple] = []
    for p in candidates:
        rel = str(p.relative_to(ext_path))
        idx = matches_prefix(rel)
        if idx is None:
            continue
        scored.append((idx, rel, p))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [p for _, _, p in scored[:ATTRIBUTE_CATALOG_FILE_CAP]]
