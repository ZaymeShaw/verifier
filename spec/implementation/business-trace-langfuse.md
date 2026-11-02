# Langfuse 业务 Trace provider

## 契约

入口仍为 `{provider, config}`，`provider: langfuse` 走冻结案卷路线。注册表返回默认配置，
前端的通用 provider 配置编辑器可直接使用。没有增加 SDK 或 Python 依赖。

```json
{
  "provider": "langfuse",
  "config": {
    "base_url": "http://127.0.0.1:3300",
    "public_key": "${LANGFUSE_PUBLIC_KEY}",
    "secret_key": "${LANGFUSE_SECRET_KEY}",
    "match_field": "metadata.request_trace_id",
    "bindings": {
      "business_trace_id": {"source": "request", "pointer": "/body/trace_id"}
    },
    "content_char_limit": 20000
  }
}
```

此示例针对当前 Insurance：调用方每次 HTTP 请求须提供新的 `body.trace_id`，
业务响应回显该 ID，Langfuse 将其保存到 `metadata.request_trace_id`。
`metadata.business_trace_id` 是业务内部 ID，与对外 ID 不同，不能混用。
其他业务可按自身契约选择 provider 默认的 response `/trace_id` 绑定。

密钥由 verifier 进程环境解析，不把值写入场景、快照或报告。示例长度上限只适用于业务也配置了
20000 的情况；默认上限为 null（未知）。不改变业务的脱敏策略。部署在
`/Users/xiaozijian/WorkSpace/package/langfuse-deploy`，凭据文件不进仓库。

## 关联与采集

1. 从 request/response JSON Pointer 取非空业务 ID。只允许 `id` 或 `metadata.<key>` 精确匹配。
2. ID 模式读取 `/api/public/traces/{id}`；metadata 模式分页检索，必须唯一匹配，且详情再次验证 ID。
   无匹配等待异步入库；多匹配直接失败。分页不完整不能宣称唯一。
3. 读取 trace、分页 observation 清单以及每条 observation 详情。v3.184.1 的 v1 observation
   API 可返回完整字段，避免 v2 默认字段组和 metadata 预览导致遗漏；没有协议回退。
4. 记录数、内容、完成状态都稳定且所有非 EVENT 记录有 endTime，才结束轮询。
   默认等待 60 秒、间隔 1 秒、稳定窗口 3 秒。变化中的相同数量记录不会提前结束。
   失败的详情保留已经读到的清单行并标 partial；分页限制、未结束及读取错误显式记录。
5. 同 session、时间严格早于本轮的 trace 作为 history。无可信 session/时间不猜；历史观察记录不采集。
   异常时间（包括溢出为 9999 年）标缺证，不参与历史或时间线。
   历史采集有独立的同长度时间预算和分页上限。所有 HTTP 请求遵守剩余预算。
6. 快照保存原始数据、关联、错误、历史覆盖、SHA-256 指纹与限制。分析期间禁止再访问网络。

一次稳定采集只说明当时可见记录稳定，不证明没有采样、漏埋点或未来的迟到数据。

## 通用分析边界

- trace → runs；GENERATION/EMBEDDING → model_calls；TOOL/RETRIEVER → tool_calls；
  RETRIEVER 输出也登记 references；EVENT → events；其余 observation → steps。
- 显式 SPAN 的 `metadata.attributes.openinference.span.kind` 可声明 TOOL/LLM/AGENT 等语义；不按名字猜类型。
- parentObservationId 保留为明确父子引用。未知类型和缺失父节点列入限制。
- SDK input 仅标为 recorded_request，不能标成已证明的 exact_request。模型环节与输入传递环节
  直接引用该原始字段；内容缺失、脱敏或截断时材料层据字段状态判缺证。
- 不把按时间排序的 sibling observations 当成串行步骤，不凭名称或时间猜工具和模型的配对。
- 内容中含脱敏标记，或字符串达到业务声明长度上限时标 redacted/truncated；仍保留原文。
  不含标记不能证明没有上游截断，因此完整请求覆盖一直为 unverified。
- 上游 scores 只作为资料，不是 verifier 结论。没有自动写回 scores。
- 环节说明由 reader 声明；Agno 的旧表示与重建逻辑仍只由它的记录触发。

## 验证

使用 `miniconda3/envs/agno/bin/python` 运行业务 trace 测试。默认 conda base 的 Agno 版本过旧。

五份 `report/business-trace-agno-20260913/snapshots/*.json` 的 overview / dossier / links /
material_view / catalog 在修改前后按相同 JSON 序列化比较，SHA-256 必须完全一致。

本地服务验收分开报告：

