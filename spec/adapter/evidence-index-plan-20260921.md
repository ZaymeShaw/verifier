# 证据链「仓库 + 清单 + 侦探」实施方案

- 日期：2026-09-21
- 状态：A 线已实施（A4 尾项待做）；B1/B2 完成；**B3 机制完成但 30 样本验收未过**（见「实施状态」）；B4/§6/§7/C 未开工
- 背景报告：`report/process-dossier-20260920/`（30 样本实测、judge prompt 体积分布、失败模式时间线）

## 实施状态（2026-09-21）

### 端到端实测（`report/process-dossier-20260920/verify-a1/`）

样本 `clean--llm-probe-insurance-real-baseline-insured-name`（frozen trace，1142s，单 workers）：

- 结论：`fulfilled`，与基线一致；七个轴中六个与基线一致。
- 端点路由：全部成功调用落在 fallback2（容量 384k），超过 fallback1 容量（184k）的 prompt 被 A2 预检跳过。
- 主 judge prompt 最大 **327,994 字符**（基线 run_trace 单项就 1.58M）；run_trace payload 510k→5.6k 字符。
- 唯一漂移：`tool_execution` 基线 `sound` → 本次 `not_evaluable`，缺证原文「policy_detail 或 policy_svc /policy/full 的适用超时阈值或正常耗时依据」。
- **漂移原因（已定位，与 A1 无关）**：分析轴本次落在 `cursor-grok-4.6-medium-fast`，基线落在 `qwen3.8-flash`；两条 run 的选段不同（tool_execution 视图 7 条→5 条，planning_routing 20 条→23 条），丢证据的那条就诚实报了缺证。即：**分析轴的选段是模型相关的、不可复现的**——这正是 B1/B3 要替代的东西（改成程序化索引 + 侦探回执）。

旁证发现：`outputs/insurance-e2e-20260921/run/axes_run.py:49` 自建 `LlmEndpoint(name="forced")` 直连端点，不走 verifier 路由器，因此不受 A2/A3 约束（实测该路径曾把 `Prompt too large (227616 chars)` 记为 success）。

| 项 | 状态 | 产物与实测 |
|---|---|---|
| A1 judge 去原始快照 | ✅ | `core/judge.py` `_JUDGE_EXCLUDED_PROJECT_FIELDS`；删死键 `judge_evidence`；run_trace 510k→5.6k 字符（−98.9%） |
| A2 端点容量与预检 | ✅ | `LlmEndpoint.max_prompt_chars` + `serves()`；客户端预检拒绝发送；`config_check` 新增 `llm_prompt_budget_unservable`；实测容量表见 A2 |
| A3 端点错误体记失败 | ✅ | `provider_error_body()`：配额/超长/截断类 HTTP 200 纯文本不再记 success，改走端点失败与降级 |
| A4 调用小票整治 | ◐ | 完全重复记录合并 + `retry_count` 已落地；「批次体检摘要写进结案报告」待做 |
| A5 端点工具能力声明 | ✅ | `LlmEndpoint.tool_calls` + `serves(needs_tools=)`；`LLM_FALLBACK_1_TOOL_CALLS=false`（本地 cursor 桥不支持 tool calls）。实测：整理阶段从「fallback1 两次废产出、六轴全缺证」变为一次打到 fallback2 拿真产出 |
| A6 调用记录落档不再静默丢 | ✅ | 根因：记录里出现机器绝对路径 → 路径契约抛 `PathContractError` → `_track_context` 吞异常 → 整条调用记录消失（旧批次轴记录目录整个是空的）。修：`redact_forbidden_paths` 同口径隐去 + 落档失败不再静默 |
| B1 纯测量 | ✅ | `build_manifest` + 两项前置已进代码；`report/process-dossier-20260920/evidence-index/`。轴视图 −93.2%（>160k 的 47 个→0）；组织者 −84.4%；引用可达性 99.59%（1 条自造编号，材料已登记） |
| B2 可达性抽查 | ✅ | `scripts/_b2_reachability_tmp.py`（离线，不打 LLM）：5 个有人工结论的冻结样本，历史判词引用 **255/255 可达**；逐条复核量级 72–157 次读取 / 11–28 万字符（说明 `TOOL_CALL_LIMIT=32` 是定位预算，不是逐条复核预算）；产物 `report/process-dossier-20260920/evidence-index/b2-reachability.json` |
| B3 分析轴侦探化 | ◐ | **机制全部落地**（工具层/清单化/同粒度/需求说明/完整读取/回执常驻，测试全绿）。**方向已实测成立**：需求方讲需求→侦探做映射（`AxisSpec.requires`），三个最缺证样本缺证 11/21/21→1/4/4；ctx-cache 连跑 4 次，修前缺证 11/5 且两轴无结论，修后两次完全一致、五轴有结论且与基线一致（仅 context_memory 因案卷自声明 `gap.exact_model_request` 而按轴规则缺证）。**但计划的验收关口（30 样本同批「缺证率不升」）仍未通过**：旧实现下为缺证 179→45、43 处降级 `not_evaluable`、3 样本端点耗尽整批失败；这三类根因已分别修（需求前置、完整读取、路由器兜底重试），**需重跑 30 样本才知是否达标**。遗留：轴自身口径待拥有者定（context_memory 是否接受「重建输入+token 校对」为充分证据） |
| B4 业务响应侧 | ⬜ | **没开工，且当下的默认路径事实上已在跑**：轮级 `turnN/records/run.request_and_response`（`business_trace/dossier.py:489`）已把响应体整包入库 + 进清单 + 可由 read 取。缺的是「需要更细时」的配置面（`response.extract` / `response.post_processor`），按计划设计随下一个有需要的业务接入再做（现在没有第二个业务在要） |
| C 清理 | ❌ | **计划前提不成立，作废**：`intent_frame` 是被代码构造、且被多项目消费的结构，不是「只写不读」。llm_probe 里 `judge.py:99` 构造、`eval_axes/adapters/fulfillment.py:128` 读取并补 `request_candidates`；但 llm_probe 的 judge prompt 只渲染 `system_prompt_extras`/`user_prompt_extras`（`core/judge.py:428/476`），所以它本身不进 llm_probe 的 prompt。别的项目是**真在用**：QA / marketting-planning / deerflow / marketting-planning-intent 读 `critical_intent_dimensions` 决定判定维度，client_search 用 `request_candidates` 拼请求文本。可删的只有 `judge_evidence` 死写入（随 A1 已删）；`build_judge_evidence_view` 是 `run_trace` payload 构建器，不是死的。**用户裁定（2026-09-22）：intent_frame 不是 trace 里 mock 传的，全局都不能动，llm_probe 项目内也不单独删——这条翻篇** |

