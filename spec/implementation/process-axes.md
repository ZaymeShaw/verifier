# 过程六轴与上下文一致性实施记录

> 更新：2026-10-07。本文持续维护实施边界、任务状态、验证证据和未决事项。
> 当前阶段：v2 主体实现已落地并通过离线回归；**真实端到端验收未通过**。两次完整重跑分别在候选办法投影、分析阶段环境请求失败；需求分别产出 4/3 条，完整性与稳定性未验收。最新状态、未完成项见第 8 节。
> 第 7 节保留为调查历史，不代表当前实现状态；不改变需求／算法方案口径。

## 1. 三类文档的分工

| 文档 | 回答的问题 | 入口 |
|---|---|---|
| 需求 | 要解决什么问题、业务含义与验收目标是什么 | [过程六轴需求](../../demand/process_axes.md) |
| 方案 | 用什么协议、判定方式和结构满足需求 | [过程六轴协议](../alg/process-axes.md)、[需求轴协议](../alg/expectations.md) |
| 实施 | 具体改哪里、按什么顺序做、做到哪一步、有什么验证证据 | 本文 |
| 独立验收机制方案 | 如何从实际 llmtrace 审阅 verifier，何时允许放行 | [verifier-ready gate](../verifier-ready-gate.md) |

需求决定验收目标，方案承接协议设计，实施记录实际落地。发现三者冲突时，在本文记录差异并回到对应文档修订，不能通过改实施记录偷偷改变需求或方案。代码存在、测试通过、真实运行通过分别记录，不互相替代。

初始授权是建立实施文档；随后用户授权修复后处理结构假设（见 4.2）、确认系统契约调整方向，再要求先调查清楚具体可实行性。当前执行范围是调查、离线探针和实施记录。gate 主流程接入与自动 hook 注册尚未开展。

## 2. 本次讨论形成的实施约束

### 2.1 分清业务系统和 verifier 两层

业务系统是被评测对象；verifier 是评测器。业务 trace 中存在矛盾，可以正是需要评测的事实。

- 工具 data 有姓名、gaps 却说姓名未返回：业务证据内部矛盾。
- verifier 原样转交这份证据，并明确来源和对象：不能仅因此判 verifier 的上下文组装有错。
- verifier 丢失、改义、混淆这份证据，或依据矛盾材料无说明地判定正常：另有 verifier 自身的问题，需要它的实际输入输出证明。
- verifier 的模型调用失败、schema 被拒绝、预算耗尽：记录为评测运行失败，不能转成业务系统的问题或业务缺证。

实施记录中的每个发现都要说明评的是哪一层。进入门的 finding 还要核对：这是 verifier 的上下文缺陷、处理业务矛盾的失败，还是仅仅发现了业务缺陷。不能把三者混为一种门失败。

### 2.2 用户期望描述结果，路径约束必须另有依据

“告诉我投保人、被保人和当前状态”首先对应要交付的信息。不能仅凭这一句话要求必须调用某个工具、恰好查询一次或采用固定路线。

“该发生但没有发生”的发现仍然必须支持：依据用户目标、适用系统规则与当时有效信息判断是否缺少必要行动；接受能兑现目标的等价路径。若实时数据必须本轮重查，这条路径约束要引用实际适用的规则。

### 2.3 系统契约保留原文、条件和作用范围

审查一个环节时，至少解释清楚：约束来自哪里，属于哪个组件、阶段和版本，什么条件下适用，约束整个响应还是某个字段，以及上下游如何消费它的产出。

“全部响应是 JSON”不能缩成“某段 JSON 字段齐全”；“允许某行为”不能变成“必须做”；采集时的组件定义不能直接充当已验证的运行时契约。规则冲突且没有可见的优先级时，保留未决，不能让评测模型自行补一套优先级。

这是一组实施核对要求，暂不为它新增通用配置层、规则语言或运行时 LLM 角色。先用已有证据、引用和报告完成一个端到端样本。

### 2.4 同时比较应该收到的材料和实际收到的材料

评某次模型表现，依据该次实际输入；评输入组装与传递，还要比较有依据的应交付内容和实际交付内容。

如果上游漏传了格式约束，不能把模型未遵守它直接算成模型能力问题，也不能因为模型遵守了现有输入就宣称整个系统正常。输入无效只能影响依赖该输入的子能力，并按现有需求指向具体上游问题；不豁免独立的编造等问题。

verifier 完工门仍遵守自己的证据边界：以 llmtrace 实际请求/响应及已允许的运行产物为依据。源码、配置或内部 snapshot 可以辅助实施定位，不能证明某段内容已发给模型。如果应交付的一端在允许证据中不可见，记为不可核验，不补造。

### 2.5 引用正确不等于判定正确或检查完整

程序可以校验引用存在、身份对应、结构合法；语义审查还要核对：

1. 引文是否完整保留条件、否定、范围和规范强度；
2. 引用的规则是否适用于当前环节；
3. 两端证据是否支持所下结论；
4. 有没有遗漏关键约束或未检查的环节。

先列出已确认矛盾、已解释的差异、证据不足、已核对一致及未覆盖部分。不在缺少完整分母和校准依据时给“一致性百分比”。现有门的覆盖计数和耗时硬性项继续单独报告，不用速度、引用通过或 schema 通过抵消语义问题。

## 3. 已确认方向与待补齐的方案接缝

| 事项 | 当前方案/实现 | 本次讨论方向 | 实施状态 |
|---|---|---|---|
| 需求轴的系统承诺 | 当前 `expectations.py` 仍从 want / commitment 提取期望 | 取消全系统规则提前拆成大清单，用户期望独立，系统契约按环节从原文核对 | **方案已定稿**：`spec/alg/expectations.md` v2、`spec/alg/process-axes.md` §2.2/§3.4（2026-10-07）；运行代码未切换 |
| 防止对着实际缩写规则 | 当前方案在看实际前定格期望 | 仅“边判边引用原文”不足；新方案需说明如何保留完整约束、避免事后缩写并验证覆盖 | 待方案明确，不凭实施文档新增一套模型流水线 |
| 未发生的必要行动 | 当前方案由期望与设计展开单位 | 简化系统规则处理后，仍须保留从目标与适用设计检查“该做没做”的能力 | 必须在候选方案中验证 |
| 门如何处理业务证据矛盾 | 门审整个 verifier llmtrace 的自洽性 | 原样携带业务矛盾不自动算 verifier 错；要核对来源标记、任务要求与处理结果 | 待核对门的角色卡、checklist、finding 与聚合逻辑 |

方向已获用户确认；这不代表局部规则覆盖机制已经被验证。现有方案正文与方向仍有差异，第 7 节列出须同步修改的协议和接口；不能仅改 prompt 或通过放松校验完成切换。

## 4. 已有状态与证据

| 项目 | 已证实的状态 | 尚未证实 |
|---|---|---|
| 独立 gate 与 pi hook | 独立命令和适配器已存在，未注册到正常项目会话；用法见 [README](../../hooks/verifier-ready/README.md) | 新门在真实业务及完整语义审阅上的闭环 |
| hook 机制 | [既有独立验证报告](../../report/verifier-ready-validation/20261007/hook-cli-independent-final/verification.md) 记录 12 个真实 pi CLI 场景、103 项 pytest 回归通过；provider 是本机脚本模拟服务 | 外部真实模型能否准确发现问题；不能把模拟 PASS 当真实 PASS |
| 前端运行人工审查 | [报告与原始证据](../../report/current-frontend-context-audit/20261007/conclusion.md) 对 8021 当前工作区 batch 指向的一个用例完成审查，导出 16 条 verifier 调用 | 其余工作区结果、新代码重新运行、hook 自动检出 |
| 本次契约处理讨论 | 已落本文的边界、验收要求和方案差异 | 尚未实施需求轴职责调整 |

上述测试数引用既有报告，本次文档更新没有重跑这些测试。前端样本来自 2026-10-06 保存的运行，不能证明之后的代码仍有相同问题或已经修复。

### 4.1 真实样本应如何解释

样本 execution：`1016a2d852a3465c9f66fdaf27feb999:0`。case：`llm-probe-insurance-real-smoke-policy-detail-renyanlin`。详细定位与哈希见 [evidence.json](../../report/current-frontend-context-audit/20261007/evidence.json)。

| 发现 | 所属层及已证实内容 | 验证时不能跨越的边界 |
|---|---|---|
| data 有姓名，gaps 声称未提供姓名 | 业务工具结果内部矛盾；相关原文确实通过 dossier 工具进入 verifier 请求 | 不能仅凭材料矛盾认定 verifier 组装有错 |
| 要求 JSON，模型返回文本，bridge 包装为对象 | 业务模型未遵守可见格式要求；bridge 转换可定位 | 内部草稿字段与接口字段不同本身不等于错误；包装成功不等于模型遵约 |
| `submit_structure` 枚举包含空字符串，被 provider 拒绝 | verifier 自身实际 schema 请求失败；两轴 failed，六轴 blocked | 应记录评测失败；不能生成业务能力结论 |
| 实收完整答复，transcript 的 assistant 内容为 `ok` | verifier RunTrace 的对话表示失真 | 本案未证明该 `ok` 被下游模型消费，不能据此断言已经造成误判 |
| Check 为 passed，Judge 为 not_evaluable | 两种结果的检查范围不同 | Check 不能证明整体上下文一致，也不能仅凭两个值不同认定造假 |

对先前审查结论的解释修正：它证明这条保存链路存在上述问题，但其中业务缺陷和 verifier 缺陷必须分别归属；“业务有矛盾 ⇒ verifier 完工门必须失败”不是已经成立的结论。保留原始报告与原始运行，不回写历史证据。

### 4.2 单位格式真实验收失败与默认值解析修复

关联方案：过程六轴当前单位输出协议；不涉及第 3 节待确认的系统契约调整。

真实运行 `unit-format-full-live-20261007` 用时 2527.053 秒，expectations、trace_analysis 成功，六个过程轴均失败；五轴报 `KeyError: matched`，tool_execution 报 `KeyError: missing`，最终 Judge 为 `not_evaluable`。证据：[原始摘要](../../report/expectations-20261006/unit-format-full-live-20261007/summary.json)。进程退出码不能替代各轴状态，原运行不因本次修复改写为成功。

根因：prompt 和 dataclass 生成的 schema 都允许省略可选字段；`enforce_output` 只校验、不实例化默认值，`process_output.expand` 却直接下标读取这些字段。原测试显式填全了可选字段，漏掉合法省略情况。这是 verifier 自身的结构契约衔接错误。

修复：在 `process_output.expand` 入口使用已有 Pydantic `TypeAdapter(AxisJudgment)` 按生成 schema 的同一份 dataclass 解析，再用 `asdict` 进入现有转换；嵌套默认值自动实例化，不逐字段另写缺省规则。严格 schema 检查、覆盖检查、证据引用检查和判定汇总保留。没有修改业务判断标准，也没有把结构错误变成 pass。

验证：

- `test_process_unit_output.py`、`test_process_prompt_contract.py`、`test_process_axis_investigation.py`、`test_process_criterion_checks.py`、`test_process_axes_protocol.py` 共 65 项通过。新增合法省略、问题证据省略，以及缺必填、null、错误类型、额外字段仍拒绝的测试。
- [离线回放脚本](../../report/expectations-20261006/unit-format-defaults-replay-20261007/replay.py) 与 [结果](../../report/expectations-20261006/unit-format-defaults-replay-20261007/result.json)：使用原始请求/响应、现有 JSON 提取器、严格 schema 和真实 expand，未调用模型。八份保存响应覆盖六轴，其中两份 tool_execution 较早响应仍因 checks 内额外字段被拒绝。其余六份 schema 合法响应不再出现 KeyError：intent_understanding、planning_routing、knowledge_data 通过转换；context_memory、tool_execution 因 evidence 引用不可读独立编号被拒绝，model_capability 因 `U8/C40` 的 fail 未被 problems.breaks 引用而被拒绝。
- 回放只验证结构到转换这一段，未运行完整下游证据/期望校验、纠错轮次、其他批次及最终 Judge。后三项是后续待定位问题；当前结果不证明六轴、语义一致性或 gate 真实验收通过。

状态：默认值解析修复与局部验证完成；完整真实验收仍未通过，系统契约方案调整仍未实施。

### 4.3 单位格式后续修复与六轴回放（接手方 Claude，2026-10-07）

关联方案：过程六轴单位输出协议（模型只写判断，单位、判准、端点、预期、汇总由程序负责；抽象见 [report/…/process-axes-output-abstraction-20261007.md](../../report/expectations-20261006/process-axes-output-abstraction-20261007.md)）。不涉及第 3 节系统契约调整；`attach_criteria` 仍消费全局 commitment 映射，属于 7.5 待删除路径。

