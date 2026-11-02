# llm_probe 业务 Trace：llmtracing provider 方案

ToolLoop 实例化的职责边界、核心完成 hook 与框架作者确认事项，见
[llmtracing 的 ToolLoop 实例化方案](llmtracing-toolloop-instance.md)。下文保留各实施阶段记录。

## 1. 目标与边界

为 llm_probe 新增 `llmtracing` 业务 Trace provider：每次被测业务请求，取回它触发的全部模型调用
（实际发出的请求上下文、tools、参数、响应、usage、耗时），作为过程证据进入 dossier。

- 与 `agno` provider 相互独立，场景二选一；不做合并。
- 只覆盖经过 llmtracing 中转的模型协议流量。业务内部步骤、未进入模型上下文的工具执行、session/memory
  不可见；其余信息由评测模型从上下文反推。reader 必须把这条边界写成 limitation。
- 不改 Insurance、不改 llmtracing 代码（方式 A）。llmtracing 的接口优化见
  https://github.com/ZaymeShaw/llmtracing/issues/1 ，本方案不依赖它。

## 2. 关联方式

中转在进程外，只能看到业务发出的模型请求。被测系统不携带标记时，外部无法把模型调用可靠对应到某次业务
请求；Langfuse、Helicone 等进程外方案同样如此。时间窗、正文相似度只作审计，不作归属。

### A. 显式请求头透传（本期实现）

verifier 每次业务投递生成 ID，经请求头传给被测系统，被测系统透传到内部模型请求，中转按显式头归属：

| 头 | 值 | 说明 |
|---|---|---|
| `X-Eval-Run-Id` | verifier 本次运行 ID | 区分批次；与 eval_harness 的 run 天然不同 |
| `X-Eval-Case-Id` | verifier case_id（规范化为 `[A-Za-z0-9._:-]{1,128}`） | llmtracing 规则：case + execution 同时存在才判为显式归属；verifier 切片本身只用 execution_id |
| `X-Eval-Execution-Id` | 每次投递一个 uuid4 hex | 多轮 case 每轮独立，按轮精确切片 |

- 并发安全：切片只按 `execution_id`，不依赖时间或 lane。
- 与 eval_harness 共用 4002 网关、Insurance 工作树不冲突：两边都带显式头，各自的 run/execution 不同。
- 前提：被测系统支持透传。Insurance 评测工作树（`eval/current`，`IQA_EVAL_HEADER_PASSTHROUGH=1`）已支持，
  `scripts/insurance_backend.sh` 已切换并在启动时校验。
- 风险：被测系统某次模型调用未继承请求上下文时不带头，落为未归属；verifier 看不到它，只能以 limitation 声明
  "未归属调用不可见"，不得声称已采全。

### B. W3C `traceparent`/`baggage`（扩展选项）

A 的标准化版本：业务入口 HTTP 服务端与出口 HTTP 客户端都接了 OpenTelemetry 自动插桩时，无需改业务逻辑即可传递。
是否可用取决于业务：未接插桩的业务仍需加依赖、改启动配置。Insurance 目前只有 `AgnoInstrumentor`，不适用，用 A。

- `traceparent` 只带 trace-id/span-id。verifier 自己生成 trace-id 并记入 association，
  trace-id 即充当 execution_id；case_id/run_id 是 verifier 的本地簿记，无需经业务传递。
- 需要在中转日志里直接看到 case/run 时，另发 `baggage: eval.run_id=...,eval.case_id=...`；OTel 默认传播器会一并带下去。
- 前提：业务入口与模型出口的 HTTP 都被插桩且在同一上下文；后台任务新开 trace 时会断链，按未归属处理。
- 依赖 llmtracing 读取 trace-id 并写入日志（issue #1 第 3 点）。verifier 侧只是 `prepare` 多生成一组头，provider 结构不变。

### C. 独占实例池（扩展选项，被测系统不改代码）

- 被测系统起 N 个实例，各自模型 base_url 指向中转的不同入口；中转按入口打 `lane_id`。
- verifier 每 lane 加锁串行，并发数 = 实例数；切片为 `lane_id` + [请求开始, 响应结束 + 排空]，
  排空以该 lane 在途调用归零为必要条件；超时 lane 标记 blocked，不再派发。
