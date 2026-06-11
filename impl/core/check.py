from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from .schema import AttributeResult, CheckReport, ClusterSummary, JudgeResult, ProjectSpec, RunTrace

DEFAULT_PROJECT_FIELD_MARKERS = []


def _score_in_range(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, (int, float)) and 0 <= value <= 1


def _attribute_taxonomy(spec: ProjectSpec) -> set[str]:
    taxonomy = spec.frontend_extensions.get("error_taxonomy") if spec.frontend_extensions else None
    return set(taxonomy or [])


def _check_rules(spec: ProjectSpec) -> dict[str, Any]:
    rules = spec.frontend_extensions.get("check_rules") if spec.frontend_extensions else None
    return rules if isinstance(rules, dict) else {}


def _project_document_gaps(spec: ProjectSpec) -> list[str]:
    gaps = []
    root = Path(spec.root)
    for key, rel in sorted((spec.documents or {}).items()):
        path = root / str(rel)
        if key.startswith("source_") and not path.exists():
            gaps.append(f"{spec.project_id} source document is missing: {key} -> {rel}")
    return gaps


def _downstream_boundary_gaps(trace: RunTrace, judge: Optional[JudgeResult]) -> list[str]:
    gaps = []
    downstream = trace.project_fields.get("downstream_search") if isinstance(trace.project_fields, dict) else None
    if not isinstance(downstream, dict) or not downstream:
        return gaps
    status = downstream.get("status")
    boundary = judge.boundary_decision if judge else {}
    if status == "ok":
        if judge and boundary.get("result_set_verified") is not True:
            gaps.append("Downstream search succeeded but JudgeResult does not mark boundary_decision.result_set_verified=true.")
        return gaps
    if judge:
        if boundary.get("result_set_verified") is True:
            gaps.append("Downstream search is unavailable/skipped but JudgeResult claims result_set_verified=true.")
        application_boundary = boundary.get("application_boundary") if isinstance(boundary, dict) else {}
        if application_boundary.get("judge_scope") != "parser_condition_semantics_only":
            gaps.append("Downstream search is unavailable/skipped but JudgeResult does not constrain application_boundary.judge_scope to parser_condition_semantics_only.")
        if judge and any(isinstance(item, dict) and item.get("application_boundary") for item in (judge.evidence or [])):
            gaps.append("Downstream search is unavailable/skipped; application boundary should be recorded in boundary_decision, not repeated as judge evidence.")
    if not downstream.get("payload") and status not in {"not_configured"}:
        gaps.append("Downstream search evidence is missing the attempted payload.")
    return gaps


def _field_values(value: Any) -> set[str]:
    fields = set()
    if isinstance(value, dict):
        field = value.get("field")
        if field:
            fields.add(str(field))
        for item in value.values():
            fields.update(_field_values(item))
    elif isinstance(value, list):
        for item in value:
            fields.update(_field_values(item))
    return fields


def _judge_fields(trace: Optional[RunTrace], judge: Optional[JudgeResult]) -> set[str]:
    fields = set()
    if trace:
        fields.update(_field_values(trace.normalized_request))
        fields.update(_field_values(trace.extracted_output))
        fields.update(_field_values(trace.project_fields))
    if judge:
        fields.update(_field_values(judge.expected))
        fields.update(_field_values(judge.actual))
        fields.update(_field_values(judge.missing))
        fields.update(_field_values(judge.wrong))
        fields.update(_field_values(judge.extra))
        fields.update(_field_values(judge.condition_assessments))
    return fields


def _attribute_claimed_fields(attribute: AttributeResult) -> set[str]:
    fields = set()
    fields.update(_field_values(attribute.suspected_locations))
    fields.update(_field_values(attribute.earliest_divergence))
    fields.update(_field_values(attribute.evidence_coverage))
    fields.update(_field_values(attribute.chain_nodes))
    return fields


