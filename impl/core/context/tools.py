from __future__ import annotations

from typing import Mapping, Optional, Sequence

from .runtime import ContextRun


def search_context_units_tool(
    context_run: ContextRun,
    queries: Sequence[str],
    top_k_per_query: Optional[int] = None,
):
    return context_run.search_context_units(queries, top_k_per_query=top_k_per_query)


def load_context_units_tool(context_run: ContextRun, unit_ids: Sequence[str]):
    return [
        {
            "id": unit.id,
            "name": unit.name,
            "description": unit.description,
            "content": unit.content,
        }
        for unit in context_run.load_context_units(unit_ids)
    ]


class GuardedContextTools:
    """Bound methods expose only model-controlled queries/ids, never governance fields."""

    def __init__(self, context_run: ContextRun):
        self._context_run = context_run

    def search_context_units(
        self, queries: Sequence[str], top_k_per_query: Optional[int] = None
    ):
        return search_context_units_tool(
            self._context_run, queries, top_k_per_query=top_k_per_query
        )

    def load_context_units(self, unit_ids: Sequence[str]):
        return load_context_units_tool(self._context_run, unit_ids)

    def context_debug(self) -> Mapping[str, object]:
        return self._context_run.debug_snapshot()
