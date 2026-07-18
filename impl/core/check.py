from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable, Optional

from .schema import AttributeResult, CheckReport, ClusterSummary, FallbackDecision, JudgeResult, ProjectSpec, RunTrace, judge_expected_actual_gaps, judge_primary_signal, trace_application_boundary, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_raw_response

DEFAULT_PROJECT_FIELD_MARKERS = []

REQUIRED_AGENT_ROLES = ["analysis", "application", "build", "mock", "judge", "attribute", "check"]
REQUIRED_AGENT_ROLE_FIELDS = ["owned capability", "trigger", "inputs", "outputs", "allowed implementation scope", "handoff"]
REQUIRED_TRIGGER_PHASES = ["project initialization", "project information update", "business project update", "prebuilt batch mock generation", "trace runtime", "post-trace analysis"]
CLAUDE_SUBAGENT_ROLES = ["analysis", "application", "build", "check"]
RUNTIME_SCRIPT_AGENT_ROLES = ["mock", "judge", "attribute"]
REQUIRED_ROLE_RESPONSIBILITY_MARKERS = {
    "analysis": {
        "api call chain": ["api call chain"],
        "api document": ["api document", "api understanding"],
        "mock strategy": ["mock strategy"],
        "frontend architecture": ["frontend architecture", "frontend adaptation"],
        "judge standard": ["judge standard"],
        "attribution trace plan": ["attribution trace plan"],
        "key pipeline links": ["key pipeline", "key code"],
    },
    "application": {
        "context-independent environment": ["context-independent environment", "independent environment"],
        "existing service startup": ["existing service", "service startup"],
        "generated service or pipeline": ["generated service", "simulated service", "pipeline"],
        "application folder standard": ["application folder", "application standard", "startup/run standard"],
        "self verification": ["self verification", "health checks"],
    },
    "build": {
        "analysis handoff": ["analysis output", "analysis handoff"],
        "frontend construction": ["frontend construction"],
        "project frontend standards": ["project frontend standards"],
    },
}
REQUIRED_PROTOCOL_MARKERS = {
    "analysis_protocol.md": [
        "api call chain",
        "api document",
        "mock strategy",
        "frontend architecture",
        "judge standard",
        "attribution trace plan",
        "key pipeline",
    ],
    "application_protocol.md": [
        "context-independent environment",
        "existing service",
        "generated service",
        "application folder",
        "self verification",
    ],
    "frontend_build_standard.md": [
        "analysis output",
        "frontend construction",
        "project frontend standards",
    ],
}
REQUIRED_PROJECT_STANDARD_FIELDS = [
    "api",
    "application",
    "request_construction",
    "output_extraction",
    "reference_handling",
    "judge_boundary",
    "attribution_trace",
    "frontend_view",
    "batch_persistence",
    "check_evidence",
]


def _normalized_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").lower().replace("_", "-")


def audit_agent_role_protocol(path: Path) -> list[str]:
    text = _normalized_text(path)
    gaps = []
    if not text:
        return [f"missing protocol: {path}"]
    for role in REQUIRED_AGENT_ROLES:
        if f"{role} agent" not in text and role not in text:
            gaps.append(f"missing agent role: {role}")
    for field in REQUIRED_AGENT_ROLE_FIELDS:
        if field not in text:
            gaps.append(f"missing agent role field: {field}")
    for phase in REQUIRED_TRIGGER_PHASES:
        if phase not in text:
            gaps.append(f"missing trigger phase: {phase}")
    for role in CLAUDE_SUBAGENT_ROLES:
        if f"{role} agent" in text and "claude subagent" not in _role_section(text, role):
            gaps.append(f"{role} agent missing execution backend: claude subagent")
    for role in RUNTIME_SCRIPT_AGENT_ROLES:
        if f"{role} agent" in text and "runtime script agent" not in _role_section(text, role):
            gaps.append(f"{role} agent missing execution backend: runtime script agent")
    for role, responsibilities in REQUIRED_ROLE_RESPONSIBILITY_MARKERS.items():
        section = _role_section(text, role)
        if not section:
            continue
        for responsibility, markers in responsibilities.items():
            if not any(marker in section for marker in markers):
                gaps.append(f"{role} agent missing demand responsibility: {responsibility}")
    return gaps


