from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional

from .embedding import UnconfiguredEmbeddingProvider
from .errors import ContextValidationError
from .policy import ContextPolicyResolver
from .registry import SQLiteContextDatabase, SQLiteContextRegistry
from .resolvers import CompositeContentResolver, FileContentResolver
from .runtime import ContextRuntime
from .vector_index import SQLiteContextVectorIndex

_IMPL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTEXT_DATA_ROOT = _IMPL_ROOT / "data" / "context_runtime"

DEFAULT_PUBLIC_POLICY = {
    # Fail closed until the common layer explicitly defines role/operation boundaries.
    "default": {
        "enabled": False,
        "allowed_statuses": ["active"],
        "candidate_limit": 20,
        "load_limit": 8,
        "content_char_budget": 100_000,
        "query_limit": 4,
        "top_k_per_query": 5,
    }
}

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def build_context_runtime(
    *,
    project_id: str,
    data_root: Optional[Path] = None,
    project_root: Optional[Path] = None,
    embedding_provider: Any = None,
    content_resolver: Any = None,
    public_policy: Optional[Mapping[str, Any]] = None,
    project_policy: Optional[Mapping[str, Any]] = None,
) -> ContextRuntime:
    normalized_project_id = str(project_id or "").strip()
    if not _PROJECT_ID_RE.fullmatch(normalized_project_id) or normalized_project_id in {".", ".."}:
        raise ContextValidationError(f"invalid project_id for context runtime: {project_id!r}")
    root = Path(data_root or DEFAULT_CONTEXT_DATA_ROOT)
    database = SQLiteContextDatabase(root / normalized_project_id / "context.sqlite3")

    resolver = content_resolver
    if resolver is None:
        resolvers = []
        if project_root is not None:
            resolvers.append(FileContentResolver([Path(project_root)]))
        resolver = CompositeContentResolver(resolvers)

    return ContextRuntime(
        project_id=normalized_project_id,
        registry=SQLiteContextRegistry(database),
        vector_index=SQLiteContextVectorIndex(database),
        embedding_provider=embedding_provider or UnconfiguredEmbeddingProvider(),
        content_resolver=resolver,
        policy_resolver=ContextPolicyResolver(
            public_config=public_policy or DEFAULT_PUBLIC_POLICY,
            project_config=project_policy,
        ),
    )
