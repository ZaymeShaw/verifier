# 按 trace 复评：实施方案

> 状态：2026-11-03 用户确认。
> 依据：`spec/alg/trace-replay.md`（2026-11-03 用户确认）、`demand/trace_replay.md`。

## 0. 命名

框架里已有"回放"：`ReplayDriver` 拿一份写好的多轮用户话术**逐字再发给业务**，仍然调业务。本功能不调业务、只用 trace 里的记录，二者不同。为免混淆：

- case 字段叫 `from_trace`，中文叫"按 trace 复评"；
- 方案文档里的"回放"在代码和界面上一律用"按 trace 复评"。

## 1. 框架层 `impl/core`（协议改动，2026-11-03 用户确认）

| 文件 / 位置 | 改什么 | 其他项目受影响吗 |
|---|---|---|
| `live_protocol.py` 新增扩展点 `case_provides_output(request) -> bool` | 默认返回 `False`。项目可以覆盖：这个 case 是否自带产出（不调业务） | 不影响：默认否 |
| `live_protocol.py` 投递分支（现在是 `if self._has_provided_output():`） | 改为 `if self._has_provided_output() or self.case_provides_output(request):`，后面原样走 `_run_provided` | 不影响：只多一个"或"，其他项目永远为否 |
| `live_protocol.py` `_run_provided` 的失败分类 | 现在把所有异常都记成协议错误。改为和现场一样用 `live_failure_type(exc)` 分类，这样 `deliver_provided` 报"业务调用失败"时，能和现场的非 2xx 落进同一类 | QA 项目的 `deliver_provided` 不抛这类异常，行为不变；要用测试确认 |
| `live_protocol.py` Session 选 driver | `case_provides_output(initial_request)` 为真时用 `OneShotDriver`（单轮），不进多轮交互 | 不影响：只有为真时才生效 |
| `trace.py` 执行模式 | 单轮且 `case_provides_output` 为真时，`execution_mode="provided"`、`output_source="provided_output"`（沿用已有取值） | 不影响 |

## 2. trace 源层 `impl/projects/llm_probe_loop/business_trace`

| 文件 / 位置 | 改什么 |
|---|---|
| `providers/langfuse.py` 新增 `replay(config, trace_id)` | 按 id 采快照：复用 `collect` 的轮询、步骤详情、同 session 列表、指纹，抽出"按给定 id 采"的公共部分，现场的 W3C 采集也调它，行为不变。<br>找唯一根步骤（上一级为空或不在本 trace 里；不唯一就报原因）。<br>先判失败（`spec/alg/trace-replay.md` §5）：根步骤的 `http.response.status_code` 非 2xx，或者没有状态码但 `level=ERROR`。<br>不失败才取请求和交付：根步骤 input/output 优先，没有再取 trace 级；没有就报原因。<br>返回 `{request, delivered, delivered_from, failure, snapshot}` |
| `providers/agno.py`、`llmtracing.py` | 不改（不实现 `replay`，所以不支持按 trace 复评） |
| `__init__.py` 新增 `replay(selection, trace_id)`、`supports_replay(selection)` | 和 `propagation_headers` 一样按 provider 分发；provider 有 `replay` 就支持 |
| `mcp_servers/trace` | 增加 `replay` 工具。采集现在走 trace 源的本地 MCP 服务，复评也走它，凭据的传法不变 |
| `providers/langfuse_reader.py` | 不改 |

## 3. 项目层 `impl/projects/llm_probe_loop`

