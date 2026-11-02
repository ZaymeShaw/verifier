# Judge Boundary

In scope:

- 非流式 HTTP 响应字符串是否兑现能力描述
- 声明了 `response_mode: sse_last_frame` 的伪流式接口：只评最后一个 data 帧（要求该帧是全量内容）
- show_schema 指出的输出片段

Out of scope:

- 增量流式（帧是 delta、需要逐帧累加才能还原内容的接口）
- 未声明 last-frame 模式的 SSE 响应（直接拒绝，不进 judge）
- 下游检索结果集
- 被测服务是否由 verifier 启动
- 各业务项目自己的 EXTRACT 字段协议
