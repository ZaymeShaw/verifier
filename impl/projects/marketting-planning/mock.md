# marketting-planning mock

mock agent 不只生成固定单轮查询，还要围绕单一 `user_intent` 构建输入、turns、expected stage、path types 和 reference contract。

v1 mock cases 覆盖：

- intent recognition：识别营销规划意图。
- clarification：缺字段时应澄清而不是生成规划卡片。
- multi-turn field accumulation：多轮补齐字段后进入规划。
- execution planning：按 path_types 生成规划卡片。
- fallback/data unavailable：外部数据不可用时的允许或禁止 fallback。
- non-agent intent：非本 agent 意图应拒绝或转出。
- streaming protocol：SSE event 顺序和 completion 状态可被摘要验证。
- interactive intent：通过通用 `interaction.mode = interactive_intent` envelope 声明一个原始用户意图，由 adapter 根据每轮 compact feedback 生成下一轮用户输入。

interactive case contract：

- `interaction.mode` 是 core 唯一识别的交互模式字段；`turn_expectations`、`stop_when` 和业务事实由 adapter 解释。
- `user_intent` 保存 goal、target value、path type intent 等模拟用户事实，不能只把路径选择写进 reference。
- `mock_agent.driver = adapter` 表示下一轮输入由项目 adapter 基于当前 case 事实和前序 turn feedback 生成。
- 结果保持一个 source case id 对应一个 batch run，并只暴露 `conversation_summary` 与 compact `turn_traces`。

所有 batch mock case 默认隔离 session id，避免状态污染。
