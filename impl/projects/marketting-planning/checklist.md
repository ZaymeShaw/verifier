# marketting-planning checklist

- 项目必须通过统一 `/api/run_chain`、`/api/batch_start`、`/api/batch_status` 跑通。
- 不新增 project-private verifier endpoint。
- 不修改或推送外部 marketing-planning 仓库。
- batch case 默认隔离 session id。
- output/reference 使用同形状 summary/contract，避免逗号拼接丢结构。
- case pool 和 batch compact status 不持久化 raw SSE、完整 card payload 或 judge raw model output。
- clarification 场景不能把规划卡片直接判为正确，除非 boundary 明确允许。
- planning 场景必须暴露 missing/extra path type、wrong card、disallowed fallback 等证据。
- `interaction` 是通用协议 envelope：缺省为 single_run，legacy turns 为 static_turns，只有显式 `interactive_intent` 才进入 adapter interactive hook。
- interactive mock agent 的 `user_intent`、`mock_agent`、`turn_expectations` 和 stop condition 由 adapter 解释，core 不解释 target/path/stage 等项目字段。
- interactive result 必须保持一个 intent case 一条 run，使用 compact `conversation_summary`/`turn_traces`，不能把每轮 raw payload 写入前端持久化。
- check report 必须记录机制证据、过拟合风险、前端持久化和 live UAT 限制。
