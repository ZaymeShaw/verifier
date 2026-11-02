# 过程六轴：按环节契约判定 实施方案（2026-09-29）

上承 `spec/math-abstract/process-axes.md`（W1，环节归属 π + 局部内核 K）与 `process-axes-plan-20260927.md`（W1–W4 已完成部分）。
本方案不推翻 W1：环节链路、π、K 保留，改的是"契约从哪来"、"一个事件能否记多个环节"、"分析轴产出什么"、"判定结果长什么样"。

## 0. 要解决的问题（实测）

`report/process-axes-live-20260928`（32 条前端实跑）里，程序按时间先后确定检出 12 条用例存在"看到不可重试结果后仍同参再调"：

| 模型轴决策项 | 规划轴重试项 | 用例数 |
|---|---|---:|
| pass | fail | 9 |
| fail | fail | 2 |
| pass | pass | 1（E02，重试 4 次） |

另有规划轴写"无重复调用 → not_applicable"而程序检出了重复。根因不在状态枚举，而在一次判定的三件事都交给评测模型临场决定：

1. **判谁**（哪个环节）——靠它理解轴描述，所以容量拒绝被记成工具故障；
2. **按什么判**（义务及出处）——靠它临场编，所以同一事件判法不一致；B01 模型提示词里只写了"EMPTY/不可用/BUDGET 不重试、DENIED 不重试"，没写 UPSTREAM/`retryable:false`，模型轴却判"违反输入契约"；
3. **发生了什么**（事件）——靠它在长 trace 里自己找，所以会漏；一个检查项要一次判完本轮全部 7 次模型调用。

## 1. 边界约束

- **llm_probe 是公共层**：只认 Agno 的结构（workflow step / Condition / Router / Loop、agent run、model call、tool call、session/state、definition）。不读、不适配任何业务代码。
- **业务语义由评测模型从 trace 内容里判**：结果信封里的 EMPTY、BUDGET、"不可重试"等不写死键名。
- **只归到环节**，报清问题和现象；不做业务代码内部归因（"编排没拦住同参重试"即止）。
- **看不到的不猜**：Agno 没记下的只按可见效果判；看不清就是看不清。业务写进 session_state 的机制（如去重缓存、预算计数、门控决策）是 Agno 记录的一部分，照常读取。
- **地图是先验，不是边界**：环节类型表用来指导分析轴去哪找、各轴怎么判；表外的东西照样列为环节、照样判，只多一个"类型未在地图中"标注。

## 2. 判定抽象的修订（W1 增补）

### 2.1 判定单元

一次判定 = **一条义务 × 一个环节实例**。

```
义务 Obligation（按环节类型写模板；内容从 trace 读）
  link_type   : ι | ρ | χ | σ | μ | κ         # 决定归哪个轴（π 不变）
  situation   : 何种情形下适用                 # 例：上一次同名同参调用的结果已表明重试无效
  duty        : 应做到什么                     # 例：不再原样发出 / 系统不放行
  source      : 出处——trace 中的原文指针       # system_message、工具 description、步骤定义、结果正文、项目声明
  judged_by   : program | llm                  # 能机器判的由程序判
```

### 2.2 出处层级（义务从哪来）

1. **Agno 通用语义**（llm_probe 内置，所有业务共用）：工具返回的对象应是请求的对象；步骤 N 的产出应原义到达步骤 N+1；Condition 按声明条件分支；Loop 按上限终止；模型按收到的输入决策。
2. **运行时记录**（从 trace 读，Agno 通用容器，内容由评测模型按语义读）：
   - 定义：workflow `steps`（步骤、Condition 结构）、agent `model/system_message/response_settings`（含 output_schema、重试次数）、每个工具 `description/parameters`；
   - 运行：run `input/output/status/metrics`；step `input/output/success/error/耗时`；模型调用 `model/invocation_parameters/token 数/耗时`（input/output 目前被隐藏，见 P0）；
   - 消息：每条 message 的 role、content、tool_calls/arguments、`from_history`；
   - 工具调用：`arguments/result/error/耗时/tool_description`；
   - 会话与状态：`session_state`（本业务里有 `budget.tool_result_cache`、`budget.deduplicated_tool_calls`、`budget.tool_call_counts`、各类预算计数与上限、`route.decision` 含门控理由、`evidence`、`entities`）、`chat_history`、`session_summary`；
   - 输出：落库输出、调用方实收输出。

   其中 session_state 的键名是业务自定的，程序不写死，由评测模型按语义识别（例：看到 `deduplicated_tool_calls: 4` 与缓存键即可判断重复调用被缓存吞掉）。
3. **项目声明**（`project.yaml` 一处写，仅限 trace 里读不到、又需要判的约定）：例如本次用户确认的"收到不可重试结果后，编排应拦住同参重试"。必须少而显式，每条带确认日期。

