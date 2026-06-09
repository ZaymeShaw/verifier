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

    if impl_root:
        markers = []
        frontend_extensions = spec.frontend_extensions or {}
        if isinstance(frontend_extensions.get("core_forbidden_markers"), list):
            markers = frontend_extensions["core_forbidden_markers"]
        boundary_violations.extend(scan_core_boundary(impl_root, markers))
        protocol_gaps.extend(scan_protocol_alignment(impl_root))

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
    else:
        protocol_gaps.append("Missing JudgeResult; run -> judge part of chain is not verified.")

    if attribute:
        if trace and attribute.trace_id != trace.trace_id:
            consistency_gaps.append("AttributeResult trace_id does not match RunTrace.")
        if not attribute.evidence_chain:
            protocol_gaps.append("AttributeResult missing evidence_chain.")
        if judge and judge.verdict in {"incorrect", "uncertain"} and not attribute.trace_analysis:
            protocol_gaps.append("Failure attribution missing trace_analysis; root cause is not tied to executable chain evidence.")
        if judge and judge.verdict in {"incorrect", "uncertain"} and not attribute.suspected_locations:
            protocol_gaps.append("Failure attribution missing suspected_locations or explicit hypotheses for developer verification.")
        if not attribute.root_cause_hypothesis:
            protocol_gaps.append("AttributeResult missing root_cause_hypothesis.")
        if not attribute.verification_steps:
            protocol_gaps.append("AttributeResult missing verification_steps.")
        if not attribute.patch_direction:
            protocol_gaps.append("AttributeResult missing patch_direction.")
        if attribute.primary_error_type and attribute.error_types and attribute.primary_error_type not in attribute.error_types and attribute.primary_error_type != "none":
            consistency_gaps.append("AttributeResult primary_error_type should appear in error_types.")
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
