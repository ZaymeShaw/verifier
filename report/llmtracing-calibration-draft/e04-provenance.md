# E04 历史不足：证据来源复核

只读调查；未调用业务/评判模型，未修改 llmtracing、Insurance 或 verifier 实现。

## 已核实

原始文件：`/Users/xiaozijian/WorkSpace/package/llmtracing/llm_gateway/logs/gateways/insurance_4002/llm_calls.jsonl`。

|项目|首轮|次轮|
|---|---|---|
|execution_id|`9f2c168921a0499093ca2ec9e831884c`|`64fa5cb445704b60a8fce50e805f1cff`|
|模型调用数|6|1|
|首个 pre 时间（UTC）|2026-10-01 04:05:18.859326|2026-10-01 04:08:24.978558|
|末次 success 时间（UTC）|2026-10-01 04:08:21.819884|2026-10-01 04:08:28.429585|

共21条事件（每次调用 pre、first_frame、success），均为 explicit 归属。
两轮原始事件具有相同的 `run_id=verifier-8e91b3a35bdb` 和 `case_id=llm-probe-insurance-real-main-E04-carry-second-status-llmtracing`。次轮开始距首轮末次模型成功约3.16秒。这是同一次 case 的连续执行证据，而不只是重放脚本手工配对；仍不能替代业务 session_id 的核验。

次轮 call_id：`b92052d3-d838-4943-b191-99260bee52d7`。

- 原始 `pre_api_call.messages` 恰有两条：system（3069字符）、user（18字符）。
- user 为：`有两张的话，把另一张的状态也查一下。`
- 原始 `client_request.messages` 与上述 `messages` 完全相同，也只有两条。
- 因而历史不足已存在于网关保存的客户端请求，不是 verifier 的 transcript 去重/渲染才丢掉的。

记录实现核对：`llm_gateway/callbacks/trace_callback.py:429–457` 同时保存 proxy 请求 body 与 callback messages；`:130–143` 的 `_safe_client_request` 只递归遮盖凭据字段，没有过滤历史消息逻辑。这里只核对当前代码，未证明其版本等于当时运行版本；两份字段仍来自同一记录系统，并非独立抓包。

## 尚未确定

- 两次业务 HTTP 请求是否携带相同 session_id，调用方是否正确续会话。
- Insurance 是否读取了前轮状态，以及为什么没有把已有历史组装进模型请求。
- 当时运行的业务代码与采集代码版本。
- 是否存在记录前的代理改写；未取得独立出站抓包，不声称形式上完全排除。

现有业务 server.log 在相邻时刻有首轮 workflow 完成/HTTP 200 记录，但本次没有找到能直接按上述 execution_id 连接两轮 session 的记录。不用单纯时间相邻冒充精确归因。

## 校准含义

1. 可以确定：次轮模型请求在网关保存的请求体中缺少前轮历史。
2. 可以排除该解释：verifier 把已有模型消息转换成 transcript 时才删掉历史。
3. 强化但未最终证明：两轮是同 case 的连续执行；尚未证明同一个业务会话被正确传入。
4. 暂不能确定：是 verifier/调用方会话构造问题，还是 Insurance 的会话读取/历史组装问题。
5. 因而 P07 仍是待归因条件项，不直接标成 Insurance fail。
6. 模型面对实际不足的输入澄清，不因上游历史缺失而自动判错。首轮也未取得两张保单，不能期待模型知道“另一张”是哪张。

补证优先级：先找两轮原始业务 request/session_id 与 execution_id 的关联；再按真实 session 追查业务模型输入组装。暂不为了补证启动新业务请求。业务日志可用于人工确立事实，但不能暗中加入 llmtracing-only 判定器的输入范围。
