from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from impl.core.context.adapters import (
    initialize_context_adapters,
    load_configured_context_adapter,
    load_project_context_adapter,
)
from impl.core.context.bootstrap import build_context_runtime
from impl.core.project_loader import load_project


def initialize_project_context(
    project_id: str,
    *,
    data_root: Optional[Path] = None,
    embedding_provider: Any = None,
    public_adapters: Sequence[Any] = (),
) -> Mapping[str, Any]:
    spec = load_project(project_id)
    context_config = dict((getattr(spec, "extra", {}) or {}).get("context") or {})
    project_policy = context_config.get("policy") if isinstance(context_config.get("policy"), Mapping) else None
    runtime = build_context_runtime(
        project_id=spec.project_id,
        data_root=data_root,
        project_root=Path(spec.root),
        embedding_provider=embedding_provider,
        project_policy=project_policy,
    )
    project_adapters = [
        adapter
        for adapter in (
            load_configured_context_adapter(spec),
            load_project_context_adapter(spec),
        )
        if adapter is not None
    ]
    result = dict(
        initialize_context_adapters(
            runtime,
            project_spec=spec,
            public_adapters=public_adapters,
            project_adapters=project_adapters,
        )
    )
    result.update(
        {
            "ok": True,
            "project_id": spec.project_id,
            "message": (
                "context initialization completed"
                if result["record_count"]
                else "project has no configured context units yet"
            ),
        }
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Initialize governed ContextUnit knowledge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="register stable project context units")
    init_parser.add_argument("--project", required=True)
    init_parser.add_argument("--data-root", help="override context data root (primarily for tests)")
    args = parser.parse_args(argv)

    if args.command == "init":
        result = initialize_project_context(
            args.project,
            data_root=Path(args.data_root) if args.data_root else None,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