def _role_section(text: str, role: str) -> str:
    marker = f"## {role} agent"
    start = text.find(marker)
    if start < 0:
        return ""
    next_start = text.find("\n## ", start + len(marker))
    return text[start:] if next_start < 0 else text[start:next_start]



def audit_required_protocol_markers(protocols_root: Path) -> list[str]:
    gaps = []
    for filename, markers in REQUIRED_PROTOCOL_MARKERS.items():
        path = protocols_root / filename
        text = _normalized_text(path)
        if not text:
            gaps.append(f"missing protocol: impl/protocols/{filename}")
            continue
        for marker in markers:
            if marker not in text:
                gaps.append(f"{filename} missing demand marker: {marker}")
    return gaps

def audit_project_implementation_standard(spec: ProjectSpec) -> list[str]:
    gaps = []
    docs = spec.documents or {}
    extensions = spec.frontend_extensions or {}
    app_doc = docs.get("application")
    project_root = Path(spec.root) if spec.root else Path("impl") / "projects" / spec.project_id
    app_text = _normalized_text(project_root / str(app_doc)) if app_doc else ""
    if "frontend" in app_text and ("start" in app_text or "startup" in app_text):
        gaps.append(f"{spec.project_id} application document contains frontend startup owned by build agent")
    standard = extensions.get("implementation_standard") if isinstance(extensions.get("implementation_standard"), dict) else {}
    sources = {
        "api": spec.api,
        "application": spec.application or docs.get("application"),
        "request_construction": standard.get("request_construction") or extensions.get("request_construction"),
        "output_extraction": standard.get("output_extraction") or extensions.get("output_extraction"),
        "reference_handling": standard.get("reference_handling") or extensions.get("reference_handling"),
        "judge_boundary": standard.get("judge_boundary") or docs.get("judge_boundary") or docs.get("evaluation"),
        "attribution_trace": standard.get("attribution_trace") or docs.get("attribution"),
        "frontend_view": standard.get("frontend_view") or extensions.get("frontend_view") or docs.get("frontend"),
        "batch_persistence": standard.get("batch_persistence") or extensions.get("batch_persistence"),
        "check_evidence": standard.get("check_evidence") or docs.get("checklist"),
    }
    for field in REQUIRED_PROJECT_STANDARD_FIELDS:
        if not sources.get(field):
            gaps.append(f"{spec.project_id} missing project implementation field: {field}")
    return gaps


def _load_project_specs_from_root(root: Path) -> list[ProjectSpec]:
    from .project_loader import load_simple_yaml, _resolve_source_project

    specs = []
    projects_root = root / "impl" / "projects"
    if not projects_root.exists():
        return specs
    for cfg_path in sorted(projects_root.glob("*/project.yaml")):
        data = load_simple_yaml(cfg_path)
        project_root = cfg_path.parent
        specs.append(
            ProjectSpec(
                project_id=str(data.get("project_id") or project_root.name),
                name=str(data.get("name") or project_root.name),
                description=str(data.get("description") or ""),
                adapter=str(data.get("adapter") or "adapter.py"),
                capabilities=list(data.get("capabilities") or []),
                documents=dict(data.get("documents") or {}),
                api=dict(data.get("api") or {}),
                application=dict(data.get("application") or {}),
                frontend_extensions=dict(data.get("frontend_extensions") or {}),
                root=str(project_root),
                source_project=_resolve_source_project(data, project_root),
            )
        )
    return specs


def _read_optional_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _extract_terms(text: str, candidates: Iterable[str]) -> list[str]:
    found = []
    for term in candidates:
        if term in text and term not in found:
            found.append(term)
    return found


