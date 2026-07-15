#!/usr/bin/env python3
"""
Git PreCommand Hook
在 git checkout/pull 前检查未提交改动，避免误操作

通过 settings.json 的 PreToolUse hook 调用，匹配 Bash 命令中包含 git checkout/git pull 时触发
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def has_uncommitted_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def load_config() -> dict:
    config_path = (
        Path(__file__).parent.parent
        / "skills" / "issue-manager" / "config.yaml"
    )
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def extract_bash_command(tool_input: dict) -> str:
    return (tool_input or {}).get("command", "")


def is_git_command(cmd: str, subcommand: str) -> bool:
    pattern = rf"\bgit\s+{subcommand}\b"
    return bool(re.search(pattern, cmd))


# 硬编码受保护分支列表，禁止直接 push 到这些分支
PROTECTED_BRANCHES = ("main", "master", "trunk", "develop", "dev")


def is_direct_push_to_protected(cmd: str) -> bool:
    """检测是否是直接 git push 到受保护分支（如 main）"""
    for branch in PROTECTED_BRANCHES:
        # git push <remote> <branch>
        if re.search(rf"\bgit\s+push\s+\S+\s+{branch}\b", cmd):
            return True
        # git push <remote> <src>:<branch>
        if re.search(rf"\bgit\s+push\s+\S+\s+\S+:{branch}\b", cmd):
            return True
    return False


def extract_checkout_target(cmd: str) -> str:
    """从 git checkout/switch 命令中提取目标分支名"""
    # 匹配 git checkout [-b|-B] <branch> 或 git checkout <branch>
    # 不捕捉 -b/-B/--等参数
    m = re.search(r"\bgit\s+(?:checkout|switch)\s+(?:-[bB]\s+\S+\s+)?(--\s+)?(\S+)", cmd)
    if m:
        target = m.group(2)
        if target.startswith("-"):
            return ""
        return target
    return ""


def is_active_issue_branch(target: str, marker_dir: Path) -> bool:
    """检查目标分支是否对应 active/ 目录里的某个 issue 印记文件"""
    if not target or not marker_dir.exists():
        return False
    # 印记文件名形如 issue-{N}-{slug}.yaml，分支名形如 issue-{N}-{slug}
    for f in marker_dir.glob("issue-*.yaml"):
        # 从文件名提取 issue-{N}-{slug}
        branch_name = f.stem  # issue-{N}-{slug}
        if target == branch_name:
            return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    command = extract_bash_command(tool_input)

    if not command:
        sys.exit(0)

    # 硬编码安全约束：禁止任何直接 git push 到 main/master/trunk/develop/dev
    if is_direct_push_to_protected(command):
        msg = (
            "\n" + "=" * 60 + "\n"
            "SECURITY BLOCKED: Direct push to protected branch detected\n"
            f"Command: {command}\n"
            f"Protected branches: {', '.join(PROTECTED_BRANCHES)}\n"
            "Issue-Manager 不允许直接推送到受保护分支。\n"
            "请使用 'python3 .claude/skills/issue-manager/manage.py publish <id>'\n"
            "  该命令会硬编码推送到 issue-{N}-{slug}-pr 分支并创建 PR\n"
            + "=" * 60 + "\n"
        )
        print(msg, file=sys.stderr)
        sys.exit(2)

    config = load_config()
    git_config = config.get("git_pre_command_hooks", {})
    checkout_guard = git_config.get("checkout_guard", True)
    pull_guard = git_config.get("pull_guard", True)
    fetch_guard = git_config.get("fetch_guard", False)

    is_checkout = is_git_command(command, "checkout") or is_git_command(command, "switch")
    is_pull = is_git_command(command, "pull")
    is_fetch = is_git_command(command, "fetch")

    # ===== git checkout 额外保护：禁止切到非 issue 分支（避免误切换丢工作）=====
    if is_checkout and checkout_guard:
        # 先检查未提交改动
        if has_uncommitted_changes():
            msg = (
                "\n" + "=" * 60 + "\n"
                "Issue-Manager PreCommand: BLOCKED git checkout\n"
                "原因: 工作区有未提交改动，强制切换会丢失工作\n"
                "请先 commit 或 stash:\n"
                " - commit: git add . && git commit -m '...'\n"
                " - stash:  git stash\n"
                + "=" * 60 + "\n"
            )
            print(msg, file=sys.stderr)
            sys.exit(2)

        # 检查目标分支是否是 active issue 分支
        target = extract_checkout_target(command)
        # 跳过特殊场景：checkout -b/-B 创建新分支（target 是新分支名，允许）
        # 但如果是 checkout <非issue分支>，应该提示
        if target and not target.startswith("-"):
            marker_dir = (
                Path(__file__).parent.parent.parent
                / "skills" / "issue-manager" / "active"
            )
            # 如果目标分支不是任何 active issue 的分支，提示用户
            # 但允许 checkout 到 main 等基础分支（仅警告不 block）
            is_issue_branch = bool(re.match(r"^issue-\d+-", target))
            if is_issue_branch and not is_active_issue_branch(target, marker_dir):
                msg = (
                    "\n" + "=" * 60 + "\n"
                    f"Issue-Manager PreCommand: BLOCKED git checkout {target}\n"
                    "原因: 目标 issue 分支没有对应的印记文件\n"
                    "请使用 'python3 .claude/skills/issue-manager/manage.py checkout <id>'\n"
                    "  或先 pull <id> 创建印记\n"
                    + "=" * 60 + "\n"
                )
                print(msg, file=sys.stderr)
                sys.exit(2)

    # ===== git pull 保护：必须先 commit 或 stash =====
    elif is_pull and pull_guard:
        if has_uncommitted_changes():
            msg = (
                "\n" + "=" * 60 + "\n"
                "Issue-Manager PreCommand: BLOCKED git pull\n"
                "原因: 工作区有未提交改动，pull 可能引发冲突\n"
                "请先 commit 或 stash:\n"
                " - commit: git add . && git commit -m '...'\n"
                " - stash:  git stash\n"
                + "=" * 60 + "\n"
            )
            print(msg, file=sys.stderr)
            sys.exit(2)

    # ===== git fetch 保护：默认放行（按 spec 要求）=====
    elif is_fetch and fetch_guard:
        if has_uncommitted_changes():
            msg = (
                "\n" + "=" * 60 + "\n"
                "Issue-Manager PreCommand: WARNING git fetch\n"
                "提示: 工作区有未提交改动（fetch 本身安全，放行）\n"
                + "=" * 60 + "\n"
            )
            print(msg, file=sys.stderr)
            # fetch 只警告不 block
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()