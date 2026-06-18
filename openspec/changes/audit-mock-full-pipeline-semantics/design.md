## Context

用户纠正了 mock 语义：mock 的目标只是模拟测试数据，模拟好 `input/reference/case` 后仍要执行统一全流程，而不是把 mock case 理解成只服务于 `mock_response()` 的隔离 fixture。现有协议中已有正确口径，例如 `impl/protocols/batch_protocol.md` 写明 mock batch 和 live batch 是同一 batch pipeline，执行模式只改变 run stage；`impl/protocols/run_trace_protocol.md` 写明 mock/live 要归一成语义等价的 `RunTrace`；历史 `client_search` UAT 报告也曾按“构建 mock 用例池 -> 真实服务批量归因”复现并修复问题。

当前偏差主要来自实现和展示层的可读性不足，而不是 core pipeline 完全分裂：`impl/core/pipeline.py` 的 `batch_run()` 始终调用 `_batch_case() -> run_chain() -> live_run() -> judge -> attribute -> cluster -> check`，但 `summary.html` 将“构建 Mock 用例池”和“执行模式 Mock 响应/真实服务”并列展示，且候选区没有明确展示 run 输入、run mode、实际 output 来源与测试断言之间的一致关系。这会让人误以为 mock case 只应在 mock mode 下解释，或让测试只验证 API JSON 而没有验证用户最终看到的候选区状态。

check.md 审查还发现若干潜在无用/过时函数候选：`impl/core/adapter.py:203 ensure_jsonable`、`impl/core/http_client.py:get_json`、`impl/core/judge.py:_has_input_reference`、`impl/projects/client_search/adapter.py:_canonical_conditions`、`impl/projects/QA/adapter.py:_text_overlap_ratio`。其中 HTTP handler 方法由框架反射调用，不能按文本引用计数误删；其余需要逐个确认依赖和业务意义后清理或补测试。

## Goals / Non-Goals

**Goals:**

- 明确协议：mock case pool 是模拟数据来源；批量归因必须执行统一全流程，`mock` flag 只表示 actual output 来源或服务替代方式，不改变 reference 评估目标。
- 修正前端：用户看到的候选区 `Input / Output / Reference / 状态 / Judge / Attribute` 必须来自同一 run，并能展示或追踪 execution mode 与 case id。
- 修正测试：新增 summary 等价 UAT，测试断言必须覆盖用户实际看到的候选区字段，而不是只断言后端 batch JSON。
- 按 check.md 审查并处理无用/过时函数，避免死代码或旧表述影响后续判断。
- 生成中文 check 报告，记录机制源头、协议/前端/测试一致性、无用函数排查和验证结果。

**Non-Goals:**

- 不修改外部 `/Users/xiaozijian/WorkSpace/package/marketing-planning` 仓库。
- 不新增 project-private verifier endpoint。
- 不把所有 mock case 强制改成一定 correct；如果真实全流程输出不满足 reference，仍应展示 incorrect，并通过 attribute/check 指出源头。
- 不用前端展示规则掩盖 judge 失败。

## Decisions

1. **以 case/reference 为评估目标，以 run mode 为 output 来源标记。**
   - 选择：保留 `mock` 执行参数，但文案和协议明确它只影响 output 生成路径：`adapter.mock_response()` 或真实服务调用；之后的 judge/attribute/cluster/check 不分叉。
   - 替代方案：构建 mock 用例池后自动切换 Mock 响应。拒绝作为主方案，因为这会再次把 mock case 误导成 mock-only；最多可以作为显式 UI 便利操作，但不能改变全流程语义。

2. **前端候选区必须展示用户可核对的一致性证据。**
   - 选择：在候选区或 batch summary 中保留并展示 `execution_mode/run_mode`、`case_id`、`trace.input` 与 case input 是否匹配、`trace.extracted_output`、`reference` 来源。
   - 替代方案：只在 Raw JSON 里查看。拒绝，因为用户反馈的核心就是“用户看到的东西”和测试不一致，必须在主表可见或至少可追踪。

3. **测试按页面等价路径断言用户可见字段。**
   - 选择：新增/调整 UAT 测试模拟 `mock_cases -> batch_start/batch_status 或 pipeline.batch_run -> apply-to-case-pool 等价映射`，断言候选区所用的 output/reference/status 与 batch run 一致。
   - 替代方案：只测 adapter mock cases 或只测 batch result。拒绝，因为它不能证明前端候选区没有丢字段、串旧结果或展示不同 run。

4. **无用函数按 check.md 三分类处理。**
   - 选择：先用静态扫描列候选，再人工核对是否框架反射调用、扩展点、未来协议入口或真正死代码；真正无用才删除，过时但有业务意义则补齐到最新协议。
   - 替代方案：根据引用计数直接删除。拒绝，因为 HTTP handler、adapter hook 这类函数可能无文本调用但由框架/多态调用。

## Risks / Trade-offs

- **Risk: 测试仍只验证后端，不覆盖用户视图。** → Mitigation: 测试必须断言经过前端同等映射后的候选区字段，包括 status/output/reference/run mode。
- **Risk: 为了让 mock case 全部 correct 而改弱 reference。** → Mitigation: check 报告必须区分“mock 数据源错误”“业务 live 输出错误”“judge/reference 错误”，不得只 patch 数据。
- **Risk: 删除扩展点造成项目 adapter 失效。** → Mitigation: 无用函数清理前先 grep、LSP/AST 查引用，并跑 QA/client_search/marketting-planning 回归。
- **Risk: 前端展示新增字段导致页面复杂。** → Mitigation: 只展示最小证据：run mode、case id、output/reference/status 一致性；详细内容保留在现有详情 JSON。