找不到任何出处 → 结果为 **契约缺失**，不判 pass/fail，汇总后交用户决定是否补一条项目声明。

### 2.3 承诺表修订

| 原承诺 | 修订 |
|---|---|
| 偏差记在首个出错环节 | **每个环节按自己的义务判**。一次事件可同时违反两个环节的义务（重试：μ 违反模型收到的规则 + ρ 违反项目声明），各自引用各自的出处；与已有"多环节出错不去重"一致 |
| 边界看不到时共担并标"未定位" | 不变 |
| 已判出的偏差不被程序抹掉 | 不变 |
| 平台永久缺口不制造"看不清" | 按 §3 结果重新核定哪些缺口仍是永久的 |
| （新增）义务必须有出处 | 无出处不得 fail，也不得 pass；记"契约缺失" |
| （新增）地图外环节照常判定 | 标"类型未在地图中"，不丢弃 |

### 2.4 结果结构

```
LinkResult
  obligation_id, link_id
  outcome           : pass | fail | insufficient_evidence | not_applicable | contract_missing
  expected          : 义务在该环节上的具体要求（引用 source）
  observed          : 实际看到了什么
  evidence          : { input: [refs], output: [refs] }     # 两端分开
  missing           : 缺哪一端（仅 insufficient_evidence）
  flags             : 程序标注（不改结论）
```

- 四个原状态保留（覆盖"未发生 / 看不清 / 做到 / 没做到"），新增 `contract_missing`。
- 轴级：按轴汇总 LinkResult；有 fail → problematic；有 contract_missing 单列计数，不参与 sound 判定。
- 不加严重度、根因角色等字段；等出现具体下游消费者再加。

### 2.5 程序与评测模型的分工

| 部分 | 谁 | 说明 |
|---|---|---|
| 环节实例枚举 | 程序 | 从 dossier 列出 μ（每次模型调用）、χ（每次工具调用）、κ（工具返回→模型输入、步骤→步骤、模型输出→后续步骤→交付）、ρ（Condition/Router/Loop 决策、同参重复）、ι（用户原文→首个步骤/首批参数） |
| 机器可检事实 | 程序 | 同名同参重复且发生在前次结束之后；步骤输出与下一步输入是否同一内容；交付文本与模型输出是否一致；耗时 |
| 可疑环节召回与语义标注 | 分析轴（LLM） | 在程序给的环节表上标可疑、补地图外环节、找出处原文 |
| 义务出处匹配、语义判定 | 各轴（LLM） | 例：结果正文是否表达"重试无效"；替换是否丢义；输出是否忠实输入 |
| 结构校验 | 程序 | 出处存在且读过；fail 有两端证据；只标注不改结论 |

## 3. 实施阶段

每阶段独立可交付，完成即验证，不留半成品。

### P0 业务侧：本地评测打开 span IO —— 已完成（2026-09-29）

结果：verifier 自用实例 :18062（`scripts/insurance_backend.sh`；:18063 归 llmtracing）重启后，新 span 的 step/tool input/output 有正文，LLM span 带完整请求 messages、`llm.tools.*` 工具定义与输出。reader 在 span 输入可见时把 `model_calls.exact_request` 记为 available；全部调用可见时 `exact_model_request` 缺口关闭，否则仍回落重建输入。业务仓库相关测试改动前后失败集合一致（14 条既有失败）。

现状：`insurance-qa-agent-eval/app/main.py:154-155` 硬写 `OPENINFERENCE_HIDE_INPUTS/OUTPUTS=true`，Agno `setup_tracing` 不传 TraceConfig，完全由这两个环境变量决定。openinference 官方支持。

改动（分支 `eval/current`，3 处）：
- `app/runtime/model_router.py` `HarnessConf` 加 `tracing_capture_io: bool = False`；
- `app/main.py` 仅在 `not harness.tracing_capture_io` 时设置两个 HIDE 变量；
- `app/conf/harness/harness_dev_args.yaml` 加 `tracing_capture_io: true`；common 保持默认 false。

验证：重启 18063，跑 1 条用例，确认 span input/output 有正文、LLM span 带完整 messages。
随后：`business_trace/providers/agno*.py` 读取 span IO；重新核定 `exact_model_request` 是否仍是永久缺口，更新 dossier gaps 与系统提示词里的平台缺口声明。

风险：本地 `runtime-real.db` 会存模型完整输入（含客户信息），仅本地评测开启。

### P1 协议：修订 W1

- `spec/math-abstract/process-axes.md`：按 §2 增补义务定义、出处层级、承诺表修订、LinkResult、地图作为先验。
- 附"环节类型地图"：每类环节在 Agno trace 里通常的形态与位置，及其通用义务模板。

