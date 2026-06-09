from __future__ import annotations

from .project_loader import load_project, load_project_document
from .schema import ProjectAnalysis


def analyze_project(project_id: str) -> ProjectAnalysis:
    spec = load_project(project_id)
    quality_flags = []
    documents = dict(spec.documents or {})
    mock = load_project_document(spec, "mock")
    evaluation = load_project_document(spec, "evaluation")
    attribution = load_project_document(spec, "attribution")
    application = load_project_document(spec, "application")
    if not spec.api:
        quality_flags.append("missing_api_spec")
    if not mock:
        quality_flags.append("missing_mock_guidance")
    if not evaluation:
        quality_flags.append("missing_evaluation_guidance")
    if not attribution:
        quality_flags.append("missing_attribution_guidance")
    if not application and not spec.application:
        quality_flags.append("missing_application_guidance")
    return ProjectAnalysis(
        project_id=spec.project_id,
        api=spec.api,
        application=spec.application,
        capabilities=spec.capabilities,
        documents=documents,
        mock_guidance=mock,
        evaluation_guidance=evaluation,
        attribution_guidance=attribution,
        quality_flags=quality_flags,
    )
