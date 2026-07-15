#!/usr/bin/env python3
"""
Sync marker files to remote .issue-markers branch
解决"印记文件本地存储"问题，让印记可跨机器同步
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


MARKER_BRANCH = ".issue-markers"
ACTIVE_DIR = Path(".claude/skills/issue-manager/active")


def run(cmd, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def push_markers():
    """推送本地印记文件到远程 .issue-markers 分支"""
    if not ACTIVE_DIR.exists():
        print(f"印记目录不存在: {ACTIVE_DIR}")
        sys.exit(1)

    markers = list(ACTIVE_DIR.glob("issue-*.yaml"))
    if not markers:
        print("没有印记文件可推送")
        sys.exit(1)

    print(f"[sync] 准备推送 {len(markers)} 个印记到远程 {MARKER_BRANCH}")

    current = run(["git", "branch", "--show-current"]).stdout.strip()
    print(f"  当前分支: {current}")

    tmp_dir = Path("/tmp/.issue-markers-sync")
    if tmp_dir.exists():
        run(["rm", "-rf", str(tmp_dir)])

    remote_check = run(
        ["git", "ls-remote", "--heads", "origin", MARKER_BRANCH],
        check=False,
    )
    branch_exists = bool(remote_check.stdout.strip())

    if branch_exists:
        print(f"  远程分支 {MARKER_BRANCH} 已存在，fetch")
        run(["git", "worktree", "add", str(tmp_dir), f"origin/{MARKER_BRANCH}"])
    else:
        print(f"  远程分支 {MARKER_BRANCH} 不存在，创建孤儿分支")
        run(["git", "worktree", "--detach", str(tmp_dir)])
        run(["git", "-C", str(tmp_dir), "checkout", "--orphan", MARKER_BRANCH])
        run(["git", "-C", str(tmp_dir), "rm", "-rf", "."], check=False)

    marker_target = tmp_dir / "markers"
    marker_target.mkdir(exist_ok=True)
    for marker in markers:
        target = marker_target / marker.name
        target.write_text(marker.read_text())
        print(f"  复制: {marker.name}")

    run(["git", "-C", str(tmp_dir), "add", "."])
    run(["git", "-C", str(tmp_dir), "commit", "-m", f"sync: {len(markers)} markers"])

    if branch_exists:
        run(["git", "-C", str(tmp_dir), "push", "origin", MARKER_BRANCH])
    else:
        run(["git", "-C", str(tmp_dir), "push", "-u", "origin", MARKER_BRANCH])

    run(["git", "worktree", "remove", str(tmp_dir), "--force"])

    print(f"\n✓ 已同步 {len(markers)} 个印记到远程 {MARKER_BRANCH}")


def pull_markers():
    """从远程 .issue-markers 分支拉取印记到本地"""
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)

    remote_check = run(
        ["git", "ls-remote", "--heads", "origin", MARKER_BRANCH],
        check=False,
    )
    if not remote_check.stdout.strip():
        print(f"远程分支 {MARKER_BRANCH} 不存在")
        sys.exit(1)

    print(f"[sync] 从远程 {MARKER_BRANCH} 拉取印记")

    run(["git", "fetch", "origin", MARKER_BRANCH])

    result = run(
        ["git", "show", f"origin/{MARKER_BRANCH}:markers/"],
        check=False,
    )
    if result.returncode != 0:
        print("远程没有 markers/ 目录")
        sys.exit(1)

    files = re.findall(r"^(issue-\d+-\S+\.yaml)$", result.stdout, re.MULTILINE)
    if not files:
        print("远程没有印记文件")
        sys.exit(1)

    print(f"  发现 {len(files)} 个远程印记")
    for fname in files:
        content = run(
            ["git", "show", f"origin/{MARKER_BRANCH}:markers/{fname}"]
        ).stdout
        target = ACTIVE_DIR / fname
        target.write_text(content)
        print(f"  拉取: {fname}")

    print(f"\n✓ 已同步 {len(files)} 个印记到本地 {ACTIVE_DIR}")


def list_markers():
    """列出远程印记"""
    remote_check = run(
        ["git", "ls-remote", "--heads", "origin", MARKER_BRANCH],
        check=False,
    )
    if not remote_check.stdout.strip():
        print(f"远程分支 {MARKER_BRANCH} 不存在")
        return

    result = run(
        ["git", "show", f"origin/{MARKER_BRANCH}:markers/"],
        check=False,
    )
    if result.returncode != 0:
        print("远程没有 markers/ 目录")
        return

    files = re.findall(r"^(issue-\d+-\S+\.yaml)$", result.stdout, re.MULTILINE)
    print(f"远程印记 ({len(files)}):")
    for fname in files:
        print(f"  - {fname}")


def main():
    parser = argparse.ArgumentParser(description="Issue markers sync")
    parser.add_argument("action", choices=["push", "pull", "list"])
    args = parser.parse_args()

    if args.action == "push":
        push_markers()
    elif args.action == "pull":
        pull_markers()
    elif args.action == "list":
        list_markers()


if __name__ == "__main__":
    main()
