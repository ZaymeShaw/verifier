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
            item
            for item in selected_assets
            if item["mapping"].kind == "investigation"
            and item["mapping"].asset_id == "attribute_investigation"
            and item["available"]
        ),
        None,
    )
    if investigation is None:
        raise FileNotFoundError("marketing intent Attribute investigation asset is unavailable")
    package = Path(investigation["path"])
    definitions = (
        (
            "project.marketing_intent.attribute.investigation.overview",
            "project investigation boundary",
            "Optional scope notes: confirmed repository, attribution boundary and unresolved observation limits.",
            package / "overview.md",
            "investigation_overview",
        ),
        (
            "project.marketing_intent.attribute.investigation.flow",
            "marketing intent business flow",
            "Operational index for mapping current RunTrace observations to the shortest branch-specific verification path.",
            package / "docs" / "traces" / "intent-recognition.md",
            "business_trace",
        ),
        (
            "project.marketing_intent.attribute.investigation.graph",
            "machine-readable Mermaid artifact",
            "Optional graph representation of the intent-recognition topology; use the text operational document for investigation.",
            package / "docs" / "traces" / "intent-recognition.mmd",
            "business_trace_graph",
        ),
    )
    records = []
    for unit_id, name, description, path, unit_type in definitions:
        if not path.is_file():
            raise FileNotFoundError(f"marketing intent investigation Context source missing: {path}")
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
