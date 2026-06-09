# 20260609 empty_query 与服务启动 check 报告

## 审查范围

- `review.md` 第 15 条：空结构化输出仍显示 `empty_result_reason: empty_query`，并怀疑服务未按 `start.md` 启动。
- `projects/client_search/start.md`
- `impl/projects/client_search/adapter.py`
- `impl/projects/client_search/evaluation.md`
- client_search 8000 业务服务与 8020 评估前端

## 问题定位

`empty_query` 的触发条件来自 adapter 对 API 响应中的查询文本判断。原逻辑只读取 `extra_output_params.rewritten_query`：

- 如果服务返回空 `conditions`，且 `rewritten_query` 缺失，就会被误判成 `empty_query`。
- 但真实服务响应里可能有原始 `query`，即使 `rewritten_query` 缺失，也不代表用户输入为空。
- 因此 `empty_query` 在非空请求上出现是不准确的分类，会让前端看起来像“没传 query”或“服务没启动好”。

## 已执行修复

- `impl/projects/client_search/adapter.py`
  - 新增响应 query 提取优先级：`rewritten_query` -> `query` -> `data.query`。
  - 非空 query + 空 `conditions` 现在归类为 `service_returned_no_conditions`。
  - 只有响应里确实没有任何 query 证据时才标记 `empty_query`。
  - `project_fields` 增加 `source_query`，方便前端/trace 查看空结果判断依据。
  - `summary` 兼容真实服务使用的 `msg` 字段。
- `impl/projects/client_search/evaluation.md`
  - 补充空结果分类口径：不能因为 `rewritten_query` 缺失就把非空请求判成 `empty_query`。

## start.md 核查

`start.md` 位于 `projects/client_search/start.md`，要求：

1. 启动 8000 业务服务。
2. 启动 8020 前端分析界面。
3. 调用 `/api/v1/fields/reindex` 更新 ES 字段索引。
4. 调用实时接口、judge、attribute 验证链路。

当前核查结果：

- 8000 端口：已有 `python3.9` 监听。
- 8020 端口：已有 `python3.9` 监听。
- `/api/v1/fields/reindex`：已成功提交，返回 `success: true`。
- 8020 `/health`：OK。
- 8020 `/projects`：返回 `QA` 与 `client_search`。
- 8020 `/frontend/summary.html`：HTTP 200。

## 验证结果

- `python -m compileall impl`：通过。
- adapter 单元验证：
  - 非空 query + 空 conditions -> `empty_result_reason: service_returned_no_conditions`。
  - 真正缺失 query + 空 conditions -> `empty_result_reason: empty_query`。
  - 空 conditions trace 阶段仍标记 `suspicious`。
- live 链路验证：
  - `有生存金未领取的客户`：真实服务返回 `polNoInfo.payamountdue` 条件。
  - `上有老下有小的客户`：真实服务当前返回家庭关系条件，不再是空结构化输出。
- mock 链路验证：
  - `上有老下有小的客户` mock 仍是空 conditions，但现在明确标记为 `service_returned_no_conditions`，不是 `empty_query`。
- 协议与边界扫描：
  - `scan_protocol_alignment(impl)`：无问题。
  - client_search core boundary：无问题。
  - QA core boundary：无问题。
- cluster 过滤验证：`none` attribution 不产生 cluster，真实失败 attribution 仍产生 cluster。

## 结论

本轮问题不是 8000/8020 服务未启动，而是 adapter 对“空 conditions 的 query 来源”判断过窄：只看 `rewritten_query`，导致某些非空请求被误标为 `empty_query`。修复后，非空请求的空结构化输出会显示为 `service_returned_no_conditions`，并通过 `source_query` 暴露判断依据。
