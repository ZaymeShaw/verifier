# marketting-planning application

本项目适配 `/api/v1/marketing-planning/stream` 作为主评估路径。拆分接口只能作为局部验证线索，不作为 verifier 的另一条 orchestration 路径。

## 输入协议

适配器接受以下项目字段：

- `user_intent`：本 case 的业务意图描述。
- `query`：单轮输入。
- `turns`：多轮输入，按数组顺序执行；每轮可包含 `role`、`content`、`output`。
- `scenario`：评估场景，如 clarification、execution_planning、streaming_protocol。
- `expected_stage`、`expected_path_types`、`expected_cards`：参考契约字段。
- `boundary`：当前 case 的外部依赖、数据可用性、fallback 允许范围。
- `output`、`raw_response`、`response`：已提供业务输出时直接作为被评估输出。
- `reference`：已提供参考契约时作为 judge expected。

## 执行边界

v1 优先支持 mock/provided-output。未启动外部业务服务时，adapter 记录 unavailable 边界，不修改或推送 `/Users/xiaozijian/WorkSpace/package/marketing-planning`。

每个 batch case 默认生成隔离 session id。只有 case 显式声明 `shared_session: true` 时，才保留输入中的 session id 进行共享会话测试。