- 被测系统要求：实例间会话/缓存/数据库不冲突；响应返回后不再发起模型调用。
- 依赖 llmtracing 提供按入口识别 lane、查询接口、在途计数（issue #1 第 1、2、4 点）。

## 3. verifier 改动

分六期，每期可单独验收，前一期不依赖后一期。第 6 期已将 llmtracing 六轴接入 ToolLoop，
替代第 5 期的一次性评判执行；第 5 期把 llmtracing 的评测从案卷路线换成对话稿路线，
第 3 期的 `llmtracing_reader.py` 与第 1 期的 `reader_files()` 已随之删除。

### 第 1 期：Agno 专有逻辑挪回 Agno reader（纯重构，输出不变）

现有通用层里的 Agno 假设：

| 位置 | 现状 | 改为 |
|---|---|---|
| `business_trace/reader.py` `_KIND_NOTES` | 各 KIND 说明按 Agno 语义写（LLM span、reconstructed_input、Agno checkpoints 等） | 基类只保留中性说明；`TraceReader` 增加类属性 `kind_notes`，`AgnoReader` 覆盖为现有文案 |
| `reader.py` `invocation_summary()` | 硬编码 `span/sqlite_span/api` 表示名做配对统计 | 基类只按 kind + 字段状态计数；span/api 配对统计挪到 `AgnoReader.invocation_summary()` |
| `reader.py` `timeline()` | 只收 `representation in {api, span, sqlite_span}` 的条目 | 基类收所有带时间戳的 runs/steps/messages/tool_calls/model_calls；Agno 过滤挪到 `AgnoReader` |
| `reader.py` `mark_copies(canonical="api")` | 默认值是 Agno 表示名 | 保留为通用方法，去掉默认值，`AgnoReader` 显式传 `"api"` |
| `dossier.py:866-876` | 从 `snapshot.records.run.content` 取 final_output | reader 增加 `final_output_ref() -> str | None`，基类返回 None；`AgnoReader` 返回 `/records/run/content` |
| `dossier.py` model_calls 的 `input_limit` 文案 | 写死 "持久化消息重建 / llm.tools.* span 属性" | reader 增加 `model_call_note(entry) -> str`；Agno 文案挪进 `AgnoReader` |
| `eval_axes/adapters/trace_analysis.py:394` | `implementation_files` 写死 `agno_reader.py` | 由 `business_trace` 注册表导出各 provider reader 文件列表拼接 |

验收：现有 `tests/test_business_trace_reader.py` 等测试通过；取 `report/business-trace-agno-20260913/snapshots/*.json`
在重构前后各跑一遍 `build_dossier`，输出逐字节一致（中性化的 `meaning` 文案除外，Agno 覆盖后应一致）。

已实施：基类另有类属性 `reading`、`timeline_kinds`、`timeline_note`、`invocation_note`，`LlmtracingReader`
只用类属性和 `model_call_note`，不再覆盖 `overview/timeline/invocation_summary`。注册表导出 `reader_files()`
（约定 `providers/<name>_reader.py`）。5 个 Agno 快照的 overview/invocation_summary/timeline/dossier/links/catalog
重构前后逐字节一致；llmtracing 快照只有 `input_limit` 由误用的 Agno 文案改为中转语义。
`links.py` 的环节枚举和 `LIMITS` 文案同样按 Agno 结构写，不在本期表内，llmtracing 案卷下实测产出 μ/κ/χ 三类环节。

### 第 2 期：provider 接口增加请求前阶段

- provider 模块新增可选函数 `prepare(config, *, case_id, run_id) -> {"headers": {...}, "association": {...}}`。
  未实现（如 agno）视为无操作，`collect` 也不传 `association`。
