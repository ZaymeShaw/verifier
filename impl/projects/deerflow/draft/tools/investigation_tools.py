"""Deterministic replays for the deerflow Gateway/verifier boundary."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from impl.projects.deerflow.live import (
    _extract_reply_and_tool_calls,
    _scripts_called,
    _stage_inference,
)
from impl.tools import ToolResult, VerifiableTool


_PARAMETERS = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "description": "One current turn's exact Gateway message-history array from RunTrace raw_response.",
            "items": {"type": "object"},
        }
    },
    "required": ["messages"],
}

_BUDGET_PARAMETERS = {
    "type": "object",
    "properties": {
        "budget_limit": {"type": "number", "description": "Budget ceiling stated by the current user/output."},
        "claimed_total": {"type": "number", "description": "Optional total claimed by the business output."},
        "components": {
            "type": "array",
            "description": "Cost components copied from the current business output, each with its original quote.",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "unit_cost": {"type": "number"},
                    "quantity": {"type": "number"},
                    "total": {"type": "number"},
                    "source_quote": {"type": "string"},
                },
                "required": ["name", "source_quote"],
            },
        },
    },
    "required": ["budget_limit", "components"],
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def build_budget_reconcile_tool() -> VerifiableTool:
    tool_id = "deerflow.budget_reconcile"
    description = (
        "Deterministically recompute a plan budget from cost components quoted from the current "
        "business output, compare it with the claimed total and budget ceiling, and preserve each quote."
    )

    def execute(**kwargs: Any) -> ToolResult:
        limit = _finite_number(kwargs.get("budget_limit"))
        claimed = _finite_number(kwargs.get("claimed_total"))
        components = kwargs.get("components")
        if limit is None or limit < 0 or not isinstance(components, list) or not components:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="budget reconciliation requires a non-negative budget_limit and quoted components",
                missing_evidence=["budget_limit", "components"],
            )

        normalized = []
        for index, item in enumerate(components):
            if not isinstance(item, dict):
                return ToolResult(
                    tool_id=tool_id,
                    status="inconclusive",
                    evidence="every budget component must be an object copied from the current output",
                    missing_evidence=[f"components[{index}]"],
                )
            name = str(item.get("name") or "").strip()
            quote = str(item.get("source_quote") or "").strip()
            supplied_total = _finite_number(item.get("total"))
            unit_cost = _finite_number(item.get("unit_cost"))
            quantity = _finite_number(item.get("quantity"))
            unit_extended_total = (
                unit_cost * quantity
                if unit_cost is not None and quantity is not None
                else None
            )
            # When the output states both a unit formula and a component total,
            # preserving their disagreement is the point of reconciliation.  The
            # arithmetic extension is deterministic; silently preferring the
            # declared total would reproduce the business output's own omission.
            reconciled_total = unit_extended_total if unit_extended_total is not None else supplied_total
            if not name or not quote or reconciled_total is None or reconciled_total < 0:
                return ToolResult(
                    tool_id=tool_id,
                    status="inconclusive",
                    evidence="each component needs a name, source_quote, and non-negative total or unit_cost×quantity",
                    missing_evidence=[f"components[{index}]"],
                )
            normalized.append({
                "name": name,
                "unit_cost": unit_cost,
                "quantity": quantity,
                "supplied_total": supplied_total,
                "unit_extended_total": unit_extended_total,
                "computed_total": reconciled_total,
                "supplied_vs_unit_delta": (
                    None
                    if supplied_total is None or unit_extended_total is None
                    else unit_extended_total - supplied_total
                ),
                "source_quote": quote,
            })

        computed = sum(item["computed_total"] for item in normalized)
        return ToolResult(
            tool_id=tool_id,
            status="succeeded",
            actual={
                "budget_limit": limit,
                "claimed_total": claimed,
                "components": normalized,
                "computed_total": computed,
                "over_budget_by": max(0.0, computed - limit),
                "within_budget": computed <= limit,
                "claimed_total_delta": None if claimed is None else computed - claimed,
                "component_total_conflicts": [
                    {
                        "name": item["name"],
                        "supplied_total": item["supplied_total"],
                        "unit_extended_total": item["unit_extended_total"],
                        "delta": item["supplied_vs_unit_delta"],
                    }
                    for item in normalized
                    if item["supplied_vs_unit_delta"] not in (None, 0.0)
                ],
            },
            evidence="recomputed quoted cost components and compared them with the stated budget ceiling",
            boundary_limits=[
                "This tool verifies arithmetic for the supplied quoted components; the current business output must be loaded separately to authenticate the quotes.",
                "It does not identify whether a discrepancy originated in model reasoning, prompt design, or another hidden mechanism.",
            ],
        )

    execute.__name__ = "deerflow_budget_reconcile"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=(
            "A Judge gap concerns a numeric budget ceiling and the current business output states "
            "the cost components needed to recompute the plan total."
        ),
        parameters=_BUDGET_PARAMETERS,
        execute_fn=execute,
    )


def build_message_history_replay_tool() -> VerifiableTool:
    tool_id = "deerflow.message_history_replay"
    description = (
        "Replay the current verifier extraction and stage inference on one exact Gateway "
        "message-history array, returning the selected latest non-middleware AI message, "
        "its tool calls, and the derived stage."
    )

    def execute(**kwargs: Any) -> ToolResult:
        messages = kwargs.get("messages")
        if not isinstance(messages, list):
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="message-history replay requires the exact messages array",
                missing_evidence=["messages"],
            )
        try:
            reply, tool_calls = _extract_reply_and_tool_calls(messages)
            scripts = _scripts_called(tool_calls)
            stage, rule = _stage_inference(reply, tool_calls, scripts)
            selected_index = None
            selected_caller = ""
            for index in range(len(messages) - 1, -1, -1):
                message = messages[index]
                if not isinstance(message, dict):
                    continue
                caller = str((message.get("metadata") or {}).get("caller") or "")
                content = message.get("content")
                if caller.startswith("middleware:"):
                    continue
                if isinstance(content, dict) and content.get("type") == "ai":
                    selected_index = index
                    selected_caller = caller
                    break
            source = Path(__file__).resolve().parents[2] / "live.py"
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={
                    "message_count": len(messages),
                    "selected_message_index": selected_index,
                    "selected_caller": selected_caller,
                    "reply_text": reply,
                    "tool_calls": tool_calls,
                    "scripts_called": scripts,
                    "derived_stage": stage,
                    "stage_rule": rule,
                    "source_path": str(source),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                evidence="replayed current deerflow verifier extraction on the supplied Gateway message history",
                boundary_limits=[
                    "This replay verifies the verifier project boundary, not hidden model reasoning.",
                    "The supplied messages must come from the current RunTrace turn.",
                    "A derived stage is verifier metadata; it is not a Gateway-provided business stage field.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"message-history replay failed: {type(exc).__name__}: {exc}",
                evidence="attempted current deerflow Gateway message-history replay",
            )

    execute.__name__ = "deerflow_message_history_replay"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=(
            "A Judge gap depends on reply_text, tool_calls, scripts_called, or stage and the "
            "current trace contains Gateway message history that can distinguish business output "
            "from verifier extraction."
        ),
        parameters=_PARAMETERS,
        execute_fn=execute,
    )
