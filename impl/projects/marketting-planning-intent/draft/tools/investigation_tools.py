"""Verification tools backed by the current marketing-planning business source.

These probes replay existing business functions.  They deliberately contain no
replacement regex, expected labels, historical query fixtures, or inferred gap.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import re
import sys
import threading
from pathlib import Path
from typing import Any

from impl.core.project_loader import load_project
from impl.tools import ToolResult, VerifiableTool


_IMPORT_LOCK = threading.Lock()
_EXECUTION_LOCK = threading.Lock()


def _business_modules() -> tuple[Any, Any, Any]:
    spec = load_project("marketting-planning-intent")
    source_root = Path(spec.source_project).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"business source repository not found: {source_root}")
    with _IMPORT_LOCK:
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        intent_module = importlib.import_module("app.workflow.steps.intent_recognition")
        workflow_module = importlib.import_module("app.workflow.nbev_workflow")
        request_module = importlib.import_module("app.schemas.request")
    return intent_module, workflow_module, request_module


def _contexts(request_module: Any, raw_contexts: Any) -> list[Any] | None:
    if raw_contexts in (None, []):
        return None
    if not isinstance(raw_contexts, list):
        raise TypeError("contexts must be an array")
    return [
        item if isinstance(item, request_module.ContextItem) else request_module.ContextItem.model_validate(item)
        for item in raw_contexts
    ]


def _result_payload(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    if hasattr(result, "model_dump"):
        payload = result.model_dump(mode="json")
    else:
        payload = dict(result)
    intent = payload.get("intent")
    payload["intent"] = getattr(intent, "value", intent)
    return payload


_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Current business query to replay; it must come from the RunTrace being attributed.",
        },
        "contexts": {
            "type": "array",
            "description": "Optional current conversation contexts using the business ContextItem shape.",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": ["string", "null"]},
                    "query": {"type": ["string", "null"]},
                    "answer": {"type": ["string", "null"]},
                },
            },
        },
    },
    "required": ["query"],
}


def build_rule_stage_replay_tool() -> VerifiableTool:
    tool_id = "marketing_intent.rule_stage_replay"
    description = (
        "Execute the checked-out business try_rule_based_intent for the current query and contexts, "
        "returning its actual result or an explicit no-match. A no-match means the business pipeline "
        "must use its LLM branch; it is not itself evidence of a defect."
    )
    scenario = (
        "Attribute a marketing intent mismatch after the public RunTrace establishes the actual API result, "
        "when the reviewer needs to distinguish a deterministic rule branch from the LLM fallback branch."
    )

    def execute(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="rule-stage replay was not executed because query is empty",
                missing_evidence=["query"],
            )
        try:
            intent_module, _workflow_module, request_module = _business_modules()
            contexts = _contexts(request_module, kwargs.get("contexts"))
            with _EXECUTION_LOCK:
                result = intent_module.try_rule_based_intent(query, contexts)
            payload = _result_payload(result)
            normalized_query = re.sub(r"\s+", "", query)
            homepage_match = None
            for index, (pattern, intent_type) in enumerate(intent_module._HOMEPAGE_RULES):
                match = pattern.search(normalized_query)
                if match is None:
                    continue
                homepage_match = {
                    "rule_index": index,
                    "pattern": pattern.pattern,
                    "intent": intent_type.value,
                    "matched_text": match.group(0),
                    "match_span": [match.start(), match.end()],
                }
                break
            source_path = Path(intent_module.__file__).resolve()
            if homepage_match is not None and payload is not None:
                active_branch = "homepage_rule"
            elif payload is None:
                active_branch = "llm_fallback"
            else:
                active_branch = "non_homepage_rule"
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={
                    "query": query,
                    "stage": "try_rule_based_intent",
                    "matched": payload is not None,
                    "result": payload,
                    "active_branch": active_branch,
                    "homepage_match": homepage_match,
                    "next_branch": "rule_result" if payload is not None else "llm_fallback",
                    "source_path": str(source_path),
                    "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                },
                evidence=(
                    "executed app.workflow.steps.intent_recognition.try_rule_based_intent "
                    f"from {Path(load_project('marketting-planning-intent').source_project).resolve()}"
                ),
                boundary_limits=[
                    "A rule result proves only the deterministic recognizer output, not the public API envelope.",
                    "homepage_match is computed from the checked-out _HOMEPAGE_RULES object used by the replayed function.",
                    "A no-match selects the LLM fallback branch and does not prove that the rule coverage is defective.",
                    "The final public result must be connected to the same query in the current RunTrace.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"rule-stage replay failed: {type(exc).__name__}: {exc}",
                evidence=f"attempted current business rule replay for query={query}",
            )

    execute.__name__ = "marketing_intent_rule_stage_replay"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=scenario,
        parameters=_PARAMETERS,
        execute_fn=execute,
    )


def build_resolver_replay_tool() -> VerifiableTool:
    tool_id = "marketing_intent.resolver_replay"
    description = (
        "Execute the checked-out business _resolve_intent_result for the current query and contexts, "
        "including its rule selection and configured LLM fallback or supplementation, and return the actual "
        "internal IntentResult."
    )
    scenario = (
        "Attribute a public intent mismatch when the rule-stage replay alone cannot determine whether the "
        "deviation is introduced by deterministic recognition, LLM fallback, or LLM supplementation."
    )

    def execute(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="resolver replay was not executed because query is empty",
                missing_evidence=["query"],
            )
        try:
            intent_module, workflow_module, request_module = _business_modules()
            contexts = _contexts(request_module, kwargs.get("contexts"))
            with _EXECUTION_LOCK:
                rule_result = intent_module.try_rule_based_intent(query, contexts)
                result = asyncio.run(workflow_module._resolve_intent_result(query, contexts))
            rule_payload = _result_payload(rule_result)
            final_payload = _result_payload(result)
            if rule_payload is None:
                execution_path = "llm_fallback"
            elif rule_payload.get("intent") == "nbev_planning" and (
                not rule_payload.get("target_value") or not rule_payload.get("path_types")
            ):
                execution_path = "rule_with_llm_supplementation"
            else:
                execution_path = "rule_only"
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={
                    "query": query,
                    "stage": "_resolve_intent_result",
                    "execution_path": execution_path,
                    "rule_result": rule_payload,
                    "final_result": final_payload,
                },
                evidence=(
                    "executed app.workflow.nbev_workflow._resolve_intent_result "
                    f"from {Path(load_project('marketting-planning-intent').source_project).resolve()}"
                ),
                boundary_limits=[
                    "This is an in-process business resolver replay, not an HTTP request or adapter extraction.",
                    "When the LLM path runs, the result is valid for the configured model and current invocation only.",
                    "A root-cause finding still requires the current public RunTrace and the relevant source/ContextUnit.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"resolver replay failed: {type(exc).__name__}: {exc}",
                evidence=f"attempted current business resolver replay for query={query}",
            )

    execute.__name__ = "marketing_intent_resolver_replay"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=scenario,
        parameters=_PARAMETERS,
        execute_fn=execute,
    )
