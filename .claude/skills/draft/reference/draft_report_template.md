# Draft 结论

## 目标

- Objective: `<本轮真正要改善什么>`
- Review: `<用户如何判断是否改善>`
- Project / role: `<project_id> / <role>`
- Frozen cases: `<mock_source>`

## 实际探索与改动

- 检查了：`<源码 / 配置 / 文档 / 现有 comparator 或 tool>`
- 实测了：`<局部链路 / 业务接口 / probe>`
- 观察到：`<目标相关事实>`
- 因此只改了：`<draft 改动及原因>`

## Current vs Draft

| Case | Current 的目标相关行为 | Draft 行为 | 关键实验/证据 |
| --- | --- | --- | --- |
| `<case>` | `<事实>` | `<事实>` | `<可复现证据>` |

## 按 Review 判断

- `<review 原则>`：通过 / 不通过 / 证据不足 — `<理由>`

字段更多、文本更长、结构更丰富或 confidence 更高不能作为通过理由。

## 结论

- Objective 是否真正改善：是 / 否 / 证据不足
- 遗留问题：`<blocker>`
- Promotion：建议 / 不建议

只有 objective 真正改善、review 逐条通过、frozen case 无退化且后台硬门禁通过，才等待用户人工确认 promotion。