| 问题（来源） | 改动 | 位置 |
|---|---|---|
| 应发生单位 matched 填了记录编号（回放 1：三轴“对接的实际行使不存在”）；提示只说“对接的事件编号”，未给可选范围 | 应发生单位在 units 中带 `candidates`，matched 只能从中选，报错列出可选项；候选含无轮次的分析轴表外环节，对接时不强求轮次 | `process_common.run_process_axis`、`process_output.expand`、`expectation_projection.bind_results` |
| source=trace/case 模板单位未挂具体期望仍被判 pass/fail（两次 live 规划轴均因此失败） | “有无具体判准”由程序直接判定为 contract_missing（§3.2 缺判准），不交模型；代价：这类单位不再区分 not_applicable / input_invalid | `run_process_axis` |
| 模型把 missing 写在判准层被拒（回放 1 工具轴） | missing 移到每条判准（逐条缺口更准确），单位层由程序汇总；每条 insufficient_evidence / contract_missing 必须自写 missing | `process_output` |
| 一个问题跨单位时，把各单位证据与出处合并回每个单位，触发“模型引用不属于该次实际输入”“通用义务须指向本单位”（回放 2 模型轴） | 问题副本只带本单位端点＋模型指出的额外依据；同一 problem_id 比较正文时排除单位局部字段（端点、出处、expected），汇总取并集 | `process_output.expand`、`process_protocol.issues_for`、`validate_result_evidence` |
| 新格式提示词漏掉 §4/P3 规则（提示缺失不免除不编造、同一事件多轴各记、后文不抵消前文等，业务审查发现） | 抽出与格式无关的 `EVIDENCE_GUIDE`、`JUDGING_GUIDE` 到协议文件，新旧格式提示词共用同一原文，测试锁定 | `process_protocol`、`process_output.UNIT_SYSTEM`、`process_common._SYSTEM` |
| 案卷路径旧系统提示词已无代码使用 | 删除 `_MATERIAL_SYSTEM` | `process_common` |

验证：六轴相关回归 212 项通过（含上述每项的正反例）。真实六轴回放（复用 `unit-format-full-live` 冻结的需求、分析与投影，生产 runner）：

| 运行 | 六轴通过 | 调用 | 重试 | 原文非法 JSON | 输出字符 |
|---|---:|---:|---:|---:|---:|
| `criteria-attach-full-live`（旧格式） | 4/6 | 20 | 3 | 3 | 133,643 |
| `unit-format-six-axes-replay`（修复前） | 1/6 | 22 | 9 | 4 | 66,465 |
| `unit-format-six-axes-replay2` | 4/6 | 14 | 3 | 5 | 53,472 |
| `unit-format-six-axes-replay3`（含上表全部修复） | **6/6** | 13 | 2 | 2 | 39,413 |

回放 3 六轴部分用时 862 秒。上下文、意图、规划、知识 sound；工具执行 problematic（policy_detail 返回 PARTIAL 并称姓名未返回，records 中姓名有值，与此前人工原文核对一致）；模型能力 problematic（第 1 次调用输出含过程话、未遵循 JSON 契约；第 2 次调用输出纯文本未按 JSON 契约、主附加险合并陈述、使用内部词与非标准简称）。两次重试均由原文非法 JSON 触发，纠错轮通过。模型能力的 5 条问题尚未逐条人工核对原文；本结果只证明单位格式链路在该冻结样本上跑通，不证明语义准确，也不是主 Judge 或 gate 验收。

仍未解决：
- **原文非法 JSON 仍存在**：回放 2 为 14 次中 5 次，回放 3 为 13 次中 2 次（靠纠错轮恢复），均为字符串内英文双引号未转义；提示词两处禁止仍发生。仅靠 prompt 内结构约束（`spec/struct_output.md` 的 prompt＋事后校验两层）不足；方案 §31 的 response_format 层从未启用（git 全历史核实）。2026-10-07 用户决定**不启用** response_format，保持现有 prompt＋事后校验＋纠错轮；非法 JSON 由纠错轮兜底。
- 回放 2 上下文轴：首轮 JSON 被修复成 list，重试只判 2/8 个单位。
- 7.2.5 编号歧义、7.2.6 问题摘要丢条件仍成立；回放中出现模型把上游 problem_id 写进 evidence。
- 新旧两种提交格式并存（llmtracing / ToolLoop 仍用 `ProcessAssessment`），按 7.5 须统一。

## 5. 后续实施顺序与验收

先完成一个最小端到端样本，再扩展到需求中的 P1–P7 和门规定的全量 smoke 范围。以下任务均未因本文建立而自动启动。

| 顺序 | 工作 | 完成证据 | 当前状态 |
|---|---|---|---|
| 1 | 方案对齐：处理第 3 节差异，明确系统契约来源、适用范围、覆盖方式和门的责任边界 | 对应方案修订位置、实施接缝、明确待删旧路径 | 方向已确认；调查和接缝清单见第 7 节，方案正文待同步 |
| 2 | 固定一个真实样本，逐段核对请求 → 模型输入 → 工具参数/结果 → 模型输出 → bridge → 实收答复；同时核对 verifier 自身输入输出 | 可定位的两端证据、局部结论、未决及未覆盖范围 | 已有人工样本；候选方案验证待做 |
| 3 | 在独立入口落实确认后的最小改动，复用已有 dossier、llmtrace、引用校验与输出校验 | 变更文件、替换的旧路径、必要测试结果 | 未开展 |
| 4 | 原失败例与相邻正常例对照，验证归属、漏检与误报 | 下述反例对照表、P1–P7 输出解释、实际请求与结果 | 未开展 |
| 5 | 新实现真实运行与独立审阅，验证门能否发现 verifier 问题并正确解释业务矛盾 | 新 execution、完整原文、审阅发现与实施回应闭环；门原定硬性项与覆盖要求不缩减 | 未开展 |
| 6 | 达到原定验收后决定主流程接入及自动 hook 注册 | 接入记录、真实运行、启用范围 | 未接入 |

步骤 4 至少包含以下对照；明确区分真实冻结样本和人工构造样本，后者不能冒充真实运行：

- 上游内容有错但原样传递：业务原始问题被记录，传递环节不被误判为改义。
- 格式规则实际已送达，模型输出非 JSON：不能因 bridge 包装后合法就判模型遵约。
- 格式规则在组装时丢失：核对两端，定位上游问题，不能归错模型。
- 合法草稿到交付结构转换：不因字段改名或结构变化本身报错；检查语义与明确转换契约。
- 引用原文存在但约束被缩写、或关键约束漏查：引用校验通过仍不能放行语义结论。
- 应有必要行动未发生与等价路径正常完成：前者能发现，后者不强制固定工具或调用次数。
- verifier schema/模型调用失败：保留运行错误，与业务缺证分开。

## 6. 持续维护规则

每次实施更新本文件对应任务行，最少留下：关联需求/方案、改动位置、状态、验证范围与证据、剩余问题。纯讨论记入待确认，不写成已完成。

“已修复”只是代码变化；验证通过须有相应运行证据。语义问题关闭要能在新调用中回查原问题，并核对相邻正常例没有被误伤。历史样本、旧报告与失败记录保留，不能用新的成功结果覆盖。

发现方案与实现不一致时记录差异，不维护两套兼容口径。主流程未接入、真实模型未测、覆盖不完整等边界必须随结论一起保留。

| 日期 | 更新 | 证据/影响 |
|---|---|---|
| 2026-10-07 | 建立实施记录；纳入系统契约讨论、双层归属、真实样本及 hook 验证边界 | 本轮仅文档变更；未改变需求轴、六轴或 gate 行为 |
| 2026-10-07 | 修复单位后处理重复维护的可选字段假设；记录完整 live 失败与离线回放 | 65 项测试通过；原六份响应不再 KeyError，三份继续被语义引用/问题覆盖检查拒绝；未重跑完整 live |
| 2026-10-07 | 确认用户期望与局部系统契约分离方向；完成调用链、冻结样本和删减探针调查 | 第 7 节；新建离线调查产物，未调用外部模型，未切换需求轴/六轴；上轮已补 gate checklist 的双层归属要求，尚未语义验收 |
| 2026-10-07 | 方案定稿：用 v2 替换 `spec/alg/expectations.md`（v1 未入库，原文不再保留），同步 `spec/alg/process-axes.md` §2.2、§3.2、新增 §3.4、差距 D9–D11；下游要求定为场景 `downstream` 字符串列表占位、暂缓实现；结构化输出**不启用** `response_format`（用户决定），维持现有 prompt＋事后校验＋纠错轮 | 仅文档；代码未改 |
| 2026-10-07 | 新建需求文档 `demand/expectations.md`（需求＝用户和下游对业务系统的期望；设计规则不进需求）；方案草稿 `spec/draft/expectations-v2.md` 第 3 版（经两轮 Codex 只读审阅，消费者部分改写为带样例的说明），用户已认可草稿内容 | 仅文档；现行 `spec/alg/expectations.md`、`spec/alg/process-axes.md` 与代码未改；替换方案文档与按 §7.9 改代码待用户发起 |
| 2026-10-07 | Claude 接手：单位格式后续修复（候选对接、模板单位程序判缺判准、逐条 missing、问题证据单位局部、共享业务规则原文），三轮真实六轴回放 | 4.3；212 项回归通过；回放 3 六轴 6/6 通过（13 次调用、2 次重试、输出 3.9 万字符）；模型能力问题待人工核对，非法 JSON 仍靠纠错轮恢复；未重跑需求轴与主 Judge |
| 2026-10-08 | 第三次完整真实运行（live3）六轴 0/6；据此删除"原文块逐块标注"（方案 §6.4 同步修订），原文改由案卷交付一次、按记录 id＋摘录引用；同轴两批合并为一次调用；案卷内按来源指针无损去重 | 第 9 节；离线上下文回放 12→6 次调用、123.2→34.3 万字符；六轴相关 782 项通过；全仓 2389 passed / 14 failed / 5 skipped，失败与既有 14 项逐一相同、无新增（用例总数少 27，为删除的逐块标注/块内路径参数化用例）；真实重跑未做 |
| 2026-10-08 | 3/4 项落实（单候选程序对接、规划/知识交付当次实际输入、提示与报错修正）；改动后完整真实运行 live4 与只重跑六轴的 live5–8；修复主判 `expected` 形状被 live-schema 校验打成 not_evaluable 的缺陷 | 第 10 节；全仓 2392 passed / 14 failed（与既有 14 项逐一相同）/ 5 skipped；六轴 4–5/6，主判 fulfilled（live8） |
| 2026-10-08 | 结构约束收回结构化输出机制：`structured_output`/`SchemaValidator` 增加多选一（按 Literal 区分字段）与显式 `nonempty`（嵌套同样生效）；过程轴输出改为静态多选一，删掉对应手写校验与提示词结构描述，去掉 pydantic；`AuthorityRequest.claim`、`AuthorityResolution.independent_resolution` 由 `X \| None` 改 `Optional[X]` | 第 12 节；全仓 2409 passed / 13 failed（均为既有）/ 5 skipped；其余 91 个输出结构 schema 与渲染提示词逐字不变；真实六轴 6/6、0 次出错、10 次调用 |
| 2026-10-08 | 慢因分析与输出定价；"做到"只交证据编号（新增 PassCheck/PassRule，做到的规则只留摘录，`reason`/`scope_note` 不动） | 第 13 节；全仓 2412 passed / 12 failed（均为既有）/ 5 skipped；真实六轴 live12 6/6、verdict 与 live11 相同、六轴耗时 −23%；模型轴"错误说明但数据正确"的口径待定 |
| 2026-10-09 | 「本应产出」手工走查（保单、D01 两个 case × 六轴，手写 + 独立模型盲写两遍）；未改需求/规格/代码 | 第 14 节；产物 `report/process-axes-reference-20261009/`；待用户决定是否改 `demand/process_axes.md` §4 |

## 7. 实施可行性调查（2026-10-07）

### 7.1 结论与证据边界

结论：可以基于已有材料与评测入口做独立候选实验；“移除 commitment 提取、让六轴边看实际边引用规则”不能直接成为可交付实现。规则覆盖、适用性及未发生行动的判定仍有语义难点，必须用原文登记、程序覆盖检查和独立对照实验共同验证。

本次读取实际运行 `unit-format-full-live-20261007` 的结果、原始请求/响应以及当前采集、投影、三种评测入口、结果转换与 gate 实现。离线 [investigate.py](../../report/expectations-20261006/contract-implementation-investigation-20261007/investigate.py) 和 [evidence.json](../../report/expectations-20261006/contract-implementation-investigation-20261007/evidence.json) 保存源文件/实现哈希、计数、三项删减探针与条件投影探针；无业务调用、无外部模型调用。构造探针明确独立于真实样本。

### 7.2 已查实的现状