- `business_trace/__init__.py` 增加 `prepare(value, *, case_id, run_id)` 分发。
- `live.py`（已实施）：
  - `deliver_real` 在 `resolve_http` 之后按 `capability_ref` 取场景 `business_trace` 调 `prepare`，
    把返回的 headers 合入本次请求头（大小写不敏感覆盖场景配置的同名头，避免场景写死 ID 导致串案）。
  - case_id 来源：`LlmProbeLive._execute_via_session` 把 `ctx.case_id` 放进 ContextVar（live 实例跨 case
    共享且不持有 ctx），`deliver_real` 读取；不改 core。run_id 暂用进程级 `verifier-<hex12>`。
  - association 写入 `request["business_trace_association"]`，每次投递先清再写；该字段已声明在
    `LlmProbeRequest`，多轮沿用首轮信封时可通过 REQUEST_SCHEMA 校验并被下一次投递覆盖。
    `project_fields` 取出传给 `collect(value, request=..., response=..., association=...)`。已确认 `core/session.py` `send_request`
    把同一个 request dict 先交给 `deliver_turn`，再包进 `LiveRequest.normalized_request` 调 `project_fields`，
    `deliver_real` 的写入可见（现有 url/method 回写即依赖此行为）。
  - `collect` 签名增加 `association` 关键字参数，仅对实现了 `prepare` 的 provider 传入。
- 验收：agno 场景行为不变；新增单测覆盖 prepare 头合并、优先级、association 传递。

### 第 3 期：llmtracing provider 与 reader

新文件：`business_trace/providers/llmtracing.py`、`business_trace/providers/llmtracing_reader.py`。

**配置**（`validate_config`）

```json
{
  "provider": "llmtracing",
  "config": {
    "log_path": "/Users/xiaozijian/WorkSpace/package/llmtracing/llm_gateway/logs/gateways/insurance_4002/llm_calls.jsonl",
    "settle_timeout_seconds": 30,
    "poll_interval_seconds": 1,
    "quiet_seconds": 3
  }
}
```

- `log_path` 必须显式给出，不从 `.env.*` 推断（不同 profile 的 `LLM_GATEWAY_LOG_DIR` 不同）。
- 不暴露关联方式开关；本期只有方式 A，B/C 落地时再加字段。

**check_connection**：`log_path` 存在且可读；返回文件大小与最后修改时间。不发业务请求。

**prepare**：生成 `execution_id`；读 case_id / run_id 并规范化。case_id 取 verifier 的 case id
（`TraceContext.case_id`，需随请求传入 live 层）；run_id 取 verifier 本次批量运行 ID，live 层目前拿不到，
需从运行入口向下传，实施时定位具体入口；记录 `log_offset = 文件当前大小`；
返回三个 `X-Eval-*` 头和 association `{method: "explicit_headers", run_id, case_id, execution_id, log_path, log_offset}`。

**collect**（业务响应返回后）：

1. 从 `log_offset` 读增量，按 `call_id` 合并 `pre_api_call` / `first_frame` / `success` / `failure`，
   只保留 `execution_id` 匹配的调用。若匹配调用的 `case_id` 与 association 不一致，记 error。
2. 轮询至满足：所有匹配调用都有 `success` 或 `failure`，且连续 `quiet_seconds` 无新的匹配 `pre_api_call`；
   或到达 `settle_timeout_seconds`。
3. 状态：全部完结 → `complete`；超时仍有未完结 → `partial`（列出 call_id）；零调用 → `no_calls`
   （可能是业务未调模型，也可能透传失效，limitation 写明两种可能）；文件不可读/被截断 → `failed`。
4. 快照：`records.calls` 保存每次调用的原生事件（不改写），`association` 附 `log_offset_end`，
   `limitations` 至少包含：只见中转流量；未带头调用不可见；响应返回后的后台调用可能漏采；
   `client_request` 是中转收到的请求，经 thinking 策略与 `drop_params` 后上游实际请求可能不同。

合并逻辑按 llmtracing 的事件级 JSONL 格式自行实现（约百行），不 import `eval_harness`：避免 verifier 依赖
另一仓库的内部模块和它的 Python 环境。事件格式以 `llm_gateway/callbacks/trace_callback.py` 为准，用真实日志
抽样做 fixture 锁定。llmtracing 提供查询接口后，只替换读取层，reader 不变。

**reader 映射**（`LlmtracingReader(TraceReader)`）