## 0. 目标

判案证据链从「把整堆原件无损塞给每个 AI 角色」改为：

> 原件入仓库、模型只看清单、侦探按需取证、结论逐字可回仓库核对。

量化目标（2026-09-21 实测校准）：

- A1：judge payload 的 `run_trace` 部分 avg 510k → 5.6k 字符（−98.9%，25 条真实 trace 离线实测）；
- judge 总 prompt ~780k → ~275k（A1 后 process 材料 avg 262k 成为下一个大头，归 B3）；
- 分析轴单样本 prompt 输入 ~670k → ≤ 100k 字符（B3 验收 ≥80% 降幅）；
- 轴视图超 160k 比例 47% → 0（A2 预算契约强制）；
- 缺证可审计：所有 `missing_evidence` / `not_evaluable(缺证)` 附工具回执。

非目标：语义去重（AI 判相似性）；侦探改写证据；要求被测业务系统运行时声明任何信息；一次到位填死种类策略。

## 1. 已确认的决策（本方案不再讨论）

| # | 决策 | 依据 |
|---|---|---|
| D1 | 分拣分两层：长期=静态声明（机械、身份判据、代码+配置），短期=侦探运行时选择 | 「永远没用」不许由 AI 判内容得出 |
| D2 | 侦探 = 分析轴（trace_analysis），六轴不动，仍只看分析轴选段 | spec/adapter/business-trace-v1.md:74 的单闸门设计保留 |
| D3 | 机制在代码（5 个动词），策略在能力配置（前端可编辑），特殊整形走具名插件 | 对齐现有 `_PROVIDERS` 注册表与 capability_map.json 模式 |
| D4 | 默认全开、只做减法：默认全 fetchable + 自动预算；配置只接受注册过的覆盖，未注册报错 | 照抄 `impl/core/config.py:106-109` resolve_runtime_config 模式 |
| D5 | 侦探只「选择」不「塑造」：摘要/整形必须走声明式后处理 | 防止 AI 重写证据 |
| D6 | 业务侧「声明」= 运行时收据（已有）+ 接入时固化的 provider 知识 + 清单自选；不要求业务系统实时给东西 | capability_map.json `business_trace.config` 即接入面 |
| D7 | 种类策略先留空，监视驱动，用真实使用数据决定减法 | 避免拍脑袋填表 |
| D8 | intent 维持「judge 自己推断」不回滚；以后探索路径要传策展意图，走 trace 已有的 `mock_intent`/`intent_history` 字段 | spec/mock/discussion-20260907-two-intents.md；09-21 实测 payload user_intent=None 且用户文本仍在 payload 内 |
| D9 | 止血三刀顺序：judge 去快照 → 端点能力/预算契约 → 案卷改清单 | 上下文问题优先 |

动词集合（契约，定了不改）：`drop / index_only / fetchable / alias / summarize`。

## 2. 总架构

```
Layer 0  机械规整（采集时，provider 内，纯代码）：解析/去重/空字段不生成/copy_of 别名/脱敏/来源收据
Layer 1  静态分拣（机制=代码 5 动词，策略=配置 evidence_policy，默认全 fetchable）
Layer 2  清单渲染（案卷构建时，程序）：每条 → {id, kind, 时间, 尺寸, 状态, 摘要, ref}，正文不进 prompt
Layer 3  侦探=分析轴（运行时）：清单 + list/read/timeline 工具 + 取件回执 + 逐字引用校验
Layer 4  完整性检查（运行时，程序）：缺证必附回执；所有 model_call 至少被 list 过
```

安全不变式：**分拣永不销毁证据**。原始快照永远完整存于 `RunTrace.project_fields.business_trace`；`index_only/drop` 只影响视图与清单，侦探随时可 read 原文。

## 3. 主线 A：止血（不动判定行为，可立即实施）

### A1 judge 去原始快照

- 现状链路：`live.py:174-188 project_fields()` 把整份 raw 快照塞进 `fields["business_trace"]` → `core/session.py:419/435` 入 turn record → `core/judge.py:62-79 _judge_turn_view` 原样白名单进 payload（`:459`）。实测占 judge prompt 72%（avg 434k / max 1.39M）。
- 改动：`core/judge.py` `_judge_turn_view` 增加模块级排除常量 `_JUDGE_EXCLUDED_PROJECT_FIELDS = {"business_trace"}`，构建 turn view 时剔除该键。
- 不受影响面：案卷构建 `eval_axes/runner.py:193-195` 直接读 `trace.project_fields["business_trace"]`，与 judge 视图无关；judge 已有 `process_dossier`/`process_axes`（`llm_probe/judge.py:96-100`）。
- 验收：`run_trace` payload 降幅 ≥95%（离线实测 −98.9%）；重放单样本无字段缺失报错、结论与基线一致；30 样本结论对比无系统性漂移。
- 顺带删除：`core/judge.py:82 build_judge_evidence_view` 与 `llm_probe/judge.py:100`、`core/judge_execution.py:41` 的 `judge_evidence` 写入（只写不读，每次白构建 ~1.4M 结构）。

