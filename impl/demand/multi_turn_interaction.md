# Impl Demand: 多轮交互协议

## 总体方向

评测系统必须支持多轮交互场景——即一个抽象的用户意图通过多轮与系统的交互逐步展开，而系统保持协议驱动、项目无关的设计。多轮协议在现有单轮 `EvaluationSample` 和 `RunTrace` 结构基础之上扩展，不破坏已有单轮 case 的向后兼容性。

---

## Trace 语义

### 一个 trace，一条完整交互链

一个 trace 代表同一个抽象用户意图下，mock agent 与 live 系统之间的**完整交互链**，不是每轮拆分成独立 trace。这意味着：

- trace 的 `input` 只捕获抽象用户意图，不展开逐轮输入。
- trace 的 `output` 捕获整条多轮交互日志——每一轮 mock agent 的产出和 live 系统的对应反馈都完整记录。
- judge 和 attribute 以 trace 为整体进行判定/归因，评估整条交互链是否满足用户意图。

### Input 列：只存意图

多轮 case 的 `input` 字段是用户的抽象意图，以单一值表达。其具体形态取决于模式：

| 模式 | `input` 内容 | 说明 |
|------|-------------|------|
| `single_run` | 实际用户请求（如查询字符串、结构化请求对象） | 与当前行为一致。意图和具体输入是同一件事。 |
| `multi_turn` | 抽象意图描述（如"用户想查找某客户的下游客户关系，需要多轮补充约束条件"） | 不编码逐轮步骤或系统输入，只表达高层目标。 |

单轮模式下，output 中的逐轮日志只有一条记录，input 里不会嵌入逐轮输入细节——这一抽象对用户不可见。多轮模式下，output 列展开为完整的多轮 trace。

### Output 列：完整交互日志

多轮 case 的 `output` 字段必须记录每一轮交互的内容。每一轮记录两个部分：

1. **Mock agent 的轮次决策**——mock agent 基于初始意图和之前所有轮次的结果，推理本轮应给 live 系统什么输入。
2. **Live 系统的响应**——live 系统对该轮输入的实际输出。

每一轮条目的固定结构：

```json
{
  "round": 1,
  "mock_agent": {
    "intent_refinement": "在第一轮需要先获取用户的基本身份信息，为后续查询做准备",
    "system_input": {"fieldA": "valueA", "fieldB": "valueB"},
    "rationale": "根据初始意图，用户需要先做身份确认"
  },
  "live_system": {
    "raw_response": {...},
    "extracted_output": {...},
    "status": "ok|error|partial",
    "execution_trace": [...]
  }
}
```

Output 整体结构：

```json
{
  "mode": "multi_turn",
  "total_rounds": 3,
  "termination_reason": "mock_agent_decided|round_limit",
  "rounds": [ /* 上述 round 条目的数组 */ ],
  "final_extracted_output": {...}
}
```

**单轮模式向后兼容**：当 `mode` 为 `single_run` 时，output 格式折叠为单条 round 记录，无 `rounds` 数组——直接沿用现有 `raw_response` / `extracted_output` 结构。这确保仅使用单轮 case 的已有项目和前端代码不受影响。

---

## Mock Agent 多轮行为

### 触发条件

Mock agent 仅在 case 的 `interaction` 段指定 `mode: "interactive_intent"` 时进入多轮模式。触发时点与 `agent.md` 文档一致：

- 预构建批量数据：mock agent 构建意图/输入 query 信息（此阶段不涉及实时多轮交互）。
- Trace 运行时：mock agent 模拟用户，涉及实时多轮交互。

### 每轮决策循环

对于第 `i` 轮（从 1 开始）：

1. **收集上下文**：mock agent 读取初始用户意图 + 第 1 轮到第 `i-1` 轮的所有轮次结果。
2. **决策下一轮输入**：mock agent 判断交互是否应继续；若继续，决定下一轮给 live 系统的输入是什么。决策依据为：已收集的信息是否已足够满足用户意图，还是需要额外交互步骤。
3. **发送输入给 live 系统**：mock agent 通过现有 adapter 机制将计算出的 `system_input` 发送给 live 系统。
4. **接收 live 系统响应**：live 系统返回输出，mock agent 将其记录到轮次日志。
5. **检查终止**：收到响应后，mock agent 检查交互目标是否已达成。若达成则结束交互；若未达成则进入第 `i+1` 轮。

### 终止条件

多轮交互在以下任一条件下结束：

- **目标达成**：mock agent 判定通过多轮交互已收集到足够信息来满足用户意图。轮次日志中 `termination_reason` 为 `"mock_agent_decided"`。
- **轮次上限到达**：交互达到可配置的最大轮次数（项目专属，默认值由 adapter 设定）。轮次日志中 `termination_reason` 为 `"round_limit"`。

当轮次上限到达但 mock agent 未声明目标达成时，trace 进入 judge/attribute 阶段，携带最终累积的输出。Judge 和 attribute 将此视为部分达成而非硬错误——系统可能只部分满足了意图。

### Mock agent 作为项目 adapter 扩展

Mock agent 的多轮逻辑通过项目 adapter 扩展实现（`run_interactive`）。当 `interaction.mode == "interactive_intent"` 时，pipeline 调用 `adapter.run_interactive(normalized_case)`。Adapter 负责：