| 文件 / 位置 | 改什么 |
|---|---|
| `schema/__init__.py` `LlmProbeRequest` | 加 `from_trace: Dict = {}`；`body` 改为可缺省（默认 `{}`），必填由校验管 |
| `live_schema.py` `request_errors` | `body`（非空）和 `from_trace` 必须有且只有一个；`from_trace` 只能有 `trace_id`（非空字符串）；场景必须选了 trace 源，且 `supports_replay` 为真 |
| `live.py` `LlmProbeLive.case_provides_output` | 带 `from_trace` 时返回真 |
| `live.py` `LlmProbeLive.deliver_provided`（新） | 调 `business_trace.replay`；失败时抛和现场非 2xx 同一类的异常（原文为状态码或状态说明）；成功时把取到的请求写成 `body`（对话消息数组时写 `{"messages": [...]}`，否则写原样），返回交付。快照在同一次投递里交给 `project_fields`，不写进请求记录 |
| `live.py` `project_fields` | 复评 case 直接用投递时拿到的快照，不再采第二遍；现场不变 |
| `live.py` `extract_output` | 不改：交付是字符串就原样，是对象就转 JSON 文本，和现场同一个函数 |
| `live.py` `application_boundary` | 复评 case 返回 `{"scope": "trace_record", "delivered_from": "root_observation" 或 "trace"}`；现场不变 |
| `eval_axes/materials.py` `_deliveries` | 复评 case 的交付条目多带一个 `source`：一句话，"本轮交付取自业务 trace 的记录（根步骤 / trace 级），不是评测方实际收到的"。现场条目不带。材料的 schema 加一个可选属性 `source`（schema 不进提示词，只在加载时核对引用路径） |
| `eval_axes` 其余、轴定义、合成 | 不改 |

## 4. 服务端与前端

| 文件 / 位置 | 改什么 |
|---|---|
| `impl/server/routes.py`、`service.py` | 新增 `POST /api/business_trace/replay_preview`，传 `{project, capability_ref, trace_id}`，返回会取到的请求、交付、交付取自哪里、失败判定、取不到的原因。新增 `POST /api/business_trace/calibrate`，传 `{project, capability_ref, pool_indexes}`，对现场跑过的 case 逐轮比较，返回一致性报告（每轮的本轮原话、历史条数、交付各字段是否一致，以及不一致的字段） |
| `materials.html` 场景页 | 在"测试 Trace 连接与配置"旁加"试取复评"（输入 trace id）、"校准"（选候选区里本场景现场跑过的行） |
| `summary.html` 候选区 | 加筛选"来源方式：现场调用 / 按 trace 复评"（按 case 里有没有 `from_trace` 判断）。复评用例和其他用例一样放在数据集里，通过"加载 Mock 数据集"进入候选区（2026-11-03 用户定：统一走数据集，不另设导入入口） |
| 结果详情 | 复评 case 显示交付来源，附 trace 链接 |

## 5. 测试

| 测什么 | 怎么测 |
|---|---|
| 框架 | 默认扩展点为否时，各项目投递路径不变；`case_provides_output` 为真时走 `_run_provided` 和单轮 driver；`_run_provided` 的失败分类和现场一致；QA 项目原有测试全过 |
| Langfuse 取数 | 用 5 种上报写法的快照（显式 trace 级、根步骤 Langfuse / OpenInference / GenAI、只有 HTTP 根步骤）：前 4 种取得到，第 5 种报原因；根步骤不唯一时报原因；失败判定 3 种（状态码非 2xx、`level=ERROR`、都没有） |
| case 校验 | `body` / `from_trace` 互斥；trace 源不支持复评时拒绝 |
| 项目投递 | 复评不发 HTTP；运行记录与现场同形（本轮请求、交付、快照）；快照不采第二遍；失败落进"被测系统调用失败" |
| 材料 | 复评交付带 `source`；现场交付不带 |
| **现场不变** | 改代码前，从 8036 候选区取现场跑过的 case（Langfuse、MCP、Agno 各几条），离线重建各轴的材料值和完整提示词，记 SHA-256；改代码后再算一遍，要求逐条相同 |

## 6. 验收

1. 上面的测试全过；现有测试无新增失败。
2. 现场不变：材料和提示词的 SHA-256 前后一致；8036 回归一批现场 case，结论和效率与改前持平。
3. 复评：用 Langfuse 场景现场跑过的 11 条 case 的 trace id 做复评，和现场结论逐条对照。差异要说得清，主要应来自交付记录和实收的差别（Insurance 有脱敏）。
4. 校准：对 Langfuse 场景出一份一致性报告，结果应和 2026-11-03 手算的一致（原话 14/14、交付 8/14、`trace_id` 字段 0/14）。
5. 试取复评：用 5 种上报写法的 trace 各试一次，结果和 §5 一致。

## 7. 顺序

1. 先做"现场不变"的基线：离线算出改前的材料和提示词的 SHA-256。
2. 框架层，跑全部项目的测试。
3. trace 源层和项目层，补测试。
4. 服务端和前端。
5. 重启 8036：先比对现场基线，再做复评和校准的验收。
6. 更新场景接入指南。

## 8. 实施记录（2026-11-03）