验收：用户确认。原 7 条判例 + 重试判例都能由"按自己的义务判 + 出处"推出，不加特例。

### P2 程序：环节实例枚举

**已完成（2026-09-29）**：

- `business_trace/links.py`（`comparisons.py` 已删除）：`build_links(dossier, axis_id=None)` → `{types, links: [{link_id, link_type, turn, input[{ref, field}], output[{ref, field}], facts, basis}], limits}`。
  - ι：run.input → 首个顶层步骤产出 + 首次模型决策。
  - ρ：带子步骤的控制步骤（Condition/Router/Loop）→ 实际执行的子步骤；同一 agent run 内同名同参（规范 JSON，列表顺序保留）再次调用 → `repeat_of`、`started_after_prior_ended`、`same_result`。
  - χ：工具参数 → 返回，`duration_s`；与持久化调用配对的 span 副本不重复列出。
  - μ：有 `exact_request` 用 span 请求，否则用重建消息并标 `input_source`。
  - κ：工具返回 → 首次携带它的模型输入（`contains`）；同父步骤的相邻步骤（下一步输入由 span 记录时给 `contains`，未记录时 `next_input_recorded=false`）；最后顶层步骤 → 实收（`vs_stored{changed,dropped,added}`）。
- 不写进 dossier：links 是 dossier 的纯函数，现场计算，冻结重判不用重建案卷。分析轴看全表，过程轴只看 π 分给自己的类型（σ 读 χ）。
- 冻结 32 例实测：χ 162、μ 142、κ 376、ρ 71、ι 44；单轴表最大 10.6K 字。前次返回 `retryable:false` 后同参再调：**11 例 22 次**（独立脚本复核一致）。此前"12 例约 50 次"是手工粗计，以本数为准。交付：42 轮只差 `trace_id`，2 轮整体不同。
- 测试：`tests/test_business_trace_links.py`（3 条）；全量 11 failed 与改前同集。

### P3 分析轴：从"按轴选材"改为"可疑环节清单"（即 W2）

- `trace_analysis` 输入：dossier 目录 + 程序环节表。
- 输出：
  ```
  suspects: [{link_id | new_link{type, input_refs, output_refs, off_map: true},
              why, source_refs}]
  ```
  偏召回：程序事实命中的环节默认入表；分析轴补语义可疑与地图外环节，并为每个找出处原文。
- 各轴视图 = 本轴类型的全部环节（可疑者带正文，其余带摘要）+ 出处原文。
- 分析失败仍整例阻断（不变）。

**已完成（2026-09-29）**，与上文的偏差与细化：
- 模型输出扁平为 `{link_id, new_link_type, input_refs, output_refs, why, source_refs}`（结构化输出不便表达可选嵌套）；程序并表后为 `{link_id|new:N, link_type, origin[program|analysis], why[], source_refs, input_refs, output_refs, off_map, axes}`。归不进六类的填 `unclassified`，发给所有启用轴并在 coverage_note 提示用户。
- 程序命中（`links.program_suspects`，只看关系事实）：`repeat_of`、`contains=false`、`vs_stored.changed/dropped`、Agno `tool_error`。冻结 32 例命中：κ:deliver 44（其中 42 仅 `dropped=[trace_id]`）、ρ:repeat 27、χ tool_error 2。`trace_id` 是否属于用户可见内容是语义判断，程序不写键名规则，留给上下文轴判。
- 各轴视图 = 本轴可疑环节的出处与两端 → 本轴其余环节两端 → gaps，按预算截断并列出 excluded（没有采用"其余带摘要"：两端原文本身是判据，大记录已按读取回执/结构图渲染）。冻结 32 例 excluded 合计：context_memory 38、model_capability 10、其余 ≤1。
- 删除：`selections` 由模型产出、`information_needs`、`AxisSpec.needs` 与 `axes_missing_needs`、`axes_without_evidence`（每轴材料由环节表决定，不再有空选段）。`output.selections` 保留为程序生成的每轴 refs，供 process_common 与主轴使用。
- 轴 prompt 字段 `selected_for_this_axis` → `suspects_for_this_axis`。

### P4 六轴：检查项改写为按环节类型的义务模板

- `process_common`：`Check` → `Obligation`（situation/duty/source 要求/judged_by）；输出按 LinkResult；`_annotate` 增加"fail/pass 无出处 → 标注"，仍不改 fail。
- 程序判定的义务（judged_by=program）直接由 P2 facts 产出结果，不进 LLM。
- 各 adapter 去掉业务专有写法（`answer_draft/gaps/needs_user_input`、"桥接"、"保单"），改为 Agno 概念："Agent 之后的函数步骤"、"agent output_schema 字段"、"请求对象标识"。
- `project.yaml` 增加 `process_obligations`（项目声明，首条为不可重试拦截）。
- `judge.py`：主判读取新结构；`_CHECK_KEYS_FOR_MAIN` 同步。
- 导出：明细表每行 = 一个 LinkResult；契约缺失单独一张表。

