# 20260609 live-summary-judge-alignment check 报告

## 审查范围

- `review.md` 第 16 条：live、judge、归因总结里的 judge 明显不一样，需要对齐。
- `impl/server.py`
- `impl/frontend/live.html`
- `impl/frontend/summary.html`
- `impl/protocols/frontend_protocol.md`
- `impl/protocols/judge_protocol.md`

## 问题定位

本轮问题不是 judge agent 有多套后端逻辑，而是不同入口的展示/批量摘要把同一个 `JudgeResult` 裁剪成了不同形状：

- live 页单步 judge 和全链路都拿 `/api/judge` 或 `/api/run_chain` 的完整 `JudgeResult`。
- summary 单链路也拿 `/api/run_chain` 的完整 `JudgeResult`，但只以 raw JSON 方式展示，和 live 页的人类可读卡片不一致。
- batch job 的 compact result 曾只保留 judge 的少量字段，导致批量归因/归因总结里的 judge 结果看起来不像完整 judge 协议对象。

这会造成用户看到“live 的 judge”和“归因总结里的 judge”不一样，虽然底层 pipeline 大体复用，但前端/compact 层破坏了协议一致性。

## 已执行修复

- `impl/server.py`
  - `_compact_run()` 改为保留完整 `judge`、`attribute`、`cluster`、`check`、`frontend_view` 协议对象。
  - 仅从 compact trace 中移除大体积 `raw_response`，避免重新引入页面卡顿。
  - batch 状态结果不再裁剪 judge 核心协议字段，例如 `evaluation_boundary`、`boundary_decision`、`primary_assessment`、`missing/wrong/extra` 等。

- `impl/frontend/summary.html`
  - summary 单链路 Judge 区改为和 live 页一致的可读卡片：结论、评分、置信度、原因。
  - 同时保留可展开的完整 `JudgeResult`，避免只展示局部摘要。
  - Attribute 区也做同样处理：可读摘要 + 完整 `AttributeResult`。

- `impl/protocols/frontend_protocol.md`
  - 增加规则：live 和 summary 页必须渲染同一套 `JudgeResult` / `AttributeResult` 协议对象；布局可以不同，但不能裁剪核心字段或发明另一种 judge 展示形状。

## Checklist

- [x] 确认 `/api/judge`、`/api/run_chain`、summary 单链路都复用 `pipeline.judge()`。
- [x] 检查 batch compact result 是否裁剪 judge 协议字段。
- [x] 修复 compact result，保留完整 judge/attribute/check/frontend_view。
- [x] summary 页使用和 live 页一致的人类可读 judge 摘要，并保留完整协议对象。
- [x] 协议补充前端展示一致性要求。
- [x] 编译、协议扫描、边界扫描、mock 链路、QA 链路、frontend smoke 均已验证。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- `python -m impl.cli run-chain --project client_search --mock --input '{"query":"有生存金未领取的客户"}'`：通过。
- `python -m impl.cli run-chain --project QA --mock --input ...`：通过。
- `_compact_run()` 单元验证：
  - `judge.evaluation_boundary` 被保留。
  - `trace.raw_response` 被移除以避免大 payload。
  - `frontend_view` 被保留。
- 重启 8020 后 smoke：
  - `/health` OK
  - `/projects` OK
  - `/frontend/live.html` HTTP 200
  - `/frontend/summary.html` HTTP 200

## 结论

本轮修复后，live 单步 judge、live 全链路 judge、summary 单链路 judge、batch/归因总结中的 judge 都来自同一个 `JudgeResult` 协议对象。前端可以做不同布局，但不再把 judge 裁剪成不一致的数据形状。
