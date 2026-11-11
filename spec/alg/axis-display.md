# 评测轴导出展示配置

对应需求：`demand/frontend.md`。展示策略只解释已有结果，不参与评测、模型调用或结果持久化。

## 配置与接口

- 路径：`data_root() / <project> / axis_display.json`。无实例环境时是 `impl/data/<project>/axis_display.json`；通过端口启动服务时是 `.runtime/instances/<instance_id>/data/<project>/axis_display.json`。实例创建后独立维护，已有实例不会自动同步仓库配置。
- 内容：`{"axes": {"tool_execution": {"attention_verdicts": ["problematic", "not_evaluable", "untested"]}}}`。
- `axes` 的键是项目 registry 的 `type_id`；值只含字符串数组 `attention_verdicts`，精确匹配该轴声明的 verdict。未知轴、未知值、重复值、非法结构均报错。
- 文件缺失或 `axes` 为空表示未配置，不要求项目提供轴 registry。未配置的轴不产生标签。
- `POST /api/axis_display` 请求 `{"project": "llm_probe_loop"}`，返回 `{"project_id": "llm_probe_loop", "axes": {...}}`。读取时即时校验；配置非法返回 422，读取失败返回 500，不吞错。
- 导出时读取一次；请求期间切换项目则取消该次导出。后续修改配置无需重启、无需重跑模型，只需重新导出。首次部署新增接口需重启服务。

## Excel 列

1. case sheet 的“问题 tags”：仅取 `status=succeeded` 的轴级 verdict，按 `type_id`（结果只含 `axis_id` 时用它）匹配名单，输出 `[轴ID:verdict]`，按轴顺序去重并换行。展示分组不影响匹配，items 不参与推断。无命中留空，不增加或删减原有导出行。
2. 轴汇总 sheet 的“Case 需求达成状态”：读取 case 的 `table_row.fulfillment_status` 或 judge 的 `overall_fulfillment.status`，仅接受 fulfilled / not_fulfilled / not_evaluable。case 运行中、错误或带执行失败标记时留空；不使用中文 `main_verdict`，也不从扩展轴反推 case 结论。每条轴重复同一 case 值，与该轴的“轴级判定”并列。
3. 轴汇总 sheet 的“是否问题 tag”：该行轴命中关注名单为“是”，否则为“否”，与 case sheet 共用同一个轴级匹配函数。按“是”筛选具体问题轴，不将 case 中其他轴的标签传播到该行。未配置、缺失 verdict、未成功完成均为“否”，仅表示未命中。
4. 三列固定存在；空标签或“否”不代表已验证无问题。既有 case → 轴 → 项三级导出、展示分组、原文与引用保持原语义。Excel 使用现有自动筛选：“问题 tags”按包含筛选，“Case 需求达成状态”“是否问题 tag”按精确值筛选。

## 初始项目规则

`llm_probe_loop` 同时关注明确问题和待核验：六个过程轴的 problematic / not_evaluable / untested，真实性的 has_refuted / has_unverifiable，能力兑现的 not_fulfilled / not_evaluable，承载性的做不了 / 做错了 / 说不清，主轴结论的没做成 / 做不了 / 不确定（做成了不加入）。其他项目按各自配置决定，不继承这些名单。

实现入口：`impl/core/axis_display.py`（读与校验）、`impl/server/service.py` 与 `routes.py`（接口）、`impl/frontend/summary.html`（投影）、`case_pool_export.js`（Excel 列）。
