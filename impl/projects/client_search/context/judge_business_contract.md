# client_search Judge business contract

本 ContextUnit 是 Harness AI 从 Judge investigation 固化出的 Planning 合同，不包含
actual、AuthorityAnalysis 原文或调查过程。

- 产品期望：`find-target-customers`
- 评估维度：`search-intent-preservation`、`downstream-query-consumability`
- Live 责任：完整保留用户明确表达的客户筛选条件，并交付下游支持的字段、值、操作符和逻辑。
- Live 边界：不保证数据库存在匹配客户，不承担外部客户数据缺失或服务不可用责任。

当前 Case 的 frozen plan 必须覆盖：

- `explicit_conditions`：明确表达的筛选条件；
- `boolean_logic`：AND/OR/NOT 和范围关系；
- `no_unexpressed_constraints`：不得增加会改变客户集合的未表达限制。

每个 runtime expectation 必须引用产品期望和至少一个评估维度，并在 actual 可见前确定
acceptance criteria 与 blocking。