| KIND | 来源 | 说明 |
|---|---|---|
| `model_calls` | 每个 call：`client_request`、`messages`、`tools`、`optional_params`、`response`、`usage`、`latency_ms`、首帧 | `exact_request` 标 available，note 写明是中转收到的请求 |
| `messages` | 每个 call 的 `messages[i]` 按 ref 引用，不复制 | 后一次调用的 messages 通常包含前一次，reader 标注 `call_ref` 与序号，不去重计数 |
| `tool_calls` | assistant 响应中的 `tool_calls`，按 `tool_call_id` 与后续调用中的 tool 结果消息配对 | 只证明模型发起了调用、上下文里出现了结果；不证明业务执行细节 |
| 其余 KINDS | — | `not_recorded`，`kind_notes` 写明 llmtracing 不提供 |

- 协议：本期完整解析 OpenAI Chat Completions；Responses、Anthropic Messages 只做 `model_calls` 原文，
  `tool_calls` 标 limitation。实际被测系统出现后再补。
- `final_output_ref()` 返回 None：最终回答以 verifier 捕获的业务响应为准（dossier 已有 `delivered_output`）。
- `timeline()` 按 `pre_api_call.ts` 排序。

**注册**：`_PROVIDERS["llmtracing"] = llmtracing`。前端 provider 列表动态加载，无需改动。

**测试**（`tests/test_business_trace_llmtracing.py`）：用小型 JSONL fixture 覆盖事件合并、execution 过滤、
offset 起读、partial/no_calls/failed、failure 事件、case_id 冲突、tool_call 配对、reader overview 与 read 分页、
快照脱敏（`Authorization`、`api_key` 等）。

### 第 4 期：场景与端到端验证

场景指 `capability_map.json` 的一个条目（case 通过 `capability_ref` 引用），打包 service、axes、boundary、
mock_body、business_trace；一个场景只能有一个 business_trace provider。

- 新建场景 `insurance-llmtracing`，保留 `insurance-agno-e2e` 不动，两个 provider 可对比：
  - `capability_map.json`：复制 `insurance-agno-e2e` 条目，替换 `business_trace` 为 llmtracing 配置；
    `boundary` 中描述 Agno 持久化证据的一句改为 llmtracing 证据范围，其余字段一致（已实施）；
  - `project.yaml`：两处场景登记（`mock_cases.default_scenarios`、`scenarios.allowed`）加入新场景；
  - `mock_cases.json`：复制引用旧场景的 32 个 case（24 单轮、8 多轮），`id` 加后缀 `-llmtracing`，
    `scenario`、`live_request.capability_ref`、`seed.turns[*].request.capability_ref` 改为新场景（共 84 处）。
    用一次性脚本生成并校验数量，脚本不入库。
  - 两份 case 后续需同步维护；除场景引用和 id 外内容应一致，可加一条测试校验这一点。
- 端到端：`scripts/insurance_backend.sh start` 后跑 1 个单轮、1 个多轮 case，核对：
  - 快照调用数等于网关日志中该 execution_id 的 `pre_api_call` 数，全部有结束事件；
  - 多轮各轮 execution_id 不同，互不包含；
  - dossier 中 model_calls 的 messages 包含本 case 原题；
  - 同时段 eval_harness 的调用不出现在 verifier 快照中。
- 端到端会经网关调用上游模型，执行前需用户授权。
- 已执行（2026-10-01）：
  - 18062 的模型 base_url 是 4002（`insurance_4002` 命名 gateway，日志在 `logs/gateways/insurance_4002/`），
    该 gateway 同时是 eval_harness 18063 的 lane；显式头优先于 lane，归属为 `explicit`。
  - 单轮 `smoke-customer-profile-fuyunping`：快照 3 次调用 = 日志 pre/结束 3/3，工具 2/2 配对，命中原题。
  - 多轮 `E04`：两轮 execution_id 不同，快照 6/1 与日志一致，只含本 case_id；第 2 轮末次响应带工具调用后
    业务未再调模型，工具 1 个 unpaired，符合 `tool_call_parsing` 限制说明。
  - `smoke-policy-list-fuyunping`：业务下游 policy_svc 连续 75s 超时，请求超过 240s，verifier 走异常路径，
    `project_fields` 未执行，快照缺失（agno 同样如此，属 session 层“失败投递不采集过程证据”）。
    离线对同一 execution_id 跑 collect，8 次调用 7 个工具全部配对，日志侧证据完整。
