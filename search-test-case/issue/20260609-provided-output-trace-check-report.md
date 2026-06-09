# 20260609 provided-output trace 协议与 check.md 审核报告

## 用户反馈

`demand.md` 与 `review.md` 更新要求：根据业务场景特点，如果输入不包含 output，trace 要先调用项目 API 生成 output；如果输入包含 output，则直接提取，且实现需要在 impl 协议范围内调整。

## 问题确认

本轮检查发现：

1. `QA` 项目已经通过 adapter 读取上传样本中的 `actual_answer` / `output.actual_answer`，不调用外部业务服务。
2. 通用 batch 已经保留 `output/reference/metadata/scenario`，没有丢掉上传样本输出。
3. `client_search` 在输入包含 `output` 时仍会走默认项目服务调用路径；如果用户上传带 output 的 client_search 用例，trace 不会直接评估该 output。
4. `client_search.build_request()` 只读取顶层 `query/user_text`，对 batch 保留下来的 `{input:{query}, output:{...}}` 形态没有取到 query，导致 provided-output trace 的 `source_query` 可能为空。

## 已修复

- `impl/core/adapter.py`
  - 增加通用 adapter hook：
    - `has_provided_output(input_data, request)`：识别 `raw_response/response/output`。
    - `provided_output_raw(input_data, request)`：读取调用方提供的输出。

- `impl/core/pipeline.py`
  - `live_run()` 调整为统一分支：
    - `mock=True`：走 `mock_response()`。
    - 输入包含 `output/response/raw_response`：走 `adapter.provided_output_raw()`，不调用项目服务。
    - 输入不包含 output：走 `adapter.call_or_prepare()` 调用项目服务。

- `impl/projects/client_search/adapter.py`
  - 支持 batch/protocol 形态 `{input:{query}, output:{...}}` 的 query 提取。
  - 增加 `provided_output_raw()`，将调用方提供的 `output.structured_output/conditions` 转成 client_search 等价 raw response，再复用既有 `extract_output()`。
  - 保留 `raw_response/response` 直通，用于完整业务响应已由调用方提供的场景。

- `impl/protocols/run_trace_protocol.md`
  - 明确 provided-output trace：调用方已提供 output 时，adapter 要转换为项目等价 raw response，并直接抽取，不强制调用项目服务。

- `impl/protocols/batch_protocol.md`
  - 明确 batch 中携带 `output/response/raw_response` 的用例必须走 provided-output trace 路径。

## 验证

### 编译

- `python -m compileall impl`：通过。

### provided-output 单链路

`client_search` 输入包含 output：

- 输入：`45岁女性保费10万以上` + provided `structured_output`。
- 结果：`trace.status == ok`。
- 结果：`raw_response.message == provided output`，证明没有调用业务服务生成新输出。
- 结果：`extracted_output.structured_output` 保持为：
  - `clientAge RANGE {min:45,max:45}`
  - `clientSex MATCH 女`
  - `annPremSegNum GTE 100000`
- 结果：`empty_result_reason == ""`，不再出现 provided output 被当成空查询的情况。

`QA` 输入包含 actual answer：

- 输入：`question/actual_answer/golden_answer`。
- 结果：`trace.status == ok`。
- 结果：`extracted_output.actual_answer` 正确读取上传输出。
- 结果：`project_fields.scenario == qa_gold_answer`。

### 无 output 路径

`client_search` 输入不包含 output：

- mock 路径验证 `live_run('client_search', {'query':'45岁女性保费10万以上'}, mock=True)` 正常生成 output。
- 该路径仍保留项目服务/模拟服务生成 output 的行为，没有被 provided-output 逻辑覆盖。

### batch provided-output

`batch_run('client_search', cases, mock=False, concurrency=1)`，case 形态为：

```json
{
  "id": "provided-client-search-1",
  "input": {"query": "45岁女性保费10万以上"},
  "output": {"structured_output": [...], "logic": "AND", "summary": "provided output", "status_code": 0},
  "expected_intent": "45岁女性保费10万以上"
}
```

验证结果：

- `case_id == provided-client-search-1`。
- `trace.raw_response.message == provided output`。
- `trace.extracted_output.source_query == 45岁女性保费10万以上`。
- `judge.verdict == correct`。

### check.md 审核

- `check.scan_protocol_alignment(impl)`：`[]`。
- `check.scan_core_boundary(impl, client_search markers)`：`[]`。
- `check.scan_core_boundary(impl, QA markers)`：`[]`。

## check.md checklist

- [x] 不是只改展示：修复了 `pipeline -> adapter -> RunTrace` 的源头分支。
- [x] 输入不含 output 时仍生成 output：mock/API 路径保留。
- [x] 输入含 output 时直接提取：通用 hook + client_search/QA 验证通过。
- [x] batch 保留 output 并走统一 run_chain，没有新增第二套 judge/attribute/cluster。
- [x] 协议文档同步更新 run trace 与 batch 规则。
- [x] 编译与 check 扫描通过。

## 结论

本轮已对齐 review/demand 第 19 点：trace 现在按项目 adapter 判断输入是否已包含输出；有输出则直接抽取为统一 `RunTrace`，无输出则走项目服务或 mock 生成输出。`client_search` 与 `QA` 两类不同业务形态均已验证。
