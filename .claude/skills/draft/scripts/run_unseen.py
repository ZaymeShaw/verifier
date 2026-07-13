#!/usr/bin/env python3
"""在未见对照 case 上运行 current/draft，输出原始结果用于泛化退化判断。

不做分数阈值或字段匹配判断。是否退化由 skill 结合 objective、review 和真实实验决定。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from impl.core.project_loader import load_adapter, load_project, load_project_role_instance
from impl.core.schema import RunTrace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.load_mock_source import load_mock_source  # noqa: E402


def _load_compare_script(role: str):
    skill_root = Path(__file__).resolve().parents[1]
    path = skill_root / role / "scripts" / f"compare_{role}.py"
    spec = importlib.util.spec_from_file_location(f"draft_compare_{role}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="Run current/draft on unseen cases for generalization check.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True, choices=("attribute", "judge"))
    parser.add_argument("--cases", required=True, help="Path to unseen cases (.json or .py fixture) or inline JSON")
    args = parser.parse_args()

    spec = load_project(args.project)
    adapter = load_adapter(spec)

    if args.cases.strip().startswith("["):
        cases = json.loads(args.cases)
    else:
        loaded = load_mock_source(args.cases)
        cases = loaded.get("iteration_cases") or loaded.get("unseen_cases") or []

    if not cases:
        print("unseen cases: empty; cannot run generalization check")
        return 0

    current_impl = getattr(adapter, args.role)()
    setattr(spec, f"{args.role}_draft", {"enabled": True, "module": f"draft/{args.role}.py"})
    draft_impl = load_project_role_instance(spec, args.role, adapter)

    compare_mod = _load_compare_script(args.role)
    fn = getattr(compare_mod, f"compare_{args.role}_outputs")
    result = fn(spec, adapter, cases, current_impl, draft_impl)
    print(json.dumps({
        "case_count": result.get("case_count"),
        "rows": result.get("rows"),
        "note": "raw current/draft outputs on unseen cases; decide generalization against review",
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