- 第 1 期重构后评判验证（2026-10-01）：
  - 冻结重放（`scripts/_replay_llmtracing_judge_tmp.py`，结果在 `report/business-trace-llmtracing-judge-20261001/`）：
    3 个 llmtracing 执行 + 2 个 Agno 冻结快照，全部 7 个轴完成；llmtracing 下编排/数据轴在业务内部
    步骤不可见时判证据不足，理由引用网关层证据边界。
  - 全链 `batch-run`（`report/business-trace-llmtracing-e2e-20261001/`）：customer-profile 两个场景并发，
    live → 过程评估 → judge 全部完成，两份快照分属各自 provider，网关上 Agno 场景的调用为 `idle` 未归属，
    llmtracing 场景的调用为 `explicit`，互不混入。

### 第 5 期：llmtracing 走对话稿评测，不经案卷/环节表

动机：同执行 A/B 里 llmtracing 的意图/编排轴判 not_applicable/缺证，原因不是数据缺失，而是 `links.py`
只在有 Agno `runs` 时生成 ι/ρ/σ 环节，没有环节时 `process_common` 强制兜底。llmtracing 只有模型协议流量，
整次执行可确定性还原成一份线性对话稿，且装得进单次上下文（实测 4 次执行 39K–48K 字），
模型的理解、选工具、顺序、失败处理都直接写在对话稿里，不需要先切环节。

- `business_trace/providers/llmtracing_transcript.py`：快照 → 按位置编号的对话稿（`t{n}.request/final`、
  `t{n}.c{k}`、`.system/.tools`、`.m{j}`、`.response`、`t{n}.gap.*`）。后一次调用只列新增消息；
  系统提示词、工具定义、参数与前次相同只写"同 xx"；前次消息未出现在本次请求里时 call 条目写明
  （压缩/改写/丢失由评测按语义判）。超 100K 时把最长条目截到同一上限，编号不丢。
- `eval_axes/adapters/transcript_axes.py`：
  - 分析步 `run_analysis`：只重建对话稿，不调模型；输出键与案卷路线一致（structure/selections 为空）。
  - 过程轴 `run_axis`：整稿 + 轴定义（问题、排除、义务）一次给评测模型，模型自己定位义务出现的位置，
    `link_id` 是对话稿位置，情形未出现写 `transcript`。校验：每条义务至少一组、位置合法、不重复；
    二次仍不合规时只修结构，未回答的义务记缺证。不给取证工具（全文已在上下文）。
  - 复用 `process_common` 的义务、`annotate`、`_outcome`/`aggregate_verdict`，结果形状与 Agno 一致。
    `applies_to` 与 `program` 在对话稿路线不用：没有结构化环节事实，适用与否由模型按 situation 判。
- 挂点（共 3 处，各一个分支）：`trace_analysis.run` 按快照 provider 分派；`run_process_axis` 遇对话稿分派；
  `judge._main_judge_material` 遇对话稿直接给全文（≤80K）。type_id 不变，前端/主轴/归因不区分 provider。
- 删除：`llmtracing_reader.py`、`llmtracing.open_reader`、`business_trace.reader_files()`；`coverage` 改为
  `{calls, limitations}`，`limitations()` 归 provider 模块。第 1 期的 reader 中性化保留（Agno 路线仍用）。