def _demand_path(root: Path) -> Path:
    direct = root / "demand.md"
    if direct.exists():
        return direct
    nested = root / "demand" / "demand.md"
    if nested.exists():
        return nested
    return direct


def reconstruct_current_intent(root: Path, specs: Optional[Iterable[ProjectSpec]] = None) -> dict[str, Any]:
    demand_path = _demand_path(root)
    demand_text = _read_optional_text(demand_path)
    demand_terms = _extract_terms(
        demand_text,
        [
            "analysis agent",
            "application agent",
            "build agent",
            "mock agent",
            "judge agent",
            "attribute agent",
            "check agent",
            "归因能力",
            "判断能力",
            "前端页",
            "批量运行能力",
            "代码标准/一致性审查",
        ],
    )
    project_terms = {}
    for spec in specs or _load_project_specs_from_root(root):
        texts = []
        project_root = Path(spec.root) if spec.root else root / "impl" / "projects" / spec.project_id
        for rel in (spec.documents or {}).values():
            texts.append(_read_optional_text(project_root / str(rel)))
        texts.append(str(spec.frontend_extensions or {}))
        project_terms[spec.project_id] = _extract_terms(
            "\n".join(texts),
            REQUIRED_PROJECT_STANDARD_FIELDS + ["frontend_view", "batch_persistence", "attribution_trace"],
        )
    rel_path = str(demand_path.relative_to(root)) if demand_path.exists() else str(demand_path.name)
    return {"demand_path": rel_path, "demand_terms": demand_terms, "project_terms": project_terms}


