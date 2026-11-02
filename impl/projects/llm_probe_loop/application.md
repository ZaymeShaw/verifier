# Application

llm_probe 评估任意单轮 HTTP JSON 接口里带 LLM 的那一截。默认非流式；接口是伪流式（SSE 但最后一帧是全量内容）时，在 capability 预设或信封里声明 `response_mode: sse_last_frame`，取最后一个 data 帧评。帧是增量、要逐帧累加的真流式不支持。

Case 的 live_request 是 curl 信封：`body` 是被测接口的原生 JSON；`url` / `method` / `headers` 描述怎么发；`capability` 或 `capability_ref` 给出能力口径；`show_schema` 可选，告诉 judge 输出里哪些部分重要；`response_mode` 可选，覆盖 capability 预设的响应模式。

HTTP JSON body 只发 `body`。url 缺省时按 `capability_ref` 去对应项目的 `runtime.services.primary` 拼。`runtime.services.primary` 在本项目里只是模式占位，真正目标由 case 决定。

被测服务由调用方自行启动。verifier 不拉起、不重启这些服务。
