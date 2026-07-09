from __future__ import annotations

from typing import Any


def build_tool_name_tool():
    """Draft tool template.

    Replace this with a project-specific VerifiableTool factory that wraps an existing
    adapter function, project API, config lookup, or local business function. Draft
    tools must not invent a second semantic standard when the project already has a
    canonical adapter comparison or semantic-equivalence config.
    """
    raise NotImplementedError("draft tool must wrap a real project evidence source before promotion")


TOOL_EVIDENCE_CONTRACT: dict[str, Any] = {
    "name": "tool_name",
    "purpose": "What current-case attribution evidence this tool provides.",
    "input_schema": {},
    "output_schema": {},
    "evidence_type": "What this can prove, what it cannot prove, and whether it is canonical or supporting context only.",
    "canonical_standard": "Name the adapter/project tool/config that owns semantic pass/fail, or state that this tool only provides auxiliary evidence.",
    "boundary": "How unavailable services/config/permissions/missing actual/reference fail visibly without producing strong evidence.",
    "validation": "How to validate this tool with a trace or local function test before promotion.",
}
