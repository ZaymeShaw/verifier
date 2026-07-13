---
name: draft-judge
description: Judge draft 的外部业务视角、判定状态和工具边界。
---

# Draft · Judge

Judge 从业务输入输出判断系统是否满足用户意图。优化目标是让业务期望和 fulfillment 判断更准确，而不是增加更多 expectation 或 reasoning 字段。

## 要完成什么

- 围绕 config 的 `objective` 理解业务输入、输出、reference 和项目语义标准。
- 用项目已有 semantic comparator、runtime check 或业务接口验证判断边界。
- 将有效优化写入项目 `draft/judge.py`，再用固定数据集验证。
- 按 `review` 判断目标是否改善；expectations 更多、文本更长或 confidence 更高本身不算改善。

## 判定原则

- 状态只使用 `fulfilled` / `not_fulfilled` / `not_evaluable`。
- expected/reference/actual 或验证证据不足时保持 `not_evaluable`，不能强判。
- fulfilled 对照 case 不能为了显示找问题能力被改成失败。
- evidence 或业务检查失败时不能伪造高 confidence。

## 工具边界

Judge 默认只看业务系统输入输出，不读取内部代码。可以调用业务接口或复用输入输出相关的 semantic comparator/runtime check/production tool。工具使用现有 `VerifiableTool` / `ToolResult` 和统一 orchestrator。

## 运行

同数据 current/draft 运行器：`scripts/compare_judge.py`。case 提供 `RunTrace` 和可选 `expected_intent`；运行器保留两边原始 `JudgeResult`，真正结论由 objective、实验和 review 决定。
