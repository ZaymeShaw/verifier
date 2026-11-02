---
doc_type: requirements
schema_version: 1
---

# llm_probe 测评需求

- 业务目标：把任意非流式 HTTP JSON 接口当成带 LLM 的能力片段来评。Case 给出 curl 形状的请求（url/header/json body）以及对该能力的描述；输出统一收成字符串，再交给 judge。
- 范围：单轮、非流式 POST/PUT/PATCH；capability 预设（能力口径 + 探测端点）自包含登记在本项目 capability_map 内，与其他项目注册表完全解耦，不复制它们的 adapter。
- 非目标：不评流式/SSE；不把各业务项目的字段协议写进本项目 live_schema；不做归因优化；不替被测服务生成 gold output。
- 核心场景按被探测能力分桶：client_search、policy_search、marketting-planning-intent。一条 case 就是一次探针调用。
