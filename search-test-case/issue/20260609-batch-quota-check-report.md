# 20260609 batch quota 与 check.md 审核报告

## 背景

`review.md` 反馈批量归因过程中出现 `Failed to execute 'setItem' on 'Storage'... exceeded the quota`，并导致整批归因停止。`demand.md` 要求归因失败时支持跳过/重试机制，且 output/reference 展示、批量链路、协议和 check agent 都需要保持一致。

## 发现的问题

1. 前端把完整批量结果写入浏览器 sessionStorage
   - 位置：`impl/frontend/summary.html`
   - 根因：`casePool` 中保存了完整 `trace/judge/attribute/frontend_view/check/cluster` 后继续整体写入 sessionStorage，大批量运行时容易超过浏览器存储额度。
   - 影响：前端轮询过程抛异常后跳入 catch，用户看到“批量归因失败”，已完成用例的页面状态也可能无法继续更新。

2. 批量后端缺少 future 级兜底
   - 位置：`impl/core/pipeline.py:batch_run`
   - 根因：单 case 内部已有 `_batch_case()` 捕获，但如果线程执行发生外层异常，`future.result()` 会中断批量聚合。
   - 影响：少数异常可能扩大成整批失败，不符合“错误样本跳过/继续”的要求。

3. check agent 需要明确覆盖浏览器持久化和批量稳定性
   - 位置：`.claude/skills/evals/agents/specialized/check.md`
   - 根因：已有机制审查原则，但对大批量、持久化、前端状态不应掩盖源头机制问题的要求不够明确。

## 已执行修改

1. `impl/frontend/summary.html`
   - 新增轻量化持久化：只把 durable case source/status 写入 sessionStorage，不持久化完整大体积运行产物。
   - 新增安全保存：sessionStorage 写入失败时捕获错误并继续当前批量渲染/轮询。
   - `applyBatchEvents()` 和 `applyBatchRuns()` 仍在当前页面内存中保留完整结果用于展示，但持久化降级为轻量 case pool。

2. `impl/core/pipeline.py`
   - 新增 `_batch_error_run()`。
   - `batch_run()` 对 `future.result()` 增加兜底捕获，把异常转成单条 error run，并继续处理后续用例。

3. `.claude/skills/evals/agents/specialized/check.md`
   - 补充产生机制审查、批量/持久化韧性、source consistency、问题记录 checklist 的要求。

4. `.claude/skills/evals/agents/specialized/attribute-analyzer.md`
   - 补充归因证据不足时不得伪装为完成根因，必须输出缺失证据和下一步验证。

5. `.claude/skills/evals/SKILL.md`
   - 补充 batch、browser persistence、frontend display 都属于被评估机制的一部分。

## check.md 审核 checklist

- [x] 机制源头优先：修复前端持久化机制，而不是只改报错文案。
- [x] 批量容错：单条/线程异常转成 error run，不终止整批。
- [x] 前端/API 一致性：继续复用 `/api/batch_start`、`/api/batch_status` 和统一 batch pipeline。
- [x] 避免过拟合：未针对某个 query 或字段写特殊规则。
- [x] 持久化最小化：浏览器只保存候选区源数据和状态，不保存大体积 transient run artifact。
- [x] 可追踪：本报告记录问题、根因、修改位置和验证项。

## 待验证项

- `python -m compileall -q impl`
- `python -m impl.cli projects`
- 重启 8020 服务后检查 `/health`
- 通过 `/api/batch_start` + `/api/batch_status` 验证批量任务完成
- 前端 UAT：清空候选区 -> 构建 Mock 用例池 -> 批量归因，确认页面不因 storage quota 中断，结果不被清空
