# Issue Manager Skill

统一管理 GitHub issue 的生命周期，支持并行处理多个 issue。

## 目录结构

```
.claude/skills/issue-manager/
├── config.yaml              # 配置（仓库、印记路径、关卡设置等）
├── manage.py                # skill 主体，实现所有命令
├── SKILL.md                 # skill 描述
├── README.md                # 本文件
├── templates/
│   └── pr-body.md           # PR body 模板
└── active/                  # 印记目录（in_progress issues）
    └── issue-{N}-{slug}.yaml
```

## 命令接口

| 命令 | 行为 |
| --- | --- |
| `pull <id>` | fetch origin → 检查未提交改动 → checkout → 创建印记 |
| `list` | 列出 `active/` 目录所有文件 |
| `checkout <id>` | 切换到该 issue 的分支 |
| `status` | 查看当前分支状态 |
| `publish <id>` | 身份校验 → 前置检查 → 测试 → 确认 → push → PR |

## 使用示例

```bash
# 创建 issue 分支
python3 .claude/skills/issue-manager/manage.py pull 123

# 列出活跃 issue
python3 .claude/skills/issue-manager/manage.py list

# 切换到某 issue 分支
python3 .claude/skills/issue-manager/manage.py checkout 123

# 查看当前状态
python3 .claude/skills/issue-manager/manage.py status

# 发布 issue (创建 PR)
python3 .claude/skills/issue-manager/manage.py publish 123
```

## pull 前置检查（严格模式）

- 检查当前工作区是否有未提交改动 → 存在则 abort
- 检查当前分支是否有未合并的 commit → 存在则 abort
- 通过后才执行：fetch → checkout -b → 创建印记文件

## publish 完整流程

1. **身份校验** - 检查印记文件存在；检查当前分支匹配 `issue-{N}-{slug}` 模式
2. **前置检查** - 检查相对 origin/main 的实质代码 commit 数
3. **测试关卡** - 运行 `config.yaml` 配置的 test_command；为空则跳过
4. **用户确认** - 提示 push 分支、PR 目标分支、改动摘要，等待 yes 确认
5. **执行 push** - `git push origin issue-{N}-{slug}:issue-{N}-{slug}-pr`
6. **创建 PR** - `gh pr create --base issue-{N}-{slug}-pr`
7. **收尾** - 标记印记文件或按用户偏好保留

## 配置说明

`config.yaml` 中可调整：
- `repo.remote` / `repo.main_branch`: 仓库远程和主分支
- `paths.active_dir`: 印记文件目录
- `pre_checks.*`: pull 前置检查开关
- `publish.min_real_commits`: publish 最少 commit 数
- `publish.test_command`: publish 测试命令
- `publish.require_user_confirmation`: 是否要求用户确认

## 关键设计点

| 点 | 设计 |
| --- | --- |
| 印记位置 | `.claude/skills/issue-manager/active/issue-{N}-{slug}.yaml`，统一管理 |
| 配置位置 | `.claude/skills/issue-manager/config.yaml` |
| 本地 issue 解耦 | 不强制关联，`local_issue_file` 字段可选 |
| 本地改动保护 | hook 在 checkout/pull 前 block，或 skill 内部检查 |
| push 严格性 | 4 道关卡：身份校验 → 前置检查 → 测试 → 确认 |
| 远程 main 保护 | PR 目标分支 `issue-{N}-{slug}-pr` |
| issue-solved hook | 独立运行不受影响 |
| 并行支持 | 多个印记文件同时存在 |

## 关联组件

- **issue-reminder hook** (`hooks/issue-reminder/`): 会话启动时扫描印记目录，提醒正在处理的 issue 或提示开始新 issue
- **git PreCommand hooks** (settings.json): 拦截 git checkout/pull 前的未提交改动
- **issue-solved hook** (`hooks/issue-solved/`): 独立运行，不受影响