### A2 端点容量与 prompt 预检（已实施）

- `LlmEndpoint.max_prompt_chars` + `serves()`；主端点由 `llm.max_prompt_chars` 声明，备用端点由 `LLM_FALLBACK_{n}_MAX_PROMPT_CHARS` 声明（不填 = 不预检过滤）。
- 客户端预检：装不下的端点直接跳过（复用 `router.select(exclude=...)`）；**所有端点都装不下时拒绝发送**并记 `llm_request_failed`，不发请求、不毒化端点健康。
- `config_check` 新增 `llm_prompt_budget_unservable`：声明预算超过端点上限时启动即报。
- 实测容量（2026-09-21，尾部 nonce 可见性探测）：

| 端点 | 模型 | 实测 | 声明 |
|---|---|---|---|
| primary `8.148.158.241:3131` | gemini-3.8-flash-medium | `Token error: Token pool is empty`（配额耗尽，无法测量） | 未声明 |
| fallback1 `127.0.0.1:8060` | cursor-grok-4.6-medium-fast | 184,320 字符接受；204,800 起 HTTP 413 `Prompt too large` | 184320 |
| fallback2 `tokenrhythm.studio` | qwen3.8-flash | 384,000 字符全量可见；409,600 起 `finish=length` 且**尾部丢失（静默截断）** | 384000 |

  旁证：fallback2 在 307,200 字符时计 204,849 tokens，说明真实窗口（约 256k tokens）远大于 `config.yaml` 声明的 `context_window_tokens: 131072`；声明值不准且无校验。
- 待办（不属于 A2）：装配侧预算（`MAIN_VIEW_BUDGET_CHARS` / `trace_analysis.py` / `process_common.py`）改为「超限即记缺证」，随 B1/B3 落地；`dossier.py:205 admit()` 尺寸感知修复并入 B1。

### A3 端点垃圾内容记失败

- 现状：配额提示 / `Prompt too large (N chars)` 以 HTTP 200 返回 → `llm_client.py` 记 success → `record_success` 刷新 `last_health_at` → 死端点永不 stale、永不探测（实测 470/500 调用打去欠费端点）。
- 改动：响应落库前做内容形态检查（可扩展的模式清单：`Prompt too large`、配额/欠费通知模板），命中 → 走 `router.record_failure`（计入 `FAILURE_THRESHOLD=2`、冷却 180s），本次调用按协议失败处理，不进 salvage。
- 验收：构造返回配额文本的 stub 端点，断言 router 在 2 次内将其冷却并切换。

### A4 调用小票整治

- `core/context_store.py:159-161`：同一次逻辑调用的重试只保留最后一条 + `retry_count`（按请求内容 hash 归并）。
- 批次体检摘要（每调用：prompt 字符数、端点、模型、成败、失败类别）写入 run/batch 结果（`server/batch_jobs.py` / pipeline 产物），不依赖 500 条滚动窗口回溯。

## 4. 主线 B：证据链机制（分步验收，不过即停）

### B1 纯测量（零行为变更）

已完成（含三项前置补齐，全量测试 1368 passed）：

- 交付：`build_manifest` / `manifest_ids`（瘦身口径已固化：80 字预览、空键不写、异常才写字段状态）；`MANIFEST_PREVIEW_CHARS=80`。
- **案卷补登记本轮最终回答**：每轮新增 `turnN.final_output` 记录（`ref` → `turnN/records/run/content`，值与采集快照逐字一致），34/34 轮次无遗漏。此前轴想引用「本轮最终回答」只能自造编号。
- **骨架瘦身**：`build_overview` 不再携带 `model_calls` 正文与 `coverage` 冗长说明（详细限制已由 gaps 登记）。
- 组织者整理阶段：536,297 → 83,554 字符（−84.4%），最大 167,063。
- 下游轴视图（210 个）：99,712 → 6,810（−93.2%），最差单个视图 −65.8%；超过 160k 的视图 47 → 0。
- 历史引用可达性：735 条引用，710 条直接命中，24 条「编号后粘说明」书写毛病，1 条为自造编号（该材料现已登记）。
- 仍不足：小案卷逐样本压缩 4/30～6/30 不到 60%（天花板是骨架）；清单里 `ref` 与 `id` 重复，待 read 工具到位后去掉。

- `business_trace/dossier.py` 增加清单渲染器：按默认策略（全 fetchable + 自动内联阈值）产出每条 `{id, kind, time, size, status, summary, ref}`；正文仍走旧路径。
- 测量脚本（复用 `scripts/_replay_process_dossier_tmp.py` 冻结样本）输出：各类 prompt 尺寸 X→Y、压缩率、历史判词引用证据的清单可达性。
- 验收：压缩率 ≥60%；历史判词引用证据 100% 可经「清单+read」到达。报告落 `report/process-dossier-20260920/`。

### B2 可达性抽查（人工）

- 从 30 样本挑 5 个已有人工结论的，只用「清单+read」重走取证。
- 验收：5/5 可达；记录每例取证步数与读入字符数（作为 B3 侦探预算的标定依据）。

### B3 分析轴侦探化（已实施，单样本端到端实测）

已落地：

