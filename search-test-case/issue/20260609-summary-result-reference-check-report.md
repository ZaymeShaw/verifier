# 20260609 summary result reference check report

## 用户反馈

`review.md` 最新 202606091939 两点：

1. 跑完之后表格被强行清空，跑的时候其实是有东西的；旧反馈第 23 点也补充为 correct/incorrect 全部变成 pending。
2. Reference 返回内容不对：reference 应该来自输入里用户给的标准答案，或者 judge 生成的参考答案；且 demand.md 要求 reference 与 output 保持相同格式。

## 问题定位

### 1. 跑完后 correct/incorrect 变 pending

问题不在 batch 后端没有返回结果。`/api/batch_status` 的 completed result 和 running event 都有 `run.judge`、`run.attribute`。

真正问题在 summary 前端保存候选池时会调用：

- `saveCasePool()` → `sanitizeCasePool()` → `sanitizeCaseResult()` → `resultMatchesCase()`

上一轮为兼容 protocol-shaped case，`resultMatchesCase()` 对带 `scenario/reference/output/metadata` 的 case 只比较：

- `trace.input` vs `caseRunInput(item)`

但实际 batch 路径里 `_batch_case()` 会把 `case_id` 注入到送入 pipeline 的输入中；对部分用例，`trace.input` 与页面 row 的 `caseRunInput(item)` / `item.input` 形状可能存在协议包装差异。于是 batch 正在跑时 event 已经写回 correct/incorrect，但 completed 后 `applyBatchRuns()` 调用 `saveCasePool()`，sanitize 误判 result 不匹配并 `stripResult()`，最终状态被重置为 `pending`，看起来像“表格被强行清空”。

### 2. Reference 格式不对

Reference 来源与展示链路分散在：

- `impl/core/judge.py` 的 `JudgeResult.expected`
- `impl/core/frontend_view.py` 的 `reference_panel.reference`
- `impl/frontend/summary.html` 的 `caseReference()`

原逻辑存在两个问题：

- 如果输入提供了 reference，`judge.py` 直接返回原始 reference，未按 `trace.extracted_output` 形状对齐。
- `frontend_view.py` 对 input reference 也直接展示原始 reference，导致 QA 场景可能显示 `{golden_answer: ...}`，而 output 是 `{actual_answer: ...}`，格式不一致。

## 已修复

### `impl/frontend/summary.html`

- `PAGE_VERSION` 更新为 `20260609-summary-result-reference-1`。
- `resultMatchesCase(item)` 改为同时接受两种合法匹配：
  - `trace.input` vs `caseRunInput(item)`
  - `trace.input` vs `item.input`
- 这样 completed 后 `saveCasePool()` 不会因为协议包装差异误判 stale，不会把已写回的 `correct/incorrect + judge/attribute` strip 成 pending。
- `caseReference(item)` 优先展示后端统一生成的 `frontend_view.reference_panel.reference`，其次是 `judge.expected`，最后才回退到输入原始 reference，避免前端自己展示未对齐格式。

### `impl/core/judge.py`

- 新增通用 reference shape 对齐逻辑：以 `trace.extracted_output` 为目标形状。
- 如果输入提供 reference，`JudgeResult.expected` 不再原样返回，而是对齐到 output 形状。
- 如果输入没提供 reference，则 judge 生成的 expected 也会按 output 形状对齐。
- 清理 generic core 里的 QA 专用字段判断，避免违反 check core boundary。

### `impl/core/frontend_view.py`

- `reference_panel.reference` 也按 `trace.extracted_output` 形状对齐。
- 对 input reference 和 judge-generated reference 使用同一通用对齐逻辑。
- 清理 generic core 里的 QA 专用字段判断，避免把 QA 字段硬编码进通用层。

## 验证

### 编译与静态验证

- `python -m compileall impl`：通过。
- `impl/frontend/summary.html` HTML parser：通过。
- summary 源码断言通过：
  - 新 `PAGE_VERSION` 存在。
  - `resultMatchesCase()` 同时兼容 `caseRunInput(item)` 和 `item.input`。
  - `caseReference()` 优先使用 `frontend_view.reference_panel.reference`。

### pipeline UAT

#### QA 输入提供标准答案

输入：

```json
{
  "question": "什么是犹豫期？",
  "actual_answer": "犹豫期通常是投保人收到合同后的一段可无条件退保期限。",
  "golden_answer": "犹豫期是投保人收到保险合同后，在规定天数内可申请解除合同并通常退还已交保费的期限。"
}
```

结果：

- output：`{"actual_answer": "..."}`
- `judge.expected`：`{"actual_answer": "...标准答案..."}`
- `frontend_view.reference_panel.reference`：`{"actual_answer": "...标准答案..."}`
- source：`input`

说明输入标准答案被使用，且 reference 与 output 格式对齐。

#### client_search judge 生成参考答案

输入：`45岁女性保费10万以上`

结果：

- `trace.extracted_output` keys：`summary, structured_output, logic, status_code, user_visible_text, empty_result_reason, is_empty_result, source_query`
- `frontend_view.reference_panel.reference` keys 与 output keys 一致。
- source：`judge_generated`

说明 judge 生成 reference 也按 output 格式对齐。

#### client_search batch 回归

`pipeline.batch_run('client_search', mock_cases[:2], mock=True, concurrency=2)`：

- total：2
- `client-search-seed-1`：verdict=`correct`，attribute 存在
- `client-search-seed-2`：verdict=`correct`，attribute 存在

### served frontend / API UAT

重启本地 `8020` 服务后验证：

- `/health`：ok。
- served `/frontend/summary.html` 包含 `20260609-summary-result-reference-1`。
- served 页面包含新的 `resultMatchesCase()` 双路径匹配逻辑。
- `/api/run_chain` QA：reference 为 `{"actual_answer": "...标准答案..."}`，source=`input`。
- `/api/run_chain` client_search：reference keys 与 output keys 一致。
- `/api/mock_cases` → `/api/batch_start` → `/api/batch_status`：completed，2/2，两个 run 均有 verdict 和 attribute。

### check.md 扫描

- `check.scan_protocol_alignment(impl)`：`[]`
- `check.scan_core_boundary(impl, client_search markers)`：`[]`
- `check.scan_core_boundary(impl, QA markers)`：`[]`

## check.md checklist

- [x] 没有只改展示文案：修复了 completed 后 sanitize 误清结果的源头逻辑。
- [x] 没有新增第二套 batch/judge/attribute：仍复用统一 pipeline 和 compact run 写回。
- [x] 表格跑完后不会因协议包装差异把 correct/incorrect strip 成 pending。
- [x] Reference 来源遵循协议：优先用户输入标准答案，否则 judge 生成。
- [x] Reference 形状与 output 对齐。
- [x] 没有把 QA 专用字段硬编码到 generic core。
- [x] compile、HTML parser、pipeline UAT、served API UAT、check scans 均通过。

## 结论

本轮两点已修复：跑完后候选区结果不会被 sanitize 误判并重置成 pending；Reference 统一由后端协议层按 output 形状生成，输入标准答案和 judge 生成参考答案都会在前端展示为与被评估 output 一致的格式。
