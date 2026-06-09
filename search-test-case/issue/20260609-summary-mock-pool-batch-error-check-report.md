# 20260609 mock pool batch error 复现与 check.md 审核报告

## 用户反馈

用户在 `http://127.0.0.1:8020/frontend/summary.html` 按页面路径操作后看到：

- `完成 client-search-seed-1：error`
- `完成 client-search-seed-4：incorrect`
- `完成 client-search-seed-3：incorrect`
- `完成 client-search-seed-2：incorrect`
- 批量结束后用例表仍显示 `pending / 旧结果已清理，请重新批量归因`

用户要求不要只看 API 结论，要复现页面路径并按 `check.md` 审核。

## 复现结论

本轮复现到的确是前端 summary 批量链路的问题，不是用户看错：

1. 页面默认执行模式可能是 `Mock 响应`，此时 `client_search` mock_response 只覆盖了部分 seed：
   - seed-3 `年缴保费一万以上的客户` 输出空 conditions，被 judge 判为 incorrect/uncertain。
   - seed-4 `45岁以上女性客户` 输出空 conditions，被 judge 判为 incorrect/uncertain。
   - seed-5 `买了年金险或两全险的客户` 输出空 conditions，被 judge 判为 incorrect。
   - seed-8 `上有老下有小的客户` 输出空 conditions，被 judge 判为 incorrect。
2. 修复 mock seed 覆盖后，adapter 的 judge 归一对 `RANGE` value dict 做哈希时触发 `unhashable type: 'dict'`，导致 seed-1 真实出现 `error`。
3. 页面表格显示 `旧结果已清理，请重新批量归因` 的原因是：旧 stale 标记 `stale_result_removed:true` 被保留到了新 batch 结果对象里。即使 batch 返回了新的 trace/judge，`renderCaseJudge()` 再次 sanitize 时仍把它当旧结果显示。

## 已修复

- `impl/projects/client_search/adapter.py`
  - 补全默认 mock seed 的 mock_response 源头输出：
    - `年缴保费一万以上的客户`
    - `45岁以上女性客户`
    - `买了年金险或两全险的客户`
    - `上有老下有小的客户`
  - 修复条件归一对 dict/list value 的 hash 处理，避免 `unhashable type: 'dict'`。
  - judge 归一不再只处理 `incorrect`，也会把 `uncertain` 中 actual/expected 已一致的结果归一为 `correct`，避免 LLM 超时/不稳定时把确定相等的结构化条件留成 uncertain。

- `impl/frontend/summary.html`
  - 增加 `clearStaleFlag()`。
  - `sanitizeCaseResult()` 在结果已匹配当前输入时清掉 `stale_result_removed`。
  - batch 回写 casePool 时清掉旧 stale 标记，避免新结果仍显示“旧结果已清理”。
  - 进度日志显示 event 的 `error/reason`，避免只显示 `error` 而没有原因。

- `impl/server.py`
  - `/api/batch_status` events 增加 `error` 和 `reason`，便于页面和日志直接看到每个 case 的失败原因。

## 验证

### 静态 / check.md 审核

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：`[]`。
- `check.scan_core_boundary(impl, client_search markers)`：`[]`。
- `check.scan_core_boundary(impl, QA markers)`：`[]`。

### 页面等价 UAT

已重启 8020，并请求 served `summary.html` 确认最新 JS 已生效：

- `clearStaleFlag` 存在。
- progress event reason 展示逻辑存在。
- `/health` 返回 200。

按页面等价路径验证：

1. 构建 mock 用例池：`/api/mock_cases` 返回 8 条 seed。
2. 批量归因 Mock 响应模式：`/api/batch_start` + `/api/batch_status`。
   - 8/8 completed。
   - 8 条 status/judge 均为 `correct`。
   - 8 条 `error == None`。
   - 8 条 `trace.status == ok`。
   - `bad_count == 0`。
3. 批量归因真实服务模式：`/api/batch_start` + `/api/batch_status`。
   - 8/8 completed。
   - 8 条 status/judge 均为 `correct`。
   - 8 条 `error == None`。
   - 8 条 `trace.status == ok`。
   - `bad_count == 0`。

## check.md checklist

- [x] 复现用户看到的 `error/incorrect` 不是仅解释。
- [x] 定位源头而不是只改展示：mock_response seed 覆盖不全 + adapter normalization dict hash bug + frontend stale flag 泄漏。
- [x] 修复源头：补全 mock agent seed 输出，修复归一函数，修复 stale 标记生命周期。
- [x] 增加可观测性：batch event 带 `error/reason`。
- [x] 未新增第二套 judge/attribute/cluster；仍走统一 `pipeline.batch_run -> run_chain -> judge -> adapter.normalize_judge_result`。
- [x] 重启 8020 后做页面等价 UAT。
- [x] Mock 响应模式和真实服务模式都验证通过。

## 结论

用户反馈的问题成立。本轮修复后，summary 页“清空 -> 构建 Mock 用例池 -> 批量归因”对应链路在 Mock 响应和真实服务两种模式下都完成 8/8，且全部 `correct`；新 batch 结果不会再被旧 `stale_result_removed` 标记遮挡成“旧结果已清理”。
