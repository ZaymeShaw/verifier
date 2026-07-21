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
        raise FileNotFoundError("client_search Attribute investigation asset is unavailable")
    package = Path(investigation["path"])
    definitions = (
        (
            "project.client_search.attribute.investigation.overview",
            "client_search Attribute project boundary",
            "Business parser scope, confirmed topology, rejected shortcuts and unresolved observation limits.",
            package / "overview.md",
            "investigation_overview",
        ),
        (
            "project.client_search.attribute.investigation.parse_flow",
            "client_search parser business flow",
            "Operational trace map: route current trace signals to parser nodes, Tool/Evidence verification paths, result branches and unresolved boundaries.",
            package / "docs" / "traces" / "client-search-parse.md",
            "business_trace",
        ),
        (
            "project.client_search.attribute.investigation.parse_graph",
            "client_search parser flow graph",
            "Machine-readable Mermaid graph of the confirmed parser execution topology.",
            package / "docs" / "traces" / "client-search-parse.mmd",
            "business_trace_graph",
        ),
    )
    records = []
    for unit_id, name, description, path, unit_type in definitions:
        if not path.is_file():
            raise FileNotFoundError(f"client_search investigation Context source missing: {path}")
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
