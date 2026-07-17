# 2026-07-14 Bussiness 审核发现

## 执行摘要

api-check 最新运行（20260714-110400）56/56 schema=pass。多轮协议实现与 spec 完全对齐。

但发现 2 个数据结构问题需要修复：
1. 多轮 `multi_turn_state` 字段序列化不完整（live_result级只有 3 字段）
2. marketting-planning 多轮 Mock 的 turn input 未随上下文变化（重复答案）

---

## 关键发现

### 1. multouch_state 字段截断 🔴 严重

**现象**：
- API 响应中 `(trace.live_result).multi_turn_state` 只有 3 个字段：
  - `session_id`
  - `turn_index`
  - `stop_reason`
- 缺失字段：
  - `transcript` (列表)
  - `turn_traces` (列表)
  - `conversation_summary` (字典)
  - `final_stage` (字符串)

**影响**：
- 业务层无法通过 RunTrace 访问多轮轨迹
- conversation_transcript 测试显示为空列表
- 无法追踪多轮问答历史

**根因分析**：
- `deliver_multi_turn` 构建了完整的 `LiveMultiTurnState`（包含所有 9 个字段）
- `_assemble_multi_turn_result` 正确传递了 state 给 `LiveExecutionResult`
- 但 API 响应在序列化时 state 被截断

**相关代码**：
- `impl/core/live_protocol.py:684-698` — state 构建逻辑正确
- `impl/core/live_protocol.py:907` — state 传递正确
- `impl/core/live.py:86-87` — trace_from_live_result 读取 state（但在执行前 state 就被截断）

**修复建议**：
1. 在 `live.py:trace_from_live_result` 添加 debug print 检查 `live_result.multi_turn_state` 实际字段
2. 检查 adapter/spinner 的响应序列化逻辑，确认 state 是否在返回前已截断
3. 或者在 server 端覆盖 `multi_turn_state` 的序列化

---

### 2. marketting-planning 重复答案问题 🔴 业务逻辑缺陷

**现象**：
- 多轮 case `mt-039dd423`（motion planning）4 个 turn 输出完全相同内容
- intent 均为 '4001'（其他意图），stage 均为 'non_agent'
- 没有推进到澄清阶段或规划阶段

**业务期望**：
- 第一轮识别出意图后，第二轮应进入澄清阶段（stage=clarification）追问具体目标值
- 第三轮进入规划阶段（stage=planning）输出路径方案

**根因**：
- Mock 的 `next_turn` 实现没有基于 `previous_turns` 生成新的用户输入
- Mock 可能返回了相同的第一轮输入，触发重复执行

**相关代码**：
- `impl/projects/marketting-planning/mock.py` — Mock.next_turn 实现
- Task #38 的 "B1: 添加多轮 fixture case" 中 fixture 的 turn 定义

**修复建议**：
1. 对于 marketting-planning，检查 Mock.next_turn 是否正确基于 transcript 生成下一轮输入
2. 或者检查 fixture case 的 input 定义是否在所有 turn 中重复使用

---

### 3. QA/client_search live_run 语义验证

**观察**：
- QA live_run 和 client_search live_run 的 `extracted_output` 为空

**判定**：
- 这是业务设计，不是 bug。QA 项目实时调用 live service，返回预写答案，extracted_output 为空
- client_search 为单轮交互，live_run 不走多轮路径

---

## 未发现问题的端点

- run_chain: `judge.expected` 正常，`extracted_output` 正确且结构符合 live_schema
- batch_run: `judge.expected` 正常（不是 False），schema=pass
- judge: 判定正常，4 个项目都有对应裁决
- mock_cases: 3 个 case 生成成功（QA, client_search, marketting）
- 所有 56 个端点 schema 均通过

---

## 后续步骤

1. **立即修复**：定位并修复 `multi_turn_state` 截断问题
2. **业务修复**：修复 marketting-planning Mock.next_turn 逻辑
3. **验证**：重新跑 api-check 验证修复

---

**审核时间**：2026-07-14
**审核范围**：全部 api-check 端点，聚焦多轮交互与协议对齐