实施结果（2026-09-29，与上文的偏差）：
- 项目声明放在 capability_map 场景条目的 `process_obligations`，没有放 `project.yaml`：场景条目本来就是"用户确认的场景配置"的归宿，project.yaml 管项目接入协议。core 校验形状（id、link_type、situation、duty、confirmed=YYYY-MM-DD、可选 applies_to/label），llm_probe 校验 link_type ∈ 环节类型表。首条 `retry_after_non_retryable`（ρ:repeat）。
- 义务适用范围：`applies_to` 前缀限定的义务管它点名的环节；不限前缀的是兜底义务，只管同类型里没被内置限定义务点名的环节（含表外环节）。项目声明只增不减，不会让兜底义务退出。每类环节必须有一条兜底义务（axis_type 注册时校验）。
- LLM 输出按"同一义务、同一结论、同一理由"分组（link_ids），程序展开成逐对 LinkResult。覆盖是硬校验：首次严格（每对恰好一次、缺证必填 missing），不合规重试一次；第二次宽松修复——保留已给结论、丢弃未声明的对、重复取第一次、非法落点记缺证、未回答的对记缺证。证据/出处规则仍只加标注。
- 程序已判的对（κ 原文到达）只作为 `program_results` 给模型参考，不要求回显；全部由程序判定时不调模型。
- 主判材料：fail/缺证/契约缺失给全字段并排前，pass/NA 只给定位与结论。live 明细每行一对，契约缺失单列"待补项目声明"。
- π 恢复为函数：χ 只归 tool_execution，σ 只归 knowledge_data（新增 σ:turn 环节）；新增 ρ:path:turn（整轮路径与收尾）、κ:input:call（系统组装模型输入）。

### P5 验证

两种方式都做：
- **冻结重判**：同一批 trace（`batch-status.json`）新旧实现各判一遍，用于新旧对比与稳定性（输入完全相同，差异只来自判定）。复用 `_replay_process_dossier_tmp.py` 的方式，改成正式脚本。
- **重跑业务**：前端重跑全量，拿到新 trace（P0 后带模型输入），用于广度与地图外环节统计；业务路径会变，不用于新旧逐格对比。

| 维度 | 做法 | 通过标准 |
|---|---|---|
| 一致性 | 11 条重试用例、22 次重试（P2 程序统计） | 每次都得到 μ 与 ρ 两个结果，同类判法一致；无"有重复却判不适用" |
| 归轴 | 容量/预算拒绝、错对象、假空、交付替换 | 不再出现容量拒绝记工具；判例全部命中 |
| 深度 | 故障注入：在真实 trace 上程序化植入已知故障（插入同参重试、交付丢 gaps、换返回对象、删输入历史），由明显到隐蔽、单故障到叠加 | 按类型报召回与归轴准确率 |
| 广度 | 统计地图外环节数与类型；每类义务至少在一条用例上触发 | 地图外环节全部被列出并判定，不被丢弃 |
| 事实 | 每轴抽若干 fail/pass，回到原文核对 observed 是否属实 | 记录事实错误率 |
| 稳定 | 同一 trace 判两次 | 统计翻转格子，翻转处即规则没说清之处，逐条交用户 |
| 契约缺失 | 汇总全部 contract_missing | 交用户逐条决定补声明或接受 |

对照组：当前实现在同一批 trace 上的结果。新实现在一致性、归轴上无明显改善则不上线。

### P6 前端实跑

P5 通过后，前端跑 insurance-agno-e2e 全量，导出 Excel，与本批对照。

## 4. 顺序与依赖

```
P0（业务侧，可并行） ─┐
P1 协议 → P2 环节枚举 → P3 分析轴 → P4 六轴 → P5 冻结重判 → P6 实跑
```

P0 不阻塞 P1–P4；P0 完成后在 P5 前合入读取。

## 5. 需要用户确认

1. P0：是否在 `eval/current` 上做这 3 处改动。
2. P1：§2 的判定单元、出处层级、`contract_missing` 结果、承诺表修订。
3. `project.yaml` 放项目声明（§2.2 第 3 层）是否可接受——它是唯一需要按业务写的地方，每条都来自用户确认。
4. P5 的上线门槛：一致性与归轴需明显改善。

## 6. 不做

- 不读业务代码、不做代码内部归因。
- 不加严重度/根因角色字段。
- 不保留旧的 selections / 旧 checks 结构，不写兼容层。
- 证据通道（业务日志、网关、后端代理）仍按 `report/process-axes-gap-census-20260927/deeper-channels.md` 延后；P0 是唯一例外，因为它是 Agno tracing 自身的开关。