- `business_trace/tools.py`：`EvidenceIndex` 取证件（清单之外只能从这里读正文）+ 四个 agno 工具（read/search/timeline/verify_quote）；每次调用写回执，`dossier_read` 的回执就是「读过」的证据。节点超过 12000 字返回结构图让你下钻，不静默截断。
- `trace_analysis.py`：输入从「逐段读全文」改为「清单 + 工具」；`build_chunks`/`CHUNK_CHARS` 已删。
- Layer 4 `enforce_receipts`：引用必须（a）在清单里、（b）正文有读取回执（gaps 例外，它的理由已在清单里）；不满足就剔除并写进 `structure.evidence_audit` + `coverage_note`。空选段也留痕（否则那个轴会静默变成 `not_evaluable`）。
- `process_common.py` 六轴一行未动（`tools=[]` 保持）。

样本 `frozen--snap-cash-value`（冻结快照，单 workers）：

| 项 | 旧（逐段读全文） | 新（清单+侦探） |
|---|---|---|
| 组织者首轮 prompt | 248,613 字符 | **72,328（−70.9%）** |
| 组织者工具往返累计 | — | 32 次调用 / 读 29 个编号（首轮+工具回灌的总额未测，见开放项） |
| 六轴视图 prompt 合计 | 544,122 | **411,581（−24.4%）** |
| 选段引用数 | 88 | 51 |
| 六轴结论 | 全出结论（1 problematic） | **全出结论**（2 problematic、4 sound），**5/6 与基线逐格一致** |

唯一结论差异：`context_memory` `sound` → `problematic`。**不是缺证导致**（该轴拿到 10 条选段）：新判词依据的是同两份材料里三件具体事实——后端 hint「未查询到该保单，请核对保单号」没有进模型 messages、注入的 skill 正例里带着同保单号的假数据「P002 现金价值 125,300.00 元」、以及「禁重试」与「policy-query 要求再查」未消解的指令冲突。旧判词也看到了这三点（称其为「理论上的混淆风险」但判 pass）。属于对同一材料的判定宽严之差，需人工 oracle 复核，不能单方面当改进。

### B3 细粒度修正：读取粒度 = 引用粒度 = 渲染粒度

改前的真实口子（实测量的，不是推测）：整理员按 12k 结构图下钻、只读了 `session_state` 的 3 个片段，
视图却把 **29.7k 整棵子树**倒给 4 个轴（同一份正文进 4 个 prompt）。B1 当时量的「轴视图平均 8.5k」
用的是历史较窄的选段，低估了这个风险。

修正（三处同口径）：

1. **超过单条上限（`EVIDENCE_NODE_CHARS=12000`）的记录**：视图只给「整理员逐字读过的片段（`read_paths`）」
   + 其余部分的结构图（`shape`）+ 显式说明；未读到的正文不在视图里，轴只能报缺证。
2. **读到结构图不算读到正文**（`shape_only` 回执）：这种编号不可引用（剔除并单独记在
   `evidence_audit.shape_only`），要引用就必须 `path` 下钻把正文读出来。
3. **轴的材料需要声明（`AxisSpec.needs`）**：每轴声明依赖哪几类记录（上下文轴 → `model_calls`、
   工具轴 → `tool_calls`…），写进整理员 prompt，并在审计里报出「某轴没拿到它依赖的类别」。

为什么需要第 3 条：**实测发现轴的检查集是从材料推出来的**——上下文轴的 checks 是「每个 `model_calls` 三项」，
整理员没选 `model_calls` 时它的 6 项检查整体塌缩成 1 项 `model_input_availability`，轴静默降级成
`not_evaluable`（看起来像诚实缺证，实际是选材失误）。

同一样本 4 轮实测（冻结快照 `snap-cash-value`，workers=1，单样本 8–16 分钟）：

| 轮次 | 选段 | 读取 | 工具调用 | 轴结论 | 六轴 prompt | 审计 |
|---|---|---|---|---|---|---|
| 基线（逐段读全文） | — | — | 0 | 6/6 出结论（1 problematic） | 544,122 | — |
| B3 改前 | 51 | 29 | 32 | 6/6（context_memory 翻成 problematic） | 411,581 | 3 条剔除（未读） |
| 细粒度版（上限 32） | 35 | 18 | 32（碰顶） | 4/6（两轴 not_evaluable） | 288,499 | 零异常 |
| 细粒度 + needs（上限 48） | **61** | **33** | 49（碰顶） | **6/6，5/6 与基线一致** | 384,287 | **零异常** |

关键诚实点：

- 改前那轮看着「6/6 全出结论」，但它的 context_memory 是踩着 29.7k 冗余正文得出的；
- 细粒度版省了 30% 却**掉了两轴**（工具预算 32 被「下钻读正文」用光）——这正是「缺证率不升」作为验收线的意义；
- 加上 needs + 预算提到 48 后，选段比改前更多（61 vs 51）、轴 prompt 仍更低（384k vs 412k），且**审计零异常**；
- 工具预算 48 仍被碰顶（49 次）：这个预算已是卡脖子项，不能再靠加预算提覆盖。

### B3 30 样本同批对比（计划的验收关口：未通过）

`scripts/_b3_comparison_tmp.py` 对同一批 30 个冻结样本，用基线（逐段读全文，`results/`）对现在
（清单 + 侦探，`verify-b3-full/`）逐轴比。产物 `report/process-dossier-20260920/evidence-index/b3-comparison.{md,json}`。

| 轴 | 结论一致 | 检查项 现在/基线 | 缺证项 现在→基线 | 缺证率 现在→基线 | 视图字符 现在/不限单条/基线 |
|---|---|---|---|---|---|
| trace_analysis | 27/30 | — | — | — | — |
| intent_understanding | 22/30 | 135/130 | 5→0 | 4%→0% | 34,330 / 52,175 / 75,226 |
| planning_routing | 23/30 | 135/129 | 6→0 | 4%→0% | 40,266 / 54,643 / 88,638 |
| tool_execution | 13/30 | 108/84 | 32→8 | 30%→10% | 37,389 / 58,703 / 83,998 |
| context_memory | 9/30 | 179/101 | **100→22** | **56%→22%** | 45,916 / 54,032 / 102,668 |
| knowledge_data | 21/30 | 54/50 | 6→2 | 11%→4% | 34,250 / 53,691 / 78,935 |
| model_capability | 15/30 | 81/64 | 30→13 | 37%→20% | 45,163 / 45,163 / 80,894 |

