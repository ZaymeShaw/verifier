# 20260608 聚簇与空输出 check 报告

## 审查范围

- `review.md` 新增 14、15 条。
- `impl/core/cluster.py`
- `impl/core/pipeline.py`
- `impl/projects/client_search/adapter.py`
- `impl/projects/client_search/evaluation.md`
- `impl/protocols/batch_protocol.md`
- `impl/frontend/summary.html` 现有展示链路

## Checklist

- [x] 检查“无用聚簇”是否来自 correct/no-failure attribution 被纳入 cluster。
- [x] cluster 只聚合可行动失败归因，过滤 `none` failure。
- [x] 单链路 correct 结果不再生成 `none` 聚簇。
- [x] 检查 `structured_output: Array(0)` 的源头映射。
- [x] client_search adapter 对非空查询但空 conditions 增加明确空结果标识。
- [x] execution trace 对空结构化结果标记为 `suspicious`，而不是无条件 `ok`。
- [x] judge 项目文档补充空结构化输出的评估口径。
- [x] batch protocol 补充 cluster 只聚合失败归因的规则。
- [x] 编译、协议扫描、边界扫描、mock 链路、API smoke 均已验证。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- `python -m impl.cli run-chain --project client_search --mock --input '{"query":"有生存金未领取的客户"}'`：通过，生存金 mock 输出有结构化条件。
- `python -m impl.cli run-chain --project client_search --mock --input '{"query":"上有老下有小的客户"}'`：通过，空 conditions 被标记：
  - `is_empty_result: true`
  - `empty_result_reason: service_returned_no_conditions`
  - `execution_trace[-1].status: suspicious`
- cluster 过滤验证：`primary_error_type/failure_category == none` 不产生 cluster；真实失败 attribution 仍产生 cluster。
- 重启 8020 后 smoke：
  - `/health` OK
  - `/projects` OK
  - `/frontend/summary.html` OK
  - `/api/live_run` 对空结构化输出返回 suspicious 标识。

## 修复说明

1. 无用聚簇
   - 根因：正确或无失败 attribution 被当作 cluster 输入。
   - 修复：`cluster_attributes()` 过滤 `none`；`run_chain()` 仅在 incorrect/uncertain 时生成失败 cluster。

2. `structured_output: Array(0)` 不清晰
   - 根因：adapter 把空 conditions 正常映射为空数组，但没有说明这是“服务未识别条件”。
   - 修复：增加 `empty_result_reason` / `is_empty_result`，并在 trace 中标记 suspicious。

## 后续建议

如果真实服务对某些明确查询也返回 `service_returned_no_conditions`，下一步应进入 client_search 业务项目，沿 prompt/config/parser/query_router 链路定位为什么没有生成 conditions。