- 合成 ingestion → 唯一 metadata 匹配 → trace/observation 原文读回；
- Insurance 自带 live 测试：离线模型和合成业务 + 真实 OTLP 接收端，覆盖模型/工具树、JSON、SSE、多轮及错误；
- verifier provider 消费合成或 Insurance 产生的真实 Langfuse 记录，生成案卷及六轴环节材料。

上述测试不代表已完成真实保险请求的模型评判质量对照。真实单轮、多轮的
trace_analysis → 六轴 → 主轴以及与 Agno 结论对照需单独运行并记录，不能用协议测试替代。

固定版本 API 定义：

- https://github.com/langfuse/langfuse/blob/v3.184.1/fern/apis/server/definition/trace.yml
- https://github.com/langfuse/langfuse/blob/v3.184.1/fern/apis/server/definition/legacy/observations-v1.yml

## 真实验收结果（2026-10-16）

数据：Insurance 评测工作树（含 `feat(observability)` 0a138c24，Langfuse `capture_content: true`、`max_content_chars: 20000`），
同一 session 两轮真实请求，同时采 agno 与 langfuse 快照（`report/business-trace-langfuse-20261015/real/turns.json`，两边四份快照均 succeeded）。
每组只跑一次完整评判（trace_analysis → 六轴 → 主轴），结果文件为同目录 `*-judge.json`。

| 组 | agno 主轴 | langfuse 主轴 |
|---|---|---|
| 单轮：客户号 C92200000884 对应谁 | not_evaluable | fulfilled |
| 两轮：+「这位客户名下有哪些保单？」 | not_fulfilled | not_fulfilled |

- 两轮组一致，两边都查出同一个真实业务问题：第 2 轮没有接上会话历史，「这位客户」无法解析，业务用英文反问。
- 单轮组分歧不是证据差异造成的：agno 判 not_evaluable 依据的「源数据未提供明确请求字段 clientno」，在两份快照里都有。
  langfuse 那次的主轴看到了知识数据轴的「无法核」，但推翻了它，判成兑现。每组只有一次，不能归因到 provider；要下结论需要同输入重复评判。
- 六个过程轴两边的结论方向基本一致（客户查询正常；轮内执行余量提示没有递减；模型发工具调用时夹带旁白；第 2 轮工具参数没闭合导致报错）。
- 已核实的 Langfuse 证据短板：
  - Insurance 的 TOOL span 没有输入输出（Agno 插桩隐藏了），工具的真实请求和返回在子 span `backend.*` 里，归在 steps。
    tool_execution 环节照样会列出来（单轮 1 个，与 agno 相同），但两端的参数和返回都是 missing，轴需要自己去 steps 里找；
    两轮组的知识数据轴就没找到，判了「全流程无法核实」。整体环节数也比 agno 少（单轮 8 对 16，主要差在 context_memory：8 对 2）。
  - 模型调用的输入输出带脱敏标记，状态是 redacted（单轮快照里有 27 处 `[REDACTED]`）。
- 口径说明：这 4 组评判在 trace_analysis 提示词恢复为「从 Agno 结构枚举」之前就已启动，用的是改动前的措辞；之后 Agno 的提示词已恢复原文（回归 SHA-256 一致）。

### 模型能力轴漏判「没核实就断言」的原因（2026-10-17 查）

- 两次评判（agno、langfuse 单轮）都把最终回答判为「输出忠实·达到」。
- 搜索返回里那句「本次源数据未提供明确请求字段 clientno……如需核实请使用 customer_detail」**在材料里**：
  agno 组写「本应」清单的那次调用（`impl/data/context_store/llm_probe/axes-2c4ab1462a0e:langfuse-acceptance-agno-1/judge-2026-10-16T07:03:57Z-*`），输入 messages 里就有这句话。
- 漏在写「本应」这一步：E2 写成「模型应依据返回数据明确答复客户号 C92200000884 对应何承琪」，依据引的是需求期望 `t1.exp_query_customer_by_id`。
  也就是按用户想要的结果去推「本应」，没有按「这次输入能支撑什么」去推。核对时实际回答和这条「本应」一致，于是判了达到。
  按 `spec/alg/process-axes.md` §3，「本应」是「在实际拿到的输入下本应产出」。按这个口径，E2 应写成「只能作为待核实的候选给出，或先按提示调用 customer_detail」。
- 定义本身已经覆盖（§8「输出忠实（不改义、不丢关键信息）、工具调用决策一致」），§10 已补一条样例；是否还要对写「本应」的步骤做别的改动，先看样例补上后的效果，一个 case 不立新规则。

### 单轮 case 重跑（2026-10-17）

