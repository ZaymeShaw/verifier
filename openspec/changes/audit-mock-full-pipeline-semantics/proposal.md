## Why

当前系统在 mock 语义上存在容易误导实现和判断的偏差：mock 的目标应是构建模拟 case/input/reference 数据，生成后仍必须进入统一全流程评估，而不是被理解成只能走 mock_response 的隔离 fixture。用户在 summary 前端看到的 mock 用例池批量归因结果必须与测试用例验证的真实页面链路一致，否则 check.md 要求的“审查产生机制、源头一致性、前后端一致性”没有真正满足。

## What Changes

- 审查并修正 mock 数据、batch 执行、前端展示、测试验证之间的语义对齐问题。
- 明确 mock case pool 是模拟数据来源，批量归因仍复用统一 `run_chain -> judge -> attribute -> cluster -> check` 链路。
- 检查并清理/调整可能误导判断的无用、过时或冗余函数/文档表述，尤其是把 mock case 误解为 mock-only fixture 的实现或说明。
- 增加覆盖“用户实际看到的 summary 候选区结果”和“测试用例断言的 batch 结果”一致性的 UAT/回归测试。
- 按 check.md 生成审查报告，记录系统偏差、源头机制、前后端一致性、无用函数排查和验证证据。

## Capabilities

### New Capabilities
- `mock-full-pipeline-semantics`: 约束 mock 数据生成、统一全流程执行、前端候选区展示和测试验证必须语义一致。

### Modified Capabilities

## Impact

- `impl/protocols/mock_protocol.md`、`impl/protocols/batch_protocol.md`、`impl/protocols/frontend_protocol.md`：需要补强 mock 数据与全流程执行的协议口径。
- `impl/core/pipeline.py`：审查 mock flag、provided-output fallback、batch case 输入保留是否符合统一链路语义。
- `impl/frontend/summary.html`：审查用户看到的来源、执行模式、output/reference/status 是否与 batch/test 结果一致。
- `impl/projects/marketting-planning/adapter.py`：审查 mock case/reference 与 live/full pipeline 评估目标是否一致。
- `tests/`：增加或调整覆盖 summary 等价路径的测试，确保测试断言用户可见结果。
- `search-test-case/issue/`：新增 check.md 审核报告。
