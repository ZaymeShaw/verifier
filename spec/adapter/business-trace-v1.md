# llm_probe 业务 Trace v1

业务 Trace 是一次被测业务调用的过程证据，不是 verifier 自身的执行 Trace。它与 `service`、`axes` 同属
llm_probe 的场景预设；前端入口位于“资料管理 → capability 预设”。

## 场景配置

```json
{
  "business_trace": {
    "provider": "agno",
    "config": {
      "base_url": "http://127.0.0.1:7777",
      "headers": {"Authorization": "Bearer ${AGNO_TOKEN}"},
      "timeout_seconds": 15,
      "poll_attempts": 3,
      "poll_interval_seconds": 0.2,
      "bindings": {
        "session_id": {"source": "request", "pointer": "/body/session_id"},
        "user_id": {"source": "request", "pointer": "/body/user_id"},
        "business_trace_id": {"source": "response", "pointer": "/trace_id"}
      }
    }
  }
}
```

外层信封固定为 `provider + config`。`config` 由对应 provider 独立定义和校验。当前只注册 Agno；新增
Langfuse 时注册一个真实 provider 实现，不在 Agno 实现里模拟共同字段。

Agno 可选配置 `config.sqlite_path`，值为 provider 所在主机可读的 Agno SQLite 数据库绝对路径。
HTTP 模式无需此字段；配置后使用 SQLite `mode=ro` 和只读事务补充原始 run/span 数据，不修改业务数据库。
远程部署中的客户端本地路径不能代替服务端路径；当前不支持通过此字段读取远程数据库或其他数据库类型。

## 采集与关联

只有场景中至少一个已启用轴声明 `requires_business_trace=true` 时才采集。业务请求发出前校验配置；业务
响应成功后执行一次采集：

1. 按 binding 从请求取 `session_id`，可选取 `user_id`，从响应取业务 `trace_id`。
2. 查询 Agno `/sessions/{session_id}/runs`。
3. 将候选 run 的 `content` 解为 JSON，按完整业务响应或业务 `trace_id` 精确匹配。
4. 匹配结果必须恰好一条；零条为 `association_not_found`，多条为 `association_ambiguous`。不得按时间或最新记录猜测。
5. 按唯一 `run_id` 查询 `/traces` 和 `/traces/{trace_id}`。为异步落库做有限轮询；按 Agno 分页元数据读取后续页，最多 10 页、每页 20 条。超限、重复、漏页、详情失败显式记录为 partial。
6. 同 session 已返回的其他 runs，仅在身份一致、已终止且 `created_at + metrics.duration + 1秒精度余量` 早于本轮时纳入 `history_runs`。缺时间或有重叠时排除并报告，不能把创建时间当作完成时间。
7. run detail 失败不拿 run summary 冒充完整详情。保留可成功获取的 span 并报告缺失；run/trace 身份或 ID 冲突拒绝关联。
8. 根据 `/openapi.json` 声明的 GET 接口补采 `/config`、本 session 详情、关联 Workflow/Agent/Team 定义、已注册 Agent 的 checkpoint 列表及快照、明确 user_id 下的 memories。补充 HTTP 请求合计最多 40 次，memories 最多 10 页、每页 20 条。
9. 配置 SQLite 时校验数据库中本轮 run/session/user 与 HTTP 一致，再读取本轮及明确关联子 run、trace 的原始记录。原始 span 按 `(trace_id, span_id)` 与 API 记录合并，不把两个来源当作两次模型调用。关联运行最多 100 条。

补充来源逐项保存 `sources` 收据：available、empty、unsupported、not_recorded、not_configured、not_collected、forbidden、rejected、failed 或 partial。
可选来源失败不抹掉已成功采集的核心 run/trace，也不等于业务调用失败。`collection_status=succeeded` 只描述核心采集，判断证据是否齐全还必须查看来源收据和字段状态。
配置、session、memory 均标为采集时观察，不证明它们等于运行时版本或实际被模型使用。checkpoint 是 Agno 从持久化 run 消息派生的续跑快照，不是原始逐模型请求。

完整 run、trace summary 和 trace detail 固化在本次 `RunTrace.project_fields.business_trace`。所有扩展轴读取
同一快照，轴执行期间不再访问业务 Trace 服务。快照保留 `fingerprint`、关联记录、coverage 和错误。

## 失败语义

- provider/config 无效：保存或业务调用前拒绝。
- 业务调用失败：沿用业务调用原有状态，不伪造业务 Trace。
- 业务调用成功但采集、关联失败：业务 `RunTrace.status` 保持成功；需要业务 Trace 的轴输出
  `not_evaluable` 和缺失原因；不需要业务 Trace 的轴继续执行。