1. **全局拆解很大，适用性仍未解决。** 本案 167 条期望 = 4 条 want + 163 条 commitment；14 份来源中，13 份系统声明全部标为 `observed_at_collection_not_verified_run_version`。需求轴起止时间差约 1064.58 秒，包含当次执行与重试；不能把这段时间全部归因于规则拆解，更不能直接承诺删掉后节省相同时间。
2. **原文已在案卷里，无需重新抓取才能启动实验。** 两次模型调用均有 exact_request，序列化输入分别为 3529 / 9524 字符。已有 `links` 能定位输入和输出；当前 `source_in_inputs` 在两次输入各匹配到同一份系统提示来源。这个匹配只证明对应内容出现，不证明其他声明不适用，也不证明采集版本就是运行版本。
3. **六轴已经同时收到提取期望及部分出处原文。** 因此新方案收益不是“第一次能看到原文”，而是原文成为直接判准、提取结果不再替代原文。示例 planning_routing 请求约 145465 字符，材料占 103418、期望占 15780、出处占 15307；model_capability 请求约 50832 字符，材料占 27410、期望占 10917。统计是字符、不是 token；各部分 JSON 序列化口径不同，不能按相加结果当净节省量。
4. **删清单会打断现有接口。** 三项离线探针分别证明：删 commitment 后 `validate_join` 拒绝 contracts 覆盖；清空 contracts 后 data_needs 仍引用工具期望而被拒；直接引用实际规则正文，`bind_results` 仍拒绝 source=trace 的 pass/fail，因为它要求 expectation ID。`_expand` 也只接受 expectation 与本义务引用。新原文判准必须贯通投影、输出、验证和问题记录。
5. **存在真实编号混淆条件。** 原 context_memory 请求的 `content#83/#95/#96` 同时存在于可引用 contents 与 shared_contents，展开后正文不同；intent_understanding 的 `content#33`、tool_execution 的 `content#32` 也如此。两套映射在 JSON 路径上可区分，但裸 ID 不能独立确定正文。被拒的额外 evidence 中有实际 shared storage ID。不能证明所有引用错误都由此导致，但确实需要消除该命名歧义。
6. **条件在下游展示中会丢失。** 构造探针中单位 expected 为“格式：输出 JSON（条件：仅最终响应）”，`bind_results` 给 problem.expected 生成的却仅为“输出 JSON”。完整期望仍可通过引用回查；这里证实的是问题摘要失去条件，不是已经证明历史业务误判。直接引用原文也必须保护这段输出消费链。
7. **不是只有一个消费者。** Agno 材料批次入口用 `AxisJudgment`；Agno ToolLoop 与 llmtracing ToolLoop 使用 `ProcessAssessment`，共享投影和部分校验，但各自还有 prompt、引用回执、输入成员检查。只改当前样本经过的入口，会形成新的不一致。

### 7.3 建议的最小可执行流程

第一步，需求轴仅接收用户要求、场景判准和用于解析指代的历史；输出仍为定格的用户期望。系统声明移到独立的原文材料集合，保留来源、所属组件、轮次、采集范围与可见版本。规则全文不再让需求轴重述。用户期望及系统材料各自计算内容哈希，避免“用户目标没变但系统规则变了”仍复用旧结果。

第二步，在评测某个边界前生成其材料包。复用 dossier、links、call_inputs 和完整读取回执：

- 模型行为：该调用真实请求中的指令、工具声明、参数与完整响应；原请求内的工具返回是本次输入事实，不能因处于 system 字符串就自动升级成规则。
- 输入组装/传递：有来源依据的应交付端、实际输入端；只有当次实际输入，不能推出“没有漏规则”。
- 工具执行：实际参数/返回，以及能关联到该工具及当次版本的规则；采集时声明仅作为待确认候选。
- 规划：用户目标、可用能力原文、当时状态和适用策略，包含未选路径的声明；不能只读取已调用工具，否则看不见应做没做。

身份不能确定、版本无法核验、应交付端未采集时，材料包明确列缺口。当前 `links._input_links` 在找不到确切 owner 时会取同轮首个 run；这只可作为候选线索，不能在新契约匹配中当作已确认所有者。以真实 run/call/parent 关联为准，不能确认就暴露未决。

第三步，**在看被判产出之前登记本边界的规则原文位置，再判断产出**。这是候选实验的两个数据阶段，复用同一个评测职责与模型客户端，不新设治理 agent：

- 程序先按消息、工具定义、schema 字段等真实结构列出原文块，块内容保持完整；结构不明就保留整块，不用关键词过滤规则。
- 准备阶段只读该边界的前置材料及通用义务，登记规则所在 record/path、精确引文、相关条件/例外的原文位置、检查职责与适用范围。禁止用自由摘要代替判准，禁止读取目标产出后缩写标准。
- 每个候选来源块均须有处理记录：找到哪些规则、仅是数据/背景、与该职责无关、或无法确定。程序检查块未遗漏，语义审阅检查“整块判无关”“只摘半句”的错误。适用性需要目标事件事实时保留待核对条件，不能预先猜成立。
- 登记成功后冻结该边界判准，再交付完整目标产出逐条检查。精确相同的前置材料包可复用其登记结果；哈希必须包含来源范围/所有者、原文与协议版本，不能仅凭相同文本跨调用合并责任。

此步骤会增加局部准备成本，是否比全局 163 条拆解划算必须实测。它也不能数学上证明模型找全语义规则：程序能证明块覆盖和逐项检查，语义召回仍需要校准。若这一步在真实材料上不稳定，候选不应接入主流程。

第四步，逐条核对用户期望、通用义务、已确认项目规则与局部原文判准。保留现有单位 outcome、上游问题引用及 verdict 汇总原则。原文判准通过统一结构化类型生成 schema、渲染 prompt、校验和补默认值；正文由 source_ref + path + offset/hash 回填，模型不再同时重写 expected。空结果、无规则、条件不适用和采集不全必须有不同解释，不能统一变成 pass。

第五步，输出保留全部逐项结论及原文判准引用，问题记录从相同引用生成带条件的预期；程序已知的 ID、两端和总结果继续派生。独立 gate 再审整个 verifier llmtrace，包括局部准备→冻结→判断→转换→问题汇总的跨调用关系。局部检查齐全不会自动产生“全链一致”结论。

### 7.4 “该做没做”必须单独保住

现有 `DataNeed.need=tool` 依赖工具能力期望，`required_units` 据此展开工具与知识单位。工具能够提供数据，不足以证明必须采用该工具或必须本轮调用。

候选中把这一步限定为用户目标的实现条件检查：用户目标 ID、是否需要额外外部事实、对应能力/时效要求的原文出处及理由。无论工具目录是否完整，每条用户目标都要核对工作覆盖；工具缺声明应保留设计/材料缺口，不能把用户目标从检查范围移走。

外部数据需求产生的是需核实的候选行动，随后用当时已有数据、有效缓存、已完成等价路径与规则条件核对是否仍必要。允许有正面证据的等价实现；只有已证实必须发生而未发生，才触发规划问题及下游未检验。不能直接删掉当前“应发生单位不得 not_applicable”校验：须先把“候选”与“已证实必需”区分，并用反例保证模型不能以不适用逃避缺失工作。

### 7.5 具体改动接缝与删除项

| 接缝 | 现有位置 | 实施要求 |
|---|---|---|
| 用户需求 / 系统材料分开 | `business_trace/expectation_material.py`、`adapters/expectations.py`、runner / process_loop 入口 | 拆开交付；需求轴只提 want，历史只解指代；声明不丢失，不混入用户期望；用户材料是否齐全不再由缺工具/系统声明决定 |
| 必要行动与能力出处 | `process_loop/expectation_projection.py` | 删除 `tool_expectation_ids` 对 commitment 的依赖，改引用能力原文；独立记录行动必要性及证据，不把能力存在硬推成调用义务 |
| 全局规则映射 | 同文件 `ContractBinding/Join.contracts/attach_criteria/unattached` | 候选验证成功后删除全局 commitment 逐条映射路径，改为按边界冻结的原文判准与其覆盖记录；不保留兼容层 |
| 材料身份 / 所有者 | `business_trace/materials.py`、`dossier.py`、`links.py` | 共享存储 ID 与可引用证据 ID 明确分离；存储去重不合并 provenance；消除 owner 无依据选首个的强断言；不扩大 readable 绕过引用检查 |
| 单位 schema 与后处理 | `adapters/process_output.py`、`process_common.py`、`process_contract.py` | 原文判准为明确类型；逐条结论完整保存；检查覆盖、引用存在、原文定位、必要上下游依赖；聚合不丢条件；两种输出传输格式使用同一判准语义 |
| 三条评测入口 | `run_process_axis`、`process_loop/evaluation.py`、`process_loop/llmtracing.py` | 共享契约准备/验证；分别适配材料预交付和工具读取；提示词与校验同时更新，旧 expectation-only 断言一起删除 |
| 调用输入与最终交付 | `providers/llmtracing_evidence.py`、`validate_dossier_expectations`、报告/问题消费 | 实际输入成员检查继续；新原文引用不免除条件/来源校验；原始响应、bridge、HTTP 实收及 UI 可见范围按实际证据区分 |
| verifier 自身一致性 | `hooks/verifier-ready/checklists/consistency.md`、review / verdict | 上轮 checklist 已补双层归属；用业务矛盾正确处理/错误处理的对照验证。机械验证只检查结构和引用，不以关键词裁定语义归属 |

方案需同步更新 `spec/alg/expectations.md` 的输入/职责/消费投影，以及 `spec/alg/process-axes.md` 的判准来源和应发生单位口径；当前实施文档不冒充这些协议已改好。上述路径均相对 `impl/projects/llm_probe/`，hooks 路径相对仓库根。

### 7.6 独立实验与停止条件

实验起点：保存当前代码指纹、原始失败运行及已修默认值的基线。独立候选入口读取冻结业务 trace，输出到新的报告目录；先把一个完整样本跑通再扩展，不在常用服务内插半成品。当前基线是运行失败，不能用“候选有结论”直接证明准确率提升；需要同时比较人工原文核对表。

先做无需模型的验证：输入白名单不泄露目标产出；原文块覆盖、定位/hash、作用域与同名 ID 隔离；不同规则版本不复用；默认值与必填约束一致；条件/否定保留到问题和汇总；不读取原文不得引用；评测错误不写业务结论。已有 JSON/Pydantic、dossier、trace 和 receipt 足够，不引入通用规则引擎或新编排框架。

语义实验按下表做成明确标注的对照样本；真实冻结样本保持原样，变体另存，记录变更及预期责任，审阅模型不能读取答案：

| 对照 | 必须观察到的结果 |
|---|---|
| 规则实际送达、完整响应含额外文字、bridge 成功包装 | 定位模型完整输出违约，包装成功不能消除它 |
| 有已核实的应交付规则，但实际输入缺失 | 定位组装/传递，依赖该规则的模型义务记输入无效且关联上游问题；独立编造仍检查 |
| 只有采集时定义与请求不同 | 不直接认定漏传或模型违约；保留版本与应交付端未决 |
| 合法草稿→结构化交付 | 按各阶段实际规则解释差异，不把字段改变自动判错 |
| 同样用户目标：有效缓存/等价工具 vs 明确要求刷新却漏执行 | 前者接受等价路径，后者发现必要行动缺失 |
| 业务 data/gaps 矛盾：verifier 保留不确定性 vs verifier 无依据判正常 | 前者不因原样材料而判 verifier 上下文错；后者定位 verifier 判断缺陷 |
| 条件/否定/例外在长原文中，删除登记项或截短引用 | 覆盖/语义审阅能暴露漏检与改义，不能依赖最终结果碰巧正确 |
| 中间调用可只发工具调用，最终响应另有 JSON 要求 | 不把最终要求错误套用中间响应；整段输出范围按阶段解释 |
| 原文块阅读完整但模型忽略其中一条规则 | 机械覆盖可通过，独立语义审阅必须有机会判漏检；明确两者不同证明力 |
| schema 拒绝、超时、纠错预算耗尽 | 评测运行失败，不生成业务 pass 或业务缺证 |

先按独立单案入口完成上述已知缺陷和相邻正常例，再核对需求 P1–P7、两个 provider 的输入边界及全流程。语义样本建议各重复 3 次观察稳定性，报告逐例命中/漏检/误报/不可评及责任归属，不把小样本比例包装为总体准确率。继续记录实际 token、模型请求数、纠错次数、材料体量和完整墙钟；已存在门的硬阈值保持原值。

停止/返工条件：关键约束漏登或缩写；正常转换/等价路径被误判；输入成员/运行版本混淆；候选靠减少检查、放松引用或大量改缺证取得成功；语义结论重复运行不稳定且解释不了。局部失败不能据此删掉仍可运行的主路径。

达到候选单案验收后，才一次性替换受影响的共享接口并删除旧 commitment 路径，跑受影响回归与完整真实验收。独立 gate 审阅/全文覆盖、U1/L1/L2/W 与旧发现闭环仍须单独通过；hook 注册保留到此前约定的最后接入阶段。

