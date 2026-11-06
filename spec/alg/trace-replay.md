# 按 trace 回放评测方案

> 状态：2026-11-03 用户确认。
> 上游：`demand/trace_replay.md`（2026-11-03 上线）。相关：`spec/alg/business-trace-langfuse.md`（W3C 关联与采集）、`spec/alg/axis_loop.md`（loop 与材料）。

## 1. 回放从哪里接进来

```text
外层：取得这一轮                 运行记录（交接点）                 内层：loop（不改）
现场：发请求、收响应、采 trace ┐   每轮：请求（原话 + 历史）      ┌→ case.requirements
                              ├─> 交付文本 output_text         ├→ case.user_turns
回放：按 trace id 取回这一轮  ┘   业务这次有没有失败             ├→ case.deliveries
                                  trace 快照                     ├→ case.business_status
                                                                 └→ case.trace → 各轴
```

回放只换掉最左边一块，产出的运行记录和现场同形，loop 读的还是这几个位置（§4）。loop 的代码、轴定义、提示词、分发、合成都不改。

## 2. case 怎么写

```jsonc
// 现场（不变）
{"id": "...", "live_request": {"capability_ref": "<场景>", "body": {...}}}
// 回放
{"id": "...", "live_request": {"capability_ref": "<场景>", "replay": {"trace_id": "<id>"}}}
```

- `body` 和 `replay` 必须有且只有一个，否则拒绝。
- 一个回放 case 只评这一个 trace 对应的那一轮；对话历史只当这一轮的上下文。
- 场景的 trace 源必须支持回放（§3），否则拒绝。
- 场景其余配置（能力描述、各轴描述、知识源）照用；`service`、`mock_body` 回放时不用。

## 3. 回放是 trace 源的一项可选能力

和现有"投递前要随请求发什么头"（`prepare`）同一种写法：trace 源实现了就支持，没实现就不支持。评测器只问"支不支持"，不认是哪一家。

| trace 源 | 本次 |
|---|---|
| Langfuse | 实现（§3.1） |
| Agno | 不实现。以后可以做（Agno 的 run 记录自带输入和答复） |
| llmtracing | 不实现，也做不了（只看得到模型调用，看不到业务交付） |

trace 源的回放能力：给一个 trace id，返回这一轮的**请求**、**交付**、**业务有没有失败**和 **trace 快照**；任何一项取不到就报原因，不猜。

### 3.1 Langfuse 怎么取

