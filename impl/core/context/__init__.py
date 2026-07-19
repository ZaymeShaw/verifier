"""Governed ContextUnit runtime defined by spec/adapter/context.md."""

from .adapters import (
    BaseContextAdapter,
    ConfiguredContextAdapter,
    initialize_context_adapters,
    load_configured_context_adapter,
    load_project_context_adapter,
)
from .bootstrap import DEFAULT_CONTEXT_DATA_ROOT, build_context_runtime
from .models import ContextUnit, ContextUnitRecord
from .runtime import ContextRun, ContextRuntime
from .tools import (
    CONTEXT_CANDIDATE_SELECTION_INSTRUCTIONS,
    CONTEXT_QUERY_PLANNING_INSTRUCTIONS,
    GuardedContextTools,
)

__all__ = [
    "BaseContextAdapter",
    "ConfiguredContextAdapter",
    "ContextRun",
    "ContextRuntime",
    "ContextUnit",
    "ContextUnitRecord",
    "CONTEXT_CANDIDATE_SELECTION_INSTRUCTIONS",
    "CONTEXT_QUERY_PLANNING_INSTRUCTIONS",
    "DEFAULT_CONTEXT_DATA_ROOT",
    "GuardedContextTools",
    "build_context_runtime",
    "initialize_context_adapters",
    "load_configured_context_adapter",
    "load_project_context_adapter",
]
