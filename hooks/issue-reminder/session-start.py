#!/usr/bin/env python3
"""
Issue-Reminder Hook
会话启动时扫描印记目录，提醒正在处理的 issue
"""

import argparse
import os
import yaml
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Issue-Reminder Hook")
    parser.add_argument("--config", default=".claude/skills/issue-manager/config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)

    # 加载配置
    with open(config_path) as f:
        config = yaml.safe_load(f)

    active_dir = Path(config["paths"]["active_dir"])
    max_display = config["reminder"]["max_display"]

    if not active_dir.exists():
        return

    # 扫描印记文件
    issues = []
    for f in active_dir.glob("issue-*.yaml"):
        try:
            with open(f) as file:
                data = yaml.safe_load(file)
            issues.append(data)
        except Exception:
            continue

    # 过滤并排序
    issues = [i for i in issues if i.get("status") == "in_progress"]
    issues.sort(key=lambda x: int(x.get("issue_id", 0)))

    if not issues:
        print("📌 没有正在处理的 issue，可以开始新的 issue")
        print(f"   提示: 手动创建印记文件于 {active_dir}")
        return

    print(f"\n📌 当前正在处理 {len(issues)} 个 issue:")
    print("-" * 60)

    for i, issue in enumerate(issues[:max_display], 1):
        N = issue.get("issue_id", "N/A")
        slug = issue.get("slug", "unknown")
        branch = issue.get("branch", "unknown")

        print(f"\n{i}. Issue {N}: {slug}")
        print(f"   分支: {branch}")
        print(f"   印记: {active_dir / f'issue-{N}-{slug}.yaml'}")

        # 显示备注
        notes = issue.get("notes")
        if notes:
            print(f"   备注: {notes}")

    if len(issues) > max_display:
        print(f"\n... 还有 {len(issues) - max_display} 个 issue")

    print(f"\n💡 提示: 使用以下命令管理 issue:")


if __name__ == "__main__":
    main()