def audit_demand_alignment(root: Path) -> list[str]:
    gaps = []
    demand = _demand_path(root)
    if not demand.exists():
        gaps.append("missing demand.md")
    protocol_path = root / "impl" / "protocols" / "agent_role_protocol.md"
    template_path = root / "impl" / "project_implementation_standard-template.md"
    if not protocol_path.exists():
        gaps.append("missing protocol: impl/protocols/agent_role_protocol.md")
    else:
        gaps.extend(audit_agent_role_protocol(protocol_path))
    if not template_path.exists():
        gaps.append("missing protocol: impl/project_implementation_standard-template.md")
    gaps.extend(audit_required_protocol_markers(root / "impl" / "protocols"))
    for spec in _load_project_specs_from_root(root):
        standard_docs = ["implementation_standard", "checklist"]
        if not any((Path(spec.root) / str((spec.documents or {}).get(key))).exists() for key in standard_docs if (spec.documents or {}).get(key)):
            gaps.append(f"{spec.project_id} missing project implementation standard document")
        gaps.extend(audit_project_implementation_standard(spec))
    return gaps



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
    """spec/info-volume.md 后 boundary_decision 已删除，此函数返回空。

    保留函数签名是为了向后兼容 check 调用方；项目特有 boundary 检查已下沉到项目层。
    """
    return []



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
    elif isinstance(value, str):
        fields.update(re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*\b", value))
    return fields


def _judge_fields(trace: Optional[RunTrace], judge: Optional[JudgeResult]) -> set[str]:
    fields = set()
    if trace:
        fields.update(_field_values(trace_normalized_request(trace)))
        fields.update(_field_values(trace_extracted_output(trace)))
        fields.update(_field_values(trace.reference_contract))
        fields.update(_field_values(trace_application_boundary(trace)))
    if judge:
        fields.update(_field_values(judge.expected))
        fields.update(_field_values(judge.actual))
        fields.update(_field_values(judge_expected_actual_gaps(judge)))
    return fields


def _attribute_claimed_fields(attribute: AttributeResult) -> set[str]:
    fields = set()
    fields.update(_field_values(attribute.suspected_locations))
    fields.update(_field_values(attribute.root_cause_hypothesis))
    fields.update(_field_values(attribute.evidence))
    return fields


def _attribute_consistency_gaps(trace: Optional[RunTrace], judge: Optional[JudgeResult], attribute: Optional[AttributeResult]) -> list[str]:
    if not judge or not attribute:
        return []
    gaps = []
    fulfillment_status = (judge.overall_fulfillment or {}).get("status") if isinstance(judge.overall_fulfillment, dict) else ""
    if fulfillment_status == "fulfilled":
        attributions = list(attribute.expectation_attributions or [])
        if not attributions:
            gaps.append("AttributeResult lacks expectation_attributions for fulfilled JudgeResult.")
        return gaps
    if not attribute.root_cause_hypothesis and not attribute.suspected_locations:
        gaps.append("Failure attribution missing root_cause_hypothesis or suspected_locations.")
    return gaps


def _reallive_exchange_gaps(trace: RunTrace) -> list[str]:
    """检查成功 RealLive Trace 是否保留了可验证的公共传输事实。"""
    if trace.execution_mode not in {"live", "live_service", "interactive_intent"} or trace.status not in {"ok", "succeeded"}:
        return []
    gaps: list[str] = []
    records = list(trace.turn_records or [])
    if not records:
        return ["Successful RealLive RunTrace missing turn_records with LiveExchange evidence."]
    for index, record in enumerate(records, start=1):
        exchanges = list(record.get("live_exchanges") or []) if isinstance(record, dict) else []
        if not exchanges:
            gaps.append(f"Successful RealLive turn {index} missing LiveExchange evidence.")
            continue
        values = [item if isinstance(item, dict) else vars(item) for item in exchanges]
        if not any(bool(item.get("carries_live_request")) for item in values):
            gaps.append(f"Successful RealLive turn {index} has no request-carrying LiveExchange.")
        if not any(bool(item.get("contributes_raw_response")) for item in values):
            gaps.append(f"Successful RealLive turn {index} has no raw-response LiveExchange.")
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
        "adapter.py": root / "core" / "adapter.py",
        "tools": root / "tools",
        "analysis_protocol.md": root / "protocols" / "analysis_protocol.md",
        "batch_protocol.md": root / "protocols" / "batch_protocol.md",
        "tool_protocol.md": root / "protocols" / "tool_protocol.md",
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
    if files["tools"].exists() and not files["tool_protocol.md"].exists():
        gaps.append("Protocol tool layer exists without tool_protocol.md.")
    if files["adapter.py"].exists() and "run_protocol_tools" in files["adapter.py"].read_text(encoding="utf-8", errors="ignore") and not files["tool_protocol.md"].exists():
        gaps.append("ProjectAdapter exposes run_protocol_tools without tool_protocol.md.")
    if files["tool_protocol.md"].exists():
        tool_text = files["tool_protocol.md"].read_text(encoding="utf-8", errors="ignore").lower()
        for marker in ["toolcontext", "toolresult", "toolregistry", "agno", "tool_type"]:
            if marker not in tool_text:
                gaps.append(f"tool_protocol.md missing required marker: {marker}")
    if not files["judge_boundary_template.md"].exists():
        gaps.append("Judge boundary user template is missing: impl/judge_boundary-template.md.")
    return gaps


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(key) + " " + _as_text(item) for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_as_text(item) for item in value)
    return str(value or "")


def _add_category(categories: dict[str, list[str]], name: str, issue: str) -> None:
    if issue not in categories[name]:
        categories[name].append(issue)


def _output_actual_diverge(extracted_output: Any, actual: Any) -> bool:
    if not extracted_output or not actual:
        return False
    if extracted_output == actual:
        return False
    return not _value_contained_in(actual, extracted_output)


def _value_contained_in(needle: Any, haystack: Any) -> bool:
    if needle == haystack:
        return True
    if isinstance(needle, dict):
        return all(_value_contained_in(value, haystack) for value in needle.values())
    if isinstance(needle, list):
        return all(_value_contained_in(item, haystack) for item in needle)
    if isinstance(haystack, dict):
        return any(_value_contained_in(needle, value) for value in haystack.values())
    if isinstance(haystack, list):
        return any(_value_contained_in(needle, value) for value in haystack)
    return False