- 主轴 fulfillment 与基线一致 **18/30**；80 处轴结论变化，**43 处降级为 `not_evaluable`**（36 处是 `sound → not_evaluable`）。
- 缺证项合计 **179（现在）vs 45（基线）**：缺证率不是「多出检查项」造成的——各轴缺证率本身也翻了 1.8–2.5 倍。
- 整理阶段：选段 45 条、读取 33 个编号、工具调用 54.5 次、清单 85.0k 字符；**审计丢掉 59 条无回执引用 + 26 条只读到结构图**。
- **11/30 样本出现「某轴没拿到它依赖的类别」**（needs 审计报出），其中一个样本六个轴全部塌缩。
- **3/30 样本整批失败**：`AxisRequestFailed: llm_request_failed`（`no untried llm endpoint remains`）。可用端点只剩一个时，同一请求内「每个端点只试一次」的规则让一次瞬时错误直接杀掉整轴（`llm_router.select`）。

**为什么证据变薄（用数据分开两种原因）**：同一份整理员选段，按生产口径渲染 vs 不限单条渲染 vs 基线的「全部记录」，
三档是 34–46k / 45–59k / 75–103k。即：**「单条超限只给读过的片段」这一刀只占约 20–25%，
主要差距来自整理员选得比基线窄（−45%）**。也就是说，B3 的缺证上升主要不是限额造成的，而是「侦探只选它认为需要的」这个设计本身。

**因此 B3 的结论（诚实版）**：可核查性达成（每条引用都有正文回执、剔除全部留痕），
但**证据交付量显著下降、缺证率 4 倍、主轴一致率 60%**——按计划自己的验收线（缺证率不升），这一步**不通过**，
需要下一步决定：是接受这个代价（换取可核查性），还是把「侦探选段」做成「选段 + 程序化补齐」。

### B3 决策岔路口：原结论是「按下游需求取证」，B3 把「看全」的保证弄丢了

原结论（三处一致，未变过）：

- `spec/adapter/business-trace-v1.md:101`：分析轴「每段产出行动路线与**每个下游轴需要哪些编号**（只写编号与一句话用途，不写证据正文）」；
- `spec/adapter/judge-process-eval-plan-20260920.md:24`：LLM 的职责是「分析行动路线、**判断下游需要哪些信息**」；
- 同一句回链：`report/process-dossier-20260920/README.md:27`；契约落地物就是 `selections[axis] = {refs, why}`（单闸门，六轴不各自读全文）。

**这条契约没有丢**：`trace_analysis` 至今仍按轴产出 `refs + why`，六轴仍只看自己那份视图。

丢的是**「看全」这一保证**。老设计里「读遍全文」由程序保证——`CHUNK_CHARS=100k` 分片「读完为止」，选段是在
看过全部材料的基础上做的（`report/process-dossier-20260920/README.md` 效果表）。B3 换成「清单 + 按需读」后，
**可见性从「程序保证」变成「整理员自己找得到」**，于是漏选，缺证 4 倍。

与此并存的还有一处口径冲突，必须在下一步一起定：

- `business-trace-v1.md:107`：轴需要却不在视图内的材料**一律按缺证处理**（设计内后果）；
- 本计划风险表：验收线是**缺证率不升**。

两者只有在「可见性由程序保证」时才同时成立。当前实现只做到「诚实暴露缺证」，没做到「不缺证」。

给下游的需求也偏粗：整理员拿到的是每轴**一句话问题**（`question`）+ 排除项 + 类别级 `needs`（本次新增，实测只能报不能拦），
而每轴真正要跑的**检查项**（如上下文轴 = 每次模型调用三项）没有传给整理员，程序也没按它验收。

**用户裁定（2026-09-22），方向定为：需求方把需求讲清楚，侦探做「需求 → 材料」的映射。**

- 下游（六轴）是需求方：用业务语言声明「我要判断什么、需要看到什么证据」，**不含实现细节**——不写检查项编号、不写案卷类别/字段名；
- 侦探（分析轴）能看到案卷全部细节：拿需求说明 + trace 细节 + 业务 API 细节，自己分析出这些需求对应案卷里哪些编号；
- **被否决的做法**：把检查清单传给侦探（检查项是下游的实现细节，不该出现在需求描述里）；程序事后把材料直接补进轴视图（破坏单一闸门——轴只能看到侦探读过的东西）；校验只报告、不打补丁。

落地（本次已实施）：`AxisSpec` 新增 `requires`（需求说明，业务语言）；`downstream_questions` 携带 `requires`
（替换原类别级 needs 提示）；`needs`（案卷类别）只留作程序侧的塌缩审计，不进侦探 prompt。

B2 的数字仍是预算标定依据：历史判词逐条复核要 72–157 次读取，说明「按需读」覆盖不了「全面复核」——
**需求的粒度决定预算，不是预算决定覆盖**；requires 里写明的「一次都不能少」直接决定整理员要读多少。

### B3 方向验收：requires 前置（3 样本实测，2026-09-22）

改动：`AxisSpec.requires`（需求方业务语言的需求说明）→ `downstream_questions` 携带 `requires`（不再给类别级 needs 提示）；
`needs`（类别）只留作程序侧塌缩审计。另修两处工作条件：路由器兜底重试（全部端点试过之后，未进冷却的端点各再给一次机会；
一次性瞬时故障不再杀掉整轴）、`TOOL_CALL_LIMIT` 48→64。