def _attribute_consistency_gaps(trace: Optional[RunTrace], judge: Optional[JudgeResult], attribute: Optional[AttributeResult]) -> list[str]:
    if not judge or not attribute:
        return []
    gaps = []
    if judge.verdict == "correct":
        if attribute.failure_category != "none" or attribute.primary_error_type not in {"", "none"}:
            gaps.append("AttributeResult reports a failure even though JudgeResult verdict is correct.")
        return gaps
    if judge.verdict == "uncertain" and "llm_call_failed" in (judge.quality_flags or []) and attribute.analysis_quality.get("passed") is True:
        gaps.append("AttributeResult passed quality gate even though judge LLM failed; attribution should be incomplete or blocked.")
    if attribute.incomplete_reason and attribute.analysis_quality.get("passed") is True:
        gaps.append("AttributeResult has incomplete_reason but analysis_quality.passed=true.")
    if attribute.analysis_method and "fallback" in attribute.analysis_method and not attribute.local_verifications:
        gaps.append("Fallback attribution lacks local_verifications and should not be treated as canonical.")
    judge_fields = _judge_fields(trace, judge)
    claimed_fields = _attribute_claimed_fields(attribute)
    unrelated = sorted(field for field in claimed_fields if judge_fields and field not in judge_fields)
    if unrelated and attribute.analysis_quality.get("passed") is True:
        gaps.append("AttributeResult passed quality gate while claiming fields not present in current trace/judge evidence: " + ", ".join(unrelated[:6]))
    return gaps

def _semantic_rule_gaps(spec: ProjectSpec) -> list[str]:
    gaps = []
    extensions = spec.frontend_extensions or {}
    config = extensions.get("semantic_equivalence_rules")
    if not isinstance(config, dict):
        return gaps
    for group_name, rules in config.items():
        if not isinstance(rules, list):
            gaps.append(f"{spec.project_id} semantic_equivalence_rules.{group_name} must be a list of sourced rules.")
            continue
        for index, rule in enumerate(rules, 1):
            if not isinstance(rule, dict):
                gaps.append(f"{spec.project_id} semantic_equivalence_rules.{group_name}[{index}] must be an object.")
                continue
            basis = str(rule.get("basis") or rule.get("source") or rule.get("source_document") or "").strip()
            if not basis:
                gaps.append(f"{spec.project_id} semantic equivalence rule lacks source/basis: {group_name}[{index}].")
            text = " ".join(str(value) for value in rule.values())
            if any(marker in text for marker in ["case-", "seed-", "mock", "历史case", "历史 case"]):
                gaps.append(f"{spec.project_id} semantic equivalence rule appears tied to a historical/mock case instead of project semantics: {group_name}[{index}].")
    return gaps


def scan_core_boundary(root: Path, markers: Optional[Iterable[str]] = None) -> list[str]:
    markers = list(markers or DEFAULT_PROJECT_FIELD_MARKERS)
    violations = []
    if not markers:
        return violations
    core = root / "core"
    for path in core.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in markers:
            if marker in text:
                violations.append(f"generic core contains project-specific marker {marker}: {path}")
    return violations


def scan_protocol_alignment(root: Path) -> list[str]:
    gaps = []
    files = {
        "analysis.py": root / "core" / "analysis.py",
        "batch_run": root / "core" / "pipeline.py",
        "summary.html": root / "frontend" / "summary.html",
        "analysis_protocol.md": root / "protocols" / "analysis_protocol.md",
        "batch_protocol.md": root / "protocols" / "batch_protocol.md",
        "judge_boundary_template.md": root / "judge_boundary-template.md",
    }
    if files["analysis.py"].exists() and not files["analysis_protocol.md"].exists():
        gaps.append("ProjectAnalysis implementation exists without analysis_protocol.md.")
    if files["batch_run"].exists() and "batch_run" in files["batch_run"].read_text(encoding="utf-8", errors="ignore") and not files["batch_protocol.md"].exists():
        gaps.append("BatchRunResult implementation exists without batch_protocol.md.")
    if files["summary.html"].exists():
        text = files["summary.html"].read_text(encoding="utf-8", errors="ignore")
        if "Project Analysis" in text and not files["analysis_protocol.md"].exists():
            gaps.append("Frontend exposes Project Analysis without analysis protocol.")
        if "Batch Run" in text and not files["batch_protocol.md"].exists():
            gaps.append("Frontend exposes Batch Run without batch protocol.")
    if not files["judge_boundary_template.md"].exists():
        gaps.append("Judge boundary user template is missing: impl/judge_boundary-template.md.")
    return gaps


