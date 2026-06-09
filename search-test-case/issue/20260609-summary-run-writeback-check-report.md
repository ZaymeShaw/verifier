# 20260609 summary run writeback check report

## 用户反馈

`review.md` 第 22 点补充：页面跑完归因后出现“旧结果已清理，请重新批量归因”，并且用户明确指出：既然已经重跑，应该会跑 judge 和归因，为什么 judge / attribute 没出来。

## 问题定位

在上一轮移除无效提示后，本轮继续按 `check.md` 检查实际写回链路，发现 summary 前端仍有两个风险：

1. `renderCaseJudge()` / `renderCaseAttribute()` 在渲染时再次调用 `sanitizeCaseResult(item)`。如果 stale 判断在渲染阶段误判，就会把刚写回的 `judge` / `attribute` 临时清掉，导致表格仍显示“尚未评估 / 尚未归因”。渲染函数不应该修改或重新清理数据。
2. `sameInput()` 只删除顶层 `case_id`。对于协议化 case，真实 trace input 可能是 `{input:{..., case_id}, scenario:...}`，前端 caseRunInput 是 `{input:{...}, scenario:...}`。如果 nested `input.case_id` 没被忽略，容易把已完成 run 误判为 stale。

这解释了“已经重跑但 judge/归因不出来”的前端源头风险：batch event/completed result 已经带了 judge/attribute，但渲染阶段又可能因为 stale 判断清掉展示。

## 已修复

### `impl/frontend/summary.html`

- `PAGE_VERSION` 更新为 `20260609-summary-run-writeback-1`。
- `renderCaseJudge(item)` / `renderCaseAttribute(item)` 不再调用 `sanitizeCaseResult()`，只渲染当前 row 已写入的数据。
- 新增 `applyRunToCase(item, run, eventStatus)`，统一 running event 和 completed result 的写回逻辑：
  - `status`
  - `trace`
  - `judge`
  - `attribute`
  - `frontend_view`
  - `check`
  - `cluster`
  - `error`
- `applyBatchEvents(events)` 和 `applyBatchRuns(runs)` 都复用 `applyRunToCase()`，避免两套写回逻辑不一致。
- `comparableInput()` 现在同时忽略：
  - 顶层 `case_id`
  - nested `input.case_id`
- 保持旧结果清理只发生在导入/加载/保存用例池时，不在 judge/attribute 渲染阶段执行。
- 源码中不再包含：
  - `旧结果已清理`
  - `stale_result_removed`
  - `clearStaleFlag`

## 验证

### 编译与静态验证

- `python -m compileall impl`：通过。
- `impl/frontend/summary.html` HTML parser：通过。
- summary 源码断言通过：
  - 新 `PAGE_VERSION` 存在。
  - `applyRunToCase()` 存在。
  - `renderCaseJudge()` / `renderCaseAttribute()` 不再包含渲染期 sanitize。
  - `delete copy.input.case_id` 存在。
  - “旧结果已清理”不存在。
  - `stale_result_removed` 不存在。

### check.md 扫描

- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

### served frontend 验证

请求 `/frontend/summary.html`，确认 served 页面包含最新逻辑：

- `20260609-summary-run-writeback-1`：存在。
- `function applyRunToCase`：存在。
- `delete copy.input.case_id`：存在。
- “旧结果已清理”：不存在。
- `stale_result_removed`：不存在。
- 渲染期 `const clean=sanitizeCaseResult(item)`：不存在。

### frontend 等价 batch 路径 UAT

按页面路径等价执行：

1. `/api/mock_cases` 获取 `client_search` mock case。
2. 取 `client-search-seed-1` 原样提交 `/api/batch_start`。
3. 轮询 `/api/batch_status` 到 completed。

结果：

- status：`completed`
- event status：`correct`
- `run.trace`：存在
- `run.judge`：存在，verdict=`correct`
- `run.attribute`：存在
- `run.frontend_view`：存在
- completed `result.runs[0]` 带完整 compact run 字段
- `trace.extracted_output.empty_result_reason == ""`

### pipeline batch 回归

`pipeline.batch_run('client_search', mock_cases[:2], mock=True, concurrency=2)`：

- total：2
- `client-search-seed-1`：judge / attribute / frontend_view 均存在
- `client-search-seed-2`：judge / attribute / frontend_view 均存在

## check.md checklist

- [x] 没有只改展示文案：修复了渲染期错误清理和 batch run 写回逻辑。
- [x] 没有新增第二套 judge/attribute：仍复用后端 compact run。
- [x] running event 和 completed result 使用同一 `applyRunToCase()` 写回协议。
- [x] judge/attribute 已经跑出来时，渲染阶段不会再把它们清掉。
- [x] stale input 比较兼容 nested `input.case_id`。
- [x] served frontend、API UAT、pipeline batch、compile、check scans 均通过。

## 结论

第 22 点已进一步修复：summary 页面不仅不再显示“旧结果已清理”，而且 judge / attribute 的表格渲染不再执行二次 stale 清理。batch running event 和 completed result 都会通过统一 `applyRunToCase()` 写回完整 run，因此重跑后 `Output / Reference / Score-Judge / 归因摘要 / 状态` 可以稳定展示。
