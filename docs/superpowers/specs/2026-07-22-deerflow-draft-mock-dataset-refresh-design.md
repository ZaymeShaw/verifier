# DeerFlow Draft Mock 固化数据重建设计

## 目标

使用 DeerFlow 当前启用的最新 Draft Mock 实现重新生成 6 条固化 MockCase，完整替换 `impl/data/deerflow/mock_cases.json`。前端“加载 Mock 数据集”仍只读取固化数据的前 3 条，不在点击时动态调用 LLM。

## 生成方式

- 使用项目配置加载 `DeerflowMockDraft`，固定请求 `open_world_user` 场景。
- 独立生成 6 条，每条只调用一次 LLM；总计 6 次，不并发触发。
- 不使用旧固化样本作为生成提示，也不机械改写一条样本制造变体。
- 允许用户画像、知识程度、表达习惯和业务状态自然变化；生成内容必须是具体、真实的 DeerFlow 业务诉求。
- 不混入天气、翻译、列车、页面转圈、提交失败等产品支持或范围外负向用例。

## 验证与写入

候选数据先写到临时位置。写入正式文件前必须同时满足：

1. 6 条均通过 DeerFlow REQUEST_SCHEMA 校验；
2. 6 条均通过 Draft Mock 业务输入 validator；
3. query 非空且彼此不重复；
4. intent 与 live request 中的用户消息一致；
5. 不包含旧的产品支持或范围外负向场景。

任何一条失败都不覆盖正式文件。全部通过后，使用既有 `save_mock_cases` 存储格式一次性替换完整文件；不改 Mock、Live 或前端协议。

## 验收

- 重新读取固化文件，确认恰好 6 条且可被 `persisted_mock_datasets` 加载。
- 确认前端请求仍为 `count:3`，返回新文件中的前 3 条。
- 运行 DeerFlow Mock 数据相关聚焦测试。
- 输出 6 条最终 query、场景和校验结果，便于人工复查。

## 回滚

正式数据文件是 Git 跟踪文件；若新数据不合适，仅回退本次数据文件改动，不回退用户的其他工作区修改。
