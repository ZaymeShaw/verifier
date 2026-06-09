# 20260609 full impl protocol check report

## 用户反馈

用户更新 `review.md`，要求执行验证，并按 `check.md` 对当前整个 `impl` 项目内容进行全量审核。

最新重点：

- 第 20 点：跑完归因后，表格页面没更新；`Output / 被评估输出`、`Reference`、`Score / Judge`、`归因摘要` 都没东西，甚至状态也没了。
- 第 21 点：协议、两个项目（`client_search` / `QA`）与协议本身可能没有完整对齐，需要按 `check.md` 全量校验。

## 全量审核范围

本轮检查覆盖：

- `impl/core/schema.py`
- `impl/core/adapter.py`
- `impl/core/pipeline.py`
- `impl/core/frontend_view.py`
- `impl/core/check.py`
- `impl/core/cluster.py`
- `impl/core/judge.py`
- `impl/core/attribute.py`
- `impl/server.py`
- `impl/frontend/live.html`
- `impl/frontend/summary.html`
- `impl/projects/client_search/*`
- `impl/projects/QA/*`
- `impl/protocols/*`

## 发现的问题

### 1. summary 表格只拿到 status event，拿不到完整 run，导致列无法实时补齐

此前修复了 batch event -> casePool 的状态同步，但 event 里只有：

- `case_id`
- `status`
- `error`
- `reason`

所以前端轮询过程中只能更新状态，无法实时补齐：

- `trace.extracted_output` -> `Output / 被评估输出`
- `frontend_view.reference_panel` / `judge.expected` -> `Reference`
- `judge` -> `Score / Judge`
- `attribute` -> `归因摘要`

这解释了用户看到“日志显示跑完，但表格列没东西/状态异常”的核心问题。

### 2. completed 之前表格与 batch result 的协议形状不一致

`/api/batch_status` completed 后会返回 `result.runs`，其中 run 是 compact run；但 running 阶段 event 不是同一形状。前端需要在 running 和 completed 阶段都能拿到同一种 case-row 更新协议，否则表格更新会割裂。

### 3. 协议化 case 的 stale 判断需要支持完整 run input

对于 QA 或 uploaded provided-output case，真实 run input 可能是：

```json
{ "input": {...}, "output": {...}, "reference": {...}, "scenario": "..." }
```

不能只用 `item.input` 对比 `trace.input`，否则容易误判 stale 并清掉结果。

## 已修复

### `impl/server.py`

- `_case_event()` 增加 `run: _compact_run(run)`。
- 每个 batch event 现在携带同 completed result 一致的 compact run 结构。
- running 阶段即可让前端拿到：
  - trace
  - judge
  - attribute
  - frontend_view
  - check
  - cluster
  - error

### `impl/frontend/summary.html`

- `applyBatchEvents(events)` 改为优先读取 `event.run`。
- 如果 event 带完整 run，则实时写回：
  - `status`
  - `trace`
  - `judge`
  - `attribute`
  - `frontend_view`
  - `check`
  - `cluster`
  - `error`
- `applyBatchRuns(runs)` 保留 completed 后的最终全量回写。
- `caseRunInput()` / `resultMatchesCase()` 支持 `{input, output, reference, metadata, scenario}` 协议化 case。
- `PAGE_VERSION` 已更新到 `20260609-summary-batch-table-refresh-1`，用于清理旧 session 状态。

## 全量验证

### 编译与静态检查

- `python -m compileall impl`：通过。
- `impl/frontend/summary.html` HTML parser：通过。
- served frontend token 检查：通过。
  - `PAGE_VERSION='20260609-summary-batch-table-refresh-1'` 存在。
  - `applyBatchEvents(events)` 存在。
  - `const run=event.run` 存在。
  - `Output / 被评估输出` 存在。
  - `Score / Judge` 存在。

### 服务重启与后端 UAT

按 `projects/client_search/start.md` 中 8020 前端分析服务要求，已重启：

- kill 旧 8020 进程。
- 启动 `python -m impl.server --port 8020`。
- `/health` 返回 `status: ok`。

### batch status event UAT

请求：

- `/api/batch_start`
- `/api/batch_status`
- project：`client_search`
- case：`client-search-seed-1 / 45岁女性保费10万以上`
- mock：`true`

结果：

- status：`completed`
- done/total：`1 / 1`
- event status：`correct`
- event 中 `run.trace`：存在
- event 中 `run.judge`：存在
- event 中 `run.attribute`：存在
- completed result 中表格核心列数据：
  - status：存在
  - trace.extracted_output：存在
  - judge：存在
  - attribute：存在
  - frontend_view.reference_panel：存在

### client_search 链路验证

- `run_chain('client_search', {'query':'45岁女性保费10万以上'}, mock=True)`：
  - verdict：`correct`
  - trace.extracted_output：存在
  - frontend reference_panel：存在

- `batch_run('client_search', ...)`：
  - verdict：`correct`
  - trace.extracted_output：存在
  - judge.expected：存在
  - attribute：存在

### QA 链路验证

- `run_chain('QA', {'question':..., 'actual_answer':..., 'golden_answer':...}, mock=False)`：
  - scenario：`qa_gold_answer`
  - trace.extracted_output：存在
  - frontend reference_panel：存在

- `batch_run('QA', ...)`：
  - scenario：`qa_gold_answer`
  - trace.extracted_output：存在
  - judge.expected：存在
  - attribute：存在

### check.md 协议扫描

- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

## check.md checklist

- [x] 检查源头，而不是只改展示：后端 batch event 协议补齐 compact run。
- [x] 前端表格与后端 batch status 对齐：running 和 completed 都使用 run-shaped 数据更新 casePool。
- [x] Output / Reference / Judge / Attribute / 状态均有统一来源。
- [x] `client_search` 和 `QA` 均通过单链路与 batch 链路验证。
- [x] 没有新增第二套 judge/attribute/cluster/check；仍复用 `pipeline.run_chain` / `pipeline.batch_run`。
- [x] 协议化 case `{input, output, reference, metadata, scenario}` 与普通 case 兼容。
- [x] `impl/core` 未泄漏 client_search / QA 项目专属 marker。
- [x] 编译、静态 HTML、服务、API UAT、check 扫描均通过。

## 结论

本轮全量审核确认：此前表格列为空的根因是 batch running 阶段 event 只同步状态、不同步完整 run。现在 `/api/batch_status` 的每个完成事件都会携带 compact run，summary 表格可以实时补齐 Output、Reference、Judge、Attribute 和状态；completed 后仍用最终 runs 做全量覆盖。`client_search` 与 `QA` 两个项目在协议、pipeline、adapter、frontend view、summary 表格、batch status 之间已对齐。