- 验收：全量测试除既有 11 个失败外通过；Agno 路线代码路径不变；4 次既有执行 + A/B 的 llmtracing 侧重放。
- 已实施（2026-10-01）：全量 1547 passed，失败仍是既有 11 个。只评判重放 6 次（`scripts/_transcript_judge_tmp.py`，
  `report/business-trace-llmtracing-transcript-20261001/`），每轴 1 次模型调用，整案 5–12 分钟（案卷路线 15–17 分钟）：
  - 意图/编排全部给出实质结论，A/B 同一执行由"意图 not_applicable、编排缺证"变为两轴 sound，理由引用具体调用位置；
  - policy-list：编排判 problematic（policy_search 超时后反复改写重调已失败来源）；
  - E04：第 2 轮首次调用没有第 1 轮历史，κ/ρ 均检出；
  - 与 Agno 的差别符合可见性：Agno 能看到 `agent_bridge` 未抽取 JSON 代码块，llmtracing 看不到这一步，
    但同一污染仍由模型轴与主轴从 `t1.final` 检出。
  - 修正两处：客户端附带的 `metrics/raw_model_response` 在校验前去掉（否则每轴首轮必被判格式错）；
    提示词写明 `t{n}.final` 就是调用方实收响应（否则交付义务判缺证）。

### 第 6 期：llmtracing 作为 ToolLoop 的隔离实践（本地验证通过，未做真实模型验收）

- 入口仍是 `eval_axes.build_report`；仅 llmtracing 快照（全缺时按场景声明）进入新 adapter，
  Agno 与无 trace 场景继续原来的 runner。公共 ToolLoop、模型客户端、session、judge 主流程未修改。
- `process_loop/llmtracing.py`：一个 case 的六轴共用一个 ToolLoop，自主调用只读取证工具，
  用六个 `eval_*` 工具提交；失败返回具体原因，`RequireDone` 在未交全时反馈继续。
  明确缺证可提交；预算耗尽整次过程评判失败，不 salvage、不自动回退旧路线。
- `business_trace/providers/llmtracing_evidence.py`：`evidence_read` 分页读取，`call_inputs` 查询实际输入成员。
  读到别名/目录不算读到原文；同批读取与提交不当作先读后引。提交检查引用回执、μ输入归属、
  工具请求与原始产出的角色混淆、真实交付来源；这些只检查可确定关系，不声称验证所有自然语言推理。
- `llmtracing_transcript.py` 保留精确前缀继承及响应重放的输入引用，system/tools 变更后旧规则不自动继承；
  final 按是否有原始响应区分 `http_response` 与 `unverified_extracted_output`。不能恢复从未采集的证据。
- `process_loop/llmtracing_report.py` 返回现有 AxisResult；共享调用用量只记在首个过程轴，其他轴注明归属，
  使用 provider 级实现指纹。公共类型现有指纹仍包含 transcript 文件，Agno 的版本元数据可能随之变动，
  这不代表其执行路径切换；本期不改公共 fingerprint 机制。
- 删除 transcript_axes 中旧 complete_json/两次尝试/salvage 实现。单轴入口也委托同一个 ToolLoop 实现，
  整案入口一次运行全部六轴，判后 hook 消费同一报告，不重复运行。
- 主裁决仍走现有入口，本期不把它也迁入 loop；它获得原文和来源说明，但自由文本推断越界尚未解决。
  不把“六轴 ToolLoop 跑通”等同于“主裁决已通过语义核验”。
- 本地验证：完整测试 1592 passed、5 skipped，仍为既有11个失败（477.68秒）；
  新增18个 llmtracing ToolLoop 测试（含全量回归后追加的项目契约覆盖），包括真实 LlmClient + 本地假 OpenAI 服务，不调业务/真实模型。
  核心、Agno在建实例与 judge.py 的文件时间戳未变。没有重启共享服务、没有提交代码。

第5期的旧耗时及“每轴1次调用”是历史记录，不适用于当前ToolLoop。校准审计与局限见
`report/llmtracing-calibration-draft/`；未生成已获批准的 gold 或新准确率。

## 4. 已知边界

- 三种方式都需要被测系统配合，只是程度不同：A 改代码透传；B 接 OTel 插桩；C 起多实例并各自配置模型地址。
  不存在被测系统零改动的可靠关联。
- 响应返回后的后台模型调用：`quiet_seconds` 只能降低漏采概率，不能证明没有。
- 日志文件不轮转且持续增长；本方案按 offset 增量读，不全量扫描。轮转后需按 llmtracing 的新约定调整读取层。
- 18062 与 eval_harness 的 18063 共用 Insurance 评测工作树和数据库；归属靠显式头区分，不做进一步隔离。