- Agno run 可用但 span detail 缺失：快照为 `partial`，轴按现有证据判断是否足够。

## 六个过程轴

`intent_understanding`、`planning_routing`、`tool_execution`、`context_memory`、`knowledge_data`、
`model_capability` 都需要业务 Trace，它们与 `trace_analysis` 一起构成过程评测链：

```
采集 → trace_analysis（整理案卷、按轴选材料）→ 六个过程轴（各判一题）→ 主轴（唯一裁决）
```

过程轴获得整理员提供的初始选段，同时可以通过案卷只读工具补查同一冻结快照。
每轴最多 8 次补查（含格式重试，共用硬预算），支持批量读取、按路径精读、搜索和时间线。
目录、结构图、搜索片段以及指向另一条记录的指针不算读过正文；引用必须来自初始正文或本次调用的正文读取回执。
格式重试开启新会话，不沿用前次会话没有重新看到的取证内容；回执保留作审计。
provider 不认识轴名，不负责评测标准或 verdict。

各轴只回答一个问题（定义在 `impl/projects/llm_probe/eval_axes/adapters/*.py` 的 `AxisSpec`，
场景轴描述是评测标准，两者都进 prompt）：

| 轴 | 只回答 | 边界 |
| --- | --- | --- |
| intent_understanding | 系统对用户问题的理解对不对：对象、字段/知识点、约束、子问题、指代；该澄清的歧义有没有澄清 | 理解之后的一切（路由、执行、上下文、数据、模型）不在本轴 |
| planning_routing | 编排设计与实际路径合不合理：路径选择、拆解、工具/skill 顺序、失败分支、重试策略、结束时机 | 工具自身执行好坏、上下文拼装、数据源有没有、模型逐次输出质量 |
| tool_execution | 每次调用自身是否正常执行、返回是否完整且与参数相符 | 该不该调、参数从哪来、返回后怎么传、数据源里有没有 |
| context_memory | 工具/步骤到模型输入的信息传递，缓存和历史使用，以及模型输出到最终交付是否丢失、改义、用旧或混淆对象 | 模型生成本身的错误；数据源原本缺失；工具原样返回无关内容不自动归责上下文 |
| knowledge_data | 每个子问题需要的数据/知识外部给了没有；对象、版本、时点对不对 | 调用怎么发、失败怎么处置、返回后怎么传、答案事实能否回溯 |
| model_capability | 在它实际拿到的输入下，输出是否忠实、工具调用决策是否一致、输出契约是否遵循 | 输入本身缺东西、后端没数据、路径该不该走 |

结论口径：看到问题 → `problematic`；该判但案卷没材料 → 缺证（写出缺什么）；本轮确实没有该情形 → `not_applicable`。
缺证与不适用都不算通过；任一检查缺证，整轴不能 `sound`。

## 案卷与选段

`trace_analysis` 整理初始材料，不给表现或根因结论：

1. **程序建案卷**（`business_trace/dossier.py`）：保存每轮 records、原文、时间线、model_calls、coverage 和 gaps。
   内容去重不删除执行；落库结果（final_output）与调用方保存的 extracted_output（delivered_output）分别登记，后者缺失时显式记缺口。
2. **按目录取证并选材**：整理员用批量取件与按路径读取取得原文，产出行动路线与每轴初始材料引用，记录读取回执。
3. **环节表**（`business_trace/links.py`）：只凭 Agno 结构枚举环节实例（ι 轮入口、ρ 控制步骤与同参重复调用、χ 工具调用、
   μ 模型调用、κ 工具返回→模型输入 / 步骤→下一步骤 / 最后步骤→实收），每个环节给出输入端与输出端编号和机器事实
   （包含、相等、差异键、时序）。事实只陈述关系，不给语义 verdict。分析轴看全表，各过程轴只看 π 分给自己的类型。
4. **各轴补查与判断**：检查范围从完整案卷生成，不从初始选段生成，避免未选中的模型调用静默消失。
   超预算材料列入 excluded；轴可补读，仍看不到时缺证。原始请求缺失不会程序预置成不适用。
5. **主轴综合**：六轴结论与引用原文共同进入最终裁决。整理和补查回执合并后渲染同一读取粒度；
   大记录、内容块及源记录只展开已读取的路径。跨轴可同时发现问题，按证据处理事实矛盾，不做根因去重。

每项结论说明事实、环节、影响与原因确认程度。未取得知识可判 problematic，但不能凭未召回宣称整个库不存在。
pass 和 not_applicable 必须有证据与非空检查范围，不能带影响本项判断的缺口。
已确认的 fail 可以保留其他缺口；引用不存在或未读来源的结论不得通过格式修复变成有效裁定。

