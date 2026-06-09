# 20260608 check 报告

## 审查范围

- `.claude/skills/evals/agents/specialized/check.md`
- `.claude/skills/evals/agents/specialized/attribute-analyzer.md`
- `.claude/skills/evals/SKILL.md`
- `impl/frontend/summary.html`
- `impl/server.py`
- `impl/core/check.py`
- `impl/protocols/frontend_protocol.md`
- `impl/protocols/batch_protocol.md`
- `impl/projects/QA/project.yaml`

## Checklist

- [x] check agent 文档覆盖机制审查，而不是只审查最终产物。
- [x] check agent 文档覆盖过拟合、局部样本修改、展示层补丁、数据/代码/前端不一致、冗余失效组件。
- [x] attribute analyzer 增强“可修复源头机制”和“避免历史 case 过拟合”的要求。
- [x] SKILL.md 补充 check agent 的机制质量、标准化、数据/前端一致性职责。
- [x] summary 页面首屏不再自动加载和渲染 lastChain 大 JSON。
- [x] case table 限制首屏可见行数，避免一次性渲染大量用例。
- [x] batch status 返回 compact result，避免完成时把全量 batch JSON 推给前端。
- [x] batch events 后端和前端均设置上限。
- [x] protocol 文档补充大数据加载与 compact status 约束。
- [x] generic core 不再硬编码 QA scenario，改为项目配置 `frontend_extensions.check_rules` 驱动。

## 验证结果

- `python -m compileall impl`：通过。
- `python -m impl.cli projects`：返回 `QA`、`client_search`。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- `python -m impl.cli run-chain --project QA --mock ...`：通过。
- `python -m impl.cli batch-run --project QA --mock --concurrency 2 ...`：通过。
- `python -m impl.cli run-chain --project client_search --mock ...`：通过。
- 重启 `impl.server` 8020：完成。
- HTTP smoke：`/health`、`/projects`、`/frontend/live.html`、`/frontend/summary.html` 均可访问。
- `/api/batch_start` + `/api/batch_status`：完成后返回 compact runs，包含 `case_id/status/trace/judge/attribute` 摘要字段。

## 发现并修复的问题

1. summary 页面加载卡顿风险：首屏自动渲染 lastChain 和多个 raw JSON 面板。
   - 修复：改为用户点击“加载最近结果”后再加载；raw panel 使用 compact/truncated 输出。
2. 大批量用例渲染风险：表格一次性渲染所有匹配用例。
   - 修复：可见区只渲染前 100 条，执行语义仍按完整 selected 用例。
3. batch status 响应过大：任务完成时直接返回完整 batch result。
   - 修复：status 返回 compact batch result，保留关键可视化字段。
4. 进度事件无上限：长任务响应会越来越大。
   - 修复：后端保留 200 条，前端展示 120 条。
5. QA 检查规则在 generic core 中硬编码。
   - 修复：迁移为 `impl/projects/QA/project.yaml` 的 `frontend_extensions.check_rules`，core 按配置通用执行。

## 后续建议

如果之后需要前端下载完整 batch 原始结果，建议新增显式 debug/download API，而不是恢复到 `/api/batch_status` 默认返回全量结果。
