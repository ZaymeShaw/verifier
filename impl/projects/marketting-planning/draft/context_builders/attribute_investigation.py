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
        raise FileNotFoundError("marketing planning Attribute investigation asset is unavailable")
    package = Path(investigation["path"])
    definitions = (
        (
            "project.marketing_planning.attribute.investigation.overview",
            "marketing planning investigation boundary",
            "Optional scope and evidence-boundary notes for the planning investigation package.",
            package / "overview.md",
            "investigation_overview",
        ),
        (
            "project.marketing_planning.attribute.investigation.flow",
            "marketing planning business flow",
            "Operational index from public SSE through field extraction, workflow handoff, path planning, assembly and adapter.",
            package / "docs" / "traces" / "planning-execution.md",
            "business_trace",
        ),
        (
            "project.marketing_planning.attribute.investigation.graph",
            "marketing planning Mermaid topology",
            "Optional machine-readable graph; use the text operational index to choose verification actions.",
            package / "docs" / "traces" / "planning-execution.mmd",
            "business_trace_graph",
        ),
    )
    records: list[ContextUnitRecord] = []
    for unit_id, name, description, path, unit_type in definitions:
        if not path.is_file():
            raise FileNotFoundError(f"marketing planning investigation Context source missing: {path}")
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

