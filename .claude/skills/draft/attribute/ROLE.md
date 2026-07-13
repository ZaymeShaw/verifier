---
name: draft-attribute
description: Attribute draft 的内部技术视角、证据强度和工具边界。
---

# Draft · Attribute

Attribute 在系统不及预期时探索内部代码链路，目标是用真实运行证据把问题定位到可修改点，而不是把分析写得更长。

## 要完成什么

- 围绕 config 的 `objective` 探索代码、配置、trace、项目 comparator/runtime check 和业务接口。
- 通过局部链路或 probe 确认哪个阶段正常、从哪里开始偏离。
- 将有效优化写入项目 `draft/attribute.py`，再用固定数据集验证。
- 按 `review` 判断目标是否改善；suspected locations 或 evidence 更多本身不算改善。

## 证据原则

- `strong`：当前成功执行的 tool/probe/runtime check 明确显示 gap，且 expected/reference 与 actual 都存在。
- `medium`：有当前证据，但缺关键链路验证。
- `weak`：只有 judge 文本、部分 trace 或间接配置证据。
- `none`：关键输入或证据缺失。

probe 失败不能产生 strong；fulfilled case 不归因失败；证据不足就说明还缺什么。

## 工具边界

可以读取业务系统代码、调用业务接口或复用项目已有 comparator/runtime check/tool。工具使用现有 `VerifiableTool` / `ToolResult` 和统一 orchestrator，不另造冲突标准。

## 运行

同数据 current/draft 运行器：`scripts/compare_attribute.py`。case 提供 `RunTrace` 和 `JudgeResult`；运行器保留两边原始 `AttributeResult`，真正结论由 objective、实验和 review 决定。