三个最缺证样本，同批对照（基线 = `results/` 旧实现）：

| 样本 | 基线六轴 | b3-full（needs 版） | requires 版（b3f） |
| --- | --- | --- | --- |
| baseline-insured-name | 全部有结论，tool=sound，context=problematic | 缺证 11（context 6/6、model 3/3 缺） | 缺证 1；tool=sound、context=problematic、intent/planning/knowledge=sound；仅 model_capability 1/3 缺 |
| ctx-ref | tool/context/knowledge 均 not_evaluable | 缺证 21 | 缺证 4；tool/intent/planning/knowledge=sound、context/model=problematic |
| ctx-cache | 全 sound | 六轴全 not_evaluable | b3e：全轴有结论（tool sound）；b3f：整理员引了 46 个没读过的编号，被闸门剔除 → 全轴塌缩 |

结论：**「需求方讲清需求、侦探做映射」这条方向成立**——缺证量级从两位数掉到个位数，tool_execution 在补上「还要能看到本轮超时/时限上限」这句需求后回到 sound（该依据本来就在案卷里，只是没被选进去）。

残留缺证分三类，性质不同：

1. **单节点 12000 字上限卡住的「整页工具回填」**（如 `messages/3` 40921 字）：整理员读它只能拿到结构图，轴视图里也就只剩结构图
   → 轴按缺证处理。旧实现因为整棵倒出所以能判。**这是 B3 分片上限的直接代价，目前是残留缺证的主因**。
2. **轴自身的口径**：context_memory 的 sufficiency 规则写明「完整请求缺失时必须缺证」，而案卷自己声明了
   `gap.exact_model_request`（trace 没存原始 SDK 请求）。旧实现判 sound，是因为它把「重建消息 + token 对得上」
   当成了足够证据。守规则 vs 宽松，需要轴拥有者定口径。
3. **整理员行为**：引用检索片段/父编号（没有正文回执）→ 闸门剔除 → 整轴塌缩（ctx-cache b3f）。
   已在工具说明与整理员 prompt 里写明「检索片段/清单摘要/结构图都不算读过」「引用要精确到你读的那一段」。

已修（2026-09-22）：第 1 类——整理员可带 `full=true` 对超大节点申请一次完整读取（上限 `EVIDENCE_FULL_READ_CHARS=80k`），
回执算读过正文，轴视图的 `read_paths` 带上整段，去留由轴视图预算（160k）决定。理由：用户的模型是「侦探能看到案卷全部细节」，
单条 12k 上限让侦探对整页工具回填（40921 字）根本读不到正文，需求再怎么讲都落不了地——这是能力缺失，不是打补丁。
（同时把 `_render_capped_record` 的「多条片段累计受 12k 约束」改成「按每条自己的上限判断」，总量由轴视图预算兜住。）

仍待轴拥有者定口径：context_memory 的 sufficiency 是否接受「重建输入 + token 校对」为充分证据（案卷自己声明了
`gap.exact_model_request`，按轴现规则必须缺证；旧实现判 sound）。**这是口径问题，不是选材问题，程序不代答。**

**完整读取 + 回执常驻（2026-09-22，ctx-cache 连跑 4 次）**：修完上面两条后，ctx-cache 两次同代码连跑结果完全一致
（b3i1/b3i2）：intent/planning/tool/knowledge/model_capability 五轴全部有结论且与基线一致，缺证只剩 4 项，
**全部来自 `turn1/turn2.gap.exact_model_request`**（trace 自己声明没存原始 SDK 请求）；整理员每次申请 2 次完整读取
（40921 字整页），结构图残留 0、无回执引用 0。修复前（b3g1/g2）同一命令：缺证 11 / 5，model_capability 两次都缺证。

修的两个程序缺陷：
1. `structure['evidence_audit']` 原来只在「有异常」时才写 → 一切干净那次回执全丢，轴视图 `read_paths` 为空，
   整理员读过的整页正文在轴上又变成缺证。**回执是轴的唯一可见性来源，必须每次随结构下发**（已改为无条件写入）。
2. `_render_capped_record` 原来让同一条记录的所有片段累计受 12k 约束，现在按每条自己的上限判断（完整读取 80k），
   总量由轴视图预算兜住。

**同代码同样本的可复现性（重要）**：ctx-cache 连跑两次（verify-b3g1/g2，代码相同）：
g1 = tool sound / context not_evaluable；g2 = tool not_evaluable / context problematic。**同一输入下 2 个轴翻转**
→ 单样本的轴判定有 ±2 轴噪声；30 样本对比里的 43 处降级 / 19 处升级必须按这个噪声地板来读（180 个轴位）。

### B3 成本结构（为下一步定方向）

六轴视图 331,480 字符的构成（run b3c）：

| 部件 | 字符 | 占总 | 说明 |
|---|---|---|---|
| `records` | 188,916 | 57% | 真正选中的证据（每轴 25–38k） |
| `structure` | 73,824 | 22% | 整理员的行动路线，**同一份在 6 个 prompt 里各一份** |
| `coverage` | 48,126 | 15% | 采集覆盖报告，**同样 6 份** |
| 其余 | 20,614 | 6% | 时间线/model_calls/gaps/阅读说明 |

即：**37% 的轴 prompt 是同一份内容重复 6 次**，与证据多少无关，是固定开销，也是下一步最确定的省钱点。

### B3 交互形态改造：目录有真信息 + 先规划后取（2026-09-22，方案见 `evidence-catalog-plan-20260922.md`）

B3 的成本结构查出「95% 是重复发送、病根是 8~44 轮往返」之后，按 08-30 验证过的 outline 模式重做侦探交互：