def _unsupported_root_cause_claims(unsupported_claims: list[Any], trace: Optional[RunTrace], judge: Optional[JudgeResult], attribute: AttributeResult) -> list[str]:
    current_text = _as_text(trace_input(trace) if trace else {}) + " " + _as_text(trace_extracted_output(trace) if trace else {}) + " " + _as_text(judge.expected if judge else {}) + " " + _as_text(judge.actual if judge else {}) + " " + _as_text(judge.wrong if judge else {})
    verification_text = _as_text(attribute.evidence) + " "
    root_cause_text = _as_text(attribute.suspected_locations) + " " + _as_text(attribute.root_cause_hypothesis) + " "
    ungrounded = []
    for claim in unsupported_claims:
        claim_text = str(claim)
        if not claim_text:
            continue
        if claim_text in current_text and claim_text in verification_text:
            continue
        if claim_text in root_cause_text:
            ungrounded.append(claim_text)
            continue
        ungrounded.append(claim_text)
    return ungrounded


def build_check_category_report(
    spec: ProjectSpec,
    trace: Optional[RunTrace] = None,
    judge: Optional[JudgeResult] = None,
    attribute: Optional[AttributeResult] = None,
    demand_intent: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    categories = {
        "protocol_mismatch": [],
        "stale_artifact": [],
        "split_brain_flow": [],
        "overfit_rule": [],
        "frontend_api_inconsistency": [],
        "batch_persistence_risk": [],
        "ungrounded_attribution": [],
    }
    evidence_locations = []
    root_causes = []
    fixes = []
    verification_results = []
    frontend_extensions = spec.frontend_extensions or {}
    implementation_standard = frontend_extensions.get("implementation_standard") if isinstance(frontend_extensions.get("implementation_standard"), dict) else {}
    check_rules = _check_rules(spec)

    if demand_intent and not demand_intent.get("demand_terms"):
        _add_category(categories, "protocol_mismatch", "current demand intent could not be reconstructed before artifact audit")
    latest_protocol = check_rules.get("latest_protocol_version")
    if trace and latest_protocol and trace_normalized_request(trace).get("protocol_version") != latest_protocol:
        _add_category(categories, "protocol_mismatch", f"trace protocol_version {trace_normalized_request(trace).get('protocol_version')} is not latest {latest_protocol}")
        _add_category(categories, "stale_artifact", "generated artifact uses a stale protocol version")
        evidence_locations.append("RunTrace.normalized_request.protocol_version")
        fixes.append("Regenerate the affected artifact from the latest project/protocol standard before auditing its output.")

    if trace and judge:
        if _output_actual_diverge(trace_extracted_output(trace), judge.actual):
            _add_category(categories, "split_brain_flow", "RunTrace.extracted_output and JudgeResult.actual diverge")
            evidence_locations.extend(["RunTrace.extracted_output", "JudgeResult.actual"])
        if trace.project_id != judge.project_id:
            _add_category(categories, "split_brain_flow", "RunTrace and JudgeResult use different project_id values")

    if trace:
        declared_frontend = implementation_standard.get("frontend_view") if isinstance(implementation_standard.get("frontend_view"), dict) else {}
        runtime_frontend = trace_extracted_output(trace).get("frontend_view") if isinstance(trace_extracted_output(trace), dict) else None
        if isinstance(runtime_frontend, dict) and declared_frontend:
            declared_output = declared_frontend.get("output_source")
            runtime_output = runtime_frontend.get("output_source")
            if declared_output and runtime_output and declared_output != runtime_output:
                _add_category(categories, "frontend_api_inconsistency", f"frontend output source {runtime_output} differs from project standard {declared_output}")
                evidence_locations.extend(["project implementation_standard.frontend_view", "RunTrace.extracted_output.frontend_view"])
                fixes.append("Render live and summary pages from the normalized frontend view contract instead of a project-private source branch.")
        persisted_keys = trace_extracted_output(trace).get("case_pool_persisted_keys") if isinstance(trace_extracted_output(trace), dict) else None
        forbidden_persisted = {"trace", "judge", "attribute", "frontend_view", "raw_response", "raw_sections", "raw_model_output"}
        if isinstance(persisted_keys, list):
            risky = sorted(forbidden_persisted.intersection(str(key) for key in persisted_keys))
            if risky:
                _add_category(categories, "batch_persistence_risk", "case-pool persisted transient fields: " + ", ".join(risky))
                evidence_locations.append("RunTrace.extracted_output.case_pool_persisted_keys")
                root_causes.append("Batch persistence is storing runtime analysis objects instead of the compact durable case-pool shape.")
                fixes.append("Persist only compact case fields and keep trace/judge/attribute/frontend_view in current-page runtime memory.")

    if attribute:
        current_text = _as_text(trace.input if trace else {}) + " " + _as_text(judge.expected if judge else {}) + " " + _as_text(judge.actual if judge else {})
        attr_text = _as_text(attribute.suspected_locations) + " " + _as_text(attribute.root_cause_hypothesis) + " " + _as_text(attribute.evidence)
        unsupported_claims: list[Any] = []
        stale_markers = [str(marker) for marker in unsupported_claims if marker and str(marker) in attr_text and str(marker) not in current_text]
        if stale_markers:
            _add_category(categories, "overfit_rule", "attribution mentions fields from a historical case but not the current case: " + ", ".join(stale_markers))
            _add_category(categories, "stale_artifact", "attribution appears to carry stale historical-case fields")
            evidence_locations.append("AttributeResult.root_cause_hypothesis")
            root_causes.append("Attribution reused a historical rule/case pattern without grounding it in the current expected-vs-actual gap.")
            fixes.append("Reconstruct the current case gap first, then ground field/config/enum claims in current trace, judge, project docs, or local verification.")
        ungrounded_unsupported = _unsupported_root_cause_claims([], trace, judge, attribute)
        has_location_evidence = bool(attribute.evidence_strength in ("strong", "medium"))
        if ungrounded_unsupported or (attribute.suspected_locations and not has_location_evidence):
            issue = "attribution has unsupported root-cause/location claims"
            if ungrounded_unsupported:
                issue += ": " + ", ".join(str(item) for item in ungrounded_unsupported)
            _add_category(categories, "ungrounded_attribution", issue)
            evidence_locations.append("AttributeResult.evidence")
            root_causes.append("Attribute quality passed even though root-cause or suspected-location claims lack current-case evidence.")
            fixes.append("Downgrade to insufficient_evidence or next_verification_step until current-case chain evidence supports the root cause.")

    confirmation_items = [str(item) for item in list(check_rules.get("confirmation_required_changes") or [])]
    requires_user_confirmation = bool(confirmation_items)
    passed_items = []
    failed_items = []
    for name, issues in categories.items():
        if issues:
            failed_items.extend(f"{name}: {issue}" for issue in issues)
        else:
            passed_items.append(f"{name} passed")
    if requires_user_confirmation:
        verification_results.append("Non-trivial shared protocol or user-visible behavior changes require user confirmation before silent application.")
    if not failed_items:
        verification_results.append("Check categories passed current audit.")
    return {
        "passed": not failed_items,
        "passed_items": passed_items,
        "failed_items": failed_items,
        "categories": categories,
        "evidence_locations": evidence_locations,
        "root_causes": root_causes,
        "fixes": fixes,
        "verification_results": verification_results,
        "requires_user_confirmation": requires_user_confirmation,
        "confirmation_items": confirmation_items,
    }


def write_chinese_check_report(issue_dir: Path, report: dict[str, Any], filename: str = "20260612-demand-check-gap-analysis-updated-report.md") -> Path:
    issue_dir.mkdir(parents=True, exist_ok=True)
    path = issue_dir / filename
    sections = [
        ("通过项", report.get("passed_items") or []),
        ("失败项", report.get("failed_items") or []),
        ("分类明细", [f"{name}: " + ("；".join(items) if items else "通过") for name, items in (report.get("categories") or {}).items()]),
        ("证据位置", report.get("evidence_locations") or []),
        ("根因", report.get("root_causes") or []),
        ("修复方案", report.get("fixes") or []),
        ("验证结果", report.get("verification_results") or []),
    ]
    lines = ["# Check 驱动差距报告", ""]
    if report.get("requires_user_confirmation"):
        lines.extend(["## 需要用户确认", ""])
        for item in report.get("confirmation_items") or []:
            lines.append(f"- {item}")
        lines.append("")
    for title, items in sections:
        lines.extend([f"## {title}", ""])
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("- 无")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
    fallbacks: list[FallbackDecision] = []
    if trace:
        fallbacks.extend(trace.fallbacks or [])

    if fallbacks:
        verification_results.append(f"Structured fallback decisions recorded: {len(fallbacks)}.")
        if any(item.needs_human_review for item in fallbacks):
            consistency_gaps.append("Fallback decisions require human review before treating the chain as fully verified.")

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
        if not trace_normalized_request(trace):
            protocol_gaps.append("RunTrace missing normalized_request.")
        if trace_raw_response(trace) is None and trace.status == "ok":
            protocol_gaps.append("RunTrace has ok status but no raw_response.")
        if not trace_execution_trace(trace):
            protocol_gaps.append("RunTrace missing execution_trace for source -> API -> adapter verification.")
        protocol_gaps.extend(_reallive_exchange_gaps(trace))
        consistency_gaps.extend(_downstream_boundary_gaps(trace, judge))
    else:
        protocol_gaps.append("Missing RunTrace; source -> run part of chain is not verified.")

    if judge:
        if trace and judge.trace_id != trace.trace_id:
            consistency_gaps.append("JudgeResult trace_id does not match RunTrace.")
        if not judge.evidence:
            protocol_gaps.append("JudgeResult missing evidence.")
        primary_signal = judge_primary_signal(judge)
        has_fulfillment_record = bool(primary_signal.get("fulfillment_assessments")) or bool(primary_signal.get("overall_fulfillment"))
        if not has_fulfillment_record:
            protocol_gaps.append("JudgeResult missing fulfillment_assessments/overall_fulfillment for the selected evaluation boundary.")
        overall_status = (judge.overall_fulfillment or {}).get("status") if isinstance(judge.overall_fulfillment, dict) else ""
        gaps = judge_expected_actual_gaps(judge)
        if overall_status == "not_fulfilled" and not primary_signal.get("fulfillment_assessments") and not (gaps.get("missing") or gaps.get("wrong") or gaps.get("extra")):
            protocol_gaps.append("Not-fulfilled JudgeResult should identify failing fulfillment_assessments or missing/wrong/extra output.")
        if overall_status in {"not_fulfilled", "not_evaluable"}:
            if not has_fulfillment_record and not judge.expected:
                protocol_gaps.append("JudgeResult missing business_expectations/expected snapshot; fulfillment status is not tied to current-query requirements.")
            reason = (judge.reasoning_summary or "").lower()
            if overall_status == "not_fulfilled" and any(marker in reason for marker in ["最终评价为正确", "整体判定为 correct", "final verdict is correct", "overall verdict is correct", "does not affect correctness", "不影响正确性"]):
                consistency_gaps.append("JudgeResult overall_fulfillment is not_fulfilled but reasoning_summary claims the output is correct or performance is unaffected.")
    else:
        protocol_gaps.append("Missing JudgeResult; run -> judge part of chain is not verified.")

    if attribute:
        if trace and attribute.trace_id != trace.trace_id:
            consistency_gaps.append("AttributeResult trace_id does not match RunTrace.")
        if trace and attribute.case_id != trace.case_id:
            consistency_gaps.append("AttributeResult case_id does not match RunTrace.")
        if not attribute.root_cause_hypothesis:
            protocol_gaps.append("AttributeResult missing root_cause_hypothesis.")
        if not attribute.suspected_locations and not attribute.root_cause_hypothesis:
            protocol_gaps.append("Failure attribution missing suspected_locations or root_cause_hypothesis.")
        if judge and (judge.overall_fulfillment or {}).get("status") in {"not_fulfilled", "not_evaluable"}:
            if not attribute.expectation_attributions:
                protocol_gaps.append("Failure attribution missing expectation_attributions for non-fulfilled JudgeResult.")
        consistency_gaps.extend(_attribute_consistency_gaps(trace, judge, attribute))
    elif judge and (judge.overall_fulfillment or {}).get("status") in {"not_fulfilled", "not_evaluable"}:
        protocol_gaps.append("JudgeResult requires attribution, but AttributeResult is missing.")

    if cluster:
        for item in cluster.clusters:
            if not item.get("representative_cases"):
                protocol_gaps.append("Cluster missing representative_cases.")
                break

    check_rules = _check_rules(spec)
    category_report = build_check_category_report(
        spec,
        trace,
        judge,
        attribute,
        demand_intent=reconstruct_current_intent(impl_root.parent if impl_root and impl_root.name == "impl" else Path(".")),
    )
    protocol_gaps.extend(category_report["categories"].get("protocol_mismatch") or [])
    consistency_gaps.extend(category_report["categories"].get("stale_artifact") or [])
    consistency_gaps.extend(category_report["categories"].get("split_brain_flow") or [])
    overfit_risks.extend(category_report["categories"].get("overfit_rule") or [])
    consistency_gaps.extend(category_report["categories"].get("frontend_api_inconsistency") or [])
    data_only_patch_risks.extend(category_report["categories"].get("batch_persistence_risk") or [])
    protocol_gaps.extend(category_report["categories"].get("ungrounded_attribution") or [])
    recommended_fixes.extend(item for item in category_report.get("fixes", []) if item not in recommended_fixes)
    verification_results.extend(item for item in category_report.get("verification_results", []) if item not in verification_results)
    if category_report.get("requires_user_confirmation"):
        protocol_gaps.append("Non-trivial shared protocol or user-visible behavior changes require user confirmation: " + ", ".join(category_report.get("confirmation_items") or []))

    if check_rules:
        scenario = trace.scenario if trace else ""
        normalized = trace_normalized_request(trace) if trace else {}
        reference_contract = trace.reference_contract if trace else {}
        if trace and trace.status == "ok" and check_rules.get("require_scenario") and not scenario:
            protocol_gaps.append(f"{spec.project_id} RunTrace missing scenario.")
        scenario_requirements = check_rules.get("scenario_requirements") or {}
        current_requirement = scenario_requirements.get(scenario) if isinstance(scenario_requirements, dict) else None
        if isinstance(current_requirement, dict):
            reference_field = current_requirement.get("reference_field")
            input_field = current_requirement.get("input_field")
            data_quality_flag = current_requirement.get("data_quality_flag")
            if reference_field and not (reference_contract or normalized.get("reference") or {}).get(reference_field):
                protocol_gaps.append(f"{spec.project_id} {scenario} requires reference.{reference_field}.")
            if input_field and not (normalized.get("input") or {}).get(input_field):
                protocol_gaps.append(f"{spec.project_id} {scenario} requires input.{input_field}.")
            if data_quality_flag and data_quality_flag not in list(normalized.get("data_quality_flags") or []):
                protocol_gaps.append(f"{spec.project_id} {scenario} must be marked with normalized_request.data_quality_flags.{data_quality_flag}.")

    if boundary_violations:
        recommended_fixes.append("Move project-specific runtime-only facts into impl/projects/<project>/adapter.py or schema_protocol_extensions.")
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
        fallbacks=fallbacks,
    )
