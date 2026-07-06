# Review Stop Hook — 大活后捕获不确定点

## 这个 hook 干什么

每轮你做了大量改动后（改了多个文件、多处修改），Stop hook 触发，往助理的上下文注入一条 prompt，让助理在回复末尾**主动披露本轮实施过程中最没把握的一个点**。目的是把"我其实没把握但顺手做下去了"的地方挖出来，让你有机会回头看。

## 触发条件（两个都满足，仅数本轮 tool_use）

1. 本轮**成功的** Edit / MultiEdit / Write / NotebookEdit 次数 ≥ `MIN_SUCCESSFUL_EDITS`（默认 5）
2. 本轮**成功改动的不同文件路径数** ≥ `MIN_DISTINCT_FILES`（默认 3）

只数成功的——失败重试、没匹配上的 Edit 不算。只数本轮——不跨轮累积。

不满足则静默放行，不打扰。

## 文件

- `detect.py` — 检测脚本，阈值变量在文件顶部，调阈值改这里
- `prompt.md` — 注入给助理的 prompt，措辞不满意改这里
- `hooks.json` — 配置模板，手动配进 `.claude/settings.json` 用

## 怎么配进 Claude Code

把 `hooks.json` 里的 `Stop` 段合并到 `.claude/settings.json` 的 `hooks.Stop` 数组里。它和你现有的 `issue-solved` Stop hook 并存——Claude Code 多个 Stop hook 是"任一 block 则 block"，互不干扰。

示例（合并后）：

```json
"hooks": {
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash /Users/.../hooks/issue-solved/stop-hook.sh",
          "timeout": 120
        }
      ]
    },
    {
      "hooks": [
        {
          "type": "command",
          "command": "python3 /Users/.../hooks/review/detect.py",
          "timeout": 10
        }
      ]
    }
  ]
}
```

## 调阈值

打开 `detect.py`，改顶部这几个变量：

```python
MIN_SUCCESSFUL_EDITS = 5   # 调小→更易触发；调大→只盯超大活
MIN_DISTINCT_FILES = 3     # 文件数门槛
ENABLED = True             # 总开关
DEBUG_DUMP = False         # True 时把 stdin 落盘到 /tmp/review-hook-stdin.json，核对格式用
```

## 已知没把握的点

1. **stdin 里"本轮"的边界**——脚本假设 `messages` 是从最后一条真实用户消息（非 tool_result）切到末尾。若 Claude Code 实际只传本轮消息，`_slice_current_turn` 会兜底返回全部，结果一样。设 `DEBUG_DUMP=True` 跑一次能看真实输入。
2. **成功判定**——靠扫 tool_result 文本里的 error/failed/not found/denied 关键词。如果某工具失败信息不含这些词，会误判为成功。第一次跑可以核对 `DEBUG_DUMP` 的输出验证。
3. **systemMessage 注入位置**——注入的是 system 级指令（不是 user 消息），助理会作为指令执行。若披露走过场/太泛，改 `prompt.md` 措辞让它更逼。

## 防死循环

block 后 Claude Code 重入时会带 `stop_hook_active=true`，脚本检测到直接放行，不会无限 block。
