#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path


def run(args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def _root_from_worktree_path(worktree_path):
    parts = worktree_path.parts
    for index in range(len(parts) - 2):
        if parts[index] == ".claude" and parts[index + 1] == "worktrees":
            return Path(*parts[:index])
    return None


def main():
    data = json.load(sys.stdin)
    raw_path = (
        data.get("worktree_path")
        or data.get("worktreePath")
        or data.get("hookSpecificInput", {}).get("worktreePath")
        or data.get("hook_specific_input", {}).get("worktreePath")
    )
    if not raw_path:
        print(json.dumps({"continue": True, "hookSpecificOutput": {"hookEventName": "WorktreeRemove"}, "systemMessage": "WorktreeRemove hook skipped: no worktree path in input."}))
        return
    worktree_path = Path(raw_path).resolve()
    root = _root_from_worktree_path(worktree_path)
    if root is None:
        cwd = Path(data.get("cwd") or os.getcwd()).resolve()
        root = Path(run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
    allowed_dir = (root / ".claude" / "worktrees").resolve()
    if allowed_dir not in worktree_path.parents:
        raise RuntimeError(f"refusing to remove unmanaged worktree: {worktree_path}")
    run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree_path)], check=False)
    run(["git", "-C", str(root), "worktree", "prune"], check=False)
    print(json.dumps({"continue": True, "suppressOutput": True, "hookSpecificOutput": {"hookEventName": "WorktreeRemove"}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"continue": False, "systemMessage": f"WorktreeRemove hook failed: {exc}"}))
        sys.exit(2)
