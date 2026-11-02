# 平台缺口的更深获取渠道（2026-09-27 调查，只读）

调查对象：`insurance-qa-agent`（主 checkout，端口 18062，verifier 目前调用它）、`insurance-qa-agent-eval`（`eval/current` 分支，端口 18063）、本机模型网关 `mock_system/llm_gateway`（端口 4002）。
**没有修改任何被测系统或网关文件。**

## 结论速览

| 缺口 | 被测系统配置能否直接打开 | 更深的渠道 | 当前能否用于 9/26 这批 |
|---|---|---|---|
| 原始模型请求（`exact_model_request`） | **不能**：`app/main.py:153-154` 无条件写死 `OPENINFERENCE_HIDE_INPUTS/OUTPUTS=true`，环境变量也会被覆盖 | **模型网关 :4002 已逐次记录完整请求**（messages、tools、参数）与响应 | 不能：网关日志从 9/27 04:55 UTC 才有，9/26 的记录已不在 |
| 逐次状态变化（`state_transitions`） | 无对应配置 | **业务服务结构化日志**按 run_id 记录缓存复用、拒绝、预算、降级等事件 | **能**：`~/.insurance-qa-agent-real/server.log` 覆盖 9/26 整批 |
| 后端原始报文（`raw_backend_http`） | 无日志开关（`app/tools/real/auth.py` 主动屏蔽 HTTP 日志；httpx `trust_env=False`，设代理环境变量无效） | 后端地址写在工具配置 YAML，可指向一个本地录制反向代理 | 不能，需要以后运行时改配置 |

## 1. 原始模型请求：走模型网关

- 两个 insurance checkout 的 `app/conf/models/models_dev_args.yaml` 都把 `base_url` 指向 `http://127.0.0.1:4002/v1`，即本机 LiteLLM 网关（进程 4056，配置 `config.litellm.insurance.yaml`）。
- 网关回调写入 `mock_system/llm_gateway/logs/llm_calls.jsonl`。每次调用都有：
  - `pre_api_call`：完整 `messages`、`tools`、`optional_params`；
  - `success` 或 `failure`：`response`、`usage`、`latency_ms`。
- 这正是 Agno span 被脱敏的那部分：**模型实际收到的完整请求，包括工具定义**。
- **关联方式**：
  - eval 分支（18063）实现了 `IQA_EVAL_HEADER_PASSTHROUGH`，把入站请求头 `X-Eval-Case-Id`、`X-Eval-Execution-Id` 透传到模型请求，网关据此记录 `case_id`、`execution_id`。
  - `mock_system/eval_harness` 的 insurance adapter 已经这样发请求头（`adapters/insurance.py:314-330`），并有 `llm_gateway_ingest.py` 按 case 取回网关记录，可以直接参考。
  - verifier 目前调用的是 18062（主 checkout，**没有透传**），自己也不发这两个头。
- 9/26 那批走的也是网关，但日志文件从 9/27 04:55 才开始（文件是追加写，更早的内容被移走或清空了），找不回来。

**要打通（不改被测系统代码）**：
1. 评测时改用 eval 分支服务（18063），或给主 checkout 同样开启透传。这由你决定，因为涉及被测系统部署。
2. verifier 的 live 请求带上两个 `X-Eval-*` 头，并把网关记录并入案卷，作为模型调用的原始输入。这部分我可以在 verifier 里做。
3. 网关日志要保留到判完（目前单文件已有 1.27GB）。

## 2. 逐次状态：业务服务日志

`~/.insurance-qa-agent-real/server.log`（18062，9/26 13:19 UTC 起）每行都带 `trace=`、`run=`，能和案卷里的 run 对上。9/26 这批相关事件计数：

| 事件 | 次数 | 能补什么 |
|---|---:|---|
| `agent_tool_deduplicated`（`category: cache`） | 13 | **缓存或去重复用**：v3 所说"失败结果被当缓存复用"的直接证据（F5） |
| `agent_tool_refused` / `model_budget_refused` / `capacity_refused` | 5 / 9 / 3 | 系统策略拒绝（判例 1，规划轴） |
| `model_fallback_active` / `model_generation_failed` | 11 / 10 | **被测系统自己的模型降级**：同一轮里换了模型，模型轴必须知道 |
| `tool_backend_call` | 166 | 每次后端调用的 system、endpoint、attempts、status、latency |
| `tool_call_diagnostic` | 181 | HTTP 状态、超时设置、失败阶段与原因（如 3s 超时被取消） |
| `gate_decision` / `node_started` / `node_completed` | 71 / 500 / 500 | 路由决策与每一步的耗时 |

另有 `var/turn-audit.jsonl`，记录路由、信封拦截原因和策略版本。但桥接层把答复换成套话的规则（E02）不在拦截记录里，这份帮助有限。

## 3. 后端原始报文：录制代理

- 后端地址全部在 `app/conf/tool/tool_config_dev_args.yaml`，都是 http 明文，其中包括三个**解析服务**：`client_search_query_parse`、`policy-search-parse`、`product_query_parse`。
- 把这些 URL 改成指向本地录制反向代理，代理原样转发并落盘，就能拿到请求和响应原文。
- 这正好补上"工具内部解析模型出错看不见"的盲区（B17 解析时丢了人名、D01 姓氏前缀条件被拒）。
- 这是**配置改动**，由你在评测环境操作。代理可以参照网关的做法放在 `mock_system`。

## 建议顺序

1. **先接业务日志**：零改动，9/26 这批也能直接补上，覆盖缓存、拒绝、降级、后端调用元数据。
2. **再接模型网关**：需要你决定用 eval 分支服务，我在 verifier 侧发请求头、并入记录。
3. **后端录制代理**：收益集中在工具轴的解析问题，放在最后。
