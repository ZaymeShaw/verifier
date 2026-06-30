from __future__ import annotations

from typing import Any

from impl.tools import ToolContext, ToolResult

from ..field_provider import ClientSearchFieldDefinitionProvider


class ClientSearchFieldDefinitionSearchTool:
    tool_id = "client_search.field_definition_search"
    tool_type = "document"

    def run(self, context: ToolContext) -> ToolResult:
        if context.spec is None:
            return ToolResult(tool_id=self.tool_id, tool_type=self.tool_type, status="failed", error="project spec missing")
        provider = ClientSearchFieldDefinitionProvider(context.spec)
        requested = self._requested_fields(context.inputs)
        if not requested:
            return ToolResult(
                tool_id=self.tool_id,
                tool_type=self.tool_type,
                status="failed",
                missing_evidence=[{"reason": "field_name or fields input is required"}],
                error="field input missing",
            )
        definitions: dict[str, Any] = {}
        missing = []
        for field_name in requested:
            field_def = provider.get_field_definition(field_name)
            if field_def:
                definitions[field_name] = field_def
            else:
                missing.append(field_name)
        status = "succeeded" if definitions else "not_found"
        evidence = [{"source": "source_field_definitions", "fields": sorted(definitions)}] if definitions else []
        missing_evidence = [
            {"field": field_name, "reason": "field not found in client_search field definitions"}
            for field_name in missing
        ]
        return ToolResult(
            tool_id=self.tool_id,
            tool_type=self.tool_type,
            status=status,
            outputs={"definitions": definitions, "requested_fields": requested},
            evidence=evidence,
            missing_evidence=missing_evidence,
        )

    def _requested_fields(self, inputs: dict[str, Any]) -> list[str]:
        raw_fields = inputs.get("fields")
        if raw_fields is None and inputs.get("field_name"):
            raw_fields = [inputs.get("field_name")]
        if isinstance(raw_fields, str):
            raw_fields = [raw_fields]
        if not isinstance(raw_fields, list):
            return []
        fields = []
        for item in raw_fields:
            text = str(item or "").strip()
            if text and text not in fields:
                fields.append(text)
        return fields

    def format_for_llm(self, result: ToolResult, field_name: str) -> str:
        definitions = result.outputs.get("definitions") if isinstance(result.outputs, dict) else {}
        field_def = definitions.get(field_name) if isinstance(definitions, dict) else None
        if not field_def:
            return f"Field '{field_name}' not found in client_search field definitions"
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
