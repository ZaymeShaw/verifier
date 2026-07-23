---
doc_type: api
schema_version: 1
---

# DeerFlow Gateway API

- endpoint：`/api/threads` 及同一 Gateway 下的 thread 消息接口。
- method：创建 thread 和投递消息使用 `POST`，读取历史按业务 Gateway 协议使用对应读取方法。
- 请求：创建独立 thread 后逐轮发送用户消息；多轮请求必须复用同一 thread 标识。
- 响应：从 thread 历史提取 AI 回复、tool calls 和阶段事件，归一为 verifier 的 turn records。
- 错误语义：连接失败、非成功 HTTP 状态、thread 不存在或历史不可解析均作为 live 外部依赖失败记录。

旧的网页登录账号、密码和个人浏览器路径不属于 verifier 接入合同，不得写入知识路由；若未来重新启用网页登录，必须先在所属工具配置中登记凭据变量。