范围：所有补查只访问冻结案卷，不访问源码仓库或外部业务服务。真实 LLM 判准率需通过同输入复评另行验证，
离线证据可达性和自动化测试不代表语义准确率。

## 标准读取接口

provider reader 只服务案卷构建与离线核查，轴运行期不接触它：

```python
from impl.projects.llm_probe.business_trace import open_reader

reader = open_reader(snapshot)
overview = reader.overview()
page = reader.list_records("model_calls", limit=20)
call = page["items"][0]
input_info = call["fields"]["input"]
# redacted/missing 等状态已经由 provider 检查，无需模型猜字段是否存在。
if input_info["status"] == "available":
    body = reader.read(input_info["ref"], max_chars=12000)
    # next_offset 非空时可继续 reader.read(ref, offset=next_offset)
```

| 方法 | 输入 | 输出 |
| --- | --- | --- |
| `overview` | 无 | provider、关联、采集时间/指纹、采集错误、类别数量、各字段可见性数量及明确限制 |
| `list_records` | kind、可选 run_id、offset、limit（1–50） | 标准化记录描述、总数、next_offset；仅目录 |
| `read` | ref、offset、max_chars（1–24000） | 原文 text、状态、格式、总字符数、truncated、next_offset |
| `timeline` | 可选 run_id、limit（1–200） | 按开始时间排列的步骤/模型/工具节点及其关联 |

读取只针对同一固化快照，不访问任意 URL、不重新调用业务 API、不隐式拉取最新状态。

固定类别如下。Agno 自己负责把
workflow、Agent 子 run、步骤、持久化工具、span 对应到类别。每条记录保留原始 `/records/` JSON Pointer、
run_id、scope、父级关系和已有 ID；标准字段按实际来源映射，例如 tool_calls.arguments/result 和
model_calls.input/output/model/input_tokens/output_tokens。没有 tool_call_id/span_id 对应关系时不靠名字或时序猜配对。
TOOL span 与持久化工具可能是同一次调用的两种表示，不能按目录条数统计业务调用次数。
`references` 只指 Agno 原生引用；工具返回中的业务 facts/evidence 通过 result 或状态读取，不在 Agno provider 中硬编码保险字段。

| 类别 | 可读取内容与限制 |
| --- | --- |
| runs / steps | Workflow、Agent、Team 子运行，步骤、输入输出、状态、metrics、元数据 |
| messages / tool_calls | 保存的对话、工具参数与结果、错误、调用 ID；API 与数据库表示可能重复 |
| model_calls | LLM span；模型、provider、调用参数、token/缓存 token、精确耗时、状态、原始属性；正文按真实可见性标记 |
| states / sessions | 保存的运行状态及采集时会话详情，不是逐次修改日志 |
| definitions | Workflow/Agent/Team 配置、工具描述和参数 schema、输出设置；仅为当前版本 |
| references / memories | 已保存的引用与该用户当前原生 memory，不证明检索命中、实际注入或资料仍有效 |
| checkpoints | 已注册 Agent 的续跑边界与派生快照；内嵌 Agent 未单独注册时不可访问 |
| events / requirements | 已保存事件、暂停、确认、用户输入及外部执行要求；没有记录不等于没有发生 |
| reasoning / artifacts | 已记录的模型推理文本/步骤及媒体附件元数据，不把模型自述当作真值，不自动下载外部文件 |

原始 span 属性由 SQLite 补充，HTTP 单 span 接口仍使用 Agno 的字段投影，不能替代原始属性查询。
数据库中已经隐藏的 input/output 无法恢复。没有埋点的下游 HTTP 原文、运行前后状态变更、源文档版本也不能从现有 Trace 补造。

字段状态：`available`（有非空记录）、`empty`（确实保存了空值/空列表）、`missing`（字段缺少或 null）、
`redacted`（明确隐藏标记）；逐模型完整请求另标 `unverified`。允许按 assistant 消息分段用持久化消息重建每次模型调用的输入，
但必须挂在 LLM span 的 `reconstructed_input` 下并给出 `status`（`verified` 要求消息 metrics 与 span 的输入/输出 token 完全一致；
否则 `mismatch`/`unverified`/`unresolved`）、`message_refs` 和 `token_check`，且说明工具定义等非消息内容不在其中；不得写成原始请求。
同一次工具调用的持久化记录与 TOOL span 由 reader 确定性配对（`tool_call_id` 连接消息与 tools[]；span 按名称+参数，重复时再按最近开始时间），
结果写入 `pairing`（status/method/span_ref/persisted_ref）；`unpaired` 只表示不能关联，不表示调用不存在。
信息限制还区分 `not_collected`（本快照未采集）、`unsupported`（当前 provider 不提供）以及历史采集的 `partial`。
这些都是结构与采集状态，不表示内容相关、可信、业务正确或某轴证据充分。目录缺记录也不证明操作没有发生。