def check_chain(
    spec: ProjectSpec,
    trace: Optional[RunTrace] = None,
    judge: Optional[JudgeResult] = None,
    attribute: Optional[AttributeResult] = None,
    cluster: Optional[ClusterSummary] = None,
    impl_root: Optional[Path] = None,
) -> CheckReport:
    boundary_violations = []
    protocol_gaps = []
    consistency_gaps = []
    overfit_risks = []
    data_only_patch_risks = []
    verification_results = []
    recommended_fixes = []
    frontend_extensions = spec.frontend_extensions or {}

    if impl_root:
        markers = []
        if isinstance(frontend_extensions.get("core_forbidden_markers"), list):
            markers = frontend_extensions["core_forbidden_markers"]
        boundary_violations.extend(scan_core_boundary(impl_root, markers))
        protocol_gaps.extend(scan_protocol_alignment(impl_root))
    protocol_gaps.extend(_project_document_gaps(spec))
    overfit_risks.extend(_semantic_rule_gaps(spec))

    if not spec.adapter:
        protocol_gaps.append("ProjectSpec missing adapter.")
    if trace:
        if trace.project_id != spec.project_id:
            consistency_gaps.append("RunTrace project_id does not match ProjectSpec.")
        if not trace.normalized_request:
            protocol_gaps.append("RunTrace missing normalized_request.")
        if trace.raw_response is None and trace.status == "ok":
            protocol_gaps.append("RunTrace has ok status but no raw_response.")
        if not trace.execution_trace:
            protocol_gaps.append("RunTrace missing execution_trace for source -> API -> adapter verification.")
        consistency_gaps.extend(_downstream_boundary_gaps(trace, judge))
    else:
        protocol_gaps.append("Missing RunTrace; source -> run part of chain is not verified.")

    if judge:
        if trace and judge.trace_id != trace.trace_id:
            consistency_gaps.append("JudgeResult trace_id does not match RunTrace.")
        if judge.verdict not in {"correct", "incorrect", "uncertain"}:
            protocol_gaps.append("JudgeResult verdict must be correct/incorrect/uncertain.")
        if not _score_in_range(judge.score):
            protocol_gaps.append("JudgeResult score must be within 0-1 when present.")
        for detail in judge.score_details or []:
            if not _score_in_range(detail.get("score") if isinstance(detail, dict) else None):
                protocol_gaps.append("JudgeResult score_details scores must be within 0-1.")
                break
        if not judge.evidence:
            protocol_gaps.append("JudgeResult missing evidence.")
        if not judge.evaluation_boundary:
            protocol_gaps.append("JudgeResult missing evaluation_boundary; verdict boundary is unclear.")
        if not judge.primary_assessment:
            protocol_gaps.append("JudgeResult missing primary_assessment for the selected evaluation boundary.")
        if judge.verdict == "incorrect" and not (judge.missing or judge.wrong or judge.extra):
            protocol_gaps.append("Incorrect JudgeResult should identify missing/wrong/extra output or explain why unavailable.")
        if judge.verdict in {"incorrect", "uncertain"}:
            if not judge.intent_decomposition:
                protocol_gaps.append("JudgeResult missing intent_decomposition; verdict is not tied to current-query requirements.")
            if not judge.condition_assessments:
                protocol_gaps.append("JudgeResult missing condition_assessments; expected-vs-actual comparison is not inspectable.")
            if not judge.verdict_derivation:
                protocol_gaps.append("JudgeResult missing verdict_derivation; final verdict cannot be traced to comparison evidence and boundary decision.")
            if not judge.reference_generation_basis:
                protocol_gaps.append("JudgeResult missing reference_generation_basis; expected output source is unclear.")
            if judge.verdict == "uncertain" and not (judge.verdict_derivation or {}).get("blocking_gaps") and "llm_call_failed" not in (judge.quality_flags or []):
                protocol_gaps.append("Uncertain JudgeResult must identify blocking evidence gaps; use correct/incorrect when expected-vs-actual is inspectable.")
    else:
        protocol_gaps.append("Missing JudgeResult; run -> judge part of chain is not verified.")

    if attribute:
        if trace and attribute.trace_id != trace.trace_id:
            consistency_gaps.append("AttributeResult trace_id does not match RunTrace.")
        if not attribute.evidence_chain:
            protocol_gaps.append("AttributeResult missing evidence_chain.")
        if judge and judge.verdict in {"incorrect", "uncertain"} and not attribute.trace_analysis:
            protocol_gaps.append("Failure attribution missing trace_analysis; root cause is not tied to executable chain evidence.")
        if judge and judge.verdict in {"incorrect", "uncertain"} and not attribute.suspected_locations and not (attribute.root_cause_hypothesis or attribute.incomplete_reason):
            protocol_gaps.append("Failure attribution missing suspected_locations or explicit hypotheses for developer verification.")
        if not attribute.root_cause_hypothesis:
            protocol_gaps.append("AttributeResult missing root_cause_hypothesis.")
        if not attribute.verification_steps:
            protocol_gaps.append("AttributeResult missing verification_steps.")
        if not attribute.patch_direction:
            protocol_gaps.append("AttributeResult missing patch_direction.")
        if judge and judge.verdict in {"incorrect", "uncertain"}:
            if not attribute.analysis_method:
                protocol_gaps.append("Failure attribution missing analysis_method; source of attribution is unclear.")
            if not attribute.chain_nodes:
                protocol_gaps.append("Failure attribution missing chain_nodes; executable/documented path was not walked.")
            if not attribute.earliest_divergence and not attribute.incomplete_reason:
                protocol_gaps.append("Failure attribution missing earliest_divergence or explicit incomplete_reason.")
            if not attribute.analysis_quality:
                protocol_gaps.append("Failure attribution missing analysis_quality gate.")
            elif attribute.analysis_quality.get("passed") is False and not attribute.incomplete_reason:
                protocol_gaps.append("Failure attribution quality gate failed but incomplete_reason is missing.")
            if not attribute.evidence_coverage:
                protocol_gaps.append("Failure attribution missing evidence_coverage for current-case grounding.")
            if attribute.analysis_quality.get("passed") is True and attribute.suspected_locations:
                has_location_evidence = bool(attribute.evidence_coverage.get("code_or_config") or attribute.local_verifications)
                if not has_location_evidence:
                    protocol_gaps.append("Failure attribution passed quality gate with suspected_locations but no code/config or local verification evidence.")
        if attribute.primary_error_type and attribute.error_types and attribute.primary_error_type not in attribute.error_types and attribute.primary_error_type != "none":
            consistency_gaps.append("AttributeResult primary_error_type should appear in error_types.")
        consistency_gaps.extend(_attribute_consistency_gaps(trace, judge, attribute))
    elif judge and judge.verdict in {"incorrect", "uncertain"}:
        protocol_gaps.append("JudgeResult requires attribution, but AttributeResult is missing.")

    if cluster:
        for item in cluster.clusters:
            if not item.get("representative_cases"):
                protocol_gaps.append("Cluster missing representative_cases.")
                break

    check_rules = _check_rules(spec)
    if check_rules:
        taxonomy = _attribute_taxonomy(spec)
        scenario = trace.project_fields.get("scenario") if trace else ""
        normalized = trace.normalized_request if trace else {}
        if trace and trace.status == "ok" and check_rules.get("require_scenario") and not scenario:
            protocol_gaps.append(f"{spec.project_id} RunTrace missing scenario.")
        scenario_requirements = check_rules.get("scenario_requirements") or {}
        current_requirement = scenario_requirements.get(scenario) if isinstance(scenario_requirements, dict) else None
        if isinstance(current_requirement, dict):
            reference_field = current_requirement.get("reference_field")
            input_field = current_requirement.get("input_field")
            project_field = current_requirement.get("project_field")
            if reference_field and not (normalized.get("reference") or {}).get(reference_field):
                protocol_gaps.append(f"{spec.project_id} {scenario} requires reference.{reference_field}.")
            if input_field and not (normalized.get("input") or {}).get(input_field):
                protocol_gaps.append(f"{spec.project_id} {scenario} requires input.{input_field}.")
            if project_field and not trace.project_fields.get(project_field):
                protocol_gaps.append(f"{spec.project_id} {scenario} must be marked with project_fields.{project_field}.")
        if attribute and taxonomy:
            error_types = set(attribute.error_types or [])
            if attribute.primary_error_type:
                error_types.add(attribute.primary_error_type)
            unknown = sorted(error_types - taxonomy)
            if unknown:
                protocol_gaps.append(f"{spec.project_id} attribution error types outside taxonomy: " + ", ".join(unknown))

    if boundary_violations:
        recommended_fixes.append("Move project-specific fields into impl/projects/<project>/adapter.py or project_fields.")
    if protocol_gaps:
        recommended_fixes.append("Complete missing protocol outputs before treating the chain as valid.")
    if consistency_gaps:
        recommended_fixes.append("Ensure all steps use the same trace_id and latest run output.")

    passed = not (boundary_violations or protocol_gaps or consistency_gaps or overfit_risks or data_only_patch_risks)
    if passed:
        verification_results.append("Protocol chain passed current v1 checks.")
    return CheckReport(
        passed=passed,
        issues=boundary_violations + protocol_gaps + consistency_gaps + overfit_risks + data_only_patch_risks,
        boundary_violations=boundary_violations,
        protocol_gaps=protocol_gaps,
        consistency_gaps=consistency_gaps,
        overfit_risks=overfit_risks,
        data_only_patch_risks=data_only_patch_risks,
        verification_results=verification_results,
        recommended_fixes=recommended_fixes,
    )
