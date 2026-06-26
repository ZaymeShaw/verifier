# Issue-Solved Hook

当 issue 被标记为 closed（frontmatter `status: closed`）时，Stop hook 自动检查是否有审核 verdict。如果没有，block 会话让你启动审核 agent；如果有，根据 verdict 决定放行或阻止退出。

## 依赖

| 工具 | 用途 | 安装 |
|------|------|------|
| `python3` + `pyyaml` | YAML 解析 | `pip3 install pyyaml` |
| `jq` | JSON 输出 | macOS: `brew install jq`, Linux: `apt install jq` |

## 配置体系

所有可配置项统一在 `config.yaml` 中管理：

| 配置路径 | 用途 | 默认值 |
|---------|------|--------|
| `issue.dir` | issue 文件存放目录 | `issue` |
| `issue.file_pattern` | issue 文件匹配模式 | `issue*.md` |
| `status.field_name` | frontmatter 状态字段名 | `status:` |
| `status.closed_value` | "已关闭"的值（忽略大小写） | `closed` |
| `status.open_value` | "打开"的值（忽略大小写） | `open` |
| `audit.dir` | 审核结果目录 | `issue/audit` |
| `audit.file_pattern` | 审核文件名模板 | `{issue_id}.txt` |
| `verdict.verdict_field` | 审核判定字段标识 | `审核 verdict:` |
| `verdict.approved_value` | 审核通过的值 | `APPROVED` |
| `verdict.rejected_value` | 审核不通过的值 | `REJECTED` |
| `verdict.reason_field` | 审核理由字段标识 | `理由：` |

修改配置直接改 `config.yaml`，`stop-hook.sh` 和 `audit-prompt.md` 均依赖此文件。

## 文件结构

```
hooks/issue-solved/
├── config.yaml          # ★ 集中配置（所有可配置项）
├── README.md            # 本说明文档
├── stop-hook.sh         # Stop hook 脚本（从 config.yaml 读取配置）
├── hooks.json           # Hook 注册模板（供复制到 settings.json 使用）
└── audit-prompt.md      # 审核 agent 的 prompt 模板（引用 config.yaml 中的字段名）

issue/audit/
└── {issueid}.txt        # 审核 verdict 文件（路径和命名由 config.yaml 定义）
```

## 操作流程

### 1. 用户提出 issue

在 `issue/` 下创建 `issue{issueid}-{title}.md`，按照 `issue.md` 的规范：
- frontmatter 包含 `status: open`
- 对话框描述问题和现象
- 按对话形式更新进展

### 2. 处理 issue

- 在 issue 文件中添加对话框记录进展
- 完成实质性工作（代码改动、测试、验证）
- **关闭 issue 时：将 frontmatter 的 `status:` 改为 `closed`**（忽略大小写，如 `status: CLOSED`、`status: Closed` 均可）
- 不需要在 body 对话框中写 `Status: closed`

### 3. 结束会话时触发审核

> **机制：** Stop hook 在**会话结束/退出时**触发执行。
> 审核完成后，需**关闭当前会话**，新的 Stop hook 触发时才能读取 verdict 并做 allow 决策。

Stop hook 自动执行：
1. 从 `config.yaml` 加载配置（状态字段名、状态值、审核文件路径等）
2. 扫描 `issue/` 下所有 `issue*.md`
3. 检查 frontmatter 的 `status:` 是否为 `closed`（忽略大小写）
4. 检查 `issue/audit/{issueid}.txt` 是否有审核 verdict

**情况 A**：没有 closed issue → 直接放行

**情况 B**：有 closed issue 且全部 APPROVED → 直接放行

**情况 C**：有 closed issue 且存在 REJECTED，且 issue 未重新修改 → block，要求修复

**情况 D**：有 closed issue 且缺少审核 verdict → block，通知 Claude 启动审核 agent

**情况 E**：有 closed issue + REJECTED，但 issue 文件更新（用户已修复并重新 close）→ 自动删除旧审核，走"无审核"路径

