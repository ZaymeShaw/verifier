# 20260609 summary batch table refresh check report

## 用户反馈

`review.md` 新增第 20 点：跑完归因后，表格页面没有更新，需要按 `check.md` 审核。

## 复现与问题定位

本轮检查 `summary.html` 批量归因链路后，确认表格更新存在两个源头风险：

1. 批量任务运行过程中，前端只更新进度条和日志，不把 `/api/batch_status` 的 per-case events 写回 `casePool`。因此用户看到“完成 xxx：correct/incorrect/error”时，表格仍可能保持旧的 pending 状态，直到整个 batch 完全 completed。
2. batch 完成后才通过 `runs.find()` 回写完整 trace/judge/attribute；如果用户在完成前看表格，或 batch 状态与结果到达之间有延迟，会表现为“归因跑完/日志有结果，但表格没更新”。
3. `resultMatchesCase()` 只比较 `trace.input` 和 `item.input`，对带 `output/reference/scenario` 的协议化 case 不够准确；这会影响 provided-output / EvaluationSample-shaped 用例的结果保留。

## 已修复

- `impl/frontend/summary.html`
  - 升级 `PAGE_VERSION` 为 `20260609-summary-batch-table-refresh-1`，清理旧 session 状态。
  - 新增 `clearCaseResult()`，用于 per-case event 到达时先安全清空旧 trace/judge/attribute，再更新行状态。
  - 新增 `applyBatchEvents(events)`：轮询 `/api/batch_status` 时，根据 event 的 `case_id/status` 实时写回 `casePool` 并 `renderCasePool()`，让表格状态跟进度日志同步更新。
  - 新增 `applyBatchRuns(runs)`：batch completed 后集中写回完整 `trace/judge/attribute/frontend_view/check/cluster/error`，并持久化到 project-scoped sessionStorage。
  - 更新 `resultMatchesCase()` 和 `caseRunInput()`，让普通 input case 与 `{input, output, reference, metadata, scenario}` 协议化 case 都能按真实 run input 判断是否 stale。

## 验证

### 静态验证

- `python -m compileall impl`：通过。
- HTML parser 解析 `impl/frontend/summary.html`：通过。
- 关键前端 hook 存在：
  - `applyBatchEvents(events)`：存在。
  - `applyBatchRuns(runs)`：存在。
  - `PAGE_VERSION='20260609-summary-batch-table-refresh-1'`：存在。
  - `clearCaseResult(item,event.status...)`：存在。

### 后端 UAT

- `/health`：返回 `status: ok`。
- `/api/batch_start` + `/api/batch_status`，用例：`client-search-seed-1 / 45岁女性保费10万以上`，Mock 模式：
  - batch status：`completed`。
  - done/total：`1 / 1`。
  - event：`case_id=client-search-seed-1, status=correct`。
  - result run：`status=correct`。
  - judge verdict：`correct`。
  - trace 存在。
  - `empty_result_reason == ""`。

### check.md 审核

- `check.scan_protocol_alignment(impl)`：`[]`。
- `check.scan_core_boundary(impl, client_search markers)`：`[]`。
- `check.scan_core_boundary(impl, QA markers)`：`[]`。

## check.md checklist

- [x] 没有只改展示文案：修复了 batch status event 到 casePool 的状态同步源头。
- [x] 保持统一链路：仍使用 `/api/batch_start` / `/api/batch_status` / `pipeline.batch_run`，没有新增第二套 judge/attribute/cluster。
- [x] 表格实时更新：batch polling 中每次拿到 events 都会同步 per-case status 并重渲染表格。
- [x] 完成后完整更新：completed 后用 `runs` 回写完整 trace/judge/attribute。
- [x] 协议化 case 兼容：`output/reference/scenario` 型 case 不会因为 stale 判断错误而丢结果。
- [x] 静态、API、check 扫描均通过。

## 结论

第 20 点已修复：批量归因过程中，进度日志和用例池表格现在使用同一个 batch status event 源同步；batch 完成后再用完整 run 结果补齐 trace/judge/attribute。用户不需要等刷新页面才能看到状态变化，也不会因为旧 stale 判断导致跑完后表格仍显示 pending。
