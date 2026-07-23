from __future__ import annotations

from .project_loader import load_project, load_project_document
from .schema import ProjectAnalysis


def analyze_project(project_id: str) -> ProjectAnalysis:
    spec = load_project(project_id)
    quality_flags = []
    documents = spec.document_paths
    api = spec.service("primary")
    source = ((spec.project.get("resources") or {}).get("source") or {})
    application_config = {
        "mode": spec.runtime_mode,
        "external_repo": source.get("repository") or "",
        "contract": spec.application_contract,
    }
    application_config.update(
        dict(((spec.runtime.get("services") or {}).get("dependencies") or {}))
    )
    mock = load_project_document(spec, "mock")
    evaluation = load_project_document(spec, "evaluation")
    attribution = load_project_document(spec, "attribution")
    application = load_project_document(spec, "application")
    adapter_standard = spec.adapter_contract
    frontend_standard = spec.frontend_view_contract
    persistence_standard = spec.batch_persistence_contract
    judge_standard = spec.judge_boundary_contract
    attribute_standard = spec.attribution_trace_contract
    if not api:
        quality_flags.append("missing_api_spec")
    if not mock:
        quality_flags.append("missing_mock_guidance")
    if not evaluation:
        quality_flags.append("missing_evaluation_guidance")
    if not attribution:
        quality_flags.append("missing_attribution_guidance")
    if not application and not application_config:
        quality_flags.append("missing_application_guidance")
    if not frontend_standard:
        quality_flags.append("missing_frontend_build_standard")
    return ProjectAnalysis(
        project_id=spec.project_id,
        api=api,
        application=application_config,
        capabilities=spec.capabilities,
        documents=documents,
        mock_guidance=mock,
        evaluation_guidance=evaluation,
        attribution_guidance=attribution,
        analysis_handoff={
            "api_document": api,
            "api_call_chain": (spec.application_contract.get("interface") or {}).get("source") or documents.get("source_readme") or documents.get("application") or api,
            "mock_strategy": documents.get("mock") or bool(mock),
            "frontend_architecture": frontend_standard,
            "judge_standard": documents.get("judge_standard") or documents.get("judge_boundary") or judge_standard,
            "attribution_trace_plan": documents.get("attribution") or attribute_standard,
            "key_pipeline_links": attribute_standard.get("trace_nodes") or [],
            "adapter_contract": adapter_standard,
        },
        frontend_build_handoff={
            "analysis_output": "ProjectAnalysis.frontend_build_handoff",
            "frontend_architecture": frontend_standard,
            "project_frontend_standards": {
                "frontend_view": frontend_standard,
                "batch_persistence": persistence_standard,
            },
            "display_contract": {
                "output_source": "trace.extracted_output",
                "reference_source": "input.reference or judge.expected",
                "formatting": ["json formatting", "truncation", "output/reference alignment"],
            },
        },
        judge_handoff={
            "judge_standard": documents.get("judge_standard") or documents.get("judge_boundary") or judge_standard,
            "evaluation_guidance": bool(evaluation),
        },
        attribute_handoff={
            "attribution_trace_plan": documents.get("attribution") or attribute_standard,
            "key_pipeline_links": attribute_standard.get("trace_nodes") or [],
        },
        quality_flags=quality_flags,
    )