### 4. 启动审核 agent（block 后）

hook 通过 block + reason 通知 Claude：
1. 阅读 issue 文件
2. 收集 git 证据（git log、git diff HEAD~1）
3. 用 Agent 工具 spawn 独立审核 agent
4. 审核 agent 完成**三项操作**：
   - 更新 issue 文件（追加审核对话框 + 修改 frontmatter 状态）
   - 写入 verdict 文件到 `issue/audit/{issueid}.txt`（供 hook 解析）
   - 通知主会话审核完成，提示关闭会话触发 re-check

### 5. 审核 agent 判断标准的核心

- 只评估**用户核心诉求**是否通过实质性工作解决
- 挑剔地评估 AI 的进度，不接受空洞声明
- 必须有代码改动 + 验证证据才算解决
- 通过：追加审核对话框到 issue 文件 + frontmatter 改为 `status: closed` + 写入 verdict
- 不通过：追加审核对话框到 issue 文件 + frontmatter 改为 `status: open` + 写入 verdict

### 6. 审核后触发 re-check

审核 agent 完成三项操作（更新 issue 文件 + 写入 verdict + 通知）后：
1. 通知用户**关闭当前会话**（Ctrl+C 或 `:q`）
2. 会话结束时 Stop hook 再次触发
3. 读取到新的 verdict：
   - **APPROVED** → 放行
   - **REJECTED** → 阻止退出，要求修复后再次 close

## 多重 issue 决策优先级

当多个 issue 文件存在时，hook 统一收集所有状态后决策：

| 组合 | 结果 |
|------|------|
| 全部 open（无 closed） | allow |
| 有 closed + 无审核 → 其他忽略 | block（要求审核所有无审核的） |
| 有 closed + REJECTED（未修改） + 其他 APPROVED | block（要求修复所有 REJECTED 的） |
| 有 closed + REJECTED + 但已重新修改 | 删除旧审核，重新审核 |
| 全部 closed + APPROVED | allow |

**注意**："无审核"优先级 > "REJECTED"优先级。当同时存在无审核和 REJECTED 的 closed issue 时，先要求完成审核。

## REJECTED 与修复循环

### 死循环风险

如果审核 verdict 为 REJECTED 且用户修复后重新 close：
1. 修复代码 → 修改 issue 文件（追加修复说明）→ `status: closed`
2. 关闭会话 → Stop hook 读取旧审核文件（REJECTED）
3. 旧审核文件不是 APPROVED → block

### 自动打破循环

hook 会自动比较 issue 文件修改时间和审核文件修改时间：
- **issue 修改时间 > 审核修改时间** → 用户已修复并重新 close，自动删除旧审核文件，重新触发审核（走"无审核"路径）
- **issue 修改时间 ≤ 审核修改时间** → 用户未修复，继续 REJECTED block

### 手动打破循环

```bash
rm issue/audit/{issueid}.txt
```
或修改 issue 的 status 为非 closed：
```yaml
status: open
```

## 数据流

```
config.yaml                  ← hook 读取所有配置
issue/{id}.md
  └── frontmatter: status: closed（忽略大小写）
       ↓ 被 hook 检测到，block 会话
审核 agent 被 spawn
  ├── 更新 issue/{id}.md（追加审核对话框 + 改 frontmatter 状态）
  ├── 写入 issue/audit/{issueid}.txt（verdict 供 hook 解析）
  └── 通知主会话 → 用户关闭会话
       ↓
Stop hook 再次触发 → 读取 verdict
  ├── 审核 verdict: APPROVED → hook 放行
  └── 审核 verdict: REJECTED → hook 阻止退出（但 issue 更新后自动重审）
```

**无状态文件**。hook 每次触发都重新扫描和读取 config.yaml。

## 如何启用

在 `.claude/settings.json` 中添加：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash hooks/issue-solved/stop-hook.sh",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

也可以直接复制 `hooks.json` 的内容到 settings.json 的 hooks 字段中。
