# Review Stop Hook — 使用指南

## 这个 hook 的价值

这个 hook 不是单纯提醒“改了很多文件”，而是给大改动加一层可配置的自动审查入口：当 Claude 在一轮里修改了大量代码后，系统自动暂停，并把你配置好的审查动作注入给下一轮 Claude 执行。

它的价值在于：你可以围绕不同风险点构建多套审查配置，让系统在大改动后自动进入复查流程，例如：

- 审查是否符合标准文档、协议文档、项目规范
- 调用审查脚本、单元测试、API 测试、UAT 测试
- 调用 `/check`、`/code-review` 或业务审核 agent
- 检查风格一致性、数据一致性、前后端协议对齐
- 披露本轮最没把握的实现细节，暴露潜在风险

多个 Stop hook 可以共用同一个 `detect.py`，但传入不同 config。这样同一轮大改动可以同时触发“代码标准化审查”“业务规则审查”“测试补跑提醒”“不确定点披露”等多个审查点。

长期看，它可以作为自治开发链路的一部分：代码生成后自动审查，审查后继续修正，再触发下一轮验证。虽然距离完全自治还有距离，但它已经能把“大改动后靠人记得复查”变成“系统自动拉起复查与纠错迭代”的工具模块。

## 这个 hook 干什么

Claude 完成一轮响应、准备停止时，Stop hook 会读取 `transcript_path` 指向的 JSONL，只统计最后一条真实用户消息之后的本轮工具调用。达到阈值后，它会返回 `decision=block`，在终端展示 `reason`，并把配置里的 `action.prompt` 注入到下一轮 Claude 的 `systemMessage` 里。

核心目标：**大改动之后，自动要求 Claude 按配置完成一次审查、测试、对齐、风险披露或纠错迭代。**

## 快速使用

### 1. 选一个配置文件

常用配置在本目录：

- `config-code-check.json`：触发后要求调用 `/check`
- `config-code-review.json`：触发后要求调用 `/code-review`
- `config-uncertainty.json`：触发后披露最没把握的点
- `config.json`：默认配置

如果要改触发后做什么，优先改对应配置里的 `action.prompt`。

### 2. 配到 Claude Code Stop hook

每个 Stop hook 都调用同一个 `detect.py`，只传不同 config：

```json
{
  "type": "command",
  "command": "/Users/xiaozijian/miniconda3/envs/agno/bin/python /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-branch/verifier/hooks/review/detect.py --config=/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-branch/verifier/hooks/review/config-code-check.json",
  "timeout": 30
}
```

本项目依赖 agno，命令里必须使用 `impl/config.yaml` 的 `python.executable`，不要直接用系统 `python3`。

### 3. 多个审查同时触发

如果想一次触发多个动作，就在 Claude Code settings 的 `Stop` hooks 里配置多条命令，每条命令传不同 config。例如一条用 `config-code-check.json`，另一条用业务审查 config。它们会独立读取同一轮 transcript；只要各自满足阈值，就会各自返回一条 Stop hook feedback。

