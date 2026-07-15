---
name: issue-manager
description: issue-manager skill 统一管理 GitHub issue 的生命周期，支持并行处理多个 issue
---

# Issue Manager Skill

统一管理 GitHub issue 的生命周期，支持并行处理多个 issue。

## 核心功能

- `pull <id>`: 获取 issue 分支流程
- `list`: 列出所有活跃 issue
- `checkout <id>`: 切换到 issue 分支
- `status`: 查看当前分支状态
- `publish <id>`: 发布流程（身份校验 → 前置检查 → 测试 → 确认 → push → PR）

## 印记文件

位置: `.claude/skills/issue-manager/active/issue-{N}-{slug}.yaml`

印记文件包含：
- `issue_id`: issue 编号
- `slug`: slugified 标题
- `branch`: 工作分支名
- `pr_target_branch`: PR 目标分支名
- `status`: (in_progress)

## 分支命名规则

- 工作分支: `issue-{N}-{slug}`
- PR 目标分支: `issue-{N}-{slug}-pr` (远程 main 保护分支)

## 使用流程

```
用户发起 issue dueling 分支
  ↓
issue-manager pull <id>
  ↓ (创建 issue-{N}-{slug} 分支，基于 origin/main)
开发，提交代码
  ↓
issue-manager checkout <id>
  ↓ (切换回工作分支)
开发，提交代码
  ↓
issue-manager status
  ↓ (查看分支状态)
issue-manager publish <id>
  ↓ (身份校验 → 前置检查 → 测试 → 确认 → push → PR)
```

## 并行支持

多个 issue 可同时拥有印记文件在 `active/` 目录下，同时进行开发。
