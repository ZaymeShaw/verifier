# 20260609 summary equal JSON cells check report

## Scope

对应最新 `demand.md` / `review.md` 的新增点：

- `Output / 被评估输出` 与 `Reference` 如果是 JSON/object，需要格式化换行展示。
- Output 和 Reference 两个前端格子需要使用一样的大小，方便对照查看。
- 继续保证 Reference 来源与 shape 规则：输入有 reference 则用输入 reference；没有则用 judge 生成 reference；展示前向 evaluated output 对齐格式。
- 继续保证 batch 完成后候选区结果不被清空、不从 `correct/incorrect` 回退成 `pending`。

## Changes checked

- `impl/frontend/summary.html`
  - 页面版本更新为 `20260609-summary-json-reference-equal-cells-1`，清理旧 session/page state，避免浏览器使用旧展示逻辑。
  - Output 与 Reference 表格列统一使用：
    - `.case-output,.case-reference{min-width:420px;max-width:520px;...}`
  - Reference 单元格从通用 `.case-summary` 拆为 `.case-reference`，与 Output 使用相同视觉宽度。
  - Reference 和 Output 都使用 `formatJsonCell(..., 1800)`，保持相同展示截断标准。

- `impl/protocols/frontend_protocol.md`
  - 明确 JSON/object-shaped 的 Output/Reference 应格式化换行展示。
  - 明确 Output/Reference table cells 应使用相同视觉大小，便于对照。

- `impl/core/judge.py` / `impl/core/frontend_view.py`
  - 本轮 check 发现此前 generic core 中还有 `structured_output` 这样的 client_search 私有字段 marker。
  - 已移除 generic core 对该字段名的硬编码，改为通用 list-valued field shape alignment：如果 output shape 中存在 list 字段、reference 中也存在 list 字段，则按 output 的 list 字段位置对齐。
  - 这样继续满足 client_search reference 对齐，同时不把项目私有字段写进 core。

## Verification

- Compile:
  - `python -m compileall impl` passed.

- Static frontend checks:
  - summary page contains `20260609-summary-json-reference-equal-cells-1`.
  - summary page contains `class="case-reference"`.
  - summary page contains shared CSS `.case-output,.case-reference{min-width:420px;max-width:520px;...}`.
  - Reference cell uses `formatJsonCell(caseReference(x),1800)`.
  - Output/Reference still render via formatted JSON function.

- Protocol/check scans:
  - `check.scan_protocol_alignment(impl_root)` returned `[]`.
  - `check.scan_core_boundary(...)` for `client_search` markers returned `[]`.
  - `check.scan_core_boundary(...)` for QA markers returned `[]`.

- Served UAT on port 8020:
  - `/health` returned ok.
  - `/frontend/summary.html` served the updated version and equal-cell CSS.
  - QA `/api/run_chain`:
    - `reference_panel.source == "input"`.
    - Reference was exposed in output-shaped key `actual_answer`.
  - client_search `/api/run_chain`:
    - `reference_panel.reference` keys matched extracted output shape:
      - `summary`
      - `structured_output`
      - `logic`
      - `status_code`
      - `user_visible_text`
      - `empty_result_reason`
      - `is_empty_result`
      - `source_query`
  - client_search `/api/batch_start` + `/api/batch_status`:
    - Batch completed.
    - Result rows retained verdict/status and `frontend_view`, proving batch writeback did not clear row result objects.

## Result

本轮按 `check.md` 审核通过：不是只改文字展示，而是同步了 frontend protocol、summary page 和 generic core boundary。Output/Reference 现在格式化 JSON 展示，并且两个表格格子大小一致；Reference shape alignment 继续保留，同时 core 不再硬编码项目私有字段。