- 从 `normalized_case.execution_input` 读取初始意图。
- 在轮次之间维护内部对话上下文。
- 每轮决策发什么 `system_input`。
- 产出完整轮次日志作为 adapter 返回值。

通用 pipeline 不规定 mock agent 如何在轮次间推理——这是项目专属逻辑。Adapter 只需遵守以上定义的 output 形状即可，前端和 judge/attribute 按统一格式消费。

---

## 前端：多轮表格渲染

### Live 页面表格

Live 页面的 case 表格必须支持展示多轮 trace，同时不破坏单轮视图：

- **单轮 case**：Input 列显示具体用户输入；Output 列直接显示单轮的 `extracted_output`。
- **多轮 case**：Input 列只显示抽象用户意图（一行描述）；Output 列渲染为可展开的多轮 trace，点击展开后逐轮展示 mock_agent.input → live_system.response 的完整链路。

展开/折叠机制在列级实现——底层数据形状相同，仅按 `mode` 渲染不同。

### Summary 页面表格

Summary 页面的表格使用与 live 页面相同的渲染逻辑：

- 多轮 case 在 Input 列展示抽象意图。
- 多轮 case 在 Output 列展示可展开的多轮交互日志。
- 聚合视图（cluster 摘要、分数分布）将每个 trace 视为单一单元，无论其轮次数——轮次数不影响聚合权重或分组标准。

### 前端扩展原则

多轮渲染属于项目前端扩展层（`ProjectSpec.frontend_extensions` 和 `project_frontend_standards`）。通用前端代码提供展开/折叠壳和列布局。项目专属渲染细节（如轮次中 mock agent 意图细化如何可视化、是否展示系统输入的代码格式还是自然语言）定义在项目前端标准中。

---

## Judge 和 Attribute 对多轮 Trace 的处理

### Judge：trace 级别评估

Judge 将整个多轮 trace 作为单一单元评估。核心判断问题为：给定用户抽象意图，所有轮次累积的交互是否充分满足该意图？

Judge 不逐轮孤立判定正确性。具体规则：

- 多轮 case 的 `expected` 和 `actual`：`actual` 使用 `final_extracted_output`，`expected` 使用 case 的 `reference`。
- Judge 的 `business_expectations` 从抽象意图重建，不基于任何单轮的输入。
- 若 mock agent 声明目标达成，judge 评估最终输出是否充分满足意图。
- 若轮次上限到达，judge 可将交互标记为部分达成——部分 expectation 为 `not_fulfilled` 的原因不是系统有误，而是可用轮次不足以收集全部所需信息。

### Attribute：trace 级别归因

Attribute 基于 judge 对整条 trace 的评估结果运行。当 judge 发现 `not_fulfilled` 的 expectation 时，attribute 在整个交互链中定位最早偏离点——是哪一轮、哪个 mock agent 决策、或哪个 live 系统响应首次导致了差距。

Attribute 输出必须包含：

- 最早偏离发生在哪一轮的具体引用。
- 偏离是来自 mock agent 的轮次决策（如 mock agent 选错了系统输入）还是来自 live 系统对正确输入的响应。
- 若轮次上限导致部分达成，必须明确说明，不应将此归因为 live 系统缺陷。

### RunTrace 对多轮的适配

现有 `RunTrace` 数据类通过 `execution_trace` 和 `state_history` 字段已能支持多轮 trace。多轮运行时，`execution_trace` 将每轮 live 系统调用记录为独立条目。Mock agent 的每轮决策在 `execution_trace` 中以独立阶段标记记录（如 `mock_agent.round_i`），与 live 系统的对应条目（如 `live_system.round_i`）并列。

通用 `RunTrace` 数据类无需新增字段。多轮特有信息通过已有的 `execution_trace` 列表和充实后的 `output` / `raw_response` / `extracted_output` 值来承载。

---

## 协议兼容性

现有单轮项目和 case 无需任何改动。`interaction` 字段的 `mode` 默认值为 `single_run`，output 渲染回退到现有扁平结构。多轮支持是可选扩展：

- Case 层面：通过在 case 数据中指定 `interaction: { mode: "interactive_intent" }` 来启用多轮。
- Project 层面：通过实现 `adapter.run_interactive()` 来启用多轮。
- 未实现 `run_interactive` 的项目，其多轮 case 将被标记为 `unsupported_interactive_intent` 并评估为 `uncertain`，不阻断批次运行（行为与当前 `pipeline.py` 中的兜底一致）。

---

## 多轮场景的 Check 要求

Generic check 必须验证多轮场景特有的协议一致性：

- 多轮 case 必须有合法的 `interaction.mode` 且 `output.rounds` 非空。
- output 中声明的总轮次数必须与实际 round 条目数一致。
- mock agent 的 `termination_reason` 必须是已认可的值（`mock_agent_decided`、`round_limit`）。
- 聚合批次摘要不得将多轮轮次数作为分组维度——轮次是内部细节，不是分类数据。
- 项目专属 check 可增加对 mock agent 轮次决策的验证（如无重复的 system input 值、继续下一轮前必需字段已全部填充等）。
