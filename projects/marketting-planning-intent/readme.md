---
doc_type: api
schema_version: 1
---

# 营销规划意图识别 API

- endpoint：`/api/v1/marketing-planning/intent-recognition`
- method：`POST`
- 请求：单轮用户文本和业务调用所需上下文。
- 响应：意图标签、置信度及可选槽位信息。
- 错误语义：连接失败、非成功状态、未知标签、字段缺失或超时均作为 live 执行失败或不可评价证据。
