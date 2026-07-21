from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from impl.core.context.models import ContextUnitRecord


def build_context_unit_records(
    spec: Any,
    role: str,
    use_candidate: bool,
    selected_assets: list[Mapping[str, Any]],
) -> list[ContextUnitRecord]:
    investigation = next(
        (
            item for item in selected_assets
            if item["mapping"].kind == "investigation"
            and item["mapping"].asset_id == "attribute_investigation"
            and item["available"]
        ),
        None,
    )
    if investigation is None:
        raise FileNotFoundError("deerflow Attribute investigation asset is unavailable")
    package = Path(investigation["path"])
    definitions = (
        (
            "project.deerflow.attribute.investigation.overview",
            "deerflow investigation boundary",
            "Scope and revision boundaries for separating business output from verifier-derived fields.",
            package / "overview.md",
            "investigation_overview",
        ),
        (
            "project.deerflow.attribute.investigation.flow",
            "deerflow gateway message flow",
            "Operational index from Gateway message history through verifier extraction and the separate NBEV skill branch.",
            package / "docs" / "traces" / "gateway-message-flow.md",
            "business_trace",
        ),
        (
            "project.deerflow.attribute.investigation.graph",
            "deerflow gateway Mermaid topology",
            "Optional machine-readable topology; use the text operational index for verification actions.",
            package / "docs" / "traces" / "gateway-message-flow.mmd",
            "business_trace_graph",
        ),
        (
            "project.deerflow.attribute.investigation.clarification_flow",
            "deerflow clarification-to-planning flow",
            "Operational index for cumulative user inputs, repeated clarification, prompt policy, skill selection, and planning execution.",
            package / "docs" / "traces" / "clarification-planning-flow.md",
            "business_trace",
        ),
        (
            "project.deerflow.attribute.investigation.clarification_graph",
            "deerflow clarification-to-planning Mermaid topology",
            "Machine-readable topology for the clarification-to-planning business branch.",
            package / "docs" / "traces" / "clarification-planning-flow.mmd",
            "business_trace_graph",
        ),
    )
    records: list[ContextUnitRecord] = []
    for unit_id, name, description, path, unit_type in definitions:
        if not path.is_file():
            raise FileNotFoundError(f"deerflow investigation Context source missing: {path}")
        records.append(ContextUnitRecord(
            id=unit_id,
            name=name,
            description=description,
            content=None,
            content_ref=path.resolve().as_uri(),
            project_id=spec.project_id,
            scope="project_static",
            roles=(role,),
            unit_type=unit_type,
            source_type="investigation_context_builder",
            tags={
                "asset_id": investigation["mapping"].asset_id,
                "source": investigation["source"],
                "mode": "draft" if use_candidate else "production",
            },
        ))
    return records