原始业务快照保留不变；模型读取的是其脱敏视图，凭据键以及 JSON 字符串内的凭据键同样脱敏。
字段路径按 JSON Pointer 正确转义，直接读取凭据子路径也不能绕过脱敏。消息与工具内容仍为待评资料，不能作为执行指令。
案卷由程序完整构建，不截断也不改写正文；reader 的分页读取只用于案卷构建与离线核查。
**写入 `AxisResult.usage` 的评审依据是各轴的选段视图与 budget，可以离线用同一份快照重建对照。**
迁移期启用 `fulfillment` 时，保存和运行前强制比较其 description 与主轴 capability 展开资料引用后的有效正文；
不要求同源，但正文必须完全一致。长期主轴退出后删除这条迁移校验，以扩展轴标准为唯一口径。

## 已保存场景：insurance-agno-e2e

入口：资料管理 → llm_probe → capability 预设 → `insurance-agno-e2e`。
存储：`impl/data/llm_probe/capability_map.json`。通过现有 capability save 接口维护，不另加场景配置层。

- 业务接口：`http://127.0.0.1:18062/v1/chat`，POST，非流式，240 秒超时。
- 业务 Trace：Agno provider，base_url 为 `http://127.0.0.1:18062`，按 request body 的 session/user 和 response trace_id 关联。
- 本机只读补充源：`sqlite_path=/private/tmp/insurance-trace-check-20260913/runtime-real.db`；部署迁移时需配置实际可访问路径或去掉该可选字段。
- 身份：不涉及个人数据的动态请求默认使用 `SYNTHETIC-LLM-PROBE`；需要命中个人保单的 case 必须显式保存已授权的工号、保单号及 `empno/agentno`。本机实例须开启 `trusted_body_identity=True`。
- 后端：七个查询工具必须全部以 `real` 模式启动；`insurance-demo-v1` 或其他 Mock 结果不得作为该场景的评测证据。
- 开启的轴：`fulfillment` 加七个过程轴。主 Judge 的 capability 与 fulfillment 使用一致的业务目标。
- 场景保存不代表业务服务已启动、Trace 连接成功或真实 Judge 已通过；运行前在资料页执行“测试 Trace 连接”。该检查只验证 Agno Trace API 可访问，不能证明业务工具处于 `real` 模式。

mock_body 中 `{query}` 注入问题，`{session_id}` 在每次生成新 case 时创建新 UUID，同一模板里多处引用得到同一个值。
占位符仅在模板上替换，用户问题中的相同字面量不会再次展开。
`{request_id}` 与之不同：生成 case 时不落定，每次投递发送前才换成新的请求标识（多轮每轮各一个）。用于被测系统按调用方请求标识关联本轮 trace（如 Langfuse 场景的 `trace_id`），同一 case 重跑也不会撞号。生成后 case 中保存的是具体 session_id。
重跑已保存 case 会复用其中的 ID；独立重复实验需要生成新 case 或显式改成新 ID。多轮追问则显式保留同一 ID。
当前 llm_probe 仍为单轮执行入口，不把配置模板当成自动多轮调度器。

建议用于下一轮优化的 case：

| case | 请求 | 需要核对的证据 |
| --- | --- | --- |
| Direct | 保单 P002 的现金价值是多少？ | Direct/gate 路由、真实工具返回与时点；未命中时核对缺口处理，无模型调用时模型能力缺证 |
| 复合 | 请查询保单 P002 的现金价值，并告诉我犹豫期内退保怎么办理。 | 两个子目标、对应真实工具参数和结果、答案中的缺口声明 |
| 格式约束 | 请介绍平安福的等待期，只讲等待期，回答用一句话。 | 产品与版本、检索证据、输出约束 |
| 追问 | 同 session 追加：那盛世金越呢？继续遵守刚才的要求。 | 前轮主题和约束、本轮产品切换、实际使用的历史和新工具结果 |

评测口径：历史中出现前轮服务失败本身不是污染；必须证实错误复用或混入无关用户/样本。
单次真实接口返回只用于本 case 的证据核验，不硬编码成轴的通用真值。
真实 LLM Judge 的结果与使用本地 stub 的结构验证结果必须分别标识；后者不能用于评判业务质量或优化收益。
