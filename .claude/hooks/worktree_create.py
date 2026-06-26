#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)


def main():
    data = json.load(sys.stdin)
    cwd = Path(data.get("cwd") or os.getcwd()).resolve()
    root = Path(run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
    worktrees_dir = root / ".claude" / "worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:12]
    branch = f"claude-agent-{suffix}"
    worktree_path = worktrees_dir / branch
    run(["git", "-C", str(root), "worktree", "add", "-b", branch, str(worktree_path), "HEAD"])
    print(str(worktree_path))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"continue": False, "systemMessage": f"WorktreeCreate hook failed: {exc}"}))
        sys.exit(2)
