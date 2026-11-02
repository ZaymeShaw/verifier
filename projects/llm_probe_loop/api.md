---
doc_type: api
schema_version: 1
---

# llm_probe API

本项目没有自己的业务 endpoint。每条 case 自带 curl 信封，live 按信封发非流式 HTTP。

- endpoint：case.`url`；缺省时用 `capability_ref` 对应项目的 `runtime.services.primary`
- method：case.`method`，默认 POST
- 请求：JSON body 是 case.`body`（被测接口的原生请求体）。信封上的 url/method/headers/capability/show_schema 不进 HTTP JSON。
- 响应：HTTP body 原样收成 `output_text` 字符串。能 parse 成 JSON 也仍以字符串为 EXTRACT 形状。
- 错误语义：连不上或超时是服务不可用；HTTP 4xx/5xx 是 live 失败，不伪装成语义错误。`Content-Type: text/event-stream` 直接拒绝。
