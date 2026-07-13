# Draft 结论

## 目标

- Objective: `<本轮真正要改善什么>`
- Review: `<用户如何判断是否改善，含泛化能力>`
- Project / role: `<project_id> / <role>`
- Iteration cases: `<mock_source.iteration_cases>`
- Unseen cases: `<mock_source.unseen_cases>`

## 探索层

- 当前 production 在目标上的真实差距：`<运行观察到的首个偏离点及证据>`
- 差距根因：`<哪段代码/配置/链路，附可复现证据>`
- 验证过能解决该 gap 的最小实验：`<临时脚本/手工调用，不在 production/draft 上改>`
- 探索路径证明：`<如何证明路径可行>`

## 固化层

- 从探索路径提取的稳定 tool/probe：`<路径 → 产物>`
- 跨 case 复用的 gap 模式：`<进入 knowledge.md 的条目>`
- 由 agno 框架现有能力承担的部分：`<直接复用什么>`
- 新建产物：`<draft/tools/ / draft/probes/ / draft/context_builders/ 中的新增>`

## 执行层

### Current vs Draft

| Case | Current 目标相关行为 | Draft 行为 | 关键实验/证据 |
| --- | --- | --- | --- |
| `<case>` | `<事实>` | `<事实>` | `<可复现证据>` |

### 泛化验证（unseen cases）

| Case | Current 行为 | Draft 行为 | 是否退化 |
| --- | --- | --- | --- |
| `<case>` | `<事实>` | `<事实>` | 是 / 否 / 证据不足 |

字段更多、文本更长、结构更复杂或 confidence 更高不能作为通过理由。

## 按 Review 判断

- `<review 原则>`：通过 / 不通过 / 证据不足 — `<理由>`

## 知识层更新

- 链路地图新增：`<条目>`
- gap 模式新增：`<条目>`
- probe 库新增：`<条目>`
- 被否决假设新增：`<条目>`
- 泛化边界更新：`<条目>`

## 结论

- Objective 是否真正改善：是 / 否 / 证据不足
- 固定数据是否无退化：是 / 否 / 证据不足
- 未见对照 case 是否无退化：是 / 否 / 证据不足
- check 脚本是否通过：是 / 否 / `<失败原因>`
- 探索路径和知识是否已固化：是 / 否 / `<缺什么>`
- 无 overfit / 无伪造 / 无异常被吞：是 / 否 / `<失败原因>`

只有六条 promotion 条件全部满足才建议 promotion，并等待用户人工确认。
