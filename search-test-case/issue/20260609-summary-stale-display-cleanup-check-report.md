# 20260609 summary stale display cleanup check report

## 用户反馈

`review.md` 新增第 22 点：页面跑完归因后出现“旧结果已清理，请重新批量归因”。用户已经重跑，不应该继续看到这种无效信息，要求按 `check.md` 审核。

## 问题定位

检查 `impl/frontend/summary.html` 后确认，问题来自前端 stale 结果清理逻辑：

- `stripResult(item)` 清理过期 trace/judge/attribute 后额外写入 `stale_result_removed: true`。
- `renderCaseJudge()` / `renderCaseAttribute()` 遇到该 flag 时直接展示“旧结果已清理，请重新批量归因”。
- 这使得一个内部清理状态被暴露到用户页面，并且在用户已经重跑时仍可能短暂或持续出现在表格列里。

这不是 judge/attribute 的源头问题，而是 summary 前端状态模型把内部清理标记变成了用户可见文案。

## 已修复

### `impl/frontend/summary.html`

- 更新 `PAGE_VERSION` 为 `20260609-summary-stale-display-cleanup-1`，清理旧 session 状态。
- 删除 `stale_result_removed` 状态写入。
- 删除 `clearStaleFlag()` 和相关调用。
- `sanitizeCaseResult()` 仍会清理不匹配或 stale empty_query 旧结果，但清理后统一回到普通 `pending` 状态。
- `renderCaseJudge()`：没有 judge 时只显示“尚未评估”。
- `renderCaseAttribute()`：没有 attribute 时只显示“尚未归因”。
- batch event / completed run 到达时仍直接写回完整 `trace/judge/attribute/frontend_view/check/cluster`，不会受 stale 标记影响。

## 验证

### 静态验证

- `grep` 确认 served 源码中不再包含：
  - `旧结果已清理`
  - `stale_result_removed`
  - `clearStaleFlag`
- `python -m compileall impl`：通过。
- `impl/frontend/summary.html` HTML parser：通过。

### check.md 协议扫描

- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

### served frontend 验证

请求 `/frontend/summary.html` 后确认：

- 新 `PAGE_VERSION='20260609-summary-stale-display-cleanup-1'` 存在。
- “旧结果已清理”不存在。
- `stale_result_removed` 不存在。
- `applyBatchEvents(events)` 存在。
- `const run=event.run` 存在。
- `Output / 被评估输出` 存在。
- `Score / Judge` 存在。

### batch_status UAT

使用 `client_search` 的 `45岁女性保费10万以上` 走 `/api/batch_start` + `/api/batch_status`：

- status：`completed`
- done/total：`1 / 1`
- event status：`correct`
- event 中 `run`：存在
- `run.trace`：存在
- `run.judge`：存在
- `run.attribute`：存在
- `run.frontend_view`：存在
- `trace.extracted_output.empty_result_reason == ""`
- `frontend_view.reference_panel.reference`：存在

## check.md checklist

- [x] 没有只改后端：本问题源头在 summary 前端状态展示，已从源头移除无效 UI 状态。
- [x] 没有新增第二套 batch/judge/attribute 逻辑：仍复用 `/api/batch_start` / `/api/batch_status` 的 compact run。
- [x] stale 清理仍保留，但只作为内部数据清理，不再展示无效提示。
- [x] running event 与 completed result 仍会回写完整 run，表格列可正常更新。
- [x] 编译、HTML parser、served frontend token、batch_status UAT、check 扫描均通过。

## 结论

第 22 点已修复：summary 页面不再展示“旧结果已清理，请重新批量归因”。过期/不匹配结果仍会被安全清理为普通 pending 状态；用户重跑后 batch event / completed result 会直接写回真实 Output、Reference、Judge、Attribute 和状态。
