#!/usr/bin/env python3
"""
Issue-Manager Skill 主体
# 命令接口：
# pull <id>     - fetch origin → 检查未提交改动 → checkout → 创建印记文件
# list          - 列出 active/ 目录所有文件
# checkout <id> - 切换到该 issue 的分支
# status        - 查看当前分支状态
# publish <id>  - 身份校验 → 前置检查 → 测试 → 确认 → push → PR
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


class IssueManager:
    """Issue 管理 skill 主体"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = (
                Path(__file__).parent / "config.yaml"
            ).resolve()
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.active_dir = Path(__file__).parent / "active"

    def _load_config(self) -> Dict:
        """加载配置文件"""
        import yaml

        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def run(self, args: list):
        """执行命令"""
        cmd = args[0] if args else "help"

        if cmd == "pull":
            self.pull(args[1])
        elif cmd == "list":
            self._list_issues()
        elif cmd == "checkout":
            self.checkout(args[1])
        elif cmd == "status":
            self._status()
        elif cmd == "publish":
            self.publish(args[1])
        elif cmd == "help":
            self._help()
        else:
            print(f"Unknown command: {cmd}")
            self._help()

    # ============ pull 命令 ============

    def pull(self, issue_id: str):
        """pull <id> - fetch origin → 检查未提交改动 → checkout → 创建印记文件"""
        N = self._parse_issue_id(issue_id)
        slug = self._get_slug()
        branch_pattern = self.config["branch"]["pattern"].format(N=N, slug=slug)

        print(f"[pull] Creating branch: {branch_pattern}")

        # Step 0: fetch origin
        print("\n[1/5] Fetching origin...")
        self._run_git("fetch", self.config["repo"]["remote"])
        print("✓ Fetched origin")

        # Step 1: 检查未提交改动
        print("\n[2/5] Checking uncommitted changes...")
        self._check_uncommitted_changes()

        # Step 2: 检查当前分支有未合并的 commit
        print("\n[3/5] Checking unmerged commits...")
        self._check_unmerged_commits()

        # Step 3: checkout -b
        print(f"\n[4/5] Creating branch: {branch_pattern}")
        self._run_git("checkout", "-b", branch_pattern, "origin/main")
        print("✓ Checked out and created branch")

        # Step 4: 创建印记文件
        print(f"\n[5/5] Creating印记 file...")
        self._create_marker_file(N, slug)
        print(f"✓ Created印记 file:  issue-{N}-{slug}.yaml")

        print(f"\n{'='*60}")
        print(f"✓ Issue {N} 准备完成")
        print(f"  Branch: {branch_pattern}")
        print(f"  印记: .claude/skills/issue-manager/active/issue-{N}-{slug}.yaml")
        print(f"{'='*60}")

    # ============ list 命令 ============

    def _list_issues(self):
        """list - 列出 active/ 目录所有文件"""
        if not self.active_dir.exists():
            print(f"印记目录不存在: {self.active_dir}")
            return

        issues = []
        for f in self.active_dir.glob("issue-*.yaml"):
            try:
                N = int(f.stem.split("-")[1])
                slug = "-".join(f.stem.split("-")[2:])
                issues.append({"N": N, "slug": slug, "file": f.name})
            except (IndexError, ValueError):
                continue

        if not issues:
            print("没有活跃的 issue")
            return

        print(f"\n活跃的 issue ({len(issues)}):")
        print("-" * 60)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. Issue {issue['N']}: {issue['slug']}")
            print(f"   文件: {issue['file']}")

    # ============ checkout 命令 ============

    def checkout(self, issue_id: str):
        """checkout <id> - 切换到该 issue 的分支"""
        N = self._parse_issue_id(issue_id)
        slug = self._get_slug()
        branch_pattern = self.config["branch"]["pattern"].format(N=N, slug=slug)

        # 检查印记文件
        marker_file_path = self.active_dir / f"issue-{N}-{slug}.yaml"
        if not marker_file_path.exists():
            print(f"印记文件不存在: {marker_file_path}")
            print("可用 issue:")
            self._list_issues()
            return

        # 检查当前是否有未提交改动才能 checkout
        if self._has_uncommitted_changes():
            print("⚠ 当前有未提交改动，请先 commit 或 stash")
            print("  不可强制 checkout/切换分支")
            return

        # checkout
        print(f"Switching to branch: {branch_pattern}")
        self._run_git("checkout", branch_pattern)

        print(f"\n✓ 已切换到分支: {branch_pattern}")
        print(f"  印记: {marker_file_path}")
        # PR 目标分支仅用于信息显示
        target_branch = f"issue-{N}-{slug}-pr"
        print(f"  PR 目标分支: {target_branch}")

    # ============ publish 命令 ============

    def publish(self, issue_id: str):
        """publish <id> - 身份校验 → 前置检查 → 测试 → 确认 → push → PR"""
        N = self._parse_issue_id(issue_id)
        slug = self._get_slug()
        branch_pattern = self.config["branch"]["pattern"].format(N=N, slug=slug)

        # 硬编码安全约束：PR 目标分支必须以 -pr 结尾，绝不允许直接推送到 main
        PR_TARGET_BRANCH = f"issue-{N}-{slug}-pr"
        if PR_TARGET_BRANCH.endswith("-pr") is False:
            print(f"✗ 安全拦截：PR 目标分支命名不合规: {PR_TARGET_BRANCH}")
            print("  PR 目标分支必须以 '-pr' 结尾，禁止直接推送到 main")
            return

        # 额外安全检查：禁止任何包含 'main'、'master'、'trunk' 的目标分支
        PROTECTED_BRANCHES = ["main", "master", "trunk", "develop", "dev"]
        for protected in PROTECTED_BRANCHES:
            if protected in PR_TARGET_BRANCH.lower():
                print(f"✗ 安全拦截：PR 目标分支包含受保护分支名: {PR_TARGET_BRANCH}")
                print(f"  禁止推送到: {protected}")
                return

        marker_file_path = self.active_dir / f"issue-{N}-{slug}.yaml"
        if not marker_file_path.exists():
            print(f"印记文件不存在: {marker_file_path}")
            return

        print(f"[publish] Publishing issue {N}")
        print(f"  安全策略: PR 目标分支硬编码为 {PR_TARGET_BRANCH}")

        # Step 1: 身份校验 (已在 checkout 检查当前分支模式)
        print("\n[1/6] 身份校验...")
        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip()
        if not re.match(rf"issue-{N}-.*", current_branch):
            print(f"⚠ 当前分支不是 issue {N} 的分支: {current_branch}")
            print("   请先运行 'issue-manager checkout <id>'")
            return
        print(f"✓ 身份校验通过: {current_branch}")

        # Step 2: 前置检查
        print("\n[2/6] 前置检查...")
        real_commits = self._count_real_commits()
        min_commits = self.config["publish"]["min_real_commits"]

        if real_commits < min_commits:
            print(
                f"⚠ 有实质代码 commit 数 ({real_commits}) < 要求下限 ({min_commits})"
            )
            print(
                f"   请先进行与 origin/main 相对的实质改动 (git commit)"
            )
            return
        print(f"✓ 有 {real_commits} 个实质代码 commit")

        # Step 3: 测试关卡
        test_command = self.config["publish"]["test_command"]
        if test_command:
            print(f"\n[3/6] 测试关卡...")
            try:
                result = subprocess.run(
                    test_command,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print("✓ 测试通过")
            except subprocess.CalledProcessError as e:
                print(f"✗ 测试失败: {e}")
                return
        else:
            print("\n[3/6] 测试关卡 - 跳过 (test_command 为空)")

        # Step 4: 用户确认
        print("\n[4/6] 请确认:")
        print(f"\n  1. Push 分支: {current_branch}")
        print(f"  2. PR 目标分支: {PR_TARGET_BRANCH} (远程 main 保护)")
        print(f"  3. 印记文件: {marker_file_path}")

        confirm_msg = input(
            f"\n  将 push 到 {PR_TARGET_BRANCH}，继续? (yes/no): "
        )
        if confirm_msg.lower() != "yes":
            print("✗ 用户取消")
            return
        print("✓ 用户确认")

        # Step 5: 执行 push
        print(f"\n[5/6] Pushing to {PR_TARGET_BRANCH}...")
        self._run_git("push", "origin", f"{current_branch}:{PR_TARGET_BRANCH}")
        print("✓ Push 完成")

        # Step 6: 创建 PR
        print(f"\n[6/6] Creating PR...")
        pr_name = f"Issue {N}: {slug}"

        # 读取 PR body 模板
        pr_body_template_path = self.config["paths"]["pr_body_template"]
        if os.path.exists(pr_body_template_path):
            with open(pr_body_template_path) as f:
                pr_body = f.read().format(N=N, slug=slug)
        else:
            pr_body = f"Closes #{N}."

        # 生成 PR 标题：问题名/简单缩写
        pr_title = slug

        # 创建 PR
        gh_pr_args = [
            "gh",
            "pr",
            "create",
            "--title", pr_title,
            "--base", PR_TARGET_BRANCH,
            "--body", pr_body,
        ]

        result = subprocess.run(gh_pr_args, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ PR 创建成功")
            # 输出 PR URL
            pr_output = result.stdout
            output_lines = pr_output.strip().split("\n")
            for line in output_lines:
                if "https://github.com" in line:
                    print(f"  URL: {line}")
        else:
            print(f"✗ PR 创建失败: {result.stderr}")
            return

        # Step 7: 收尾
        print("\n收尾...")
        print(f"  印记文件保留在: {marker_file_path}")
        print(f"  PR 目标分支: {pr_target_pattern}")
        print(f"\n{'='*60}")
        print(f"✓ Issue {N} 发布完成")
        print(f"{'='*60}")

    # ============ status 命令 ============

    def _status(self):
        """status - 查看当前分支状态"""
        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip()

        print(f"当前分支: {current_branch}")

        # 检查输出
        status = subprocess.run(
            ["git", "status"],
            capture_output=True,
            text=True,
        )
        print(self._colorize_status(status.stdout))

        # 检查与 origin
        try:
            ahead, behind = self._check_branch_tracking()
            if ahead == 0 and behind == 0:
                print("\n✓ Up to date with origin")
            elif ahead > 0:
                print(f"\n⚠ {ahead} commit(s) ahead of origin")
            elif behind > 0:
                print(f"\n⚠ {behind} commit(s) behind origin，需要 pull")
        except:
            pass

    # ============ 工具方法 ============

    def _parse_issue_id(self, issue_id: str) -> int:
        """解析 issue ID"""
        try:
            return int(issue_id)
        except ValueError:
            print(f"无效的 issue ID: {issue_id}，应为数字")
            sys.exit(1)

    def _get_slug(self) -> str:
        """获取当前分支的 slug，或当前目录名作为 slug"""
        # 尝试从当前目录名获取
        repo_name = Path.cwd().name
        slug = self._slugify(repo_name)
        if slug == repo_name:
            slug = "work"
        return slug

    def _slugify(self, text: str) -> str:
        """将文本转换为 slug"""
        import uuid
        # 移除非字母数字、空格、连字符的字符，转小写
        name_part = re.sub(r"[^\w\s-]", "", text).strip().lower()
        # 附加时间戳避免冲突
        ts = uuid.uuid4().hex[:6]
        return f"{name_part}-{ts}"

    def _create_marker_file(self, N: int, slug: str):
        """创建印记文件"""
        marker_file_path = self.active_dir / f"issue-{N}-{slug}.yaml"
        marker_file_path.parent.mkdir(parents=True, exist_ok=True)

        # 读取模板并插入数据
        template = f"""# Issue 印记文件
# 由 issue-manager skill 管理

# Issue 信息
issue_id: {N}
slug: {slug}

# 分支信息
branch: issue-{N}-{slug}
pr_target_branch: issue-{N}-{slug}-pr

# 状态
status: in_progress

# 创建时间
created_at: {__import__('datetime').datetime.now().isoformat()}

# 可选：关联的本地 issue 文件
# local_issue_file: issue/{N}-{slug}.md

# 可选：备注
# notes: ""
"""

        with open(marker_file_path, "w") as f:
            f.write(template)

    def _check_uncommitted_changes(self):
        """检查未提交改动"""
        if not self.config["pre_checks"]["check_uncommitted_before_pull"]:
            return

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(f"⚠ 存在未提交改动:")
            print(self._format_git_status(result.stdout))
            raise ValueError("存在未提交改动，无法 pull")

    def _check_unmerged_commits(self):
        """检查当前分支有未合并的 commit"""
        if not self.config["pre_checks"]["check_unmerged_commits_before_pull"]:
            return

        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip()
        main_branch = self.config["repo"]["main_branch"]

        # 检查 current_branch 是否有在 main_branch 之后的 commit
        result = subprocess.run(
            ["git", "log", f"{main_branch}..HEAD", "--oneline"],
            capture_output=True,
            text=True,
        )

        if result.stdout:
            print(f"⚠ 当前分支 {current_branch} 有未合并到 {main_branch} 的 commit:")
            for line in result.stdout.strip().split("\n"):
                print(f"  {line}")
            raise ValueError(f"当前分支 {current_branch} 有未合并的 commit")

    def _count_real_commits(self) -> int:
        """统计相对 origin/main 的实质代码 commit 数（排除 merge/initial）"""
        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip()
        main_branch = self.config["repo"]["main_branch"]

        # git log origin/main..HEAD --oneline --no-merges
        result = subprocess.run(
            ["git", "log", f"origin/{main_branch}..HEAD", "--oneline", "--no-merges"],
            capture_output=True,
            text=True,
        )
        return len([line for line in result.stdout.strip().split("\n") if line])

    def _has_uncommitted_changes(self) -> bool:
        """检查是否有未提交改动"""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout)

    def _check_branch_tracking(self) -> tuple:
        """检查分支对比情况"""
        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip()

        result = subprocess.run(
            ["git", "rev-list", "--left-right", "HEAD...origin/main"],
            capture_output=True,
            text=True,
        )

        ahead = result.stdout.count("\tA")
        behind = result.stdout.count("\tB")
        return ahead, behind

    def _run_git(self, *args):
        """执行 git 命令"""
        print(f"  $ git {' '.join(args)}")
        try:
            subprocess.run(
                ["git"] + list(args),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"✗ Git 命令失败: {e.stderr}")
            sys.exit(1)

    def _format_git_status(self, output: str) -> str:
        """格式化 git status 输出"""
        lines = output.strip().split("\n") if output else []
        formatted = []
        for line_number, line in enumerate(lines, 1):
            if not line:
                continue
            code, path = line[:2], line[3:]
            # 取第一列
            code = code.split()[0] if code.strip() else ""
            # 简化 codes
            if code.startswith("M"):
                status = "M"
            elif code.startswith("A"):
                status = "A"
            elif code.startswith("D"):
                status = "D"
            elif code.startswith("R"):
                status = "R"
            elif code.startswith("C"):
                status = "C"
            elif code.startswith("MM"):
                status = "MM"
            elif code.startswith("AM"):
                status = "AM"
            elif code.startswith("??"):
                status = "?"
            else:
                status = code[:2]

            color = f"\033[33m{status}\033[0m" if status in ["M", "D", "R", "C"] else status
            formatted.append(f"  {color} {path}")
        return "\n".join(formatted)

    def _colorize_status(self, output: str) -> str:
        """让 git status 输出带颜色"""
        # 简单的颜色标记
        output = output.replace("Untracked files:", "\n\033[36mUntracked files:\033[0m\n")
        output = output.replace("Changes to be committed:", "\n\033[32mChanges to be committed:\033[0m\n")
        output = output.replace("Changes not staged for commit:", "\n\033[31mChanges not staged for commit:\033[0m\n")
        output = output.replace("no changes added to commit (use \"git add\" and/or \"git commit -a\")",
                               "\n\033[33mno changes added (try 'git add' and 'git commit')\033[0m")
        return output

    def _help(self):
        print("""
Issue-Manager Skill 命令帮助:

  pull <id>    fetch origin → 检查未提交改动 → checkout → 创建印记文件
  list         列出 active/ 目录所有文件
  checkout <id> 切换到该 issue 的分支
  status       查看当前分支状态
  publish <id> 身份校验 → 前置检查 → 测试 → 确认 → push → PR

示例:
  issue-manager pull 123
  issue-manager list
  issue-manager checkout 123
  issue-manager status
  issue-manager publish 123

印记文件位置: .claude/skills/issue-manager/active/issue-{N}-{slug}.yaml
""")


if __name__ == "__main__":
    issue_manager = IssueManager()
    issue_manager.run(sys.argv[1:])
