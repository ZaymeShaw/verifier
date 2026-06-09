# 20260609 summary stale judge alignment check 报告

## 审查范围

- `review.md` 第 16 条新增细节：`45岁女性保费10万以上` 在 live judge 是三条结构化条件，但归因总结页显示 `未识别到明确查询条件` / `structured_output: Array(0)` / `empty_result_reason: empty_query`，需要对齐并 UAT 到合理。
- `impl/frontend/summary.html`
- `impl/protocols/frontend_protocol.md`
- client_search live / batch 链路

## 问题定位

后端 live、run_chain、batch_run 对同一个当前输入 `45岁女性保费10万以上` 实测都能得到一致的结构化结果：

```json
[
  {"field":"clientAge","operator":"RANGE","value":{"min":45,"max":45}},
  {"field":"clientSex","operator":"MATCH","value":"女"},
  {"field":"annPremSegNum","operator":"GTE","value":100000}
]
```

因此本轮问题不是 judge agent 后端多套逻辑，也不是 client_search adapter 当前解析错误，而是 summary 页会从 `sessionStorage` / 持久化用例池加载历史 case pool。历史 case row 可能保存了旧 trace/judge/attribute，当 row 的 `input` 已经变成当前用例时，旧结果仍残留在表格里，造成“45岁女性保费10万以上”这一行展示了旧的 `empty_query` 结果。

这属于 check.md 里的“数据更新不同步不一致”：前端复用了旧结果数据，而不是按当前 case input 重新通过统一 batch pipeline 生成。

## 已执行修复

- `impl/frontend/summary.html`
  - 增加 `comparableInput()` / `sameInput()`：比较 case input 与 trace input，忽略 batch 注入的 `case_id`。
  - 增加 `hasStaleEmptyQueryResult()`：对 `client_search` 非空 query 却带有 `empty_result_reason === 'empty_query'` 的旧结果判定为 stale。
  - 增加 `stripResult()` / `sanitizeCaseResult()` / `sanitizeCasePool()`：发现 stale 结果时清空 `trace` / `judge` / `attribute` / `frontend_view` 等运行结果字段，并把状态恢复为 `pending`。
  - `switchProject()` 从 sessionStorage 加载 case pool 时执行 sanitize，并写回清理后的 sessionStorage。
  - `saveCasePool()` 保存前执行 sanitize，避免把 stale 结果继续持久化到页面状态。
  - `loadNamedPool()` 加载持久化用例池后执行 sanitize。
  - `normalizeCase()` 对导入/加载的 case 执行 sanitize，但不再无条件清空有效 trace/judge，避免破坏合法已完成用例池。

- `impl/protocols/frontend_protocol.md`
  - 补充规则：持久化或 session case-pool rows 如果存储结果的输入与当前 row input 不一致，不能复用旧 trace/judge/attribute，应清空后通过统一 batch pipeline 重新运行。

## Checklist

- [x] 后端 live 与 batch 对 `45岁女性保费10万以上` 当前输入结果一致。
- [x] summary 页不再复用输入不匹配的历史 trace/judge/attribute。
- [x] summary 页会清理非空 client_search query 却显示 `empty_query` 的 stale 结果。
- [x] batch 执行仍使用当前 selected case input。
- [x] 协议补充前端状态一致性要求。
- [x] 未引入 client_search 专用后端逻辑；修复点在通用前端状态卫生 + 一个项目异常展示保护。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- live vs batch 真实服务 UAT：
  - live conditions = `clientAge` + `clientSex` + `annPremSegNum`
  - batch conditions = `clientAge` + `clientSex` + `annPremSegNum`
  - `same_conditions == True`
  - `empty_result_reason == ""`
- summary 前端静态审核：
  - save/switch/load 均执行 stale sanitize：通过。
  - stale `empty_query` 保护存在：通过。
  - trace input 比较忽略 `case_id`：通过。
  - batch 仍提交 selected 当前 case：通过。
- client_search mock batch 回归：
  - `45岁女性保费10万以上` 输出三条条件。
  - `有生存金未领取的客户` 输出 `polNoInfo.payamountdue` 条件。
  - 无 `empty_query`。
  - correct case 不产生无用 cluster。
- QA generated reference 回归：
  - `reference_panel.source == judge_generated`
  - reference 非空。
- 8020 smoke：
  - `/health` HTTP 200
  - `/projects` HTTP 200
  - `/frontend/live.html` HTTP 200
  - `/frontend/summary.html` HTTP 200

## 结论

本轮修复后，`45岁女性保费10万以上` 在 live 和归因总结批量链路中都会基于当前输入重新运行并得到一致的三条结构化条件。summary 页不会再把历史 stale 的 `empty_query` trace/judge 展示到当前 case 上。