### 4. 测试配置是否能跑

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python hooks/review/test_detect.py
```

这个测试验证 transcript 切片、成功工具统计、文件数阈值、防死循环等基础逻辑。

### 5. 手动触发验证

默认阈值是：本轮成功改文件工具调用至少 5 次，并且涉及至少 3 个不同文件。

可以在同一轮里创建或编辑 3 个临时文件，累计 5 次以上 `Write` / `Edit` / `MultiEdit` / `NotebookEdit`。Stop 时如果触发，会看到类似：

```text
📋 代码标准化审查：已触发；本轮统计：成功改文件工具调用 6 次，涉及 3 个不同文件。；下一步行动请执行：本轮进行了大量代码改动。请先调用 /check 对上述改动进行审查
```

## 配置结构

配置只分四块：

1. `trigger`：什么时候触发
2. `action`：触发后先做什么
3. `instructions`：action 完成后的输出要求
4. `debug`：调试 dump

最小配置：

```json
{
  "trigger": {
    "enabled": true,
    "successful_tool_names": ["Edit", "MultiEdit", "Write", "NotebookEdit"],
    "min_successful_edit_tools": 5,
    "min_distinct_files": 3,
    "distinct_file_keys": ["file_path", "notebook_path"]
  },
  "action": {
    "title": "代码标准化审查",
    "prompt": "本轮进行了大量代码改动。请先调用 /check 对上述改动进行审查",
    "decision": "block",
    "block_reason": "📋 {title}：已触发；{stats}；下一步行动请执行：{action_preview}"
  },
  "instructions": {
    "after_action": ["如果调用了 skill，以 skill 结果为主；如果没调用，至少指出一个最值得人工复查的点。"]
  },
  "debug": {
    "dump": false,
    "dump_path": "/tmp/review-hook-stdin.json"
  }
}
```

## 字段映射关系

这份 config 不是工作流 DSL，只映射到 Stop hook 的几个输出位置：

| 配置字段 | detect.py 怎么用 | 最终影响 |
| --- | --- | --- |
| `trigger.enabled` | 总开关 | `false` 时静默放行 |
| `trigger.successful_tool_names` | 指定哪些工具算改文件工具 | 只统计这些工具的成功调用 |
| `trigger.min_successful_edit_tools` | 成功改文件工具调用次数阈值 | 少于这个次数不触发 |
| `trigger.min_distinct_files` | 成功改动的不同文件数阈值 | 少于这个文件数不触发 |
| `trigger.distinct_file_keys` | 从工具 input 里取文件路径的字段名 | 用来计算不同文件数 |
| `action.title` | 填到标题和 `{title}` | 影响终端 feedback 标题、`systemMessage` 标题 |
| `action.prompt` | 原文放进 `systemMessage` 的 action 区域 | Claude 下一轮首先要执行的主动作 |
| `action.prompt` | 压成 `{action_preview}` | 让终端 feedback 能看到本次行动摘要 |
| `action.decision` | 作为 Stop hook 返回的 `decision` | 通常填 `block` |
| `action.block_reason` | 格式化成 Stop hook 返回的 `reason` | 用户在终端看到的 feedback |
| `instructions.after_action` | 追加到 `systemMessage` 的 instructions 区域 | action 完成后的输出要求 |
| `debug.dump` | 是否写入 Stop hook stdin | 只影响调试 |
| `debug.dump_path` | dump 文件路径 | `debug.dump=true` 时使用 |

触发后的输出结构固定是：

```text
reason        = action.block_reason 格式化后的终端反馈
systemMessage = title + trigger统计 + action.prompt + instructions.after_action + debug信息 + 输出要求
```

最重要的规则：**触发后真正要 Claude 做的事，写在 `action.prompt`；终端里想看到什么，写在 `action.block_reason`。**

## block_reason 占位符

`action.block_reason` 是终端里看到的提示模板，支持：

- `{title}`：替换为 `action.title`
- `{action_preview}`：替换为 `action.prompt` 的单行短摘要；太长会截断
- `{stats}`：替换为本轮统计，例如成功改文件次数、涉及文件数
- `{config}`：替换为当前 config 文件路径

注意：`{stats}` 自带句号。如果模板里紧跟分号，可能显示成 `文件。；下一步...`。想更顺可以写成：

```json
"block_reason": "📋 {title}：已触发；{stats} 下一步行动请执行：{action_preview}"
```

## 四块怎么写

### trigger：只管触发

`trigger` 只决定 hook 要不要拦停本轮 Stop，不写行动内容：

- `enabled`：是否启用
- `successful_tool_names`：哪些工具算“改文件工具”
- `min_successful_edit_tools`：成功改文件工具调用至少多少次
- `min_distinct_files`：成功改动的不同文件至少多少个
- `distinct_file_keys`：从工具 input 的哪些字段取文件路径

不满足条件就静默放行。

### action：只管主动作

`action.prompt` 是触发后要注入给 Claude 的主指令，只有文字一种形式。

如果要调用某个 skill，直接把 `/check`、`/code-review` 这类要求写进 `prompt`。hook 不解析 skill 类型，也不关心 prompt 里写了什么工具；它只负责把这段文字放到 `systemMessage` 的核心位置。

### instructions：只管输出要求

`instructions` 只保留 `after_action`：action 完成后的输出要求。

如果是要 Claude 执行的具体动作，直接写进 `action.prompt`；不要拆到 `instructions`。

### debug：只管调试

```json
"debug": {
  "dump": true,
  "dump_path": "/tmp/review-hook-stdin.json"
}
```

打开后会把 Stop hook stdin 写到 `dump_path`，方便确认 Claude Code 传了什么。真实工具调用记录在 `transcript_path` 指向的 JSONL 里，不在 stdin 的 `messages` 数组里。

## 文件说明

- `detect.py` — 底层检测脚本，支持 `--config=<配置文件>`
- `config.json` — 默认配置
- `config-code-check.json` — 触发后注入要求调用 `/check` 的文字 prompt
- `config-code-review.json` — 触发后注入要求调用 `/code-review` 的文字 prompt
- `config-uncertainty.json` — 触发后只披露不确定点
- `prompt.md` — 旧版 prompt 文本，仅保留作参考
- `hooks.json` — 单配置模板
- `hooks.multi.example.json` — 多配置模板
- `test_detect.py` — 离线测试脚本

## 常见问题

### 触发了但没有执行 skill？

hook 不能直接调用 Skill tool，只能通过 `systemMessage` 要求 Claude 下一轮调用。要让 Claude 调用 skill，把要求明确写进 `action.prompt`，例如“请先调用 `/check` 对上述改动进行审查”。

### 为什么 feedback 里只有摘要？

终端 feedback 来自 `action.block_reason`。其中 `{action_preview}` 是 `action.prompt` 的单行短摘要，用来确认当前配置的主动作已经映射进 feedback。真正注入给 Claude 执行的是完整的 `action.prompt`。

### 为什么没有触发？

检查三点：

1. `trigger.enabled` 是否为 `true`
2. 本轮成功改文件工具调用是否达到 `min_successful_edit_tools`
3. 本轮不同文件数是否达到 `min_distinct_files`

### 为什么 block 后没有重复触发？

Claude Code 在 Stop hook block 后重入时会带 `stop_hook_active=true`。脚本检测到这个字段会直接放行，避免无限 block。

### 怎么看 Claude Code 传给 hook 的原始数据？

把 config 里的 `debug.dump` 改为 `true`，然后查看 `debug.dump_path` 指向的文件。

## 已知限制

1. hook 不能直接调用 Skill tool，只能通过 `systemMessage` 要求 Claude 下一轮调用。
2. 成功判定靠 tool_result 的 `is_error` 和常见失败关键词，极端失败文案可能误判。
3. block 后 Claude Code 重入时会带 `stop_hook_active=true`，脚本会自动放行，避免死循环。
