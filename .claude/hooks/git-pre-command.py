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

try:
    import yaml
except ImportError:
    yaml = None


# 配置文件路径常量（避免重复计算）
CONFIG_PATH = (
    Path(__file__).parent.parent
    / "skills" / "issue-manager" / "config.yaml"
)
MARKER_DIR = (
    Path(__file__).parent.parent.parent
    / "skills" / "issue-manager" / "active"
)


def has_uncommitted_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def load_config() -> dict:
    if not CONFIG_PATH.exists() or yaml is None:
        return {}
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def extract_bash_command(tool_input: dict) -> str:
    """从 tool_input 中提取命令字符串
    支持 Bash 工具的 'command' 字段和 mcp__ide__executeCode 的 'code' 字段
    """
    if not tool_input:
        return ""
    # Bash 工具
    if "command" in tool_input:
        return tool_input["command"]
    # mcp__ide__executeCode 工具（Jupyter kernel 执行 !cmd 或 %shell cmd）
    if "code" in tool_input:
        return tool_input["code"]
    return ""


def is_git_command(cmd: str, subcommand: str) -> bool:
    pattern = rf"\bgit\s+{subcommand}\b"
    return bool(re.search(pattern, cmd))


# 硬编码受保护分支列表，禁止直接 push 到这些分支
PROTECTED_BRANCHES = ("main", "master", "trunk", "develop", "dev", "production", "prod", "release", "hotfix")


def get_dynamic_protected_branches() -> tuple:
    """动态获取受保护分支：硬编码 + 远程默认分支 + HEAD 引用的分支"""
    branches = list(PROTECTED_BRANCHES)

    # 获取远程默认分支（origin/HEAD）
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            # 形如 origin/main
            default_branch = result.stdout.strip().split("/", 1)[-1]
            if default_branch and default_branch not in branches:
                branches.append(default_branch)
    except Exception:
        pass

    # 从 config.yaml 读取 repo.main_branch
    if CONFIG_PATH.exists() and yaml is not None:
        try:
            with open(CONFIG_PATH) as f:
                config = yaml.safe_load(f) or {}
            main_branch = config.get("repo", {}).get("main_branch")
            if main_branch and main_branch not in branches:
                branches.append(main_branch)
        except Exception:
            pass

    return tuple(branches)


def is_direct_push_to_protected(cmd: str) -> bool:
    """检测是否是直接 git push 到受保护分支（如 main）"""
    # 必须是 git push 命令（无论是否在 bash -c/eval/$() 中）
    if not re.search(r"\bgit\s+push\b", cmd):
        return False

    # 先检查 PR 目标分支模式：issue-{N}-{slug}-pr
    # PR 目标分支只能通过 manage.py publish 推送，禁止直接 push
    if re.search(r"\bissue-\d+-[^\s:]+-pr\b", cmd):
        return True

    # 检查动态受保护分支（硬编码 + 远程默认 + 配置）
    protected_branches = get_dynamic_protected_branches()
    # 后面允许的边界字符：空白、行尾、冒号、分号、&、)、|、>、<、引号
    # 这样可拦截：分号后命令、管道、&&、$() 包装、重定向、引号包装
    end_boundary = r"(?=\s|$|:|;|&|\)|\||>|<|'|\")"
    for branch in protected_branches:
        escaped = re.escape(branch)
        # 完整匹配：<branch> 作为独立 token
        if re.search(rf"(?:^|\s|'|\"){escaped}{end_boundary}", cmd):
            return True
        # refspec dst: <src>:<branch>
        if re.search(rf":{escaped}{end_boundary}", cmd):
            return True
        # 完整 refspec 形式：refs/heads/<branch>
        if re.search(rf"refs/heads/{escaped}{end_boundary}", cmd):
            return True
        # 前缀匹配 release/* 等
        if re.search(rf"(?:^|\s|'|\"){escaped}/\S+{end_boundary}", cmd):
            return True
        if re.search(rf":{escaped}/\S+{end_boundary}", cmd):
            return True
    return False


def extract_push_target_branch(cmd: str) -> str:
    """从 git push 命令中提取目标分支名（refspec 的 dst 部分）"""
    # git push <remote> <src>:<dst>
    m = re.search(r"\bgit\s+push\s+\S+\s+\S+:([^/\s:]+(?:/[^/\s:]+)*)", cmd)
    if m:
        return m.group(1)
    # git push <remote> <branch>（src 和 dst 同名）
    m = re.search(r"\bgit\s+push\s+\S+\s+([^/\s:]+(?:/[^/\s:]+)*)\s*$", cmd)
    if m and not m.group(1).startswith("-"):
        return m.group(1)
    return ""


def is_issue_branch_name(branch: str) -> bool:
    """检查分支名是否符合 issue-{N}-{slug} 模式"""
    return bool(re.match(r"^issue-\d+-", branch))


def is_direct_push_to_issue_work_branch(cmd: str) -> bool:
    """检测是否直接 push 到 issue 工作分支（应通过 publish 推到 -pr 分支）"""
    target = extract_push_target_branch(cmd)
    if not target:
        return False
    # issue 工作分支：issue-{N}-{slug}（不以 -pr 结尾）
    if is_issue_branch_name(target) and not target.endswith("-pr"):
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
        # 展示动态获取的完整受保护分支列表
        dynamic_branches = get_dynamic_protected_branches()
        msg = (
            "\n" + "=" * 60 + "\n"
            "SECURITY BLOCKED: Direct push to protected branch detected\n"
            f"Command: {command}\n"
            f"Protected branches: {', '.join(dynamic_branches)}\n"
            "Issue-Manager 不允许直接推送到受保护分支。\n"
            "请使用 'python3 .claude/skills/issue-manager/manage.py publish <id>'\n"
            "  该命令会硬编码推送到 issue-{N}-{slug}-pr 分支并创建 PR\n"
            + "=" * 60 + "\n"
        )
        print(msg, file=sys.stderr)
        sys.exit(2)

    # 安全约束：禁止直接 push 到 issue 工作分支（绕过 publish 流程）
    if is_direct_push_to_issue_work_branch(command):
        target = extract_push_target_branch(command)
        msg = (
            "\n" + "=" * 60 + "\n"
            f"SECURITY BLOCKED: Direct push to issue work branch: {target}\n"
            f"Command: {command}\n"
            "Issue 工作分支必须通过 publish 命令推送（推到 -pr 后缀分支）。\n"
            "请使用: python3 .claude/skills/issue-manager/manage.py publish <id>\n"
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
            # 如果目标分支不是任何 active issue 的分支，提示用户
            # 但允许 checkout 到 main 等基础分支（仅警告不 block）
            is_issue_branch = bool(re.match(r"^issue-\d+-", target))
            if is_issue_branch and not is_active_issue_branch(target, MARKER_DIR):
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