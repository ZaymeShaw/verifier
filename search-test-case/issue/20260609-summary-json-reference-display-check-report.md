# 20260609 summary JSON reference display check report

## Scope

对应最新 `demand.md` / `review.md`：

- 用例池跑完后候选表不能被清空或从结果状态回退成 pending。
- `Output / 被评估输出`、`Reference` 必须稳定展示。
- Reference 来源应为输入提供的标准答案或 judge 生成的参考答案。
- Reference 需要向 adapter-normalized output 对齐格式。
- 对难以阅读的对象摘要，不再展示 `summary: ..., structured_output: Array(...)` 这种压缩串，表格直接展示格式化 JSON。

## Changes checked

- `impl/frontend/summary.html`
  - 页面版本更新为 `20260609-summary-json-reference-1`，避免浏览器继续使用旧脚本。
  - 用例池表格的 Output / Reference 单元格改为 `<pre>` 格式化 JSON 展示。
  - Reference 优先取 `frontend_view.reference_panel.reference`，再回退到 `judge.expected`，最后才取输入原始 reference。
  - 保留之前的批量结果写回与筛选重置逻辑，避免 batch 完成后结果被隐藏或清理。

- `impl/protocols/frontend_protocol.md`
  - 明确 `reference_panel.reference` 必须归一化到 evaluated output 的同一顶层 shape。
  - 明确难以摘要时，case-pool 表格应展示格式化 JSON，而不是逗号拼接/压缩 key 片段。

- `impl/protocols/judge_protocol.md`
  - 明确 `JudgeResult.expected` 需要对齐 adapter-normalized `RunTrace.extracted_output` 的形状。
  - 明确即使 input/case 已提供 reference，也应在暴露为 expected/frontend reference 前完成输出形状对齐。

## Verification

- Compile:
  - `python -m compileall impl` passed.

- Static frontend checks:
  - summary page contains `20260609-summary-json-reference-1`.
  - summary page contains `formatJsonCell`.
  - Output cell renders with `<pre>`.
  - Reference cell renders with `<pre>`.
  - Reference fallback order uses `frontend_view.reference_panel.reference || judge.expected || inputReference(...)`.

- Protocol/check scans:
  - `check.scan_protocol_alignment(impl_root)` returned `[]`.
  - `check.scan_core_boundary(...)` for `client_search` project-specific markers returned `[]`.
  - `check.scan_core_boundary(...)` for QA project-specific markers returned `[]`.

- Served UAT on port 8020:
  - `/health` returned ok.
  - `/frontend/summary.html` served the updated page version and JSON display code.
  - QA `/api/run_chain` returned input reference exposed as output-shaped reference:
    - `reference_panel.source == "input"`
    - reference shape matched QA evaluated output key `actual_answer`.
  - `client_search` `/api/run_chain` returned reference keys aligned with extracted output:
    - `summary`
    - `structured_output`
    - `logic`
    - `status_code`
    - `user_visible_text`
    - `empty_result_reason`
    - `is_empty_result`
    - `source_query`
  - `client_search` batch run completed with result rows retaining verdict/status and frontend view data:
    - `client-search-seed-1`: correct, frontend view present.
    - `client-search-seed-2`: correct, frontend view present.

## Result

本轮问题按 `check.md` 审核通过：修复点不是只改展示文案，而是补齐了 judge/frontend protocol 对 reference shape 的要求，并在 summary 页面用协议输出展示格式化 JSON，避免表格继续出现不可读的对象压缩摘要或 batch 完成后结果丢失。