### 7.7 成熟模式参考与仍未知的部分

调查参考了三类原始资料：

- [OpenTelemetry GenAI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)：分别记录指令、输入与输出，支持外部正文引用。沿用“原始内容及可定位引用”的模式；该规范不证明哪份规则应被组装进输入。
- [LangChain AgentEvals](https://github.com/langchain-ai/agentevals)：轨迹结构匹配与 LLM 语义评判分开，可按任务选严格、无序或部分匹配。借鉴分别检验机械约束与语义判断的方式；固定工具轨迹不自动适合作为本项目正确路径。
- [JSON Schema annotations](https://json-schema.org/understanding-json-schema/reference/annotations)：default 是注解，不在验证时自动填值。先前类型实例化修复与这一语义一致，不能将结构通过当成语义准确。

以上是可复用模式，不是新方案已被产品验证的证据。仍需实验回答：复杂规则的登记召回率、块覆盖被模型敷衍时独立门能否检出、当前缺少运行时来源的边界能评到多深、局部准备带来的总成本，以及两个 provider 的一致性。已查清实施接口和失败条件；这些语义与成本结果尚未实测。

### 7.8 执行粒度与 token 预算

“先登记规则、再判断”是候选流程的数据阶段，不等于每个环节各加一次调用。已用冻结样本的实际 usage 校准，并以只记录不接受结果的 stub 展开完整当前调度：13 批、39 个轴内位置、86 个义务单位、245 项判准。比较全局提取、每位置两次、每批两次、共享作用域登记后批判、直接批判五种方案，详见 [方案与 token 成本](../../report/expectations-20261006/contract-implementation-investigation-20261007/token-options.md)。

初步结论：每位置两次明显扩大预算；共享登记的输入优势不确定，主要可能减少重复输出与思考；直接批判成本较低但漏检风险需验证。优先对照共享登记与直接批判，不先锁定增加调用的架构。预算含共同案卷分析、不含重试、主 Judge 和独立完工门；输出包含思考。每个候选成本均为有假设的区间，不是已完成 live 的计费结果。

需求视角补充：上述比较固定了既有分轴批次和前置分析，不代表必要成本。用户指出方案本质相近后，优先增加“程序交付完整案卷 → 整案语义审查输出六轴及问题 → 必要时定向补查”的架构基准，再决定是否需要规则登记或分轴多次推理。完整案卷当前为 259,328 字符，初始 13 批轴请求已重复到 982,141 字符；六轴是输出评价维度，不天然要求六段独立模型会话。首轮输入目标 10–15 万、输出目标 1–3 万 token（含思考），只是材料量支持的实验预算，质量、容量和补查成本未验证；不含最终主判、门审阅及重试。完整说明见成本文档“需求视角的架构基准”。

### 7.9 最新实施范围：先移除不必要的规则拆解

用户已排除本轮以一次模型调用判断六轴，随后进一步要求先移除不必要的“160+”拆分。本次重新读取冻结 `unit-format-full-live-20261007/result.json`，确认是 163 条 commitment 期望、4 条 want 期望，共 167 条；不是 163 次模型调用，也不是需求规定的固定检查数。

当前 `expectations.py` 要求从全部系统/工具声明逐条提取期望，包括与本轮无关但明确声明的规则；`expectation_projection.py` 再要求每条 commitment 映射到一个 obligation。首轮删除目标是这条“系统原文 → 重写为期望 → 全局逐条映射 → 再交给各轴”的中间处理。保留用户要求独立冻结、系统规则原文及条件/版本/作用域、各轴具体判定和证据追溯。不能把规则拆解的删除实现成规则检查的删除。

实施接缝沿用 7.5，但先只完成：需求轴仅提用户要求；消费者改用适用原文判准；必要行动准备改引用能力原文，解除 `tool_expectation_ids` 对 commitment 的依赖；同步引用、覆盖和后处理协议后删除旧全局映射。不能只改需求轴 prompt，让消费者悬空，也不能简单关闭判准校验。

不以逐环节局部登记替换同一套大清单，不在此轮同时改分析轮次、六轴批次或新增 tool-loop。7.3 的额外登记阶段仅保留为历史候选，不作为本轮默认实施要求。当前方案正文仍需与此职责调整同步。

先在独立入口验证用户目标覆盖、必要行动遗漏、条件/否定保留、规则实际送达与上游责任等既有对照；比较实际请求/响应及 token。163 条不再生成只能证明中间产物减少，不能据此声称相应检查已完成或总成本按比例下降。主流程仍在候选验收后再切换；本节更新不代表实现或验证已经完成。

## 8. 需求轴 v2 实施（2026-10-07，主体实现完成、真实验收未通过）

授权与标准：实施任务 `report/expectations-20261006/expectations-v2-impl-task.md`；`spec/alg/expectations.md` v2 与六轴协议 D9–D11。不改 `demand/`、`spec/alg/`；未提交 git。初始工作区清单、代码快照及本轮证据存于 `report/expectations-20261006/expectations-v2-impl-20261007/`。

| 步骤 | 改动位置与删除项 | 已实现 / 已验证 | 剩余问题 |
|---|---|---|---|
| 1 需求侧隔离 | `business_trace/expectation_material.py`、`adapters/expectations.py`：删除设计声明与缺系统/工具/格式原因；历史/描述不能独立产 E；capability 不入材料且记 partial；downstream 不读 | 已实现；需求／主判定向 119 项通过，见 `need-judge-tests.log` | 真模型条数、耗时和条目稳定性未验证 |
| 2 删除全局承诺映射 | `process_loop/expectation_projection.py`：删除 ContractBinding、contracts、tool_expectation_ids、attach_criteria/unattached；前置只判 external/none/unknown 及工具原文候选 | 已实现；原旧协议测试迁移中 | 案卷批次前置工具材料只读 definitions，不从实际结果推工具能力；完整回归待跑 |
| 3 候选行动四问 | 同文件及 `process_output.py`：necessity 三态；satisfied 有证据归覆盖记录而不生成问题；unknown 保留缺证；required 未发生须上游问题或未定位问题 | 已实现；三入口集成必要性正反例已通过，见 `minimal-e2e-tests.log` | 真实缓存/刷新对照及独立语义审阅未做 |
| 4 原文判准与块覆盖 | 新 `business_trace/design_rules.py`；共享 `process_output.py` 逐字定位、多处条件、scope/owner 检查；原文块同次调用逐块标注 | 初版已实现、18 项离线通过；正在纠正过细 JSON 标量切块并恢复 transcript system 消息真实边界 | 块完整不等于语义规则全核实；原文路径转义与跨调用借规则还须对照 |
| 5 结果与格式 | `process_common.py`、`process_output.py`、两 ToolLoop 入口统一 `AxisJudgment`/`validate_submission`；删除 ProcessAssessment/_expand；问题预期保留 E 条件与所有设计原文 | 已实现；需求、主判、块与两 ToolLoop 合计 121 项离线通过（3.42s），见 `minimal-e2e-tests.log` | 案卷批次完整端到端及旧测试迁移待验证 |
| 6 同一 E 主判 | 新项目内 `need_judge.py`、`judge.py`：先以 E 投影 blocking，再看交付；校验 ID 全覆盖/hash；无模型自推 business_expectations | 业务 Trace 路径已实现并离线验证；公共 JudgeResult 未改 | 非业务 Trace 的旧主判／独立 fulfillment 不在本次已有 E 链路内，尚未迁移；正常主判多一次 blocking 调用须计入 live |

### 8.1 当前验证边界与已知异常

- 第一轮全仓 `tests-before.log` 为 32 failed / 1909 passed / 27 errors / 5 skipped，其中本轮离线脚本误设 `EMBEDDING_ENABLED=false` 导致 Authority 初始化等额外失败。已删除该环境覆盖；对应 Authority/client_search/embedding 重跑 `baseline-guard-correction.log` 为 101 passed / 1 skipped。网络守护继续拒绝业务及付费端口，不允许真实调用。第一轮不能冒充用户所述 14 项基线。
- 子任务并行迁移时一次全仓收集因旧 ProcessAssessment 导入失败，保留 `need-judge-full-tests.log`；之后最小集成 121 项通过并不代替全仓回归。
- 原文块初版递归到每个 JSON 标量，超出约定的真实结构粒度；正在收敛为消息／工具定义／格式字段，摘录通过块内路径定位。不增加判定模型调用。
- 主判公共 `JudgeResult.business_expectations` 仍由程序从 E 原样投影，公共 finalize 语义不变；删除的是模型自推字段，不是公共封装。非业务 Trace 旧路径仍待定，详见 `need-judge.md`。
- 该阶段当时尚无本轮真实完整运行结果；后续结果见 8.3，不能以离线通过声称语义验收通过。

### 8.2 独立审阅与后续实施收敛

上表为第一轮落地时的逐步记录；以下为后续当前状态，保留前轮失败，不回写历史为成功。

| 审阅问题 | 具体改动 | 验证及剩余边界 |
|---|---|---|
| R1 原子判准上游/归属在单位汇总时丢失 | `process_output` 保存每个 input_invalid 的上游；每个问题的 outcome 从自己的 breaks 派生；`process_protocol` 不用单位 fail 把另一问题升级为 local；`coalesce`、组成的 criterion_counts/部分无效清单、主判混合检查均保留依赖 | `test_process_v2_atomic.py` 正反例；独立复审关闭原反例。单位计数与判准计数明确分开，不改变 verdict 优先序 |
| R2/R3 原文路径不真实、工具字段剪裁、配对 span 漏块 | 工具 fields 保留 status/value 的真实结构；完整工具定义不剪 strict/条件；块内 path 用现有 resolver 并支持 JSON pointer 转义；沿已确认 span_ref 纳入当次工具说明；消息/工具不按 JSON 标量拆块 | 原记录反向定位及冻结样本 389 字当次说明纳入的测试通过；仅配对执行说明可作 execution，采集版本不升级 |
| R4/R5 内部 user 冒充用户原话、消息身份偏移 | 原话只取外层请求或注册 Agno 的关联 run_input；历史须有独立/定序来源；gateway user 只作原文相等后的关联。transcript 消息保持原始下标；送达校验看真实内容，不仅 ID 命中 | `test_need_source_boundaries.py`。缺原话的旧 gateway-only 冻结数据明确缺料，不恢复旧 fallback |
| R6 同一 E 指纹与投影覆盖未强制 | 前置与消费重算 E hash、校验投影 hash 和 data_needs 精确覆盖；两个 ToolLoop 保存快照；单位与轴保存实用 E 指纹；补已有实现指纹依赖表 | stale/hash 缺失/重复/漏项均拒绝；不让模型计算哈希、不为测试填写假哈希 |
| R7 场景判准/描述在保存时被丢弃 | `impl/core/capability_store.py` 仅定点保留并校验 criterion/description 和 downstream 字符串列表占位；不改其他既有行为 | 经真实临时目录 save→load→save→project 验证；downstream 不读、不参与 verdict |
| 首次 live 投影的编号/路径混淆 | preparer 交付 B 短编号，模型仅给 B+块内 path+摘录，程序绑定真实引用；错误回执指明失败位置；前置失败按案缓存为评测失败，避免六轴重复同一失败调用 | 真实原文结构的离线回归通过；修复后的 live2 未运行到投影，不能声称真实已修复 |
| F1 复审：证据门禁仍按单位总结果绕过原子 pass | Agno/llmtracing 读取门禁与案卷实际输入检查改按原子 pass/fail；只对有决定性结论的 E/规则核验送达，input_invalid 不被另一 pass 强迫成已送达 | 新矩阵及来源测试 56 passed；相关扩展 613 passed / 1 deselected；最终全仓 2416 passed / 原14 failed / 5 skipped。无追加付费调用，真实验证仍待恢复环境 |

补充：删除已无人调用的旧 `SUBMISSION_GUIDE`、`PROTOCOL_PROMPT`、旧问题输出 dataclass 和 `_collect`；无兼容路径。共享正文池改 `shared#N`，保留证据 `content#N`，不扩大 readable 以掩盖引用错误。

### 8.3 两次完整真实运行（原始失败均保留）

相同冻结业务 trace，不调用业务、不复用旧 E／分析／判词；运行脚本和模型原始日志分别在新目录。请求使用现有 4008–4010 网关，未启用 response_format、未增加模型 provider 或账户。计数为网关实际请求尝试；输出字符＝content＋tool arguments，不含 reasoning。

| 运行 | E 条数/耗时 | 六轴状态 | 模型尝试 | 重试 | 原文非法 JSON | 输出字符 | 主判 |
|---|---|---|---:|---:|---:|---:|---|
| `unit-format-six-axes-replay3-20261007` 历史对照，仅六轴 | 复用旧 E | 6/6 | 13 | 2 | 2 | 39,413 | 未重跑 |
| `expectations-v2-full-live-20261007` | 4 / 33.49s；partial | 0/6，前置投影失败 | 18（E1＋分析5＋投影12；六轴判定0） | 7（分析重交1＋投影纠错6） | 0 | 66,093 | not_evaluable；交付主判未发动 |
| `expectations-v2-full-live2-20261007` | 3 / 50.93s；partial | 六轴全部 blocked | 10（4成功＋6环境失败） | 5（传输重复4＋既有路由切换1） | 0 | 2,466 | not_evaluable；交付主判未发动 |

- 首次完整墙钟 1896.606s。需求轴已降至四条用户需求，但前置投影六次重复两轮均因原文位置/编号错误被拒，没有任何有效六轴结论。不是“六轴正常完成后判出问题”。
- 第二次完整墙钟 428.276s。网关最终报 **余额不足（402）**，原日志也有备用路线 **地区不支持（400）**。分析失败导致六轴 blocked；未更换账户、未新加 fallback、停止真实尝试。
- 第二次 E 只有投保人、被保人、当前状态，没有单列“是谁的保单”。两版实现同冻结样本为 4/3 条，**完整性／稳定性尚未满足定稿样例验收**。不能由程序补第四项、不能将需求提取的 schema 通过当语义完整。
- 与历史 13 次／39,413 字不能直接做六轴成本净比较：新两次都没完成六轴，阶段范围不同。需求耗时实测低于旧 17.7 分钟，但没有成功端到端的成本／准确性结论。
- 证据：两目录 `result.json`、`summary.json`、`metrics.json`、`gateway-events.jsonl`、`contexts/`、`implementation-snapshot/`；统计脚本为实施报告目录 `summarize_live.py`。快照对应各次实际运行版本，不把之后离线修复倒算为该次成功。

### 8.4 当前验收边界

- 最终 `tests-final-after-f1.log`：**2416 passed / 14 failed / 5 skipped**，415.60s；14 个失败 node ID 与初始基线去除守护误配置后的清单一致（config_contract、deerflow、llm_probe fixture、schema_validator、tool_loop_lab/frontend/package）。此前 `tests-final.log` 为2406 passed / 同样14 failed /5 skipped。没有为既有失败改业务实现；集合比较保存在 `baseline-comparison.json`。
- 原 R1–R7 的独立复审为 602 passed / 2 deselected；未运行写磁盘与本地网络的两个独立审阅测试，不能表述为完整全仓独立验收。
- 主体实现已落地不等于真实通过。恢复网关后仍须完整重跑需求→分析→六轴→主判，并核对 B/漏行动/缓存刷新/条件保留等语义对照。未启用业务 Trace 的旧 llm_probe 主判及独立 fulfillment 仍没有 E 生产依赖，本次保持待定；其他项目主判及公共 JudgeResult 语义未改变。



## 9. 上下文迭代（2026-10-08，离线，未调用模型）

### 9.1 触发：第三次完整真实运行 `expectations-v2-full-live3-20261007`

fallback2 修复后对同一冻结样本完整重跑（primary 地区不支持，请求落 fallback1/2）。墙钟 2792s。需求轴 22.7s、4 条（含"是谁的保单"）、partial（capability 未拆分）；分析 complete；**六轴 0/6**，主判 not_evaluable（六轴全失败时不出裁决，W3 既有口径）。

| 失败类别 | 出现轴 | 原因 |
|---|---|---|
| 摘录"未逐字出现在声明位置" | 上下文、规划、工具 | 摘录其实逐字存在；块自带 `path` 与引用的块内 `path` 同名异义，模型抄了块路径，程序按块内指针解析失败；纠错提示又把方向说错 |
| 来源未核实为本次版本 | 规划、知识、模型 | 规划/知识的材料里只有采集时定义，没有实际收到的那份，设计规则只能参考 |
| 必要性/问题 evidence "引用未交付正文" | 规划、工具、知识 | 模型写"编号＋说明"，程序只收编号；字段说明未写格式 |
| 原文非法 JSON / 结构错乱 | 意图、工具、模型 | 输出过长（意图第 2 批 4.2 万字符、其中逐块标注 95%） |

上下文与输出规模：12 次六轴调用，提示词 6–21 万字符，全部超出 `demand/context.md` 判定预算（约 40k）；输出 27.8 万字符，逐块标注 1837 条、84% 为"不适用"，设计规则引用仅 43 条。

### 9.2 本轮改动（已实现，离线验证）

- 删除逐块标注：`BlockReview`、`UnitJudgment.blocks`、单位 `blocks` 清单、`original_blocks` 提示词字段、`block_reviews` 结果字段。`Quote` 改为 `{ref, quote}`：ref 为已交付记录 id。程序内部仍用 `dossier_blocks`/`transcript_blocks` 作来源索引（不发给模型），`locate_rule` 按 ref＋逐字摘录定位，并优先当次实际输入/执行的那份、最具体的块；版本/归属检查不变。三条入口（案卷批次、Agno ToolLoop、llmtracing ToolLoop）同步；ToolLoop 中规则原文与运行证据一样须先读后引。
- 证据字段：`Necessity.evidence`、`ProblemRecord.evidence` 写明只填 readable 编号；拒绝信息分别指出缺事实/非已交付编号。
- 同轴批次合并：期望倒推单位并入同轮运行环节所在批次，不再单独发第二次（同一份材料只发一次）。提示词去掉 `expectation_units`（与 links 重复）、单位内重复的 obligation/link 键；`action_candidate` 按需求去重为 `actions`（A1…），单位只写编号。
- 案卷无损去重（`materials.material_view`）：同一来源指针的字段只交付一次（`input` 与 `exact_request` 同源，保留解码后的 `exact_request`）；容器字段 `raw_attributes` 去掉已由命名字段或 `captured_tool_definitions` 交付的键，以及文本已逐字出现在同记录其他字段里的键（标注 `omitted_keys_delivered_elsewhere`）；分析选中的 `content#N` 若与已交付字段逐字相同，改为 `same_as` 指向，不再重发。均按来源指针或逐字相等判定，不摘要、不截断。
- 信息损失预估（`demand/context.md` 要求）：案卷去重只删按来源指针相同、或逐字包含于同记录已交付字段的正文，模型可见内容按设计**不丢信息**；省略处在材料里显式标注（`same_as`、`omitted_keys_delivered_elsewhere`），阅读说明已解释。被省略的只有格式差异：扁平键（如 `llm.input_messages.0.message.content`）和消息顺序/角色的对应关系由 `exact_request` 的结构承载。删除逐块标注不减少交付原文，只去掉模型的"不适用"回执。合批不减少材料，代价是单次调用失败会影响整轴（以前可能保住另一批），这一点待真实运行观察。
- 有意的精度变化：问题记录"预期"里的原文位置精确到原文块（某条消息、某个工具定义、某个格式字段），不再到块内 JSON 指针；摘录本身仍逐字核对。`locate_rule` 在同一记录多块都含摘录时，优先本单位所属环节的那块，再优先当次实际输入、最具体的块；归属与版本仍单独校验（有正反例测试）。
- 三条入口共用 `prompt_units`：单位只给 obligation/link/criteria/candidates/action，候选行动的 data_need 按需求去重列在 `actions`，链接里不再重复 data_need。审计里的批次大小按实际发送的合并视图重算，超出 `VIEW_BUDGET_CHARS` 如实标 oversize。

### 9.3 离线上下文回放 `report/expectations-20261006/context-replay-20261008/`

`replay.py` 读 live3 记录的需求轴/投影原始输出与分析结构，其余全部走当前代码，截下每次六轴提示词，不发请求。基线 `report-baseline.json`，当前 `report.json`。

| 轴 | 基线（两批，含系统提示词） | 当前（一次） | 主要剩余 |
|---|---:|---:|---|
| context_memory | 159,841＋204,148 | 95,401 | 16 个环节两端；两次模型调用全量输入 |
| intent_understanding | 72,302＋92,214 | 33,948 | — |
| planning_routing | 110,329＋122,483 | 86,565 | 运行末态 `session_state`（约 9k＋其中工具结果缓存 2 万）；采集时定义 1.3 万 |
| tool_execution | 62,515＋77,974 | 39,103 | — |
| knowledge_data | 60,441＋78,265 | 39,550 | — |
| model_capability | 79,625＋112,143 | 48,472 | 两次调用的实际输入（含工具定义 1 万，已共享一次） |
| 合计 | 12 次 / 1,232,280 | 6 次 / 343,039 | 3 次仍超 40k |

### 9.4 未完成与待定

- 规划、上下文仍超预算，剩余量主要是"材料范围"选择（规划路径的输入端含整份运行末态；上下文轴 16 个环节一次交付），属于取舍，待与用户确认后再动。
- 规划/知识只拿到采集时定义：应按方案改为优先交付当次实际收到的那份（同一轮模型调用的实际输入），否则设计规则在这两轴只能落缺证。
- 意图轴期望单位"未对接实际行使，不能判 pass/fail"：单候选时是否由程序直接对接，待定。
- 全仓回归见第 6 节变更行（`report/expectations-20261006/context-replay-20261008/full-tests.log`）；未真实重跑。
- 审查后补改：三条入口共用单位形状（修复提示词仍写 action_candidate 的不一致）、规则定位优先本单位来源、审计按实际发送视图计大小、阅读说明解释 same_as、Agno 简报去掉重复的 expectation_units、工具说明去掉"原文块标注"。

## 10. 改动后的真实运行（2026-10-08）

### 10.1 本节落实的改动
- 单候选对接：非候选行动单位只有一个候选环节时由程序填 `matched`；候选行动不填（"没有对接上"正是没做到的发现）。
- 规划/知识两轴把同一轮模型调用的实际输入（系统提示词、工具定义）作为可确认版本的规则来源交付；规则引用解析：引用的记录只有采集时副本、而当次执行/实际输入里有同一句时，按已确认的那份认。
- 提示与报错：规则只用于系统提示词、工具说明、格式声明（运行记录是证据，写进 fact）；`reason/scope_note` 限一两句、自写字符串引用原文用中文引号；无判准单位在单位上带提示；`satisfied` 与"行动实际发生"的区分；引错记录时指出设计原文所在的记录。
- 缺陷修复：`need_judge` 把 E 打包放进 `JudgeResult.expected`，通不过 live schema 的 `reference` 形状校验（`pipeline._enforce_judge_live_schema`），导致主判即使四项全 fulfilled 也被改写为 not_evaluable。`expected` 恢复为 `{}`；E 的指纹仍在每条 expectation/assessment 的 evidence_refs 与需求轴报告里。

### 10.2 运行结果（同一冻结样本；均为真实模型，网关 fallback1/2，primary 地区不可用）
| 运行 | 范围 | 六轴 | 主判 | 备注 |
|---|---|---|---|---|
| `expectations-v2-full-live4-20261008` | 全链路 1730s | 1/6（仅知识） | not_evaluable（轴失败） | 需求轴 4 条/64s；23 次调用 4 次出错；输出 7.1 万字符 |
| `expectations-v2-axes-live5-20261008-run1` | 仅六轴 1055s | 4/6（规划、工具失败） | not_evaluable | 复用 live4 的 E/分析/投影 |
| `expectations-v2-axes-live6-20261008` | 仅六轴 1015s | 5/6（工具失败） | not_evaluable | 工具轴判出了真问题但被我方引用校验拒 |
| `expectations-v2-axes-live7-20261008` | 仅六轴 1030s | 4/6（上下文、工具失败） | 四项 fulfilled，但被 expected 形状缺陷改成 not_evaluable | 缺陷由此发现 |
| `expectations-v2-axes-live8-20261008` | 仅六轴 876s | 4/6（规划、工具失败） | **fulfilled（四项）** | 13 次调用 2 次出错；输出 4.8 万字符 |
| `expectations-v2-axes-live9-20261008` | 仅六轴 904s | 4/6（上下文、规划失败） | fulfilled | 解析层引号修复（第一版）后；工具轴首次通过并判出真问题 |
| `expectations-v2-axes-live10-20261008` | 仅六轴 805s | **6/6 全部成功执行**（上下文 not_evaluable，其余 sound，工具 problematic） | **fulfilled（四项）** | 13 次调用 2 次出错；输出 4.8 万字符；解析层修复第二版（`]`/`}`/`,` 后须像 JSON 延续） |

### 10.3 失败根因与修复（以模型原始输出为准）
- 根因：模型在自写字符串里直接用英文双引号（引用原文、`["…"]` 片段、`"TR-…"`），整段 JSON 不合法；`json_repair` 把它"猜"成错误结构，之后冒出一堆"额外字段不允许"的假错误，纠错轮也看不到真正的语义问题。提示词多次要求改用中文引号无效。
- 修复：`llm_client.extract_json` 在 `json_repair` 之前加确定性的词法转义 `_escape_stray_quotes`（字符串内的 `"` 仅当后面是 `:`、`,`＋值开头、或 `}`/`]`＋`,}]`/结尾时才算结束，否则补反斜杠；字符串内容不变，之后仍严格解析并做 schema 校验），围栏内同样处理；`_strict_json_error` 对只因这类引号失败的输出不再报语法错。记录下来的 5 份坏输出全部可解析；新增 3 个单测。
- 全仓 2395 passed / 14 failed（与既有 14 项逐一相同）/ 5 skipped。

- **验证边界更正**：live4–live10 的运行脚本未设置 `VERIFIER_INSTANCE_ID`，读取的是仓库 `impl/data/llm_probe/` 配置，不是 8021 实例配置。用户在 8021 上运行 `customer-profile-fuyunping` 时六轴全部失败：实例 `capability_map.json` 的项目义务 `retry_after_non_retryable` 仍为旧轴名 `link_type: ρ`、`applies_to: ρ:repeat`（仓库已是 `planning_routing`）。已按仓库值同步实例两处场景（备份 `capability_map.json.bak_greek_20261008`），实例数据目录内无其他旧轴名。此前"通过"的结论只对仓库配置成立，实例配置下需重跑确认。
- 同一 case 投影阶段工具清单为空：该 trace 0 次模型调用、走直连步骤，采到的工作流定义只有 steps，没有工具定义；属如实缺口，不是取数遗漏。

### 10.4 此前版本记录的未通过原因（保留，live8 之前）
- 工具轴：模型在自写字符串里用英文双引号，JSON 无法解析（live5/7/8 三次，live6 是引用了采集时副本，已修）。工具轴 14 单位（8 个候选行动×2 条义务），输出长，引号机会多。
- 规划轴：模型把工作流定义、运行记录当规则引用（live5/8）；工作流 steps 里的路由条件目前不在设计原文索引里。
- 上下文轴：偶发漏填 `matched`（多候选时，live7）。
- 六轴逐轴波动：同一代码四次运行，通过轴集合不同，尚无法声称稳定。
- 未做：规划/上下文提示词仍超 40k；`fallback` 模型质量与 primary 差异未评估。

## 11. 待办：过程轴 `description` 的归属（2026-10-08，未定）

现状：过程六轴不读取场景里轴的 `description`（`validate.py` 对非空值报错），这是实现时自行加的限制，未经需求确认。用户运行时被该校验拦下。

讨论到的方向（未定稿）：这些说明里混着两类内容——业务方对业务系统过程的期望（如"允许 Direct、Agent、并行及等价路线"），更接近需求侧的下游/业务方要求；以及评测轴自己的判法（结论标准、问题归属、检查范围），属于评测轴设定。可能的做法是由配置维护者拆成"业务方要求（带适用轴）"和"轴说明（只写判法）"两处，但字段、是否进 E、资料页形态都还没盘清楚。

占位处理：实例配置中以下说明已置空（备份 `capability_map.json.bak_axis_desc_20261008`），原文逐字保留如下，待定稿后再拆分回填；场景 `downstream` 仍为空占位、不读取。仓库 `impl/data/llm_probe/capability_map.json` 中对应字段此前已清空。

| 场景 | 轴 | 原文 |
|---|---|---|
| `insurance-agno-e2e` | `intent_understanding` | 检查用户原文到 gate、agent_input、任务表述或首批工具参数的表达环节，是否保留对象、目标、时间、条件、比较关系、格式约束及全部子问题；指代须对应历史对象。不强制显式 plan。无歧义时的多余澄清属于模型决策或编排，不归本轴。sound 需要过程正面证据；problematic 须定位被改写或遗漏的信息。只有最终答案而无内部表达证据时 not_evaluable。 |
| `insurance-agno-e2e` | `planning_routing` | 检查编排环节：路径、拆解、工具顺序、先决条件、失败分支、重试与结束时机。允许 Direct、Agent、并行及等价路线，不强制 Skill 数量。预算、准入、容量闸等系统策略归本轴，不算工具故障；对照模型收到的规则与实际执行规则，按设计运行但设计不合理也可判 problematic。核验是否利用已有信息并保留整合交付机会；同参重试或列明缺口本身不决定好坏。缺路径证据时 not_evaluable。 |
| `insurance-agno-e2e` | `tool_execution` | 检查调用参数到工具、后端、子 agent 返回的执行环节，含内部解析与适配、函数步骤的直连调用。核对实际参数、有效契约和返回正文；返回别的对象却标成目标对象是执行偏差，span OK 不证明语义正确。EMPTY 按业务期望判：本该空正常；应有却空，查明数据缺失归知识，查明工具出错归工具，偏差已证实但原因未定位则两轴共担。系统预算、准入、容量拒绝归编排。耗时只用该调用适用时限，无时限则 not_applicable 并注明无判准。 |
| `insurance-agno-e2e` | `context_memory` | 检查传递环节：结果投影、逐调用输入组装、缓存、历史、截断，以及模型输出经桥接到实收答复，是否丢失或改义、混淆对象或复用旧状态。必须比较相关两端；模型交付链核对模型原文、桥接/收尾、实收三端，区分落库与实收。格式要求在组装时缺失、截断或冲突归本轴。合理压缩、如实传递源头错误不算故障。脱敏原始请求有经校验重建时据重建判断并声明范围，不单独记缺证；本案缺端点仍如实缺证，已证实偏差可判 problematic。 |
| `insurance-agno-e2e` | `knowledge_data` | 按每个子问题核对本次外部数据与知识是否给出，对象、产品版本、时点和适用条件是否匹配。未取得所需数据须注明已证实原因：不存在、权限范围外、字段缺失、服务不可用、查询未执行、未召回或原因未定位。模型诚实说明不能证明数据充足；已有成功调用给出数据后，多余调用失败不算数据缺失。按期望本应为空不算数据偏差；工具已定位的解析/适配偏差归工具，已证实应有却空但原因未定位时两轴共担。未召回不证明全库不存在，不推断数据最新或检索完整。 |
| `insurance-agno-e2e` | `model_capability` | 逐次评价可定位的模型输入输出对，只按实际收到的输入和明确契约判断忠实整合、推理、工具调用及澄清决策。输入已明确格式仍违约归模型；要求在传递中缺失或冲突归上下文，正确答复被桥接改写也不归模型。只评可观测调用，不推断固有能力或换模型归因。完整过程证明 Direct 无调用才不适用。原始输入脱敏但有经校验重建时据重建判断并声明限制；重建无法校验、无法对应输入输出时 not_evaluable，不能凭最终答对判 sound。 |
| `insurance-llmtracing` | `intent_understanding` | 检查用户原文到 gate、agent_input、任务表述或首批工具参数的表达环节，是否保留对象、目标、时间、条件、比较关系、格式约束及全部子问题；指代须对应历史对象。不强制显式 plan。无歧义时的多余澄清属于模型决策或编排，不归本轴。sound 需要过程正面证据；problematic 须定位被改写或遗漏的信息。只有最终答案而无内部表达证据时 not_evaluable。 |
| `insurance-llmtracing` | `planning_routing` | 检查编排环节：路径、拆解、工具顺序、先决条件、失败分支、重试与结束时机。允许 Direct、Agent、并行及等价路线，不强制 Skill 数量。预算、准入、容量闸等系统策略归本轴，不算工具故障；对照模型收到的规则与实际执行规则，按设计运行但设计不合理也可判 problematic。核验是否利用已有信息并保留整合交付机会；同参重试或列明缺口本身不决定好坏。缺路径证据时 not_evaluable。 |
| `insurance-llmtracing` | `tool_execution` | 检查调用参数到工具、后端、子 agent 返回的执行环节，含内部解析与适配、函数步骤的直连调用。核对实际参数、有效契约和返回正文；返回别的对象却标成目标对象是执行偏差，span OK 不证明语义正确。EMPTY 按业务期望判：本该空正常；应有却空，查明数据缺失归知识，查明工具出错归工具，偏差已证实但原因未定位则两轴共担。系统预算、准入、容量拒绝归编排。耗时只用该调用适用时限，无时限则 not_applicable 并注明无判准。 |
| `insurance-llmtracing` | `context_memory` | 检查传递环节：结果投影、逐调用输入组装、缓存、历史、截断，以及模型输出经桥接到实收答复，是否丢失或改义、混淆对象或复用旧状态。必须比较相关两端；模型交付链核对模型原文、桥接/收尾、实收三端，区分落库与实收。格式要求在组装时缺失、截断或冲突归本轴。合理压缩、如实传递源头错误不算故障。脱敏原始请求有经校验重建时据重建判断并声明范围，不单独记缺证；本案缺端点仍如实缺证，已证实偏差可判 problematic。 |
| `insurance-llmtracing` | `knowledge_data` | 按每个子问题核对本次外部数据与知识是否给出，对象、产品版本、时点和适用条件是否匹配。未取得所需数据须注明已证实原因：不存在、权限范围外、字段缺失、服务不可用、查询未执行、未召回或原因未定位。模型诚实说明不能证明数据充足；已有成功调用给出数据后，多余调用失败不算数据缺失。按期望本应为空不算数据偏差；工具已定位的解析/适配偏差归工具，已证实应有却空但原因未定位时两轴共担。未召回不证明全库不存在，不推断数据最新或检索完整。 |
| `insurance-llmtracing` | `model_capability` | 逐次评价可定位的模型输入输出对，只按实际收到的输入和明确契约判断忠实整合、推理、工具调用及澄清决策。输入已明确格式仍违约归模型；要求在传递中缺失或冲突归上下文，正确答复被桥接改写也不归模型。只评可观测调用，不推断固有能力或换模型归因。完整过程证明 Direct 无调用才不适用。原始输入脱敏但有经校验重建时据重建判断并声明限制；重建无法校验、无法对应输入输出时 not_evaluable，不能凭最终答对判 sound。 |

## 12. 结构约束收回结构化输出机制（2026-10-08）

### 12.1 决定与边界
用户决定：结构约束交给 `output_spec` 机制自动生成与校验，不在消费方手写；schema 只能由代码从静态 dataclass 脚本生成（可复现、可追溯：每次调用留档里已有 `output_contract.sha256`、`parser_schema_sha256`），不用模型生成，也不做每次调用动态生成的 schema。机制走自家路线（不改用 pydantic）。引用类约束（单位/判准编号覆盖、matched 属候选、evidence 属已交付编号、摘录逐字出自原文、版本与归属、fail 必有问题记录）依赖本次调用的材料，仍由程序做引用完整性检查。

### 12.2 机制改动（通用层，`impl/core/structured_output.py`、`impl/core/schema_validator.py`）
- 多选一：字段注解 `Union[A, B, ...]`，各分支为 dataclass，须有同名且取值互不相交的 `Literal` 区分字段；生成 `anyOf`，校验按区分字段选分支再逐字段校验；找不到区分字段或取值相交时构建 schema 就抛错。提示词仅在存在真实多选一时加一行分支规则。
- 显式非空：字段 `metadata={"nonempty": True}`；字符串含非空白字符（`minLength` + `pattern: \S`）、数组至少一项、对象至少一个键；嵌套层级同样校验。未声明的字段行为不变。
- 校验深入 `Optional[dataclass]`、`List[Optional/Union ...]`（此前跳过）。现有输出结构中只有 `AuthorityRequest.claim`、`AuthorityResolution.independent_resolution` 与过程轴受影响。
- 解析层：`extract_json` 在 `json_repair` 之前做确定性的未转义引号修复（见 10.3）。

### 12.3 过程轴输出（`process_output.py`）
- 一条判准/规则结论按 `outcome` 分三种固定形状：普通（pass/fail/not_applicable，`missing` 可选）、缺口（insufficient_evidence/contract_missing，`missing` 至少一条）、输入无效（`upstream` 至少一条，**上游问题 id 从单位级挪到判准级**）。必要性按 `state` 分三种：satisfied/required 须 `evidence`，unknown 须 `missing`。规则 `quotes`、`applicability`、`fact`，问题 `phenomenon`、`breaks`、`axes`，判准 `fact` 均声明 `nonempty`。
- 删除的手写校验：缺证/缺判准须 missing、input_invalid 与 upstream 互相要求、规则须有原文与适用性说明、各处 fact 非空白、必要性事实/证据/missing、问题须有 breaks；去掉 pydantic（`TypeAdapter`、`Necessity` 的 `extra=forbid`），默认值由取值处理。保留：单位/判准覆盖、matched、necessity 与候选行动对应及与 checks 的交叉约束、引用编号、摘录定位与版本、fail 须有问题记录。
- 提示词：删掉描述字段形状的文字，字段说明进 schema 的 `description`；系统提示词手写部分约 3.6k→2.1k 字符，结构说明（schema 渲染）约 6.5k→12.5k，净增约 6k 字符/次调用（分支重复）。上一轮加的 `no_criterion` 结构提示（与 schema 冲突、导致 `missing_criterion` 写成字符串）已改为只说明语义。

### 12.4 验证
- 机制单测 13 项（新增 `tests/test_structured_output_union.py`）；过程轴相关测试按新形状更新，全部通过。
- 不影响其他项目：全量测试期间给 `from_dataclass` 打点，快照所有被创建的输出结构的 schema 与渲染提示词（改动前 100 个）。改动后 91 个逐字相同，变化的 4 个均为预期（`AuthorityRequest` 与过程轴三个）；其余差异是子校验器的创建时机（空数组不再先建）与测试新增/转为通过，无校验行为变化。
- 全仓：2409 passed / 13 failed / 5 skipped；13 项均为既有失败，无新增；`test_authority_output_schemas_render_constrained_not_empty` 因 `X | None` 修正转为通过。`test_pep604_union_annotations_render_constrained_schema_not_empty`（机制本身对 `X | None` 的识别）仍是既有失败，按用户决定未改。
- 真实：网关探测两个可用模型（qwen、deepseek）均接受带 `anyOf` 的工具参数并按分支写出合法结果；六轴 live11（复用已记录需求轴/分析/投影）6/6 成功，10 次调用、0 次出错、无纠错轮，输出 4.5 万字符，主判 fulfilled，工具轴判出真问题；llmtracing ToolLoop 入口用测试转写记录真实模型跑通（model_capability、planning_routing 各 sound，26 个单位，128 秒）。
- 未验证：Agno ToolLoop 入口只有离线测试与 schema 探测，未做真实模型；Gemini（primary 因地区不可用）对 `anyOf` 工具参数的支持未测；完整链路（含需求轴与分析）在新结构下未重跑。

## 13. "做到"只交证据编号（2026-10-08）

### 13.1 依据
导出 job `fb5fda56…`（27 case）分析慢因：每 case 15.4 次调用、约 28 分钟，六轴占 66% 且串行；耗时与输出＋推理 token 相关 0.91、与输入相关 0.30；推理约为输出的 7 倍。按需求 §2 四个使用角度给六轴输出逐项定价（179 次输出、2039 个单位）：做到的说明占输出 29%、全做到单位的规则摘录 5%，四个角度都不读；问题记录（7%）、非做到的说明（21%）、支撑非做到的规则原文（15%）是主要价值。用户判断"去掉无用输出，推理也会降"。

实验（`report/expectations-20261006/reasoning-level-experiment-20261008/`，不改项目代码）：
- 只在提示词加一句"写短点"：模型不照做，输出不降（`slim.py`），不能说明问题。
- 在结构上去掉（`slim_schema.py`，D16 三轴各 3 次）：tool_execution 输出 −46%、推理 −26%、耗时 −35%；model_capability 输出 −42%、推理中位 −15%（1 次离群）；context_memory 输出本就少、无变化。结论一致率与同结构重跑相当。
- 档位与澄清：`gemini-3.8-flash-low/medium/high` 推理量无单调关系，`reasoning_effort` 被网关透传但不生效；`tiered` 是独立模型名，长提示词上几乎不推理、口径与 medium 有差异；加一句规则澄清不降推理（`clarity.py`）。均只作记录，未采用。

### 13.2 改动
- `process_output.py`：新增 `PassCheck{criterion, outcome=pass, evidence≥1, missing?}`、`PassRule{quotes≥1, outcome=pass, evidence≥1, missing?}`；`PlainCheck`/`PlainRule` 只剩 fail/not_applicable。`missing` 在做到上表示范围限制（进 `assessment.gaps`，需求 P5），不是说明。
- 做到的规则不能删：source=trace/case 的义务没有程序判准时，规则原文就是判准（`bind_results` 用它组成"预期"）；live 批次中 60 个单位（52 个在模型轴）靠它判做到。删的只是做到时的 `applicability`/`fact`。
- 程序侧：做到的 `observed` 由程序写成"通过，依据：<编号>"，判准条目保留 `evidence_refs`；做到的 evidence 须在已读编号内（与必要性、问题证据同一规则）。提示词加语义一句："程序判准已能判通过的单位不另引规则"。`reason`/`scope_note` 不动（用户确认）。
- 文档：`spec/alg/process-axes.md` §3.2、§3.4 及修订记录。
- 测试：`tests/support/unit_reply.py` 新增 `make_rule`、`set_outcome`（按 outcome 改形状，供"先造做到再改结论"的用例）、`endpoint_ids`；11 个测试文件改用它们或补证据编号；1 处断言改为更早的拒绝（同批边读边交，现在先被"做到的证据须已读"拦下，下一批读完照样接受）。

### 13.3 验证
- 全仓 2412 passed / 12 failed / 5 skipped；12 项均为既有失败，无新增。
- 真实六轴 live12（`expectations-v2-axes-live12-slim-20261008`，同 live11 复用 live4 上游）：6/6 成功、8 次调用 0 出错；93 条做到全部只给证据、2 条做到规则只给摘录；各轴 verdict 与 live11 相同，主判 fulfilled，工具轴两条问题相同。合计输出 −18%、推理 −11%、六轴耗时 1264s→976s（−23%），单次样本。
- 口径差异（待用户定）：模型轴在"工具返回数据正确、但适配层附了错误的'未返回'说明（tool_execution:p1）"的输入上，live11 判 7 条输入无效，live12 全判做到。对照重跑（`invalid_bias.py`）：旧结构 2/3 有效次判输入无效、1/3 做到（另 1 次输出解析失败），新结构 4/4 做到，推理约减半、耗时约降 2/3。新结构更稳定，但不能排除是"做到写起来更省"带来的偏向；该输入哪种判法对属于协议口径，应写成明确规则而不靠输出成本引导。

## 14. 「本应产出」手工走查（2026-10-09，探索，未改需求/规格/代码）

### 14.1 缘起与边界
讨论中用户指出：现行「每个事件 × 每项职责出一道题」像笛卡尔积，题是程序提前定死的，定得不好就无从判准。方案文档 §3.1 本来就把判定写成「实际产出 vs 本应产出」，缺的只是把「本应产出」从隐含的一句话变成**每个部件实例一份、先写先冻结的显式产物**。名字沿用「本应产出」，不造新词。用户要求：先别动需求和代码；`pair_up` 不用 `situation` 字段的问题**不修**（方向一变它就跟着废）；做完把结果与对 `demand/process_axes.md` §4 的建议一起给他再定。

### 14.2 做法与产物
`report/process-axes-reference-20261009/`（README 为入口）。两个真实 case（保单、D01），六个轴，三类条目：推出 / 守恒 / 外部真值。A=我手写（先冻结后对照，哈希留档；**D01 部分在冻结前读到了输出侧内容，可能受影响的 15 条见 `A_contamination_audit.md`，保单部分仅受早先印象影响**），B1、B2=独立模型只看输入盲写两遍并做核对（中转的 Gemini 线路当天被地区限制，改用 deepseek-flash）。

### 14.3 结果（细节与局限见 README）
- 12 个（case×轴）三个写法都写得出来；类型占比约 推出 68%、守恒 23%、外部真值 9%。
- 找到的真问题：A 6.5/9、B1 7/9、B2 8/9，现行 21 单位流水线 4/9（真问题清单 R1–R9 由我定义，无独立标准答案）。B 的误报约 22%–28%。
- 同一方法写两遍：问题层面 7/8 相同；条目层面严格口径 39%、宽松口径 94%，抽样校准后约 47%（不确定范围大致 30%–65%，样本 24 对）。清单不可逐条复现，结论较稳。
- 两遍共同犯的错（如「本应调用 run_policy_field_lookup」）引的原文是真的、用法是错的，**「依据须为原文引用」挡不住**。
- 外部真值型：B 在非知识轴把 11 条判成了「达到」而无独立来源，须由程序强制记「无法核」。
- 守恒型可由程序核：手核掉 8 条（用户原话/工具返回原样进入下一次输入、参数原样执行、执行余量提示是否更新、澄清原样进入账本与交付）。
- 顺带发现两个 case 共有的真问题：「本轮执行余量」提示在整轮调用中读数不变（保单 2 次、D01 5 次）。
- 手写核对也会错：D01 的 I4 被现行结果对照挖出误判，已更正并留痕。
- 条目一致性的「宽松口径」是看到严格口径偏低后事后加的，两个数都报；盲写的误报（22%–28%）若原样进入问题记录，就是把评测器的错写成业务缺陷（需求 §6），所以推出型必须有独立复核。

### 14.4 待用户决定
是否沿此方向；若是，`demand/process_axes.md` §4「判定单位」一行与 §2.1「verdict 跨 case 可比」的锚都要改（清单每次不同，分母不稳，只能按子能力标签汇总 met/not_met/cannot_check 计数）。推出型条目由谁复核；守恒型是否抽成通用传递核对模块。
**环境提示**：primary（Gemini）线路在 2026-10-09 被地区限制拒绝，线上批量会依赖 fallback。

### 14.5 讨论收敛与方案草稿（2026-10-09）
与用户讨论后收敛为：每个 case、每个轴输出**本应清单**与**实际清单**，拆两次调用——第一次只给该轴的输入写本应并冻结，第二次给完整案卷写实际并逐条给出达到/没达到/无法核，「没达到」与实际一起出、不另行复核。规划轴的第一次调用**不给环节列表**（那是它的输出）。推出/守恒/外部真值三分类**去掉**：守恒类改由程序独立做传递检查，外部真值只留「是否须独立查证」一个标记、由程序锁成无法核。新增 `unexpected`（清单没料到的实际行为），每条本应带子能力标签以支持跨 case 汇总。方案草稿：`spec/draft/process-axes-expected-actual.md`（未采纳；含若采纳要改的条目与同模型对比实验设计，实验未执行）。

## 15. 对比实验与文档调整（2026-10-10 ~ 2026-10-11）

### 15.1 对比实验（探索，未改代码）
在 `report/process-axes-compare-20261009/` 用 8 个真实 case（两遍）+ 4 个未见 case 对比现行六轴与「本应 / 实际」方案。最终形态 new4：两次调用（先写本应并冻结，再写实际）、「没达到 / 意外」必须带逐字短引文并由程序核对、两条通用职责、第二次以多轮追加发送（前缀缓存命中）。结果与局限见该目录 `RESULT.md`，缓存实测见 `CACHE-FINDINGS.md`，拟改需求/规格见 `CHANGE-PROPOSAL.md`。

### 15.2 文档调整（用户确认）
- `demand/process_axes.md` 新增 §1.1「每个轴在评什么」：部件与「输入 → 输出」表从 `spec/alg/process-axes.md` §2.1 上移；它定义"评什么"，与判法无关。
- `spec/alg/process-axes.md` §2.1 改为引用需求 §1.1，保留子能力生成规则的一句话；文首加修订记录。
- 用户确认两点（2026-10-11）：归因只写方向（本轴 / 上游 / 未定位），不强制指向上游记录；轴 verdict 五值按"本轴问题 → 无法核或未定位 → 达到 → 归上游 → 不需要"的顺序汇总。
- 据此修订：需求 §4「判定单位」「统一归属口径」「verdict 取值」三行，§5 新增三条 ⟡（通用职责待补、本应清单覆盖、引文只证明存在）；方案文档按「本应 / 实际」重写 §2–§5、§9–§14（改前备份不入库），§8 只改引用旧取值的措辞。
- 代码未改；改造顺序见方案 §13。

### 15.3 改造第 2 步：纠错轮改为新一轮追加（2026-10-11，已实现）
- `impl/core/llm_client.py`：`complete_json` 新增 `history`（夹在 system 与本轮 user 之间的前几轮消息）；解析失败或强校验拒收改抛 `OutputRejected(ValueError)`，带被拒收的模型原文 `content`。
- `impl/projects/llm_probe/eval_axes/adapters/process_common.py`：纠错轮从「原题 + 更正说明拼进同一条 user」改为 `history=[原题, 被拒收的产出]` + 本轮 user=更正说明；没有产出可带回的 ValueError 不纠错、照原样失败。
- 测试：三个假客户端改为从 history 第一条取原题（`test_process_axis_investigation`、`test_process_prompt_contract`、`test_axis_materials`）；`test_process_prompt_contract` 新增断言纠错请求是 [原题, 被拒收产出, 更正说明]；`test_llm_client_json_extract` 新增 history 顺序与 `OutputRejected.content` 两个测试。全量 2414 通过，失败 12 个与改前相同（与本改动无关）。
- 实测（正式 LlmClient，gemini-3.8-flash-medium，约 2.4 万 token）：第一次 cache_read 0；纠错 cache_read 21,940 / 24,130。
- 未改：`adapters/carryability.py` 也有一处把纠错拼进同一条 user 的写法，不属于六轴本次改造。

### 15.4 新判定路径核心（2026-10-11，已实现，未接入线上入口）
- 新模块 `impl/projects/llm_probe/eval_axes/adapters/process_expected.py`：实验 new4 的正式实现——两次调用（本应冻结 → 实际多轮追加）、第一次只给输入端（材料从同一份完整视图切出）、引文核对 + 至多一轮纠错（新一轮追加）、纠错后结构仍不合格才算评测器错误，引文仍不对则丢弃 / 降无法核（§4）、needs_external 锁无法核、§5 五值汇总与组成、问题记录（problem_id 带轴与批次前缀）、入口 `run_expected_axis`（环节与批次沿用分析轴产物）。子能力取各轴义务的 label + duty。
- `impl/core/llm_client.py`：新增 `constraint_in_user` 与 `with_output_constraint`（两次调用输出结构不同、system 仍逐字相同）。
- 测试 `tests/test_process_expected.py` 14 个；相关测试 527 通过。
- 真实 case 核对（`report/process-axes-compare-20261009/impl_check.py`，正式 LlmClient、gemini-3.8-flash-medium）：B01 与 agg-paid 共 12 轴全部跑通；gold hard 命中 B01 3/4（漏 B01-2）、AP 3/3，与实验一致；36 次请求、输入 0.94M、缓存 0.32M。首跑时把"纠错后引文仍不对"当成评测器错误致 B01 规划轴失败，已按 §4 改正并重跑（旧记录留作 `planning_routing.before-quote-fix.json`）。
- 未做：接入 `run_process_axis` 与三个入口、转写案卷（transcript）路径、跨批去重（实测 agg-paid 上下文轴同一假缺口在两批各报一次）、主轴/表格/前端读新结构、删除网格判法。
- 补充（同日）：跨批去重改为模型声明 `same_as`（后面批次拿到本轴前面批次已记录的问题，同一问题填其 problem_id，程序并入、不另计）——程序按证据比对认不出"同一调用在运行记录与 trace span 两种形态"的重复；第一次调用也加一轮纠错（新一轮追加）。实测：agg-paid 上下文轴 5→3 条，B01 规划轴两种形态的重复查询被合并；测试 17 个通过。

### 15.5 接入线上入口、删除网格与六轴 ToolLoop、下游改读新结构（2026-10-11）
- 入口：`process_common.run_process_axis` 对普通案卷直接走 `process_expected.run_expected_axis`；对话稿案卷（llmtracing）记评测运行错误"过程六轴暂不支持对话稿案卷"，不调模型。`eval_axes/__init__.py` 去掉 llmtracing 自动分流到六轴 ToolLoop。
- 用户确认删除两套六轴 ToolLoop（Agno 版 `process_loop/evaluation.py`、llmtracing 版 `process_loop/llmtracing.py` + `llmtracing_report.py`）——聚类用的 ToolLoop（`impl/core/tool_loop`、`tool_loop_lab`）不受影响。随之删除只为网格服务的 `process_loop/expectation_projection.py`（需求倒推展开）、`adapters/process_output.py`（网格输出结构）、`adapters/process_protocol.py`、`business_trace/providers/llmtracing_evidence.py`、`process_contract.py`；`process_common.py` 只剩轴定义（`Subcapability`、`AxisSpec`）、环节、入口、注册。分析轴 ToolLoop（`process_loop/analysis.py`、`tools.py`）保留。
- 六个轴的"义务"改为"子能力"（名字 / 什么时候用到 / 做对必须成立），去掉环节类型、适用前缀、出处类别、程序直判；duty 文字里的网格取值代码改为新说法。场景配置 `process_obligations`（"不可重试后拦住同参重发"，2026-09-29 确认）作为该场景规划轴额外子能力进第一次调用。
- 运行器去掉问题登记与"输入无效引用上游问题"校验；`AxisRuntime` 去掉 `expectation_projection`、`process_issues`。轴注册 `output_fields` 改为新结构，五值 verdict 说明改写。
- 下游：主轴 `judge.py` 的精简结果与取原文顺序改读本应 / 实际 / 引文；`table_view.py` 去掉义务与 contract_missing；前端 `axes_experiment.js` 问题卡片改为归因原文、影响一句话、逐条引文（展开看记录原文），删除上游问题跳转；`live.html` 过程轴面板改为问题 / 本应·实际 / 意外 / 未覆盖。
- 测试：删除 12 个只测网格或六轴 ToolLoop 的文件（及 `tests/support/unit_reply.py`），混合文件只删网格用例（`test_expectations`、`test_need_source_boundaries`、`test_process_axis_investigation`、`test_axis_materials`、`test_design_rule_blocks`、`test_tool_loop_package`、`test_process_axis_gap_fixes`）；`make_trace` 移到 `tests/support/llmtracing.py`；对话稿改为断言"暂不支持"；新增新输出与注册表契约一致的测试。

### 15.6 冻结样本核对（2026-10-11）
正式实现跑 8 个冻结 case 一遍：hard 召回 19/22、误报 10%、引用可解析 100%、全价输入 2.14M（缓存 0.78M）、每 case 六轴串行中位 504s；稳定漏 B01-2、D01-3、PL-1。首跑 1/48 轴因引文抄入未转义的英文双引号致输出非法，改为"引文写中文引号、核对视同"后重跑通过。详见 `report/process-axes-compare-20261009/RESULT.md` 末节。§9 P1–P7 的逐条落位与人工业务核对仍待做（方案 D12）。
- P1–P7 落位测试 `tests/test_process_axes_p1_p7.py`（8 个，程序侧汇总 / 组成 / 问题记录 / 聚类输入）全部通过。方案 §9 P2 一行改为"两轴各记一条问题"，与 §3.3"同一事件多轴各记"一致（原写"一条问题"是网格时代按 problem_id 跨轴共享的说法）。

### 15.7 步骤端点改用实际记录了内容的字段（2026-10-13，修 bug）
- 起因：fec 批 248 条「无法核」里约一半写的是 assemble / gate / finalize 等步骤"输出未记录"。核对原始 agno 库：`agno_runs.run_data.step_results[*].content` 恒为空，但 `agno_spans` 记录了每个步骤 span 的输入输出（如 gate 的 `{"action":"AGENT",…}`、finalize 的答复正文）。环节端点却指向 `step_results` 的空字段，判定材料里没有这些 span。与此前模型输出端（持久化消息不存正文 → 用 span 输出）是同一类 bug。
- `business_trace/links.py`：
  - `_step_end`：步骤记录没存该字段时，用同轮同名步骤 span 记录的；同名 span 不唯一（循环）时不配。用于意图首步产出、规划路径与分支、步骤传递、交付环节。
  - `context_memory:input`：Agent run 记录没存收到的任务时，用 `agent_run_id` 相同的 Agent span 的输入。
  - 步骤传递环节的 `contains` 事实因此能算出（以前一端缺失恒为空）；fec 批程序可疑数不变（44）。
- 未改：容器步骤（`to_agent`/`to_direct` 这类 Condition/Steps）自身无产出记录、trace 里也没有它的 span，规划分支 / 路径与前后传递环节里它的端点仍如实缺失。试过"容器无记录时改用实际执行的子步骤产出"：规划材料从 2.9M 字符涨到 6.6M、批次 44 → 71，子步骤产出与模型输出、工具调用大量重复；唯一的 direct 分支 span 也只记了 `direct_completed`，无增益，已撤回。
- 离线核对（fec 批 32 case，不调模型，`report/multiturn-needs-20261012/`）：870 个环节的环节集合不变；指向空字段的端点 737 → 179（剩余全是容器步骤）；判定材料里 missing_endpoints 规划 264 → 88、意图 44 → 0、上下文 417 → 88、知识 12 → 3；规划材料字符 +6%、批次 44 → 45，其余轴基本不变。
- 测试：`tests/test_business_trace_links.py` 新增 2 个（步骤 span、Agent span），新测试在旧代码上失败；全量失败 11 个与改前相同（与本改动无关）。
- 实测重判（`exp5_step_ends.py`，新旧 links 各判一次，同一分析产物与需求）：见该目录 README 实验 5。

### 15.8 需求按轮、一批一轮、通用职责按轴取值（2026-10-13，用户确认）
- 起因：F01「用户更正实体未被承接」聚类不属实——第 1 轮的批次被拿去对第 2 轮改口后的需求。调查与实验见 `report/multiturn-needs-20261012/README.md`（70 道多轮题 43% 会在后面改掉前面的要求；实验 1–4）。
- 规格：`spec/alg/expectations.md` §2.1–§2.2（每轮一份需求、E 每条带轮次、判准多轮归最后一轮）；`spec/alg/process-axes.md` §2.1（一批只放一轮、每批只拿本轮需求）、§3.4（通用职责带编号，本批不涉及放 not_covered，按轮按轴取值）、§5（职责每轮每条计一项）。
- 代码：
  - `adapters/expectations.py`：`turn_materials` 按轮切材料，每轮一次调用（`_write`，纠错一次）；编号程序加轮次前缀、标 `turn`；`validate_frozen` 校验冻结 E（出处属于本轮或整案），主判 `need_judge.py` 改用它；最多 8 轮（调用上限 16）。单轮 case 的材料与改前逐字相同（fec 批 24/24）。
  - `adapters/trace_analysis.py`：`turn_batches` 先按轮分组再按大小切批，批次带 `turn`；`prepare_selections` 改用它。与实验 4 的分批逐字节一致（fec 批 192/192）。
  - `adapters/process_expected.py`：`judge_batch` 新增 `turn` 参数；通用职责在提示词中编号 D1…，basis 写了通用职责但无编号时纠错；`standing_duties` 按（轮, 职责）取值，`aggregate` 不再逐条计职责条目；`run_expected_axis` 每批用 `turn_expectations` 取本轮需求，删除"没有 materials 时现场切批"的旁路（与线上分批规则不同），改为报错；结果行与批次带 `turn`、`standing_duty`。
- 测试：新增 5 个（按轮写需求、按轮分批、每批本轮需求、职责按轮取值、职责编号纠错），改 4 个文件的夹具（批次带 turn / duties，冻结 E 带轮次）。
- 实测：见 `report/multiturn-needs-20261012/README.md` 实验 6。

### 15.9 几轮合批（需求按轮标注）、意图看截至本轮的表达（2026-10-14，用户确认）
- 起因：
  - 一批一轮让多轮题批数从 96 增到 150（+56%），多出的多是半空的批，比如意图轴每轮只有一个环节。
  - 意图轴只看本轮首个步骤与首次决策，依赖前一步结果的子问题必然被判遗漏（A11、B17、F01），单轮也受影响。
  - 实验见 `report/multiturn-needs-20261012/README.md` 实验 7a、8、9。
- 规格：`spec/alg/process-axes.md` §2.1（环节按轮排序装批，一批可含几轮，需求按轮标注，本应条目带轮次）、§3.4（职责按条目所属轮取值）、§8（意图的内部表达为截至本轮的全部表达）。
- 代码：
  - `adapters/trace_analysis.py`：`turn_batches` 改为 `axis_batches`，按所属轮次排序后整体按大小切批，批次带 `turns`（列表）。
  - `adapters/process_expected.py`：
    - `ExpectedItem` 新增 `turn`，提示词要求只依据同一轮的需求与材料写；
    - `_expected_list` 校验轮次属于本批，否则纠错；
    - `judge_batch` 的 `turn` 改为 `turns`；
    - `turn_expectations` 取批里各轮的需求；
    - `standing_duties` 按条目的 `turn` 归（轮, 职责）；
    - 结果行轮次取自条目，批次视图带 `turns`。
  - `business_trace/links.py`：意图环节第 N 轮的输入 = 第 1..N 轮用户原文，输出 = 第 1..N 轮全部顶层步骤产出、Agent 收到的任务（run 未存时用其 span 输入）、各次模型调用的工具调用。
  - `adapters/intent_understanding.py`：子能力与 requires 去掉"首个/首批/首次"。
- 测试：
  - 新增 3 个：条目轮次不属本批时纠错、合批时职责按条目轮次取值、意图环节截至本轮；
  - 改写 2 个：批次按轮排序并记录 turns（原"一批一轮"）、批里几轮的需求都给到（原"每批本轮需求"）；
  - 改夹具：批次带 `turns`，本应条目带 `turn`。
- 未做（待重复对比后定）：needs_external 改写为 external_fact、通用职责挪到场景配置（实验 7b/7c）。

### 15.10 没有通用职责的轴不再要求、不再校验职责编号（2026-10-14，修 bug）
- 起因：2026-10-14 整批（c7a504df + f763d7da）里 7 个轴判定失败（model_capability 6 个、knowledge_data 1 个），错误都是"basis 写了通用职责但没写给定的编号"。15.8 把职责写法改成带编号后，提示词对所有轴都讲了通用职责，但只有 context_memory 给了职责；其他轴的模型照样写"通用职责"，却没有编号可填，纠错一次仍不合格。
- 代码：`adapters/process_expected.py` 把职责那条要求拆成 `DUTY_RULE`，只在本轴有职责时接到第一步要求后面；编号校验也只在有职责时做。
- 测试：新增 `test_axis_without_duties_neither_asks_for_nor_checks_duty_numbers`。
