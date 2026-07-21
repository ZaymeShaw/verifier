"""Planning investigation tools that execute the checked-out business workflow.

The tools report current behavior and source identity.  They do not calculate an
expected target value or encode evaluation-case answers.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import sys
import threading
from pathlib import Path
from typing import Any

from impl.core.project_loader import load_project
from impl.tools import ToolResult, VerifiableTool


_IMPORT_LOCK = threading.Lock()
_EXECUTION_LOCK = threading.Lock()


def _business_modules() -> tuple[Any, Any, Any, Any]:
    spec = load_project("marketting-planning")
    source_root = Path(spec.source_project).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"business source repository not found: {source_root}")
    with _IMPORT_LOCK:
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        path_types = importlib.import_module("app.workflow.path_types")
        workflow = importlib.import_module("app.workflow.nbev_workflow")
        request = importlib.import_module("app.schemas.request")
        events = importlib.import_module("app.schemas.events")
    return path_types, workflow, request, events


def _source_fact(callable_obj: Any) -> dict[str, str]:
    path = Path(inspect.getsourcefile(callable_obj) or "").resolve()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "function": callable_obj.__name__,
        "source": inspect.getsource(callable_obj),
    }


def _source_identity(callable_obj: Any) -> dict[str, str]:
    path = Path(inspect.getsourcefile(callable_obj) or "").resolve()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "function": callable_obj.__name__,
    }


def _compact_result(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    result = {}
    for name in ("is_complete", "target_value", "path_types", "intent", "confidence"):
        if hasattr(value, name):
            item = getattr(value, name)
            result[name] = getattr(item, "value", item)
    return result or repr(value)


_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The exact current-case user query from RunTrace.",
        },
        "contexts": {
            "type": "array",
            "description": "Optional current conversation contexts in the business ContextItem shape.",
            "items": {"type": "object"},
        },
    },
    "required": ["query"],
}


def build_field_extraction_replay_tool() -> VerifiableTool:
    tool_id = "marketing_planning.field_extraction_replay"
    description = (
        "Execute the checked-out business extract_target_value_from_text and "
        "extract_path_types_from_text on the exact current query, returning their "
        "actual values together with the executed function source and hash."
    )

    def execute(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="field extraction replay was not executed because query is empty",
                missing_evidence=["query"],
            )
        try:
            path_types, _workflow, _request, _events = _business_modules()
            with _EXECUTION_LOCK:
                target_value = path_types.extract_target_value_from_text(query)
                paths = path_types.extract_path_types_from_text(query)
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={
                    "query": query,
                    "target_value": target_value,
                    "path_types": paths,
                    "target_extractor": _source_fact(path_types.extract_target_value_from_text),
                    "path_extractor": _source_fact(path_types.extract_path_types_from_text),
                },
                evidence="executed the current business field extraction functions on the current query",
                boundary_limits=[
                    "The replay establishes parser output, not the expected business value.",
                    "It does not establish that the public request used the same query unless RunTrace confirms it.",
                    "Downstream propagation must be verified separately when the public output differs from parser output.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"field extraction replay failed: {type(exc).__name__}: {exc}",
                evidence=f"attempted current business extraction replay for query={query}",
            )

    execute.__name__ = "marketing_planning_field_extraction_replay"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=(
            "A planning gap may originate before path dispatch because target value or path types "
            "appear wrong, missing, or inconsistent with the public response."
        ),
        parameters=_PARAMETERS,
        execute_fn=execute,
    )


def build_workflow_handoff_replay_tool() -> VerifiableTool:
    tool_id = "marketing_planning.workflow_handoff_replay"
    description = (
        "Execute the checked-out business stream_nbev_workflow only through its first "
        "PlanningStartedEvent, then return the actual target value and path types handed "
        "to planning without running the planning functions."
    )

    async def replay(query: str, raw_contexts: Any) -> dict[str, Any]:
        _path_types, workflow, request_module, events = _business_modules()
        intent_module = importlib.import_module("app.workflow.steps.intent_recognition")
        clarification_module = importlib.import_module("app.workflow.steps.field_clarification")
        contexts = None
        if raw_contexts:
            if not isinstance(raw_contexts, list):
                raise TypeError("contexts must be an array")
            contexts = [request_module.ContextItem.model_validate(item) for item in raw_contexts]
        request = request_module.ChatRequest(
            session_id="attribute-workflow-handoff-replay",
            request_id="attribute-workflow-handoff-replay",
            user_message=query,
            org_id="attribute-investigation",
            contexts=contexts,
        )
        observed_calls: list[dict[str, Any]] = []
        original_homepage = workflow.try_homepage_intent
        original_rule = workflow.try_rule_based_intent
        original_llm = workflow.recognize_intent
        original_clarification = workflow.process_clarification
        original_intent_target = intent_module.extract_target_value_from_text
        original_clarification_target = clarification_module.extract_target_value_from_text

        def traced_homepage(*args: Any, **kwargs: Any) -> Any:
            result = original_homepage(*args, **kwargs)
            observed_calls.append({"call": "try_homepage_intent", "result": _compact_result(result)})
            return result

        def traced_intent_target(*args: Any, **kwargs: Any) -> Any:
            result = original_intent_target(*args, **kwargs)
            observed_calls.append({"call": "intent_recognition.extract_target_value_from_text", "result": result})
            return result

        def traced_clarification_target(*args: Any, **kwargs: Any) -> Any:
            result = original_clarification_target(*args, **kwargs)
            observed_calls.append({"call": "field_clarification.extract_target_value_from_text", "result": result})
            return result

        def traced_rule(*args: Any, **kwargs: Any) -> Any:
            result = original_rule(*args, **kwargs)
            observed_calls.append({"call": "try_rule_based_intent", "result": _compact_result(result)})
            return result

        async def traced_llm(*args: Any, **kwargs: Any) -> Any:
            result = await original_llm(*args, **kwargs)
            observed_calls.append({"call": "recognize_intent", "result": _compact_result(result)})
            return result

        async def traced_clarification(*args: Any, **kwargs: Any) -> Any:
            result = await original_clarification(*args, **kwargs)
            observed_calls.append({"call": "process_clarification", "result": _compact_result(result)})
            return result

        workflow.try_homepage_intent = traced_homepage
        workflow.try_rule_based_intent = traced_rule
        workflow.recognize_intent = traced_llm
        workflow.process_clarification = traced_clarification
        intent_module.extract_target_value_from_text = traced_intent_target
        clarification_module.extract_target_value_from_text = traced_clarification_target
        generator = workflow.stream_nbev_workflow(request, {})
        try:
            async for event in generator:
                if isinstance(event, events.PlanningStartedEvent):
                    return {
                        "event": "PlanningStartedEvent",
                        "target_value": event.target_value,
                        "path_types": list(event.path_types),
                        "think": event.think,
                        "observed_calls": observed_calls,
                    }
                if isinstance(event, events.NonPlanningResultEvent):
                    response = event.response.model_dump(mode="json")
                    return {"event": "NonPlanningResultEvent", "response": response}
        finally:
            await generator.aclose()
            workflow.try_homepage_intent = original_homepage
            workflow.try_rule_based_intent = original_rule
            workflow.recognize_intent = original_llm
            workflow.process_clarification = original_clarification
            intent_module.extract_target_value_from_text = original_intent_target
            clarification_module.extract_target_value_from_text = original_clarification_target
        return {"event": "no_event"}

    def execute(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="workflow handoff replay was not executed because query is empty",
                missing_evidence=["query"],
            )
        try:
            with _EXECUTION_LOCK:
                actual = asyncio.run(replay(query, kwargs.get("contexts")))
            _path_types, workflow, _request, _events = _business_modules()
            actual["workflow_source"] = _source_identity(workflow.stream_nbev_workflow)
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={"query": query, **actual},
                evidence="executed the current workflow through its planning handoff event",
                boundary_limits=[
                    "The replay intentionally stops before path planning and external data access.",
                    "A PlanningStartedEvent proves the current handoff value, not final card correctness.",
                    "LLM-dependent branches may vary and must be reconciled with the original public RunTrace.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"workflow handoff replay failed: {type(exc).__name__}: {exc}",
                evidence=f"attempted current business workflow handoff replay for query={query}",
            )

    execute.__name__ = "marketing_planning_workflow_handoff_replay"
    execute.__doc__ = description
    return VerifiableTool(
        tool_id=tool_id,
        description=description,
        applicable_scenario=(
            "Field extraction alone cannot show whether session merge or workflow conversion "
            "changed the value before planning dispatch."
        ),
        parameters=_PARAMETERS,
        execute_fn=execute,
    )
