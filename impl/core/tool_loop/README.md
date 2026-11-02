# ToolLoop

一个可组合的工具循环运行包。模型决定调用哪些工具，核心完成 hook 决定任务是否完成。

## 模块边界

| 模块 | 职责 |
|---|---|
| `__init__.py` | 公共导入入口与 `__all__`，不放执行逻辑 |
| `types.py` | `Call`、`History`、单步模型协议 `StepClient`、`Hook` 协议、决策类型和 `LoopResult` |
| `runtime.py` | `ToolLoop` 驱动循环、工具执行和 hook 调度，持有嵌套调用的 `ContextVar` |
| `hooks.py` | 通用依赖条件、`RequireDone`、`BudgetStop` 等可组合实现 |
| `outputs.py` | `last_assistant_text`、`take_accepted` 等结束后的结果提取策略 |

依赖方向：`runtime → hooks / outputs / types`；`outputs → hooks / types`；`hooks → types`。
内部模块不反向导入公共入口，不依赖项目、配置存储、HTTP 服务或前端。

这次是模块化，不是脱离 verifier 的独立发行包：工具定义与 Agno 适配仍复用
`impl.tools.protocol`，实际模型请求仍由外部注入的 `StepClient` 执行。

## 使用

调用方从统一入口导入：

```python
from impl.core.tool_loop import (
    ToolLoop, LoopContext, RequireDone, BudgetStop, take_accepted,
)

# client 和 submit_tool 由具体任务构造；submit_tool 负责校验参数并返回 accepted。
loop = ToolLoop(
    id="my_harness",
    system_prompt="读取任务材料，通过 submit 提交结果。被拒后按原因修正。",
    tools=[submit_tool],
    client=client,
    completion_hook=RequireDone(["submit"]),
    end=take_accepted("submit"),
    budget=BudgetStop(tool_calls=32),
)
result = loop.run(user_input, LoopContext(trace_id=run_id))
```

- 提交工具负责有效性检查；`RequireDone` 只检查有无被接受的提交。
- 模型不调用工具时，核心完成 hook 与辅助 stop hooks 一起决定 Done / Continue / Failed。
- `end` 仅在正常完成后执行。失败不补造部分成功结果。
- 请求重试由客户端负责；工具在模型请求之外执行，不随端点重试重复执行。
- `BudgetStop.seconds` 只在工具边界检查，不是可抢占任意阻塞调用的全局超时。

## 与管理台的关系

任务定义、组件注册、模型配置、实验记录和发布是上层管理能力，应构造并调用这个包，
不应把 Web 服务或项目特有逻辑塞进 `runtime.py`。

最小运行试验台位于 [`impl/tool_loop_lab/`](../../tool_loop_lab/README.md)，以普通 Python 示例构造本包的 ToolLoop；它提供独立模型连接、运行观察和最新结果，不是发布平台。

详细协议：[ToolLoop 框架方案](../../../spec/adapter/tool-loop-plan-20260922.md)。

核心回归：

```bash
python -m pytest -q tests/test_tool_loop.py tests/test_tool_loop_registration.py tests/test_tool_loop_package.py
```