- `build_catalog` 取代清单：每编号一行**程序生成的语义摘要**（工具名/状态/耗时/大小/宿主引用/正文开头），
  外置正文块反查宿主（「步骤 gate 的 fields/output 正文」），深嵌正文按直接宿主归并；旧清单平均 83,554 字 → 新目录平均 25,003 字（−70%），编号一个不丢。
- `dossier_collect` 批量取件：一次取回几十条编号；**大记录按体积从小到大装回能装下的小片段并逐段留回执**，
  装不下的登记路径——原来「大记录只能拿结构图、下钻要再花一轮」的两轮模式被压成一趟。
- 机械核验打回：输出里出现没有读取回执的编号 → 重做一次（补取或删掉），仍不改才剔除（对齐 outline 模式的「引用逐字核验打回」）。
- `TOOL_CALL_LIMIT` 64 → 12。

同批 3 样本实测（旧 = b3c/b3i1/b3d）：

| 样本 | 耗时 旧→cat1→cat3→cat4 | 侦探工具调用 | 选段数 旧→新 | 缺证 旧→新 | 无回执引用 |
|---|---|---|---|---|---|
| snap-cash-value | 683s → 386 → 348 → **335** | 49 → 13 → 12 → **6** | 61 → 54 | 0 → 3 | 0 → **10 → 0** |
| ctx-cache | 813s → 349 → 338 → **296** | 73 → 13 → 6 → **4** | 90 → 49 | 4 → **2** | 0 |
| ctx-ref | 1170s → 374 → **273** | 47 → 14 → 8 | 106 → 50 | 5 → **2** | 1 → 0 |

结论（诚实版）：**成本与耗时降 50%~70%**（往返被 collect 吃掉，末轮会话从 23~66 万降到 15~23 万字符），
ctx-cache/ctx-ref 缺证下降；snap 的 3 处缺证里 1 处是真实缺口（该 trace 的案卷里根本没有时限依据，
轴的 `latency_acceptable` 只能报缺证），2 处是 context_memory 的历史口径问题（各轮都有 3~4 处）。
cat1 曾因「引用了没取回的编号」被静默剔除 10 处、连带两个轴退化——**这正是 outline 模式里「机械核验打回重试」该在的位置**，加上后归零。

新挖到的平台缺陷（已修）：
6. **source 编号从来读不了**：`EvidenceIndex._body` 对 source 传 `{"content_ref": <dict>}`，`render_value` 直接
   `TypeError: unhashable type: 'dict'`。旧流程没人读 source 所以没暴露，目录把 source 列出来后立刻踩到。
7. **大记录只能拿结构图**：27k~144k 的会话状态记录里真正要看的时限/耗时/计数全在小字段里，
   而「拿结构图 → 再下钻」要两轮，工具预算（12 次）被烧光——改成 collect 一趟装回小片段（逐段留回执）。

### B3 实测挖出的平台缺陷（已修）

1. **端点回了 200 但产出不可用 → 被记为成功且不切端点**（最严重）：整理阶段两次拿到空产出，六轴全部静默降级成 `not_evaluable`，看起来像「诚实缺证」。修法：`llm_client._usable_structured()` 在重试循环**内部**预检产出能不能当结构化输出用，不能就 `RuntimeError` → `record_failure` → 切下一个端点。
2. **中转站把上游 4xx 当 200 回吐成 JSON**：实测主端点把 `{"error": {"code": 400, "message": "User location is not supported for the API use."}}` 当正文返回，于是被当成模型产出。修法：`provider_error_body()` 增认「只含一个 error 键」的 JSON 错误体。
3. **工具调用的消息带 pydantic 对象 → 调用记录整条丢失**：`save_context` 抛错被 `except Exception: pass` 吞掉，用了工具的调用在 context store 里查不到（成本审计看不见）。修法：`_extract_messages` 过 `_json_safe()` 拍平。
4. **路径契约拒绝带本机绝对路径的记录 → 又一层静默丢弃**（补 #3 后实测到的真根因）：模型把记录编号当文件路径写成 `tool_args.path = /Users/...`，`portable_artifact` 报 `PathContractError: PATH_SCHEMA_BYPASS`，异常同样被吞。**这不是新 bug**：旧批次有一次实测的轴记录目录（`axes-1ad8ddab76ad:replay-snap-cash-value`）整个是空的，同一个原因。修法：`redact_forbidden_paths()` 在 `portable_artifact` 里用**同一套谓词**隐去会被拒的绝对路径（相对引用 `turn1/records/run` 与普通字符串原样保留），`_track_context` 不再静默失败。实测：整理阶段调用记录现在能落档，`prompt_size=175,339`。
5. **本地 cursor 桥不支持 tool calls，却一直在降级链里吃废产出**：它把工具调用拼成正文里的 `___TOOL_CALL___` 标记，工具名还会拼错（`dossier_timeline` → `dossiersearch`），第二次直接吐 JSON 数组；整理阶段两次尝试全被结构化协议阻断 → 六轴全缺证。修法（A5）：`LlmEndpoint.tool_calls` + `serves(prompt_chars, needs_tools=)`，`LLM_FALLBACK_1_TOOL_CALLS=false`。实测：从「两次废产出、六轴全缺证」变为 `llm_attempts: 1`、直接打到 fallback2 拿到真产出。

### B3 未达标的项（诚实记录）

- 分析轴首轮 prompt 降 **70.9%**，**未达 ≥80% 验收线**（小案卷是天花板：旧口径 248k 里 overview 只占 19k，其余是必读正文）。
- 六轴 prompt 544,122→384,287（−29.4%），同样未达 ≥80%；但**单轴都 ≤100k（56–72k）**。
- **总上下文成本不降反升**：单样本旧口径是单次请求 248,613 字符；新口径首轮 72,327 字符，49 次工具往返回灌后
  **末次请求 216,236 字符**。即使按缓存命中算也不省钱——**赢的是可核查性与上限解除，不是省 token**。
  旧口径真正的问题不是贵，是装不下（组织者 prompt 最大 1,983,919 字符、47 个轴视图 >160k，任何端点都拒）。
