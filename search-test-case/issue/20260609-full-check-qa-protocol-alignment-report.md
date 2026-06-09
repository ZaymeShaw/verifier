# 20260609 full impl check QA protocol alignment report

## 用户请求

用户要求使用 `/Users/xiaozijian/WorkSpace/projects/claude_code/eval_agent/check.md` 对当前整个 `impl` 项目内容进行全量审核。

## 审核范围

本轮覆盖：

- `impl/core/*`
- `impl/server.py`
- `impl/frontend/live.html`
- `impl/frontend/summary.html`
- `impl/projects/client_search/*`
- `impl/projects/QA/*`
- `impl/protocols/*`

## 发现的问题

### 1. QA mock case 在 batch 链路中丢失 output/reference

全量审核时发现：`QA.build_mock_cases()` 生成的样例把 `actual_answer` / `golden_answer` 放在 `input` 内；而 batch 协议会保留 `{input, output, reference, metadata, scenario}` 形状传给统一 `pipeline.run_chain()`。

但 `impl/projects/QA/adapter.py::_normalize_sample()` 只从顶层或 `output` / `reference` 读取答案和参考答案，没有读取 `input.actual_answer` / `input.golden_answer`，导致 QA mock batch 归一化后出现：

- `output.actual_answer == ""`
- `reference == {}`
- `data_quality_flags` 误报 `missing_actual_answer` / `missing_golden_answer`
- judge 只能返回 `uncertain`

这是 QA mock 源头、batch 协议、QA adapter 三者未对齐的问题，不是前端展示问题。

### 2. generic core 中残留 QA 专属字段 marker

`check.scan_core_boundary()` 发现 generic core 中残留 QA 专属字段：

- `impl/core/frontend_view.py` 中直接识别 `golden_answer` / `gold_answer`
- `impl/core/judge.py` 中用 `actual_answer` 决定 generated expected 的形状，并用 `golden_answer` / `gold_answer` 判断输入 reference

这会让 core 对 QA 字段产生项目特化理解，不符合 check.md 要求的协议边界。

## 已修复

### `impl/projects/QA/adapter.py`

- `_normalize_sample()` 现在会从 `input` 中读取：
  - `actual_answer` / `answer`
  - `golden_answer` / `gold_answer`
- `metadata_fields` 也会从 `input` 中归入 metadata，例如 QA mock case 的 `category`。

修复后 QA mock batch 的 normalized request 能保留：

- `output.actual_answer`
- `reference.golden_answer`
- `metadata.category`
- `scenario`
- 正确的 `data_quality_flags`

### `impl/core/frontend_view.py`

- 移除 core 对 `golden_answer` / `gold_answer` 的直接识别。
- reference 面板只从通用协议位置取值：
  - `trace.input.reference`
  - `trace.project_fields.reference`
  - `trace.normalized_request.reference`

### `impl/core/judge.py`

- 移除 core 中根据 `actual_answer` 生成 expected 的项目特化逻辑。
- `_has_input_reference()` 只检查通用 `reference` 和 `project_fields.reference`。

## 验证结果

### 编译与扫描

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

### client_search 验证

单链路：

- `45岁女性保费10万以上`：`correct`，`trace.extracted_output` 非空，`empty_result_reason == ""`。

batch 链路：

- 取前三个 client_search mock cases 跑 `pipeline.batch_run(..., mock=True, concurrency=2)`。
- 结果：`total=3`，verdict 统计 `{'correct': 3}`。
- 每个 run 都有非空 `trace.extracted_output`。

### QA 验证

单链路：

- 输入包含 `question`、`actual_answer`、`golden_answer`。
- `normalized_request.reference.golden_answer` 保留。
- `trace.extracted_output.actual_answer` 保留。
- `trace.project_fields.reference` 保留。

batch 链路：

- 使用 `pipeline.mock_cases('QA')` 跑 `pipeline.batch_run('QA', cases, mock=False, concurrency=1)`。
- 结果：`total=3`，verdict 统计 `{'incorrect': 1, 'correct': 1, 'uncertain': 1}`。
- 三个 QA mock case 的 output/reference 状态：
  - `qa-gold-1`：`actual_answer` 保留，`reference.golden_answer` 保留，`data_quality_flags=[]`。
  - `qa-rag-1`：`actual_answer` 保留，contexts 保留，`data_quality_flags=[]`。
  - `qa-weak-1`：`actual_answer` 保留，`data_quality_flags=['estimated_quality_only']`，符合弱参考质量评估场景。

### 服务与前端协议验证

- 已重启 `python -m impl.server --port 8020`。
- `/health` 返回 `status: ok`。
- `/projects` 返回 `QA` 和 `client_search`。
- served `/frontend/summary.html` token 检查通过：
  - `PAGE_VERSION='20260609-summary-batch-table-refresh-1'`
  - `applyBatchEvents(events)`
  - `const run=event.run`
  - `Output / 被评估输出`
  - `Score / Judge`
  - `Reference`

### `/api/batch_status` UAT

请求 QA 单 case batch 后轮询 `/api/batch_status`：

- status：`completed`
- done/total：`1 / 1`
- event 包含 `run`
- `run.trace`：存在
- `run.judge`：存在
- `run.attribute`：存在
- `run.frontend_view`：存在
- `trace.normalized_request.reference.golden_answer`：存在
- `trace.extracted_output.actual_answer`：存在
- `frontend_view.reference_panel.reference`：存在，source 为 `input`

## check.md checklist

- [x] 没有只修展示：修复的是 QA adapter 源头归一化。
- [x] 没有新增第二套 QA batch/judge/attribute/cluster：仍复用 `pipeline.run_chain()` / `pipeline.batch_run()`。
- [x] QA mock case、batch 协议、adapter 归一化已对齐。
- [x] generic core 不再含 QA/client_search 项目专属 marker。
- [x] summary running event 和 completed result 都能拿到 compact run。
- [x] client_search 单链路与 batch 链路通过。
- [x] QA 单链路与 batch 链路通过。
- [x] 编译、protocol scan、boundary scan、server health、served frontend token、batch_status UAT 均通过。

## 结论

本轮全量审核发现并修复了一个真实协议源头问题：QA mock case 的答案和参考答案在 batch 归一化时被丢失。现在 QA adapter 能正确兼容 flat sample、协议化 sample、以及 mock case 中嵌套在 `input` 的答案/参考字段；同时 generic core 中的 QA 专属 marker 已清理，`client_search` 与 `QA` 在协议、pipeline、server、summary 前端更新链路上已重新对齐。
