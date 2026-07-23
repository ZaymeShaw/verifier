---
doc_type: api
schema_version: 1
---

# 营销规划 API

- endpoint：`/api/v1/marketing-planning/stream`
- method：`POST`
- 请求：包含会话标识、用户消息和业务上下文；多轮请求复用同一业务会话。
- 响应：SSE 阶段事件、规划卡片内容和终止事件，adapter 将其归一为最终输出与 turn records。
- 错误语义：连接失败、非成功状态、SSE 缺终止事件、事件无法解析或超时均记为 live 执行失败。