- 工具预算 32→48 仍被碰顶（实测 49 次）：不是调数字能解决的，要么换交互形态（批量读取），要么砍固定开销（见成本结构）。
- 缺证率：本样本未升（6/6 轴出结论、审计零异常）；30 样本同批对比运行中（`report/process-dossier-20260920/verify-b3-full/`）。
- **发现但未处理**：轴的检查集由材料推导（上下文轴 = 每个 model_calls 三项）——选材失误会让检查项整类消失，
  看起来像「本轴项少」而不是「材料丢了」。needs 只能把它报出来，不能阻止它发生。
- 另一件仍未处理：`outputs/insurance-e2e-20260921/run/axes_run.py:49` 自建端点直连（不受 A2/A3/A5 约束）。
- 方法论教训（已写进代码）：**`except Exception: pass` 是这次一半缺陷的藏身之处**；两处已改成必留痕。


### B4 业务响应侧（随下一个有需要的业务接入再做）

- 默认（零配置）：响应体整包入库 + 清单条目 + 按需 read。
- 需要更细时：能力配置声明 `extract`（JSON pointer，同 bindings 模式）或挂具名 `post_processor` 插件（注册表模式同 `_PROVIDERS`）。

## 5. 主线 C：清理（已作废，2026-09-22）

- ~~删除死结构 `intent_frame` 构建与透传（grep 确认只写不读后删）~~：**前提是错的**。`intent_frame` 在 llm_probe 内部就是活的：
  `eval_axes/adapters/fulfillment.py:102/128` 自己构造并读取它，`core/judge.py:585` / `judge_execution.py:37` / `judge.py:99` 把它交给 judge；
  另有 9 个项目的 judge 在用，`build_intent_frame` 还是 `judge_protocol.py:162` 的扩展点。**这一条不该执行**。
- 真正删掉的死结构：`judge_evidence` 的写入（只写不读，随 A1 删）；注意 `build_judge_evidence_view` 不是死的——它是 `run_trace` payload 的构建器（`core/judge.py:473`）。
- intent 决策固化为测试：live 路径 payload 不出现 `user_intent` 键（judge 自行推断）；若未来支持 `from_trace`，断言 `mock_intent`/`intent_history` 为唯一来源。

## 6. 配置面（未开工）

现状：全仓 grep 无 `evidence_policy` / `inline_budget_chars` / `post_processor`（`impl/`、`tests/` 均为零命中）——配置面一行没写，默认全开只做减法的策略目前**只存在于代码常量里**（`VIEW_BUDGET_CHARS`、`EVIDENCE_NODE_CHARS`、`MANIFEST_PREVIEW_CHARS`），前端改不了。
等 B3 方向定案再动：`evidence_policy.kinds` 正是「种类减法」（D7）的载体，现在没有减法数据可喂。

`impl/data/llm_probe/capability_map.json` 的 `business_trace` 邻居新增（默认预填，只做减法）：

```json
"evidence_policy": {
  "inline_budget_chars": "auto",
  "default_disposition": "fetchable",
  "kinds": { "definitions": "fetchable", "...": "fetchable" },
  "response": { "extract": [], "post_processor": null }
}
```

- 合并与校验：注册表制（未注册键报错），同 `resolve_runtime_config`；`auto` = 端点能力推导。
- 前端：展示「当前生效策略」（默认预填满），编辑动作仅三种：某类改 `index_only/排除`、预算调小、挂插件。

## 7. 监视（未开工）

现状：没有按 kind 统计的 {list/read/入选段次数}；能拿到的最接近物是 B2/B3 的一次性离线脚本（`scripts/_measure_evidence_index_tmp.py`、`_b3_comparison_tmp.py`）。而 B3 实测恰好证明这套监视是必需品：**11/30 样本出现过「某轴没拿到它依赖的类别」**，没有按 kind 的命中率就无法事前发现，只能等轴变 `not_evaluable` 才知道。

随 run 结果持久化：每类记录的 {出现次数, 尺寸分布, 被 list 次数, 被 read 次数, 入选段次数}，缺证率，各角色 prompt 尺寸。用于驱动种类减法（D7）与预算标定。

## 8. 测试计划

- 单元：分拣动词语义、admit() 尺寸感知、重试去重、预算校验、垃圾内容识别、清单渲染、引用逐字校验。
- 回归：冻结 30 样本重放，A1 后 judge 结论漂移报告；B3 后轴结论一致性报告。
- 现有 1319 测试保持通过（3 个既有无关失败除外）。

## 9. 回滚

每主线独立开关：`evidence_policy` 缺省即旧行为（B 线）；A1/A2/A3 各为独立小改可单独 revert。快照仍完整存于 trace，任何阶段不丢证据。

## 10. 风险

| 风险 | 对冲 |
|---|---|
| 侦探漏看 → 缺证变多 | 回执强制 + Layer 4 完整性检查 + B3 验收线「缺证率不升」 |
| 种类级分拣粒度粗（states 藏业务 facts） | 粗分拣只砍确定部分，精细挑选归侦探 |
| 动词集合成为契约后扩展需改代码 | 一次定 5 个；新增走评审 |
| 默认全开比手调费上下文 | 通用动作已砍大头；残余由监视驱动减法 |

## 11. 实施顺序

```
A1 → A3 → A2 → A4（止血，彼此独立）
B1 → B2 → B3（每步验收，C 穿插）
B4（随业务接入）
```
