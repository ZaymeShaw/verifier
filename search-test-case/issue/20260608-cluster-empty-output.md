# 20260608 聚簇与空结构化输出审查问题

## 问题

review 新增反馈：

1. “为啥会有这么多无用的聚簇？”
2. `summary: 未识别到明确查询条件, structured_output: Array(0), logic: AND, status_code: 0, user_visible_text: 未识别到明确查询条件` 这类结果不清楚为什么出现。

## 证据

- `impl/core/pipeline.py` 原先单链路总是把当前 `attribute_result` 送入 `cluster()`，即使 judge verdict 为 correct 且 attribute 是 `none`。
- `impl/core/cluster.py` 原先没有过滤 `primary_error_type == "none"` / `failure_category == "none"` 的 attribution，导致无失败结果也会生成 `none` 聚簇。
- `impl/projects/client_search/adapter.py` 原先把 `conditions` 空数组直接映射为 `structured_output: []`，没有显式标识这是空识别结果。
- `execution_trace` 的 `adapter.extract_output` 原先总是 `ok`，即便 query 非空但 conditions 为空。

## 根因

cluster 没有区分“可行动失败归因”和“正确/无失败归因”；client_search adapter 没有把非空查询的空条件结果显式暴露为 suspicious empty-result，导致前端看到 Array(0) 但链路证据不够清晰。

## 已执行修复

- `impl/core/cluster.py`
  - 过滤 `primary_error_type == "none"` 或 `failure_category == "none"` 的 attribution。
  - 空根因/空分类的 attribution 不再生成聚簇。
- `impl/core/pipeline.py`
  - 单链路只有在 judge 为 `incorrect` / `uncertain` 时才生成失败聚簇；correct 链路返回空 cluster。
- `impl/projects/client_search/adapter.py`
  - 增加 `empty_result_reason` 和 `is_empty_result`。
  - 非空 query 且 conditions 为空时标识为 `service_returned_no_conditions`。
  - `project_fields` 同步暴露空结果标识。
  - `adapter.extract_output` trace stage 在空结果时标记 `suspicious`。
- `impl/projects/client_search/evaluation.md`
  - 明确：非空查询但 `structured_output` 为空时不是成功结构化解析，judge 应判断该 query 是否应按当前 prompt/config 产出条件。
- `impl/protocols/batch_protocol.md`
  - 明确 cluster 只聚合可行动失败归因，correct/no-failure 不应生成 `none` 聚簇。

## 后续建议

如果真实服务频繁返回 `未识别到明确查询条件`，下一步应基于具体 query 调业务服务链路，检查 prompt、字段配置、query rewrite 和 parser 输出，而不是在前端把 Array(0) 隐藏掉。
