# 合并工作区端到端实测（2026-10-18）

环境：`verifier-integrate`（分支 integrate/langfuse-notrace，9e25fdaa），verifier 服务 8031（实例数据由仓库 impl/data 播种，另加三个临时预设
verify-insurance-langfuse / -agno / -mcp，均指向 18066）；Insurance 验证实例 18066（评测工作树 0f6798c6，Langfuse + Agno 同时上报，模型走 4202 网关）；
Langfuse 3.184.1 本地实例 3300；ES 本地 9200。全部经服务 API 调用（与前端相同路径）。

| 项 | 结果 | 耗时 / 调用 |
|---|---|---|
| 服务与前端 | 通过：页面 200，扩展轴含 knowledge_evidence，provider 含 langfuse | — |
| ES 知识查证在线（DashScope 业务） | 未测成：业务持续 HTTP 429（Throttling.RateQuota）；评测对 429 判 not_evaluable 并写明原因 | — |
| MCP 知识查证（insurance-tools） | 2/2 判对：伏云平保单两条投保日期 verified → fulfilled；客户号→何承琪 verified、其余 4 项 unverifiable → fulfilled（核心已核） | 评测 63s / 104s；LLM 6 / 11 次，MCP 3 / 2 次 |
| Agno trace（run_chain） | 伏云平：fulfilled；客户号：业务这次答"未命中" → not_fulfilled | 总 247s / 312s，其中 judge 242s / 291s |
| Langfuse trace（run_chain） | 客户号：业务答出何承琪 → fulfilled；伏云平：not_evaluable（Langfuse 内容脱敏、direct 路线无模型调用，归属证据缺） | 总 297s / 277s，其中 judge 279s / 267s |

## 看到的
- Langfuse 采集在线可用：主轴引用到 `observation/16`（backend.customer.search）的入参与返回。
- Langfuse 证据比 Agno 少时结论降级为 not_evaluable（伏云平那条），符合"缺证不能通过"。
- 业务本身不稳定：同一问题"客户号 C92200000884 对应谁"，一次答出何承琪、一次答"未命中"（该客户存在，见历史详情数据）。
- 客户号那条 langfuse 判 fulfilled 时，主轴再次推翻 knowledge_data 的"无法评估"，依据是搜索入参与返回——与此前查明的"未核实就断言"问题同类（未修）。
- 既有坑：`/api/live_run` 对外返回会去掉 project_fields（occam PUBLIC_DROP_KEYS），Live 页分两步"请求业务服务→请求 Judge"时主判拿不到业务 trace，一律判采集失败；trace 场景须用"统一全链路"。三个工作区同样，非合并引入。
- 新实例数据目录为空：换端口启动需先播种预设与知识源登记。