同一份冻结快照（`real/turns.json` 第 1 轮），agno / langfuse 各再跑 3 次（脚本输出 `report/business-trace-langfuse-20261015/rerun-20261017/`），加上 10-16 各 1 次，共 8 次。
本场景只开六个过程轴、没开真实性轴，D18 的改动不在这条路径上；与 10-16 的代码差别只有 trace_analysis 提示词（agno 恢复原文、langfuse 用自己的来源名）。

| 次 | agno 主轴 | langfuse 主轴 | 知识数据轴（agno / langfuse） | 模型能力·输出忠实 |
|---|---|---|---|---|
| 10-16 | not_evaluable | fulfilled | not_evaluable / not_evaluable | 达到 / 达到 |
| r1 | fulfilled | fulfilled | sound / not_evaluable | 达到 / 达到 |
| r2 | fulfilled | fulfilled | not_evaluable / not_evaluable | 达到 / 达到 |
| r3 | not_fulfilled | fulfilled | problematic / not_evaluable | 达到 / 达到 |

- 主轴不稳是系统性的，不是偶发：同一份证据 8 次里 fulfilled 6、not_evaluable 1、not_fulfilled 1。agno 一边就出了三种结论；langfuse 4 次都是 fulfilled。
  agno-r3 判 not_fulfilled 的理由是「交付了虚假对应事实」，与事实不符（历史详情数据证实客户号确对应 CE69…/何承琪）。
- 主轴推翻轴的「无法核」也是系统性的：知识数据轴判 not_evaluable 的 6 次里，主轴 5 次判了 fulfilled。
  提示词里已有「需要的证据缺失时判 not_evaluable，即使答复可读也不能据此通过」，执行不住。
- 模型能力轴 8/8 漏判：没有一次写出「搜索结果缺客户号、应先按提示调 customer_detail 核实」这条本应；输出忠实 8/8 判达到。
- 不能归因到 provider：agno 自己就在三种结论间摆动。langfuse 4/4 fulfilled、agno 2/4，是否有偏差，样本太小不下结论。

## 缺口信号结构化（2026-10-17，`spec/adapter/information-sources-plan-20261017.md` §3.2-3）

`limitations.content` 不再只给一串编号，改为逐条 `items`，每条：`ref`、`name`、`field`、`kind`、`why`。
`kind` 取 `not_recorded`（只记了结构没记输入输出，附 `recorded_attributes` 列出实际记了哪些属性）、`redacted`（含脱敏标记）、
`truncated`（长度达到 `content_char_limit`；上限未配置时不标）。案卷登记缺口时把 `items[].ref` 加轮次前缀，与案卷编号同一命名空间。
分级沿用现有 `partial / unverified`（`demand/information_sources.md` ⟡2 未定前不另立级别）。只陈述采集事实，不判影响。

实测（Insurance 单轮真实快照，`content_char_limit=20000`）：26 条，`not_recorded` 19、`redacted` 7、`truncated` 0。
S1 的搜索内部四步（`backend.customer_search.request`、`result.parse_customer_query`、`backend.customer_query.request`、`result.parse_page`）
都列为 `not_recorded`，`recorded_attributes` 只有 `request.bytes / response.bytes / http.response.status_code` 等。
Agno 5 份快照产出与 HEAD 逐字节一致（Agno 的限制没有 `items`）。


## 请求标识占位符（2026-10-18）

Insurance 场景按请求 `body.trace_id` 关联，写死的值重跑会在 Langfuse 里出现两条同 ID 的 trace，按规则判关联失败。改为场景模板与 case 里写 `"trace_id": "{request_id}"`：`capability.fresh_delivery_placeholders` 在每次投递发送前把它换成新的 `llm-probe-req-<uuid>`（生成 case 时不落定）。原 `fresh_session_placeholders` 改名并同时处理 `{session_id}` 与 `{request_id}`。这是 verifier 作为调用方自己给的请求标识，不改被测系统。

## 列表计数不可信（2026-10-18）

实测 v3.184.1 `GET /api/public/traces?filter=…metadata.request_trace_id…`：同一 ID `meta.totalItems=3`，第 1 页 1 条、第 2–3 页为空。
原实现要求"取回条数 = totalItems"否则记 `total_items_mismatch` 并持续轮询，导致约半数采集超时判失败（Codex 验收第 1 轮的 partial、
本次重复运行第 2 次的失败均为此）。改为：翻到 totalPages 且无读取错误即以实际行为准，唯一性按实际行的 ID 判断；
计数差异记入 `association.listing_notes` / `listing_notes` / `history_coverage.listing_notes`，不当作未列全。
真有多条同 ID trace 时它们会出现在返回行里，仍判 `association_ambiguous`。observation 完整性另由 trace 详情自带的 observation 清单核对。
修复后两条真实 trace 重新采集均 succeeded（各 19 个 observation，约 4 秒）。