依据：Langfuse 建议把整个应用的请求和答复放在根步骤上，trace 级的 input/output 在 v4 已废弃、只为兼容保留（[Migrate ingestion to v4](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4)，[Why are trace input and output empty?](https://langfuse.com/faq/all/empty-trace-input-and-output)）。

1. **采快照**：按 trace id 读 trace 详情（步骤取详情自带的，不走 `/observations` 接口），复用现有采集（轮询到稳定、同 session 历史、快照、指纹）。查不到算没采到。
2. **找根步骤**：步骤为空报"trace 有记录但没读到步骤"；否则，上一级为空，或上一级不在这条 trace 里的步骤。**恰好一个**才算；没有或有多个，就报"找不到唯一的根步骤"。
3. **取请求和交付**：请求取根步骤的 input，没有再取 trace 级 input；交付取根步骤的 output，没有再取 trace 级 output。任一个两处都没有，就报"这条 trace 没有记本轮的请求 / 答复"。不从子步骤（比如模型调用）取，因为那里的内容不等于业务交付。
4. **记下取自哪里**：根步骤还是 trace 级，写进快照，后面随交付来源一起交给判卷。

2026-11-03 本机实测的 5 种上报写法（`scratchpad/w3c_exp/io_styles.py`）：显式写 trace 级、根步骤写 Langfuse / OpenInference / GenAI 属性，按上面规则都取得到；根步骤只是 HTTP 自动插桩、内容只在模型子步骤里的，取不到，报原因。

## 4. 运行记录怎么拼

回放 case 按**单轮**执行，不进多轮交互（不生成追问）。

| 运行记录里的位置 | loop 谁读 | 回放时填什么 |
|---|---|---|
| 本轮请求 `request.body` | `case.requirements`（本轮原话 + 历史）、`case.user_turns` | 请求是对话消息数组（每条有 role、content）时，原样作为 `messages`：最后一条 user 是本轮原话，前面的问答是历史。和现场"调用方带历史"的单轮 case 同形。不是消息数组时，整份作为用户这一轮发来的东西，不猜字段名（沿用 `spec/alg/expectations.md` §2.1） |
| 对话记录 | `case.user_turns` | 只有本轮：本轮原话 + 交付 |
| 交付文本 `extracted_output.output_text` | `case.deliveries`、说法、真实性、兑现 | 字符串原样；对象或数组转成 JSON 文本，和现场"整个响应体作为交付"同形 |
| 业务有没有失败 | `case.business_status` | §5 |
| trace 快照 `project_fields.business_trace` | `case.trace`、过程各轴 | §3.1 采到的快照。不再采第二遍 |
| 应用边界 | 运行记录 | 新增 `trace_replay`，标明交付取自 trace 记录（根步骤 / trace 级） |

**交付来源怎么交给判卷**：只写在回放 case 的材料值里（交付条目带一句"本轮交付取自业务 trace 的记录，不是评测方实际收到的"）。材料的结构定义和通用说明不改。核实过：材料的通用说明不会进提示词，进提示词的是材料的值，所以现场 case 的提示词一个字不变。

**不靠文字特征判断有没有脱敏或改写。** 核不了的说法，现有真实性轴本来就判"无法核"，不为回放另加规则。

- **历史**：这条 trace 里记了历史（本轮请求里带着前面的问答）就用；没记就不管历史，不去同 session 的其他 trace 里拼（2026-11-03 用户定）。

## 5. 业务这次有没有失败

现场的口径：业务已经响应、但回了非 2xx，算"被测系统调用失败"（`live_protocol.business_call_failure`）。回放时从根步骤上取对等的信号，只用两个标准字段（2026-11-03 用户定）：

1. 根步骤记了 HTTP 状态码（OTel 语义约定的 `http.response.status_code`）：非 2xx 算业务调用失败，原文写状态码。和现场同一口径。
2. 没记状态码：根步骤的 Langfuse `level` 是 `ERROR`，算业务调用失败，原文取它的 `statusMessage`。OTel 把 span 状态设为错误时，Langfuse 记成 `ERROR`。
3. 两个都没有：算正常返回。

先判失败，再取交付：判为业务调用失败的，和现场一样按"被测系统调用失败"处理，不因为没有交付而记运行失败。

只看 `level` 不够：OTel 约定 HTTP 服务端 4xx 不标错误，所以 4xx 往往只体现在状态码上。2026-11-03 实测：Insurance 一次真实的 429 请求，根步骤 `level=ERROR`、状态码 429、output 为空；标准 OTel 只记状态码 500 时，`level=DEFAULT`、状态码 500；抛异常时，`level=ERROR`，`statusMessage` 是异常说明（`scratchpad/w3c_exp/fail_marks.py`）。

## 6. 框架协议怎么改（协议改动，2026-11-03 用户确认）

现在"不调业务、用给定产出"的路径（provided）是项目级的：项目继承 `ProvidedOutputLive`、并声明 `ready: output`，所有 case 都走它（目前只有 QA 项目）。

改为：协议加一个扩展点"这个 case 是否自带产出"，**默认否**。投递时，项目级 provided **或者**这个扩展点说是，就走 provided 路径（调 `deliver_provided`）；否则照原样调 `deliver_real`。

- 其他项目不覆盖这个扩展点，行为完全不变；QA 项目照旧。
- llm_probe_loop 覆盖它：带 `replay` 的 case 返回"是"，并实现 `deliver_provided`（调 trace 源的回放能力，拼 §4 的运行记录）。

## 7. 校准

同一个场景，拿现场跑过的 case（W3C 关联时，每轮发出的 trace id 就在运行记录里），逐轮比较"评测方实际收到的"和"按 §3.1 从 trace 取到的"：请求里的本轮原话、历史条数、交付逐字段是否一致，并列出不一致的字段。产出这个场景的一致性报告。对任何业务都适用，不依赖业务细节。

- 不作为门槛（2026-11-03 用户定）；结论里注明这个场景有没有校准过、一致程度怎样。

## 8. 现场模式不变怎么保证

| 风险 | 做法 |
|---|---|
| 协议投递分支 | 只新增分支；没带回放标记的 case 走原来的代码路径 |
| 材料与提示词 | 回放来源只写进回放 case 的材料值；材料定义、通用说明不改 |
| 运行记录、采集 | 现场的采集、W3C 关联、读取都不改 |

验证：同一批现场模式的固定输入，改前改后发给评测模型的材料、提示词逐字节一致（SHA-256）；现有测试全过；8036 回归的结论与效率和改前持平。

## 9. 服务端和前端

| 位置 | 做什么 |
|---|---|
| 资料管理页 · 场景 | "试取回放"：输入 trace id，显示会取到的本轮原话、历史、交付、业务状态、各取自哪里、取不到的原因。"校准"：选一批现场跑过的 case，出一致性报告 |
| 候选区 | 选场景 + 粘贴 trace id（一行一个），生成回放 case；用例表多一列"来源：现场 / 回放" |
| 结果详情 | 回放 case 标明交付来源，附 trace 链接 |

## 10. 已知局限

- 能不能回放，取决于业务有没有按 Langfuse 推荐的写法记录本轮的请求和答复。目前只在 Insurance 和本机模拟的 5 种写法上核实过。
- 回放评的是"记录的交付"，证据比现场弱一档。Insurance 的记录有脱敏和字段改写（14 轮里 6 轮有脱敏；`trace_id` 字段 14 轮都被改写）。
- 现有 Langfuse 读取代码里写死了几个脱敏、截断标记的字符串去匹配，属于已有的过拟合，另记，本次不动。
