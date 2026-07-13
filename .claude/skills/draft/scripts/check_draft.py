#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import os
import py_compile
import subprocess
from pathlib import Path

from impl.core.project_loader import load_adapter, load_project, load_project_role_instance


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a project draft role implementation.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True, choices=("attribute", "judge"))
    parser.add_argument(
        "--promotion",
        action="store_true",
        help="Run promotion prechecks: unseen generalization run and knowledge update detection.",
    )
    parser.add_argument(
        "--iteration-cases",
        help="Path or expression that loads the iteration cases. Optional for --promotion.",
    )
    parser.add_argument(
        "--unseen-cases",
        help="Path or expression that loads the unseen cases. Required for --promotion.",
    )
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

    if args.promotion:
        knowledge_path = (
            Path(__file__).resolve().parents[1]
            / args.role
            / "knowledge.md"
        )
        if not knowledge_path.is_file():
            print(f"knowledge update: missing {knowledge_path}")
        else:
            stat = os.stat(knowledge_path)
            mtime = stat.st_mtime
            print(f"knowledge update: {knowledge_path} mtime={mtime}")
        if not args.unseen_cases:
            print("unseen cases: not provided; cannot run generalization check")
        else:
            cmd = [
                os.environ.get("PYTHON", "python"),
                str(Path(__file__).resolve().parents[1] / "scripts" / "run_unseen.py"),
                "--project",
                args.project,
                "--role",
                args.role,
                "--cases",
                args.unseen_cases,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout)
            if result.returncode != 0:
                print(f"unseen run failed: {result.stderr.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
