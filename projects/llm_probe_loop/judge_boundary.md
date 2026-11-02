---
doc_type: judge_boundary
schema_version: 1
---

# Judge Boundary - llm_probe

- 可评价范围：被测非流式接口返回的 `output_text` 是否兑现了本 case 的能力描述。若 case 带了 show_schema，judge 只把其中指出的部分当作重要证据，其余当作背景。
- 不可评价范围：流式协议、下游检索结果集、被测服务进程是否由 verifier 拉起、各业务项目自己的 EXTRACT 字段协议。
- 外部依赖责任：被测 HTTP 服务由 case 的 url 或 capability_ref 指向；连接失败、超时、非 2xx、SSE 响应都记为 live 失败，不能写成能力未兑现。
