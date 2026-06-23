# Evaluation

Judge the current client_search API output by reconstructing expected-vs-actual from the current query, current response, current downstream-search evidence when available, and the current project prompt/config references from `projects/client_search`.

本文件定义”评估本 case 时的目标和重点”。边界定义和判定流程由 `judge_boundary_protocals.md` 和 `judge.md` 承载，本文件不重复。

## Project-owned source references

- `projects/client_search/readme.md`: 标准答案的答案结果由于数据库字段已经过时、跟 API 返回结果不一致，所以标准答案只能作为参考；judge 需要根据最新项目资料和当前运行证据进行实时标注。
- `projects/client_search/config.md`: 原始字段定义、枚举、值映射和规则配置是 ES/search 能力边界的重要来源；静态摘要本身只是辅助指针，不是绝对标准。
- `projects/client_search/prompt.md`: 当前 prompt 规则用于理解 parser 预期，但等价的 ES/search 结果仍然可接受。
- `RunTrace.project_fields.downstream_search`: 下游客户搜索探测结果。

## Quality requirements

- 不继承旧 case、page state、cluster 或 attribution 结论。
- 先理解用户底层意图，再比较条件。
- 边界优先级和判定流程见 `judge_boundary_protocals.md` 和 `judge.md`。
- 分离 missing、wrong、extra 条件。
- 如果 `structured_output` 为空而用户 query 非空，视为 empty-recognition，评估 query 是否应产生条件。
- 空结果分类必须使用 API 响应中的最佳来源 query；缺少 `rewritten_query` 本身不应将非空请求变成 `empty_query`。
