# 20260609 summary case pool visibility check report

## 用户反馈

`review.md` 第 23 点：跑完归因后，结果用例池候选区的结果没了。

## 问题定位

按页面逻辑检查 `impl/frontend/summary.html` 后确认，用例没有被后端删除，也不是 batch result 没写回。真正问题在前端筛选状态：

- 候选区有状态筛选 `caseFilter`，可选 `pending/correct/incorrect/uncertain`。
- batch 跑完后，`applyBatchEvents()` / `applyBatchRuns()` 会把用例状态从 `pending` 写成 judge verdict，例如 `correct`。
- 如果用户跑之前或过程中停留在 `pending` 筛选，跑完后 `renderCasePool()` 仍按 `pending` 过滤，所以可见 rows 变成 0。
- 原 UI 在筛选命中 0 条时统一展示“候选区为空，可构建 Mock 用例池或导入自定义数据集”，让用户误以为候选用例被清空。

复现等价结果：

- 跑前 `pending` 可见：2 条。
- 跑后状态变成 `correct`，旧 `pending` 筛选可见：0 条。
- 切回 `all` 后可见：2 条。

## 已修复

### `impl/frontend/summary.html`

- `PAGE_VERSION` 更新为 `20260609-summary-case-pool-visibility-1`，避免旧 session 状态继续污染。
- 新增 `resetCasePoolFilters()`，将状态筛选和场景筛选恢复为全部。
- 构建 mock 用例池、加载 mock dataset、导入用例池、加载持久化用例池时，都会重置筛选，确保新候选池直接可见。
- batch completed 后，在 `applyBatchRuns(runs)` 前重置筛选，确保跑完后的 `correct/incorrect/uncertain` 结果仍留在候选区可见。
- `renderScenarioFilter()` 在当前场景不存在时回退到 `all`，避免场景列表刷新后继续使用已失效筛选值。
- 候选池不为空但当前筛选 0 命中时，不再展示“候选区为空”，改为提示：当前筛选未命中，候选区仍有 N 条，请切回全部状态/全部场景查看。

## 验证

### 编译与静态验证

- `python -m compileall impl`：通过。
- `impl/frontend/summary.html` HTML parser：通过。
- summary 源码断言通过：
  - 新 `PAGE_VERSION` 存在。
  - `resetCasePoolFilters()` 存在。
  - batch completed 后先 `resetCasePoolFilters()` 再 `applyBatchRuns(runs)`。
  - “当前筛选未命中用例”提示存在。
  - 场景筛选失效时会回退到 `all`。

### served frontend 验证

请求 `/frontend/summary.html`，确认 served 页面包含最新逻辑：

- `20260609-summary-case-pool-visibility-1`：存在。
- `function resetCasePoolFilters()`：存在。
- `resetCasePoolFilters(); applyBatchRuns(runs);`：存在。
- “当前筛选未命中用例”：存在。
- 旧版本 `20260609-summary-run-writeback-1`：不存在。

### API / batch UAT

使用 `/api/mock_cases` + `/api/batch_start` + `/api/batch_status` 跑 `client_search` mock batch：

- mock cases：2 条。
- batch status：completed。
- events：2 条。
- result statuses：`correct`, `correct`。

这说明 batch 本身仍会写回结果；本轮修复的是跑完后的候选区可见性，不改动 judge / attribute / cluster 后端链路。

### 筛选复现验证

页面逻辑等价模拟：

- before pending visible：2。
- after old pending visible：0。
- after fixed all visible：2。

说明第 23 点确实来自筛选视图状态，而不是 casePool 数据丢失。

### check.md 扫描

- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

## check.md checklist

- [x] 没有只改文案：修复了筛选状态在 batch 完成后继续隐藏结果的源头逻辑。
- [x] 没有新增第二套 batch/judge/attribute：仍复用统一 `/api/batch_start` / `/api/batch_status` 和 compact run 写回。
- [x] 没有清空用例池：casePool 仍保留跑完后的完整结果。
- [x] 当前筛选 0 命中时不再误报“候选区为空”。
- [x] 新建/导入/加载/跑完批量归因后，候选区默认展示全部结果。
- [x] served frontend、API UAT、compile、HTML parser、check scans 均通过。

## 结论

第 23 点已修复：跑完归因后，候选区结果不会因为停留在 `pending` 或失效场景筛选而看起来消失。页面会自动切回全部筛选展示跑完后的结果；如果用户手动筛选导致 0 命中，也会明确提示只是筛选未命中而不是候选区被清空。
