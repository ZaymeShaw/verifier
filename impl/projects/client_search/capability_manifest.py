from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml


def build_capability_manifest(definitions_path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Generate the client_search field capability manifest from source YAML."""
    if not definitions_path:
        return {}
    path = Path(definitions_path)
    if not path.exists():
        return {}

    data = _yaml.safe_load(path.read_text()) or {}
    intents = data.get("intents", []) if isinstance(data, dict) else []
    fields: dict[str, dict[str, Any]] = {}
    for item in intents:
        if not isinstance(item, dict):
            continue
        field_name = item.get("field", "")
        if not field_name:
            continue
        if field_name not in fields:
            fields[field_name] = {
                "field": field_name,
                "operators": set(),
                "value_types": set(),
                "description": item.get("description", ""),
                "definition": item.get("description", ""),
                "enums": item.get("enum") or [],
                "unit": item.get("unit") or "",
                "notes": item.get("notes", ""),
            }
        fields[field_name]["operators"].add(item.get("operator", ""))
        fields[field_name]["value_types"].add(item.get("value_type", ""))

    for field in fields.values():
        field["operators"] = sorted(field["operators"])
        field["value_types"] = sorted(field["value_types"])
    return fields
