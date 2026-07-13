#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import py_compile
from pathlib import Path

from impl.core.project_loader import load_adapter, load_project, load_project_role_instance


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a project draft role implementation.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True, choices=("attribute", "judge"))
    args = parser.parse_args()

    spec = load_project(args.project)
    draft_path = Path(spec.root) / "draft" / f"{args.role}.py"
    if not draft_path.is_file():
        raise FileNotFoundError(f"draft role not found: {draft_path}")
    py_compile.compile(str(draft_path), doraise=True)

    setattr(spec, f"{args.role}_draft", {"enabled": True, "module": f"draft/{args.role}.py"})
    instance = load_project_role_instance(spec, args.role, load_adapter(spec))
    if inspect.isabstract(instance.__class__):
        raise TypeError(f"{instance.__class__.__name__} has unimplemented abstract methods")

    print(f"{args.project}/{args.role}: {instance.__class__.__name__} validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
