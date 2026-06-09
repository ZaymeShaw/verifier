# 20260609 live-summary attribution judge alignment follow-up check 报告

## 审查范围

- `review.md` 第 16 条：live、judge、归因总结里的 judge 仍不一致，尤其归因总结里的 judge 不对，需要 UAT。
- `demand.md` judge 新要求：输入数据没有参考答案时，judge 需要同步生成 reference，并放到前端对应协议字段。
- `impl/core/judge.py`
- `impl/core/frontend_view.py`
- `impl/core/schema.py`
- `impl/frontend/summary.html`
- `impl/protocols/frontend_protocol.md`
- `impl/protocols/judge_protocol.md`

## 问题定位

上一轮只修了 batch compact result 和 summary 单链路 Judge 卡片，但归因总结的“用例池候选区 / 批量归因”表仍然把每条 case 的 judge 裁剪成 `{score, verdict, reason}`。因此用户在归因总结里看到的 per-case judge 仍不是完整 `JudgeResult`，和 live 单步 judge / full chain judge 不一致。

同时，当输入或上传用例没有 reference/golden_answer 时，judge 虽然协议里有 `expected` 字段，但前端没有一个稳定的 `Reference` 协议字段承接它，导致 Reference 列仍可能为空。

## 已执行修复

- `impl/core/schema.py`
  - `FrontendViewModel` 增加 `reference_panel`，作为前端展示 Reference 的统一协议字段。

- `impl/core/frontend_view.py`
  - 新增 reference 生成逻辑：
    - 输入有 `reference` / `golden_answer` / `gold_answer` 时，`reference_panel.source = input`。
    - 输入没有参考答案但 judge 有 `expected` 时，`reference_panel.source = judge_generated`。
    - 都没有时，`source = missing`。

- `impl/core/judge.py`
  - `required_output.expected` 明确要求：输入没有 reference 时，judge 要按 `actual` 的大致格式重建参考答案。
  - 增加兜底逻辑：如果模型没有返回 `expected` 且输入没有 reference，则基于 `reconstructed_intent` / `reasoning_summary` / `judge_basis` 生成同形态 reference，避免前端 reference 空白。

- `impl/frontend/summary.html`
  - `caseReference()` 增加 `item.judge.expected` 和 `item.frontend_view.reference_panel.reference` fallback。
  - 批量归因后保存每条 run 的 `frontend_view` 到 case pool。
  - 用例池表的 Score / Judge 列改为渲染完整 `JudgeResult` 卡片（结论、评分、置信度、原因 + 可展开完整 JSON），不再只显示裁剪摘要。
  - 归因摘要列同样改为完整 `AttributeResult` 卡片，避免 attribute 在归因总结表里被裁剪成另一种形状。
  - 单链路区增加 `Reference` 面板，直接展示 `frontend_view.reference_panel`。

- `impl/protocols/frontend_protocol.md`
  - 增加 `reference_panel` 字段。
  - 明确 reference 来源规则：input / judge_generated / missing。

- `impl/protocols/judge_protocol.md`
  - 明确 `expected` 在无输入参考答案时应作为 judge 生成 reference，且格式应尽量与 `actual` 对齐。

## Checklist

- [x] 归因总结 batch/per-case judge 不再裁剪为 `{score, verdict, reason}`。
- [x] Summary 单链路和 batch case 都可展开完整 `JudgeResult`。
- [x] 输入无 reference 时，`JudgeResult.expected` 可生成并进入 `FrontendViewModel.reference_panel`。
- [x] Summary Reference 列会回退到 judge-generated reference。
- [x] Batch compact result 继续保留完整 judge 和 frontend_view，同时移除 trace raw_response。
- [x] 协议文档同步 reference_panel 和 judge-generated expected 规则。
- [x] 编译、协议扫描、边界扫描、QA 无参考答案链路、client_search 单链路/批量链路、8020 HTTP smoke 均已验证。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- QA 无 reference 单链路：
  - `frontend_view.reference_panel.source == judge_generated`
  - `frontend_view.reference_panel.reference` 非空
  - `judge.expected` 非空
- QA batch：
  - 每条 run 保留 `frontend_view.reference_panel`
  - 每条 run 保留完整 judge 字段（本次验证 24 个 judge 字段）
- client_search mock 单链路：通过。
- client_search mock batch：2/2 完成，judge 完整字段和 frontend reference_panel 均保留。
- `_compact_run()` 验证：
  - 保留 `judge.expected`、`actual`、`evaluation_boundary`、`primary_assessment`、`reasoning_summary`
  - 保留 `frontend_view.reference_panel`
  - 移除 `trace.raw_response`
- 前端静态审核：
  - `caseReference` fallback 到 `item.judge?.expected`：通过。
  - 用例池 judge 使用完整卡片：通过。
  - 用例池 attribute 使用完整卡片：通过。
  - batch 后保存 `frontend_view`：通过。
  - 单链路 Reference 面板存在：通过。
- 8020 smoke：
  - `/health` HTTP 200
  - `/projects` HTTP 200
  - `/frontend/live.html` HTTP 200
  - `/frontend/summary.html` HTTP 200

## 结论

本轮补齐的是上一轮遗漏的归因总结 per-case/batch 展示链路：live、summary 单链路、summary 批量归因中的 judge 现在都渲染同一个完整 `JudgeResult` 协议对象；没有输入参考答案时，judge 生成的 `expected` 也会作为 `reference_panel` 进入前端 Reference 展示。
