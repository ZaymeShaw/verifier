"""Deprecated compatibility module.

Project-specific field lookup tools belong under
``impl/projects/<project>/tools`` and should be registered by the project
adapter. Shared core code must not import project field providers from this
module.
"""
from __future__ import annotations

from typing import Optional, Protocol


class FieldDefinitionProvider(Protocol):
    def get_field_definition(self, field_name: str) -> Optional[dict]:
        ...


def create_field_search_tool(provider: FieldDefinitionProvider):
    """Compatibility wrapper for legacy callers.

    New code should implement a project-local ProtocolTool and expose any
    LLM-callable wrapper through ProjectAdapter.build_judge_context().
    """

    def search_field_definition(field_name: str) -> str:
        try:
            field_def = provider.get_field_definition(field_name)
            if not field_def:
                return f"Field '{field_name}' not found in field definitions"
            lines = [f"Field: {field_def.get('field', field_name)}"]
            if field_def.get("description"):
                lines.append(f"Description: {field_def['description']}")
            if field_def.get("operators"):
                lines.append(f"Allowed operators: {', '.join(field_def['operators'])}")
            if field_def.get("value_types"):
                lines.append(f"Value types: {', '.join(field_def['value_types'])}")
            if field_def.get("enums"):
                lines.append(f"Valid values: {', '.join(field_def['enums'])}")
            if field_def.get("unit"):
                lines.append(f"Unit: {field_def['unit']}")
            if field_def.get("examples"):
                lines.append(f"Examples: {'; '.join(field_def['examples'])}")
            if field_def.get("notes"):
                lines.append(f"Notes: {field_def['notes']}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Error retrieving field definition: {exc}"

    search_field_definition.__name__ = "search_field_definition"
    search_field_definition.__doc__ = "Legacy field definition lookup wrapper. Prefer project-local protocol tools."
    return search_field_definition
