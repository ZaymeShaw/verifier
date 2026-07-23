"""Factories that bind reusable client_search verification tools to project assets.

The investigation manifest needs zero-argument factories that can be imported and
validated deterministically.  The underlying tools remain the production project
tools; this module only resolves their configured source files.
"""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
import threading
from typing import Any

from impl.core.project_loader import load_project, resolve_project_source_root
from impl.core.config_schema import ConfigError
from impl.projects.client_search.tools.field_capability import build_field_capability_tool
from impl.projects.client_search.tools.rule_verify import build_rule_verify_tool
from impl.projects.client_search.tools.search_api import build_search_api_tool
from impl.tools import ToolResult, VerifiableTool


def build_investigation_field_capability_tool():
    spec = load_project("client_search")
    return build_field_capability_tool(spec.source_path("field_definitions"))


def build_investigation_rule_verify_tool():
    spec = load_project("client_search")
    return build_rule_verify_tool(
        spec.source_path("value_mappings"),
        spec.source_path("enhanced_rules"),
    )


def build_investigation_search_api_tool():
    spec = load_project("client_search")
    service = spec.service("primary")
    required = ("base_url", "endpoint", "method", "timeout_seconds")
    missing = [field for field in required if service.get(field) in (None, "")]
    if missing:
        raise ConfigError(f"client_search runtime.services.primary missing: {', '.join(missing)}")
    return build_search_api_tool(
        api_base=str(service["base_url"]),
        endpoint=str(service["endpoint"]),
        method=str(service["method"]),
        timeout=float(service["timeout_seconds"]),
    )


def build_investigation_case_route_replay_tool() -> VerifiableTool:
    """Replay the real business L2 matcher and retain its case-level internals."""
    spec = load_project("client_search")
    source_root = resolve_project_source_root(spec)
    tool_id = "client_search.case_route_replay"
    matcher: Any = None
    matcher_lock = threading.Lock()

    def get_matcher() -> Any:
        nonlocal matcher
        if matcher is not None:
            return matcher
        if not source_root.is_dir():
            raise FileNotFoundError(f"business source repository not found: {source_root}")
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        module = importlib.import_module("src.main.python.steps.level2_enhanced_matcher")
        matcher = module.Level2EnhancedMatcher()
        return matcher

    async def replay_level2(active_matcher: Any, query: str) -> dict[str, Any]:
        conditions = await active_matcher.match(query)
        normalized_query = active_matcher._preprocess_query(query)
        matched_patterns = []
        for raw in list(active_matcher._last_matched_patterns or []):
            item = dict(raw)
            pattern = str(item.get("pattern") or "")
            match = re.fullmatch(pattern, normalized_query) if pattern else None
            item["capture_groups"] = list(match.groups()) if match is not None else []
            matched_patterns.append(item)
        return {
            "query": query,
            "normalized_query": normalized_query,
            "stage": "level2_enhanced_matcher",
            "conditions": [
                {
                    "field": condition.field,
                    "operator": getattr(condition.operator, "value", str(condition.operator)),
                    "value": condition.value,
                }
                for condition in conditions
            ],
            "matched_patterns": matched_patterns,
        }

    def execute(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="query is required for L2 case replay",
                missing_evidence=["query"],
            )
        business_logger = None
        try:
            from loguru import logger as business_logger

            business_logger.disable("src.main.python")
            # The business matcher stores debug patterns in a ContextVar. Keep
            # match() and snapshotting inside the same coroutine/context.
            with matcher_lock:
                actual = asyncio.run(replay_level2(get_matcher(), query))
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual=actual,
                evidence=(
                    "executed the configured business Level2EnhancedMatcher at "
                    f"{source_root} for query={query}"
                ),
                boundary_limits=[
                    "This probe executes the business L2 matcher directly; combine it with the API matched_level to prove router selection.",
                    "It does not execute L1, L4, endpoint post-processing or downstream customer search.",
                ],
            )
        except Exception as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"L2 case replay failed: {type(exc).__name__}: {exc}",
                evidence=f"attempted business Level2EnhancedMatcher replay for query={query}",
            )
        finally:
            if business_logger is not None:
                business_logger.enable("src.main.python")

    execute.__name__ = "client_search_case_route_replay"
    execute.__doc__ = (
        "直接执行 client_search 业务源码中的 Level2EnhancedMatcher，返回归一化查询、"
        "实际命中规则、正则捕获组和生成条件。"
    )
    return VerifiableTool(
        tool_id=tool_id,
        description=(
            "Replay one business parse request in the real Level 2 matcher while retaining the normalized query, "
            "matched rule/pattern, capture groups and generated conditions, so Attribute can connect an API "
            "matched_level=2 result to the exact extraction mechanism."
        ),
        applicable_scenario=(
            "client_search attribution when the API reports matched_level=2 and a final condition is missing, "
            "extra or semantically wrong"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Required business query to replay through the real L2 matcher."},
                "trace_id": {"type": "string", "description": "Optional correlation identifier; not interpreted by L2."},
            },
            "required": ["query"],
        },
        execute_fn=execute,
    )