**和方案相比的出入：**
- 命名：trace 源的能力、分发函数、MCP 工具、项目模块统一叫 `from_trace`（`provider.from_trace`、`business_trace.from_trace` / `supports_from_trace`、项目模块 `impl/projects/llm_probe_loop/from_trace.py`），不用 replay。
- 框架又补了三处，都只在 `case_provides_output` 为真时生效：
  1. provided 分支原样抛出 `deliver_provided` 的异常，由 Session 按 `live_failure_type` 分类。原来会包成 `RuntimeError`，业务失败就归不进"被测系统调用失败"。§1 原写的"`_run_provided` 改用 `live_failure_type`"不需要了，已撤回。
  2. `_run_provided` 调 `extract_output` 时，`RealServiceLive` 只传 `raw_response`，和它的签名约定一致。
  3. `session.py` 记执行模式时，这类 case 记为 `provided`。
  另外 `live_transport.py` 新增 `LiveRecordedFailure`（`LiveHTTPStatusError` 的子类），表示"有记录的失败、但没有 HTTP 状态码"（如 `level=ERROR`），和非 2xx 同类。
- 用户原话的时序：Session 在投递**之前**就把用户原话记进对话记录。所以"按 trace 取回"在项目里做成每次执行只取一次、取完缓存（`from_trace.fetch` / `take`，用 ContextVar 存）：`mock.user_message_from_request` 和 `deliver_provided` 共用这一次结果。框架为此不改。
- 请求和失败的顺序：请求先取（业务失败了，用户这一轮说了什么照样记）；再判失败；不失败时，请求和交付都必须有。
- 场景里有 trace 源、但没有轴读 `case.trace` 时，照样能复评（用 `capability_business_trace_selection`）；只是快照不进 `project_fields`，和现场的规则一样。
- 前端：执行模式一列原本就有，复评用例显示 `provided / provided_output`，所以不加新列；复评用例的输出格里写明"交付取自业务 trace 的记录"。用户定统一走"加载 Mock 数据集"：复评用例写进数据集，候选区加"来源方式"筛选；最初做的单独导入入口已删掉。8036 数据集里追加了 Langfuse 场景的 11 条复评用例（原有 56 条逐字不变，备份在 `scratchpad/8036-before-fromtrace-dataset/`）。
- 服务端接口路径：`/api/from_trace/preview`、`/api/from_trace/calibrate`。

**验证：**
- 现场不变：17 条现场 case（Langfuse 11 条、MCP 3 条、Agno 3 条）的 406 份材料和第一批提示词，改前改后 SHA-256 全部一致；改前两遍自检也一致（`scratchpad/replay_baseline/`，脚本 `baseline.py`、`compare.py`）。
- 测试：新增 `tests/test_llm_probe_loop_from_trace.py`，25 条全过。全仓 2257 passed、27 failed；这 27 条在 HEAD（`8f67fedb`，W3C 已提交、复评未开始）的干净检出上同样失败，都是原来就有的。
- 试取复评（8036）：Insurance 单轮 trace，取自根步骤，22 个步骤；那次真实的 429 请求判为 `HTTP 429`；E01 第 3 轮带出 4 条历史；不存在的 trace 报"没采到"。
- 校准（8036，Langfuse 场景 14 轮）：原话 14/14、历史 14/14；交付里不同的字段是 `trace_id` 14 轮、`answer` 4 轮、`structured` 2 轮、`fact_refs` 1 轮，和 2026-11-03 手算的结果一致。

**8036 实跑发现的问题与修订（2026-11-03）：** 用户在候选区跑 11 条复评，4 条判"不确定"。原因是读取时认根用了"上一级 = 本次发出的 parent-id"，这要用到 trace 以外的信息。复评不知道当初那次现场发出的 parent-id，同一条 trace 被标成层级不全：意图理解环节缺输出端，fuyunping、F01 的交付环节整条缺失。修订为只看 trace 本身认根（`langfuse.root_id`，读取与复评共用；`spec/alg/business-trace-langfuse.md` §2.4），不再记、不再用 parent-id。验证：15 条现场运行（Langfuse W3C 单轮/多轮、metadata 旧运行、MCP、Agno）的 354 份材料和首批提示词改前改后一致；这 11 条复评的材料里，意图环节两端齐了，交付环节都在，层级缺口为 0。用户这一批的结论作废，需要重跑。
