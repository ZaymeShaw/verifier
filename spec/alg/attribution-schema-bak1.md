# Attribute Schema 流转协议与迁移方案

本文定义 Attribute 相关 schema 的长期标准，以及从当前 `ExpectationAttribution + root_cause_hypothesis + evidence_strength` 结构迁移到新协议的一次性任务。

本文只规定 Attribute 如何接收 Judge gap、收集事实、汇总归因、接受独立审查并输出结果。它不规定项目必须使用因果图、固定调查算法或特定类型的业务证据。

本文是 Attribute schema 与 schema 流转的真相源；`spec/alg/attribute.md` 继续描述运行环境和调查流程，但其中涉及旧 AttributeResult、evidence strength 或 Reviewer issue 字段的内容必须迁移为本文标准。

文中的“必须”“不得”是协议要求；“可以”“建议”是实现选择。全文只有两章：第一章是长期协议，第二章是现状差异和一次性改造任务。

## 第一章：Spec 标准——长期 Attribute Schema 协议

### 1.1 协议目标

Attribute 是 Judge 发现 business gap 后、修改原业务系统前的最后一个诊断环节。它必须利用 ContextUnit、Tool、源码、配置、运行结果、重放或其他可达手段实际调查，而不是为每条业务期望生成一个听起来合理的原因。

长期协议遵守以下原则：

- Attribute 只调查 Judge 已确认的 `not_fulfilled` gap；`fulfilled` 不产生缺陷归因，`not_evaluable` 不产生业务缺陷结论；
- 归因按真实业务缺陷合并，而不是按 `BusinessExpectation` 拆分；一个缺陷可以解释多条 expectation，多个彼此独立且都已确认的缺陷可以形成多个 finding；
- 最终结果只交付由当前证据支持的结论，不交付低置信度 hypothesis；无法定位时保留一个 `unresolved_reason`，不通过猜测填空；
- ContextUnit 是事实材料的统一容器；ContextUnit 被注册或在调查中加载不等于它已经是 evidence。主 Attribute 必须完成调查后再选择候选材料，协议重新加载其确切版本，主 Attribute 才能在最终结论中引用它；
- Reviewer 可以质疑 evidence 的真实性、当前 case 相关性和对结论的支持能力，也可以要求补充 evidence，但不产出自己的 evidence 字段，不提供修复方案；
- Attribute 公共 schema 不固定位置类型、因果分析方法或项目业务链。位置可以出现在 EvidenceRef 或结论中，但不设置独立 `locations` 字段；
- schema 不能单独保证归因有效。归因有效性由“真实事实记录 + finding 对证据的显式引用 + 独立 Reviewer 审查 + 有界补证 loop”共同保证。

### 1.2 Schema 总体流转

#### 本文术语与生命周期

本文只为理解 Attribute 链路定义下列术语；其中明确标为“运行态”的对象不新增公共 schema：

| 术语 | 本文中的确切含义 | 产生与生命周期 | 保存与消费 |
|---|---|---|---|
| business gap | Judge 对某条 BusinessExpectation 给出 `not_fulfilled` 时，expected/reference 与 actual 之间被确认的差异。 | 由 JudgeResult 提供；贯穿本次 attribution session。 | Attribute 用它确定调查目标；它本身不是根因证据。 |
| attribution session | 对一个 trace/case 执行完整 Attribute 的边界，从第一次主 Attribute Investigation 开始，到 Reviewer 通过或最大轮次结束。 | 协议创建；覆盖至多两轮主 Attribute/Reviewer，以及 session 级一次 Finalization 回退。 | 用于隔离动态 ContextUnit、EvidenceRef 和 audit。 |
| executor Run | 主 Attribute 或 Reviewer 的一次 Agent Run。二者上下文独立；Reviewer 后的第二轮主 Attribute 也是新的 Run。 | Agent 执行时创建，结束时关闭。 | 每个 Run 拥有自己的 ContextRun、已加载 ContextUnit ID 集合和本次 Finalization 重载成功的 ID 集合。 |
| Context Registry | ContextUnitRecord 的权威登记表，保存材料身份、权限、来源和注册版本 hash。 | 项目初始化或动态注册时写入。 | Search、Load 和确定性门禁读取。 |
| Context Store | 现有 trace、Judge、Attribute 等运行结果的持久化存储；它与 Context Registry 职责不同。 | pipeline 执行后写入。 | API、回归、离线分析读取 AttributeResult；不负责 Search/Load ContextUnit。 |
| Context policy | 当前 executor Run 的 Context 权限与预算，至少包含允许访问的 role/scope、`load_limit` 和 `content_char_budget`。 | ContextRun 创建时由现有 policy resolver 派生。 | Investigation 和 Finalization 中的 Search/Load 共同遵守；Attribute 不另设一套预算。 |
| ContextUnit.id | Registry 中一份材料的稳定身份，例如 `cu-city-config`。 | 注册 ContextUnitRecord 时确定；可跨 Run 使用。 | 运行时解析材料；最终写入 EvidenceRef.location。 |
| static ContextUnit | 不依赖当前 case 的业务源码、配置、契约和知识资料。 | 项目初始化时注册，通常跨 attribution session 复用。 | Investigation、Finalization 和 Reviewer 按权限 Search/Load。 |
| dynamic ContextUnit | 当前 case 调用 Tool、读取运行状态、probe、replay 或模拟后得到的原始结果。 | 事实产生后由运行时注册；必须绑定 project/trace/case/session。 | 同一 attribution session 内的主 Attribute/Reviewer 可访问；不得静默跨 case 复用。 |
| `content_ref` | ContextUnitRecord 指向外部文件或数据的内容地址，与内嵌 `content` 二选一。 | ContextUnit 注册时写入；Load 时解析。 | 它可能指向会变化的内容，因此不能单独证明被引用版本。 |
| `source_hash` | 对注册或重新加载时解析出的完整 ContextUnit content 计算的 hash。 | Registry 注册时保存；每次 Load 重新计算。 | Finalization 和门禁比较版本；最终复制到 EvidenceRef.metadata。 |
| Search | 根据 name/description 查找当前角色有权访问的 ContextUnit 候选，不返回完整内容。 | 某个 ContextRun 内按需调用。 | 只用于发现；Search 命中不能成为 evidence。 |
| Load | 解析并向当前 executor 返回 ContextUnit 完整 content。 | 某个 ContextRun 内调用；成功后进入该 Run 的 loaded 集合。 | Investigation/Reviewer 阅读材料；Load 本身不表示采用为 evidence。 |
| Investigation | 主 Attribute 广泛收集、读取和验证事实的阶段。 | 每轮主 Attribute Run 开始时进入；必要时可由 Finalization 回退一次。 | 产生/加载 ContextUnit 和工作记忆，不直接产生最终 finding。 |
| 暂定结论 | 主 Attribute 在 Investigation 后形成、等待证据自审的内部判断。 | 存在于主 Attribute 工作上下文；Finalization 中可修改或删除。 | 不进入结构化输出、持久化结果或 Reviewer 输入。 |
| Finalization | 主 Attribute 基于重新加载的候选材料，对暂定结论进行证据自审并收敛最终输出的阶段。 | Investigation 后进入；整个 attribution session 最多允许一次回退 Investigation。 | 通过时产生 conclusion 与引用声明；失败时收缩/删除 finding 或 unresolved。 |
| 引用声明 | 私有 AttributeLLMOutput 中的 `context_unit_id + reason`；表示主 Attribute 最终决定如何使用一份在 Finalization 中重新 Load 的材料。 | Finalization 自审通过后由主 Attribute LLM 生成。 | 协议消费并物化 EvidenceRef；不作为公共 schema 或独立记录保存。 |
| 物化 EvidenceRef | 协议校验引用声明的 ContextUnit.id，并补齐 ref_id、source_hash 和运行边界字段的纯代码转换。 | 引用声明通过确定性门禁后执行。 | 产生可内嵌 finding 的 EvidenceRef；不调用 LLM。 |
| EvidenceRef.ref_id | 某个 finding 在本次 attribution session 中对某份材料某个版本的引用 ID，例如 `ev-001`。 | 协议根据引用声明生成；模型不得生成。 | 内嵌 AttributionFinding；Reviewer 和下游 spec/changes 使用。 |
| 确定性门禁 | 不调用 LLM 的协议校验，只检查 ID、Investigation/Finalization Load 状态、hash、project/trace/case/session/run 边界和结果内部一致性。 | 模型输出后、Reviewer 通过后、项目 normalize 后执行。 | 失败时阻止 finding 进入下一阶段；不判断 evidence 是否足以证明 conclusion。 |
| session audit | 调查过程的内部审计记录，包括 phase transition、Search、Load、Tool Call、hash 和失败。 | attribution session 运行时持续追加。 | 调试和离线分析使用；不是 AttributeResult，也不能自动成为 evidence。 |
| Reviewer round | 独立 Reviewer 对已物化 finding/evidence 的一次审查。 | 每轮主 Attribute 输出通过确定性门禁后执行，最多两轮。 | 只输出 passed/issues；不修改 finding，不产生 EvidenceRef。 |

文中的 source reader、probe、runtime check、replay 和 simulation 只是“如何取得事实”的能力类别，不是本协议新增的 schema：source reader 读取授权源码/配置，probe 采集可观察状态，runtime check 查询当前运行事实，replay 对相同输入重新执行，simulation 在明确保真边界内模拟行为。它们的原始结果必须先进入 dynamic ContextUnit，不能直接宣称根因成立。

文中的“可达验证路径”是指当前项目已经暴露、当前角色有权限调用、且能在剩余一次 Investigation 回退内执行的 ContextUnit 或 Tool 能力。仅仅想象某种外部数据可能存在，不算可达路径。

```text
RunTrace + JudgeResult
  → 协议代码从 JudgeResult 派生 not_fulfilled expectation 集合
  → Investigation：主 Attribute 搜索/加载 ContextUnit，调用 Tool，读取源码或执行验证
  → Tool/probe/replay/source 结果注册为静态或当前 case 动态 ContextUnit
  → 调查材料持续积累，此时不标记 evidence
  → 调查完成后，主 Attribute 在工作上下文中形成暂定缺陷结论
  → Finalization：协议提供本轮已加载 ContextUnit 的 id/name/description 列表
  → 主 Attribute 根据列表和调查记忆选择 context_unit_ids
  → 再次调用现有 load_context_units(context_unit_ids) 批量重新 Load 完整材料
  → 主 Attribute 基于重载材料自审暂定结论与证据
      ├─ 关键证据缺失且仍有可达验证：最多一次退回 Investigation 补查
      ├─ 证据不足且无法补足：删除/收缩 finding，写入 unresolved_reason
      └─ 自审通过：生成最终 conclusion 和逐材料引用理由
  → 协议校验引用并将其物化为内嵌 EvidenceRef
  → 协议层组装待审 AttributeResult
  → 独立 Reviewer 审查 evidence 是否足以证明 gap 由 finding 所述缺陷造成
      ├─ passed：形成最终 AttributeResult
      └─ issues：交回主 Attribute 补查、反驳或删除结论
  → 新材料继续注册为 ContextUnit；下一轮再次执行选择、重载和最终引用
  → 最多再执行一轮主 Attribute 和 Reviewer
  → 只保留通过审查的 finding；其余 gap 由 unresolved_reason 说明阻塞
```

流转中只有 `AttributeResult` 是 Attribute 对下游的公共结果。失败 expectation 集合、每个 executor Run 在 Investigation/Finalization 中加载的 ContextUnit ID 集合、模型原始输出、`AttributeReviewOutput`、session audit 和轮次状态都是运行态，不定义为 Attribute 公共领域 schema，也不要求 Mock、Judge 或 `ProjectAttribute` 项目扩展消费。

长期对象被压缩为：

| 层次 | 对象 | 处理方式 |
|---|---|---|
| 已有 Context 协议 | `ContextUnitRecord`、`ContextUnit` | 原样复用，保存和加载事实材料。 |
| 已有通用引用 | `EvidenceRef` | 原样复用，作为 finding 对某个 ContextUnit 确切版本的引用。 |
| Attribute 公共结果 | `AttributionFinding`、`AttributeResult` | 前者新增，后者替换旧字段；这是本次唯一新增/重构的公共领域 schema。 |
| 私有运行边界 | 现有 `AttributeLLMOutput`、`AttributeReviewOutput/Issue` | 不对 Mock/Judge/项目协议开放，不持久化为业务结果。 |
| 运行行为 | Investigation/Finalization 阶段、现有 Search/Load、各阶段加载 ID 集合、session audit | 是执行流程、Tool 和运行状态，不是 schema。 |

协议不新增 `AttributeScope`、`EvidenceUse`、`AttributeDraftFinding` 或 Evidence ledger。

### 1.3 输入协议与归因范围

Attribute 继续直接接收现有 `RunTrace` 和 `JudgeResult`，不修改 Mock/Judge 共用协议。

协议层从 `JudgeResult.fulfillment_assessments` 派生当前范围：

```text
failed_expectation_ids =
  所有 fulfillment_status == "not_fulfilled" 的 expectation_id
```

协议代码只在内存中关联以下输入，不为它们定义额外 scope class：

- `failed_expectation_ids`；
- 对应的 `BusinessExpectation`、`FulfillmentAssessment` 和 Judge gap；
- 当前 `RunTrace` 中的 expected/reference、actual 和原始事实引用。

约束如下：

- 主 Attribute 不需要为 `failed_expectation_ids` 中的每个元素分别输出一段原因；
- finding 通过 `affected_expectation_ids` 表明一个真实缺陷解释了哪些 gap；
- 某条失败 expectation 没有被任何 finding 覆盖时，不生成猜测性占位项；
- `not_evaluable` 表示 Judge 尚未确认可归因的 business gap。Attribute 可以在 `unresolved_reason` 中说明输入或环境为何不足，但不得把评测阻塞包装成业务缺陷；
- Judge 原文和 reasoning 是调查起点，不自动成为业务根因证据。

### 1.4 ContextUnit、EvidenceRef 与证据定稿

#### 现有 ContextUnit 作为事实容器

长期协议复用现有 `ContextUnitRecord`、`ContextUnit`、Registry、Search 和 Load，不增加新的 evidence artifact store，也不增加统一文件片段 selector。

稳定源码、配置、schema、prompt、业务资料和接口契约继续通过静态 ContextUnit 初始化。项目 Tool、公共技术 Tool、source reader、probe、runtime check、replay、simulation 和 Reviewer 新取得的当前 case 结果，注册为 trace/case/session 隔离的动态 ContextUnit。

当前 `BaseContextAdapter.adapt_dynamic_context()` 已定义但尚未进入实际调用链。它的单一职责是把当前 case 已产生的项目事实转换为一个或多个 dynamic ContextUnitRecord，供 Registry 注册；它不搜索根因、不决定 evidence、也不生成 finding。长期协议要求把它或具有相同输入输出语义的公共动态注册入口接入 Attribute；这是新增运行行为，不改变 ContextUnit schema。它与 `ProjectAttribute` 不同：Context adapter 管理材料进入 Context 系统，ProjectAttribute 管理项目侧调查能力和结果规范化。

ContextUnit 的状态含义：

```text
已注册 ContextUnit
  = 当前环境可发现、可授权加载的材料

调查中已 Load ContextUnit
  = 主 Attribute 或 Reviewer 看过调查材料，但尚未决定是否采用

Finalization 根据本轮已加载材料的 id/name/description 列表选择 ContextUnit.id
  = 主 Attribute 结合调查记忆选择需要重新审核的材料

现有 load_context_units 在 Finalization 中重新加载确切版本；主 Attribute 自审结论与证据
  = 通过则生成最终引用；不通过则收缩、删除或最多一次退回 Investigation

finding 内嵌 EvidenceRef 且 Reviewer 通过
  = 最终有效 evidence
```

因此 ContextUnit 不增加 `is_evidence` 字段。某份材料是不是 evidence 取决于它是否被具体 finding 引用，以及引用理由是否经 Reviewer 审查，而不是 ContextUnit 固有类型。

#### 复用现有 EvidenceRef

长期协议复用现有 `EvidenceRef`：

```python
@dataclass
class EvidenceRef:
    ref_id: str
    source: str = ""
    kind: str = ""
    stage: str = ""
    summary: str = ""
    location: str = ""
    payload: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

字段语义：

| 字段 | 长期语义 |
|---|---|
| `ref_id` | 由运行时生成的当前 attribution session 内唯一 ID；模型不得自行发明。 |
| `source` | 对 Attribute 物化的 evidence 固定为 `context_unit`。 |
| `kind` | 复制被引用 ContextUnit 的项目自定义 `unit_type`；公共协议不解释或枚举其业务含义。 |
| `stage` | 固定记录物化该引用的主 Attribute 轮次：`attribute-main-round-1-finalization` 或 `attribute-main-round-2-finalization`。 |
| `summary` | 主 Attribute 提供的引用理由 `reason`；这是模型解释，不是可信事实。 |
| `location` | 被引用的 ContextUnit ID，用于重新 Load 完整材料。 |
| `payload` | Attribute baseline 固定为 `None`。完整材料只从 ContextUnit 重新 Load，避免复制大内容或引入未定义的裁剪策略。 |
| `metadata` | 运行时填写的引用版本与边界信息，必含 `source_hash`、`trace_id`、`case_id`、`attribute_session_id`、`executor_run_id`、`context_source_type` 和 `reason_source=attribute`；动态材料有来源 Tool Call 时另含 `origin_tool_call_id`。 |

不修改现有 EvidenceRef 字段，也不新增 `selector`、`excerpt`、顶层 `content_hash`、`context_unit_id` 或 `reason` 字段。ContextUnit 承载完整事实材料；EvidenceRef 只保存可重新加载的 ContextUnit ID、版本 hash、运行边界以及模型给出的引用理由。

`ContextUnitRecord` 不能在当前协议下直接替代 EvidenceRef：它表示“环境里存在这份材料”，但不表示“某个 finding 为什么引用它”，`source_hash` 也不在其公共字段中，而且 `content_ref` 指向的内容可能变化。EvidenceRef 因而只承担轻量的引用关系和版本快照；它直接内嵌 finding，不再引入顶层 ledger。如果未来 ContextUnit 改为不可变、版本化 ID，并能同时保存 finding 的引用理由，届时可以再折叠 EvidenceRef，本协议不会阻止该优化。

EvidenceRef 已经内嵌 finding，`ref_id` 不承担材料选择功能；保留它仅因为这是现有共享 EvidenceRef 的必需字段，并让 Reviewer/下游能精确指出某一条引用。Attribute 不为材料选择再增加第三种 ID。

#### 主 Attribute 的 evidence finalization 自审

调查过程中，主 Attribute 可以加载大量材料，但不能因为某份材料“看起来相关”就提前把它定性为最终 evidence。只有当 Investigation 已经形成暂定缺陷结论、知道需要证明什么时，才进入 Finalization。

Finalization 不是额外获取 ID 的阶段，也不是第二个 Reviewer。它是主 Attribute 使用审核材料反向检查、修正并收敛自己结论的内部阶段：

1. 协议根据当前 ContextRun 现有 `loaded_ids`，从 Registry 派生本轮已加载材料的简要列表；每项只有 `id`、`name` 和 `description`。该列表只是运行时视图，不命名为新 schema；
2. 主 Attribute 结合暂定结论、调查记忆以及 name/description，选择需要重新审核的 `context_unit_ids`；此选择只是候选重载，不代表这些材料最终都是 evidence；
3. 主 Attribute 使用现有 `load_context_units(context_unit_ids)` 批量重新 Load；协议确认这些 ID 在 Investigation 中已 Load，重新解析 `content_ref`、比较 Registry `source_hash`，并把本次确切完整内容返回主 Attribute；
4. 主 Attribute 使用重新加载的材料审查自己的暂定结论：材料是否真的支撑结论中的关键判断，是否只证明存在某个缺陷却没有连接当前 gap，是否存在冲突或会改变修复方向的解释，以及结论是否超出材料能够证明的范围；
5. 自审通过时，主 Attribute 在紧接着的最终结构化输出中给出收敛后的 `conclusion`，并为实际采用的每份材料给出 `context_unit_id + reason` 引用声明；协议物化为现有 EvidenceRef，并直接内嵌到对应 `AttributionFinding.evidence`；
6. 自审发现关键证据缺失且环境中仍有明确可达的验证路径时，可以退回 Investigation 补查；整个 attribution session 最多允许一次 Finalization → Investigation 回退；
7. 回退后再次 Finalization 仍无法证明时，必须收缩或删除 finding，并把未覆盖 gap 写入整体 `unresolved_reason`，不得继续循环或保留猜测。

Finalization 直接复用现有 `load_context_units`，不新增专用材料重载 Tool。协议只增加阶段记录：区分某个 ContextUnit ID 是在 Investigation 中首次/再次 Load，还是在 Finalization 中为自审重新 Load。只有本次 Finalization 批量 Load 成功返回的 ID 才能出现在引用声明中。

Finalization Load 继续遵守当前 Context policy 的 `load_limit` 和 `content_char_budget`，不得静默截断内容。候选集合超出数量/字符预算时，Load 必须整体失败并返回明确的预算错误；主 Attribute 应减少候选重试，或退回 Investigation，使用 source reader、probe、replay 等手段生成更聚焦且仍可追溯到原始来源的 dynamic ContextUnit。每次进入 Finalization 只允许一次成功的批量重载；预算失败后的缩参重试不计成功。协议不为所有文件格式定义统一 selector。

模型最终输出中的 `context_unit_id + reason` 是私有模型 I/O，不定义为 `EvidenceUse` 领域 schema：

- `context_unit_id` 必须属于本次 Finalization 批量 Load 成功返回的 ID 集合；模型直接从协议提供的 id/name/description 列表复制 ID，不需要凭记忆发明；
- `reason` 说明该材料中的什么事实支持 finding，它可以自然语言引用行号、字段、配置键、日志事件或原文；
- 模型不能填写 `ref_id`、`source_hash`、payload、case/session/run 等可信字段。

协议代码随后：

- 重新确认 ContextUnit ID 属于本次 Finalization Load 成功集合，并校验权限和 source hash；
- 生成 `ref_id`，并填充 `source`、`kind`、`stage`、`location` 和 metadata；
- 将模型的 `reason` 原样写入 `EvidenceRef.summary`，明确它是模型解释而不是原始事实；
- 将 `payload` 固定为空；完整材料始终通过 ContextUnit 重新 Load；
- 拒绝未在 Investigation 中 Load、未在本次 Finalization 中重新 Load、跨 case、版本变化、仅 Search 未 Load、Judge reasoning、未执行预期结果或其他 case 结论。

这里必须区分三种文本及其生成时机：

| 文本 | 谁生成 | 何时生成 | 是否新增独立 LLM Run |
|---|---|---|---|
| finding 的 `conclusion` | 主 Attribute LLM | Finalization 批量 Load 返回后的最终结构化输出 | 否。 |
| `EvidenceRef.summary` | 主 Attribute LLM 生成 reason，协议代码原样复制 | 与 `conclusion` 同一次最终结构化输出 | 否。 |
| `AttributeResult.summary.summary_text` | 协议代码 | Reviewer 处理完成后 | 否；逐字复用已通过 Reviewer 的 `conclusion` 和 `unresolved_reason`，只做确定性拼接。 |
| `AttributeResult.summary` 的状态字段 | 协议代码 | Reviewer 处理完成后 | 否；根据 Judge gap 覆盖情况计算。 |

一次 `attribute_failure(trace, judge)` 从主执行第一轮开始，到 Reviewer 通过或第二轮结束为止，构成一个 attribution session。主 Attribute 和 Reviewer 使用不同的 Agno Run，但共享可访问的 ContextUnit 环境。动态 ContextUnit 与 EvidenceRef 必须按当前 trace/case/session 隔离；重跑时不得把旧 case 动态材料静默当成当前事实。

session audit 可以保存所有 Search、分阶段 Load、Tool Call 和动态 ContextUnit；最终 AttributeResult 只保存每个 finding 实际内嵌的 EvidenceRef，不维护额外 Evidence ledger。

#### 可信边界

运行时可以严格保证：

- `location` 指向的 ContextUnit 在生成该 EvidenceRef 的 executor Run 中先在 Investigation 被 Load，并在当前 Finalization 中重新 Load 成功；
- Finalization 重新加载的完整内容与 `metadata.source_hash` 一致；
- `payload` 按 Attribute baseline 规则固定为空；
- `trace_id/case_id/attribute_session_id/executor_run_id` 和可用的 `origin_tool_call_id` 没有由模型伪造。

运行时不能直接保证：

- `summary` 中的 reason 对材料的解释正确；
- 原始业务来源一定最新、完备或代表真实业务状态；
- 这份材料足以支持 finding conclusion。

后面三项由 Reviewer 通过重新 Load ContextUnit、核对 reason 和 finding 完成。材料完整性与模型推导必须分开，不得因为 ContextUnit 可加载就自动认为归因成立。

### 1.5 AttributionFinding

归因以真实缺陷为中心，使用以下最小结构：

```python
@dataclass
class AttributionFinding:
    finding_id: str
    affected_expectation_ids: List[str] = field(default_factory=list)
    conclusion: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)
```

字段语义：

| 字段 | 长期语义 |
|---|---|
| `finding_id` | 当前结果内唯一标识，供 Reviewer、补证轮次和后续 spec/changes 引用。 |
| `affected_expectation_ids` | 该真实缺陷解释的 `not_fulfilled` expectation；用于多 gap 合并，不表示逐 expectation 独立归因。 |
| `conclusion` | 一段完整、已由当前证据支持的归因结论，同时说明确认了什么业务缺陷，以及它如何造成对应 business gap。 |
| `evidence` | 直接内嵌实际支持该结论的 EvidenceRef，不经过顶层 ledger 和 ref ID 二次跳转。 |

一个 finding 必须满足：

- 对应一个真实业务缺陷；同一缺陷影响多条 expectation 时必须合并；
- `affected_expectation_ids` 非空，且只能引用协议从当前 JudgeResult 派生的 `failed_expectation_ids`；
- `conclusion` 是已验证结论，不得使用“可能”“大概”“疑似”等措辞包装猜测；
- `conclusion` 必须把业务缺陷与 Judge gap 连接起来。仅证明某文件缺陷很多、代码质量差、配置存在异常或某阶段出错，不足以形成 finding；
- `evidence` 非空，并且每个 EvidenceRef 都来自生成该 finding 时 Finalization 批量 Load 成功返回的 ContextUnit ID；
- 证据不足时整个 finding 不进入最终结果，而不是以 `weak`、`medium` 或 hypothesis 形式保留。

协议不设置独立 `locations` 字段。归因可能落在代码、配置、数据、模型行为、prompt、外部服务边界或协议不一致上；材料位置由 EvidenceRef.location 指向 ContextUnit，必要的业务位置说明写入 `conclusion` 或 EvidenceRef.summary/reason。

协议也不拆分 `statement` 与 `verification_summary`。二者共同承担的内容统一放入 `conclusion`，避免模型用一句缺陷描述和另一句泛泛验证重复填充。

### 1.6 主 Attribute 最终输出边界

协议不定义 `AttributeDraftFinding`。`AttributionFinding` 是唯一 finding 领域结构。

实现仍需要解析不可信的模型结构化输出，但这只是现有 `AttributeLLMOutput` 的私有 I/O 边界，不是新的长期业务 schema。其形状固定为：

```json
{
  "findings": [
    {
      "finding_id": "finding-001",
      "affected_expectation_ids": ["expectation-001"],
      "conclusion": "经 Finalization 自审后收敛的结论",
      "evidence": [
        {
          "context_unit_id": "cu-city-config",
          "reason": "该 ContextUnit 在 Finalization 中重新加载的哪项事实支持该结论"
        }
      ]
    }
  ],
  "unresolved_reason": ""
}
```

其中 `evidence` 元素就是前文定义的私有引用声明；协议不会为它再定义 `EvidenceUse` class。`context_unit_id` 必须来自本次 Finalization 重新 Load 成功的 ID 集合。该输出只在主 Attribute LLM 与协议物化逻辑之间存在，物化完成后丢弃。

协议在模型返回后校验并把引用声明物化成 EvidenceRef，组装唯一的 `AttributionFinding`。这一步是“不可信模型字段 → 可信运行时字段”的必要转换，但不复制一套 draft finding 领域对象，也不向下游暴露模型原始输出。

任一引用声明未通过确定性校验时，对应 finding 不得进入 Reviewer；协议先把确定性问题交回主 Attribute 修正。模型不得直接创建 EvidenceRef、填写 payload 或伪造 ref ID。

`unresolved_reason` 的语义是：当前仍有 business gap 没有形成已验证 finding 时，用一段整体说明描述调查为什么无法继续或为什么现有证据不足。它不能包含未验证根因列表。

约束如下：

- 当前所有 `not_fulfilled` expectation 均被 finding 覆盖时，`unresolved_reason` 应为空；
- 只有部分 expectation 被 finding 覆盖时，保留已确认 findings，并用一个 `unresolved_reason` 说明剩余范围；
- 没有任何 finding 时，`unresolved_reason` 必须非空；
- Judge 为 `not_evaluable`、LLM 调用失败、Tool/Context 不可达或 Reviewer 最终不通过时，使用 `unresolved_reason` 说明阻塞，不生成业务缺陷；
- 不按 expectation 分别生成 unresolved 原因；未覆盖的 expectation ID 由协议层计算。

### 1.7 Reviewer 输出与补证 loop

Reviewer 使用以下内部 schema：

```python
@dataclass
class AttributeReviewIssue:
    target: str
    problem: str


@dataclass
class AttributeReviewOutput:
    passed: bool
    issues: List[AttributeReviewIssue] = field(default_factory=list)
```

字段语义：

- `target` 是一个 `finding_id`；如果问题影响整个结果而无法归属单一 finding，则使用 `attribute_result`；
- `problem` 指出已有 evidence 为什么不能支持该结论、某个 EvidenceRef 为什么无效，或者还需要证明什么事实。它可以引用 EvidenceRef ID，但不包含 Reviewer 自己的 `evidence` 字段。

Reviewer 与主 Attribute 使用不同上下文和 Agno Run，但拥有相同的 ContextUnit、项目 Tool、公共技术 Tool、源码和权限空间。Reviewer 可以主动执行验证；其 Tool、probe、replay 或 source 结果注册为当前 case 动态 ContextUnit，并在下一轮对主 Attribute 可见，但不会自动生成最终 EvidenceRef。

Reviewer 新取得的支持性材料不会自动改写 finding。若原 finding 尚未引用足够证据，Reviewer 仍应返回 issue；下一轮主 Attribute 完成补查后，必须在 Finalization 中用现有 Load 重新加载新材料，并在最终输出中给出引用理由，该材料才能进入 finding。

EvidenceRef 是否存在、是否属于当前 case、是否由已 Load ContextUnit 生成、hash 是否一致，先由确定性代码门禁完成。Reviewer 不应把主要上下文和调用预算消耗在重复验真上；只有来源语义、时效性或业务适用性无法由代码判断时，才质疑材料本身。

Reviewer 的核心问题是：

> 当前 findings 引用的 evidence，是否具有足够说服力证明对应 expectation 未满足是由 conclusion 所述缺陷造成？

Reviewer 必须重点检查：

- EvidenceRef.location 对应 ContextUnit 的完整内容是否真的包含 `summary` 中 reason 所声称的信息；
- reason 是否把材料与当前 Judge gap 连接起来，而不只是指出某个无关缺陷、代码坏味道或伴随现象；
- 多个 EvidenceRef 合在一起是否足以从 expected/actual 推导到 conclusion，中间是否缺少会改变修复位置的关键环节；
- 同一组材料是否也符合会导向不同业务修改的主要解释；
- conclusion 是否超出了 evidence 能够证明的范围；
- Attribute 是否忽略了环境中明显可达、足以决定结论的验证路径；
- unresolved_reason 是否诚实描述阻塞，而不是隐藏已存在的有效 finding 或夹带猜测。

Reviewer 不输出修复方案，不指定主 Attribute 必须调用哪个函数，也不产生 evidence 字段。它可以要求补充某类事实，例如“需要证明当前请求实际读取该配置”，由主 Attribute 自行决定使用何种 ContextUnit、Tool 或实验取得该事实。

Finalization 与 Reviewer 不重复：Finalization 使用主 Attribute 的调查记忆，负责主动质疑并修改自己的暂定结论；Reviewer 使用独立上下文，负责检查已提交 finding 的证据说服力，只指出问题。Finalization 自审通过不能替代 Reviewer，Reviewer 通过也不能补写主 Attribute 缺失的 evidence。

默认 loop 最多两轮：

```text
主 Attribute 第 1 轮
→ Reviewer 第 1 轮
   ├─ passed：返回
   └─ issues：主 Attribute 补证、反驳或删除 finding
→ 主 Attribute 第 2 轮
→ Reviewer 第 2 轮
   ├─ passed：返回
   └─ issues：移除未通过的 finding，并写入整体 unresolved_reason
```

第二轮仍失败时，协议层不得把被拒绝 finding 改名为 hypothesis 后保留。所有被移除 finding 原本覆盖的 expectation 自动回到 unresolved 范围。

#### LLM 调用与上下文预算

协议不新增独立 summary LLM 或 evidence registration LLM：

- Finalization 对现有 `load_context_units` 增加一次有意义的批量 Tool round-trip，使候选材料在最终写结论前重新进入模型上下文；
- 主 Attribute 在同一 Agent Run 内完成 Finalization 自审；只有自审通过后，引用理由与 finding `conclusion` 才在批量 Load 返回后的最终结构化输出中生成；
- `EvidenceRef.summary` 由普通代码原样复制引用理由；
- `AttributeResult.summary.summary_text` 由普通代码拼接 Reviewer 通过后的 finding `conclusion` 与 `unresolved_reason`；其余 summary 字段根据 `failed_expectation_ids` 与 findings 覆盖集合派生；
- 动态 ContextUnit 注册、hash 校验、EvidenceRef 生成和最终结果组装均不调用 LLM。

一次 Tool-using Attribute/Reviewer Agent Run 内部仍可能因为 Search、Load 或其他 Tool Call 发生多次模型 continuation；这里“不新增调用”指 evidence 注册和两类 summary 不再启动独立模型 Run 或独立总结步骤。

Finalization 自审发现关键证据缺失时，允许整个 attribution session 内最多一次回退 Investigation。该回退可以增加必要的 Tool Call 和模型 continuation，但不创建新的自审角色；回退预算耗尽后只能提交已证明的较窄结论或 unresolved。

常规 `not_fulfilled` case 的角色级调用为一次主 Attribute Run 和一次 Reviewer Run。只有 Reviewer 返回实质 issue 时，才进入第二次主 Attribute Run 和第二次 Reviewer Run。以下路径直接由代码结束：

- Judge 整体 fulfilled：返回 `not_applicable`；
- Judge `not_evaluable` 且没有已确认 gap：返回 unresolved；
- 主 Attribute LLM/结构化输出失败：返回 unresolved；
- 引用声明未通过 Investigation/Finalization Load、hash、case 等确定性门禁：先生成确定性问题交回主 Attribute，不调用 Reviewer。

Reviewer 初始上下文只包含：

- 被 finding 覆盖的 Judge expectation、expected/actual 和 gap；
- 当前 finding conclusion；
- finding 内嵌 EvidenceRef 的 ref_id、summary/reason、location 和必要 metadata；
- 按需 Load 对应 ContextUnit 以及继续使用同权限 Tool 的能力。

Reviewer 不预载主 Attribute 完整对话、全部 Tool audit、未使用 ContextUnit、完整项目资料或未关联 expectation。需要核查原材料时优先一次批量 Load 当前 finding 引用的 ContextUnit；只有现有 evidence 无法区分主要解释时才继续探索。

### 1.8 最终 AttributeResult

长期公共结果为：

```python
@dataclass
class AttributeResult:
    trace_id: str
    project_id: str
    case_id: str = ""
    findings: List[AttributionFinding] = field(default_factory=list)
    unresolved_reason: str = ""
    summary: Dict[str, Any] = field(default_factory=dict)
```

字段语义：

| 字段 | 长期语义 |
|---|---|
| `trace_id` | 关联本次业务执行和调查。 |
| `project_id` | 关联被测业务项目。 |
| `case_id` | 关联当前 eval/mock case；允许为空。 |
| `findings` | Reviewer 通过后保留的真实缺陷归因，按缺陷而非 expectation 组织。 |
| `unresolved_reason` | 尚未形成已验证归因时的整体阻塞说明；不包含猜测性原因列表。 |
| `summary` | 由协议层派生的展示信息，不由模型生成，不是事实源。 |

EvidenceRef 直接位于各 finding 内；完整材料通过 `location` 对应的 ContextUnit 重新 Load。`AttributeResult.summary` 完全由代码计算；`EvidenceRef.summary` 则由协议代码复制主 Attribute 最终输出中的引用理由。两者都不启动独立 LLM Run。

`summary` 至少派生：

```json
{
  "summary_text": "城市标准化映射缺失导致城市过滤条件未生成。\n排序相关 gap 仍未定位：当前环境无法取得排序服务本次请求使用的特征输入。",
  "finding_count": 1,
  "covered_expectation_ids": ["city_filter"],
  "unresolved_expectation_ids": ["result_ordering"],
  "attribution_status": "partial",
  "is_complete": false,
  "is_formal_attribution": true
}
```

派生规则：

- `summary_text` 是面向 API、CLI、table view 和前端的可直接展示文字，但不是新的事实源；
- Reviewer 通过后，协议按 findings 的稳定顺序取每个 `conclusion` 作为一行；若 `unresolved_reason` 非空，再将其原文作为最后一行；各行仅以换行符连接，不截断、不改写、不重新总结；
- findings 为空但存在 `unresolved_reason` 时，`summary_text` 就是 `unresolved_reason` 原文；
- `not_applicable` 时使用稳定文字 `Judge 未发现需要归因的 not_fulfilled business gap。`；
- `covered_expectation_ids` 是所有 finding 的 `affected_expectation_ids` 并集；
- `unresolved_expectation_ids` 是 Judge 的 `not_fulfilled` expectation 减去 covered 集合；
- 有失败 gap 且全部覆盖为 `complete`；
- 同时存在 finding 和未覆盖 gap 为 `partial`；
- 有失败 gap 但没有 finding，或 Judge `not_evaluable`，为 `unresolved`；
- Judge 没有 `not_fulfilled` 且整体 fulfilled，为 `not_applicable`；
- `is_complete` 当且仅当 `attribution_status == "complete"`；
- `is_formal_attribution` 当且仅当至少存在一个 Reviewer 通过并经确定性门禁保留的 finding。因此 partial 可以是正式归因，而 unresolved 和 not_applicable 不是。

`attribution_status` 表示归因覆盖状态，不表示业务问题已经修复。

存储层保存完整 `summary_text`；前端可以仅在视觉展示时截断，但不能把截断文本回写为归因结果。`summary_text` 与 findings 出现差异时，以 findings、其 EvidenceRef 和 `unresolved_reason` 为事实边界，并应通过重新派生修复 summary，而不是人工覆盖。

### 1.9 确定性校验

公共层在每轮主 Attribute 输出后、Reviewer 通过后和 `ProjectAttribute.normalize_result()` 后都必须执行确定性校验：

- `finding_id` 非空且结果内唯一；
- `affected_expectation_ids` 非空、去重且属于当前 `failed_expectation_ids`；
- 同一真实缺陷不得仅因影响不同 expectation 被明显重复输出；重复判断主要由 Reviewer 完成；
- `conclusion` 非空；
- 每个 finding 的 `evidence` 非空，同一 finding 内的 EvidenceRef 按 `ref_id` 去重；
- EvidenceRef 必须由生成它的 executor Run 的 Finalization 物化；对应 ContextUnit 已在该 Run 的 Investigation 中 Load，并在当前 Finalization 中重新 Load 成功，trace/case/session/run 边界合法，重新加载 content 的 hash 与 Registry `source_hash` 一致；
- 模型不能注入不存在的 EvidenceRef；
- AttributeResult 不保存顶层 Evidence ledger；仅在 Investigation Load、或在 Finalization 重载后未采用的材料只能留在 session audit；
- 没有 finding 且存在失败或不可评估 gap 时，`unresolved_reason` 非空；
- 存在未覆盖 gap 时，`unresolved_reason` 非空；
- summary 只能由代码重新派生，项目层不得自行提高 attribution status；
- Reviewer 未通过的 finding 不得进入最终结果。

确定性校验只能证明引用完整、边界合法和结果内部一致，不能机械证明 evidence 对 conclusion 有用。证据效力必须由 Reviewer 基于当前业务事实审查，不能退化为“调用过任意 Tool 即通过”的门禁。

### 1.10 项目扩展与内部调查边界

公共 schema 只规定最终交换结构，不规定 Attribute 内部调查算法。

项目可以扩展：

- ContextUnit 类型、业务资料和动态 case facts；
- 项目 Tool、probe、runtime check、重放器和模拟器；
- ContextUnit 的 `unit_type`、`source_type`、content 和 tags，以及项目特有动态材料的生成方式；
- 主 Attribute 的搜索、汇总和验证策略。

项目不得扩展或改变：

- 用 hypothesis、confidence 或 strength 绕过 finding 门槛；
- 按每条 expectation 强制生成一个 finding；
- 用项目字段替换 `affected_expectation_ids`、`conclusion` 或内嵌 `evidence` 的公共语义；
- 在 normalize 阶段恢复 Reviewer 已拒绝的 finding；
- 把模型生成的项目总结注册成事实性 ContextUnit，或绕过 Finalization 重载、hash/case 校验直接制造 EvidenceRef。

`ProjectAttribute` 指现有 `impl/projects/<project>/attribute.py` 项目扩展；`build_context()` 提供项目调查上下文，`probes()` 提供项目事实采集能力，`normalize_result()` 只能在公共结果生成后做项目合法化或收缩。它不能新增未经 Finalization/Reviewer 的 finding，也不能改变公共字段语义。

本文中的 baseline 指 evals 为一个项目自动构建、可以进入初始回归的最小 Attribute 实现；draft 指后续在固定数据上优化该 baseline 的实验实现。draft 可以维护候选解释、调查树、因果图、竞争解释或多 agent 讨论等更复杂内部状态，但必须在公共边界收敛为同一个 `AttributeResult`。二者不是本协议新增的 schema。

### 1.11 完整示例

```json
{
  "trace_id": "trace-001",
  "project_id": "client-search",
  "case_id": "case-001",
  "findings": [
    {
      "finding_id": "finding-001",
      "affected_expectation_ids": [
        "city_filter",
        "target_audience_filter"
      ],
      "conclusion": "当前请求的城市值已进入城市标准化环节，但现有映射没有产生标准城市编码；仅补充对应映射后重放相同请求，城市过滤条件恢复，因此这两项 business gap 来自城市标准化映射缺失。",
      "evidence": [
        {
      "ref_id": "ev-001",
      "source": "context_unit",
      "kind": "runtime_result",
      "stage": "attribute-round-1",
      "summary": "该运行材料显示当前请求进入城市标准化时的城市值为深圳，并记录了映射结果为空。",
      "location": "cu-trace-001-city-normalization",
      "payload": null,
      "metadata": {
        "context_source_type": "runtime_check",
        "source_hash": "sha256:runtime-content",
        "trace_id": "trace-001",
        "case_id": "case-001",
        "attribute_session_id": "attribute-session-001",
        "executor_run_id": "attribute-main-round-1",
        "reason_source": "attribute",
        "origin_tool_call_id": "tool-call-runtime-check-001"
      }
    },
    {
      "ref_id": "ev-002",
      "source": "context_unit",
      "kind": "configuration",
      "stage": "attribute-round-1",
      "summary": "该配置材料显示当前生效的城市映射中不存在深圳对应项。",
      "location": "cu-city-mapping-config",
      "payload": null,
      "metadata": {
        "context_source_type": "source_file",
        "source_hash": "sha256:config-content",
        "trace_id": "trace-001",
        "case_id": "case-001",
        "attribute_session_id": "attribute-session-001",
        "executor_run_id": "attribute-main-round-1",
        "reason_source": "attribute"
      }
    },
    {
      "ref_id": "ev-003",
      "source": "context_unit",
      "kind": "controlled_replay",
      "stage": "attribute-round-1",
      "summary": "该重放材料显示只补充城市映射后，相同输入恢复了城市过滤条件。",
      "location": "cu-trace-001-city-mapping-replay",
      "payload": null,
      "metadata": {
        "context_source_type": "replay_result",
        "source_hash": "sha256:replay-content",
        "trace_id": "trace-001",
        "case_id": "case-001",
        "attribute_session_id": "attribute-session-001",
        "executor_run_id": "attribute-main-round-1",
        "reason_source": "attribute",
        "origin_tool_call_id": "tool-call-replay-001"
      }
        }
      ]
    }
  ],
  "unresolved_reason": "排序相关 gap 仍未定位：当前环境无法取得排序服务本次请求使用的特征输入。",
  "summary": {
    "summary_text": "当前请求的城市值已进入城市标准化环节，但现有映射没有产生标准城市编码；仅补充对应映射后重放相同请求，城市过滤条件恢复，因此这两项 business gap 来自城市标准化映射缺失。\n排序相关 gap 仍未定位：当前环境无法取得排序服务本次请求使用的特征输入。",
    "finding_count": 1,
    "covered_expectation_ids": ["city_filter", "target_audience_filter"],
    "unresolved_expectation_ids": ["result_ordering"],
    "attribution_status": "partial",
    "is_complete": false,
    "is_formal_attribution": true
  }
}
```

## 第二章：Changes——现状差异与一次性改造任务

### 2.1 当前 schema 与长期协议的差异

| 当前实现 | 长期协议 | 需要解决的问题 |
|---|---|---|
| `ExpectationAttribution` 按业务期望组织归因 | `AttributionFinding` 按真实缺陷组织 | 避免为每条 expectation 分别编写一个原因；多个 gap 可以合并到一个 finding。 |
| `root_cause_hypothesis` 要求模型始终给出假设 | `conclusion` 只保存已验证结论 | 没有信心时不给猜测，改用一个 `unresolved_reason`。 |
| 顶层和逐 expectation 同时存在 root cause/evidence/location | findings 按真实缺陷组织，并直接内嵌 EvidenceRef | 删除重复、冲突、顶层 Evidence ledger 和二次 ID 跳转。 |
| `suspected_locations: List[Any]` | 删除独立 location 输出 | 位置按需要进入 EvidenceRef 或 conclusion，不假设所有归因都以代码位置为中心。 |
| `evidence: List[Any]` 由模型直接填写 | 调查材料先进入 ContextUnit；Finalization 根据已加载材料目录选择并重载候选材料，主 Attribute 自审结论后再物化内嵌 EvidenceRef | 最终采用发生在调查完成后；重载不仅防止错引，也用于主 Attribute 主动收缩或推翻自己的暂定结论。 |
| `evidence_strength` 允许 weak/medium hypothesis 进入正式结果 | 删除 strength | finding 只有“通过审查并保留”或“不进入结果”；不存在低质量正式归因。 |
| 任意成功 Tool result 可以支撑 strong | finding 必须引用 EvidenceRef，并由 Reviewer 判断其是否支持 conclusion | 真实性检查和证据效力检查分离，不能用“调用过 Tool”代替归因。 |
| Reviewer issue 包含 Reviewer 自己的 `evidence` | Reviewer 只返回 `target/problem` | Reviewer 可以取得新材料，但必须由下一轮主 Attribute 完成调查、Finalization 重载和最终引用。 |
| 第二轮失败后保留 hypothesis 并降级 strength | 删除未通过 finding，写入整体 unresolved_reason | 不把被否定结论换个低强度标签继续交付。 |
| summary 由 attribution 数量和 strength 判断完成度 | summary 从 `failed_expectation_ids` 与 findings 覆盖集合派生 | 展示状态反映已解释多少 gap，而不是模型自报强度。 |

本章中的迁移术语：

- legacy result：使用旧 `ExpectationAttribution/root_cause_hypothesis/evidence_strength` 结构已经持久化的结果；
- legacy reader：只负责读取和展示 legacy result 的兼容代码，不把旧 hypothesis 转换成新 confirmed finding；
- default switch：代表 trace 验收通过后，让 pipeline 默认写入并让下游默认读取新 AttributeResult 的切换；
- representative trace：从已知真实问题中固定下来的端到端验收输入和期望诊断，不是只验证字段形状的单元 fixture。

### 2.2 一次性改造任务

#### Task 1：替换 Attribute 公共 schema

- 在 `impl/core/schema/attribute.py` 增加 `AttributionFinding`；
- `AttributionFinding` 直接包含 `evidence: List[EvidenceRef]`；不增加 `AttributeDraftFinding`、`EvidenceUse` 或顶层 Evidence ledger；
- 将 `AttributeResult` 改为身份字段、`findings`、`unresolved_reason` 和派生 `summary`；
- 保留现有 `AttributeLLMOutput` 作为私有模型 I/O 边界，只接收最小引用声明，不把它提升为公共领域 schema；
- 删除新写入路径中的 `ExpectationAttribution`、`suspected_locations`、`root_cause_hypothesis` 和 `evidence_strength`；
- 更新 schema export、fixture、JSON Schema 生成和结构化输出测试；
- 同步更新 `spec/alg/attribute.md` 中旧 AttributeResult、evidence strength 和 Reviewer evidence 描述，避免两份长期协议冲突；
- 对旧持久化结果提供只读兼容解析，但不得把历史 hypothesis 自动升级为新 finding；旧结果缺乏本协议证据链时只能按 legacy 展示或迁移为 unresolved。

#### Task 2：接通动态 ContextUnit 和 evidence finalization

- 保持现有 `ContextUnitRecord`、`ContextUnit` 和 `EvidenceRef` 字段不变；
- 把 `BaseContextAdapter.adapt_dynamic_context()` 或等价公共入口接入 Attribute 实际运行链；
- 将项目 Tool、公共技术 Tool、source read、probe、runtime check、replay、simulation 和 Reviewer 新结果注册为 trace/case/session scoped 动态 ContextUnit；
- Search 只发现候选，Load 才表示当前 executor 看过完整材料；单纯注册或加载不会自动生成 EvidenceRef；
- 复用现有 ContextRun `loaded_ids`，并从 Registry 派生只包含 `id/name/description` 的本轮已加载材料列表；该列表是运行时视图，不新增 schema；
- Finalization 复用现有 `load_context_units(context_unit_ids)` 批量重新加载材料，不新增专用材料重载 Tool；每次进入 Finalization 只接受一次成功批量重载，预算失败后的缩参重试不计成功；
- finalization 时校验 ContextUnit、权限、project/case/session、已 Load 状态，且重新加载的 content hash 等于 Registry `source_hash`；
- Finalization Load 复用当前 Context policy 的 load_limit/content_char_budget；超限必须整体失败而非截断，随后减少候选或退回 Investigation 生成聚焦且可追溯的动态 ContextUnit；
- 由运行时生成 EvidenceRef：`source=context_unit`、`summary=reason`、`location=context_unit_id`、`payload=None`，并在 metadata 保存 source hash、trace/case/session/run、context source type 和可用的 origin Tool Call ID；
- EvidenceRef 直接内嵌到对应 finding；session audit 保留 Investigation/Finalization 中未使用材料，但 AttributeResult 不维护顶层 Evidence ledger；
- Tool 失败、权限不足和数据不可达可以注册为动态 ContextUnit，供 unresolved 审计使用，但不得绕过 finalization 直接变成业务 finding evidence；
- 对动态 ContextUnit 和 EvidenceRef 做 trace/case/session 隔离与重跑失效处理。

#### Task 3：更新主 Attribute 输出与 Prompt

- 将归因目标从逐 expectation 填写改为按真实缺陷合并；
- Prompt 明确调查过程只积累材料，不提前把材料定性为最终 evidence；
- 调查完成后进入主 Attribute 内部 Finalization：先形成暂定结论，再根据已加载材料的 id/name/description 列表与调查记忆选择候选 ContextUnit；
- 调用现有 `load_context_units` 批量重载后，要求主 Attribute 以材料反向审查暂定结论，而不是直接填写 evidence；
- 自审可以收缩、修改或删除 finding；发现关键证据缺失且存在可达验证路径时，整个 attribution session 最多回退 Investigation 一次；第二次 Finalization 仍不足时必须 unresolved；
- 只有自审通过后才生成最终 conclusion 和逐材料引用理由；
- 协议把私有引用声明物化为内嵌 EvidenceRef，不定义或持久化 draft finding；
- 删除 hypothesis、strength、locations 和逐 expectation attribution 指令；
- 允许主 Attribute 使用任意项目适用的调查方法，不强制因果图或固定 evidence 类型；
- 没有已验证结论时输出空 findings 和一个整体 `unresolved_reason`；
- 部分 gap 已定位时保留 confirmed findings，并用一个 `unresolved_reason` 描述剩余范围；
- 更新 fulfilled、not_evaluable 和 LLM failure 快速路径。

#### Task 4：更新 Reviewer schema 与 loop

- 将 Reviewer 输出改为 `passed + issues[target, problem]`；
- 删除 Reviewer issue 的 `evidence` 字段；
- EvidenceRef 存在性、当前 case 边界、已 Load 状态和 source hash 先由确定性门禁检查，不占用 Reviewer LLM；
- Reviewer 聚焦判断 evidence 是否足以证明 expectation 未满足是由 finding conclusion 所述缺陷造成，也可以指出还缺什么证明事实；
- Reviewer 自己的 Tool、probe、replay 或 source 结果注册为动态 ContextUnit，不自动追加最终 EvidenceRef；
- Reviewer 可以重新 Load EvidenceRef.location 对应的完整 ContextUnit，核对 `summary` 中 reason 是否符合原始材料；
- Reviewer 新取得的支持材料必须由下一轮主 Attribute 完成补查，并经过 Finalization 重载和最终引用后才能进入 finding；
- 第一轮 issues 交回主 Attribute，主 Attribute 自行补证、反驳或删除 finding；
- 第二轮 Reviewer 仍拒绝时，按 target 删除相关 finding；结果级问题无法安全局部处理时删除所有受影响 findings；
- 被删除 finding 的 expectation 回到 unresolved 范围，并写入一个整体 `unresolved_reason`；
- Reviewer failure 与 Reviewer 发现业务证据问题分开处理，基础设施失败不得伪装成业务审查 issue。

#### Task 5：重写确定性门禁与 summary

- 删除当前基于“任意成功 Tool result”和 expected/actual 的 strong gate；
- 校验 finding ID、`failed_expectation_ids` 边界、EvidenceRef 引用、ContextUnit Investigation/Finalization Load 状态、source hash、case 边界和 unresolved 规则；
- 禁止模型注入、覆盖或伪造 EvidenceRef；
- 从 Reviewer 通过后的 finding conclusions、`unresolved_reason`、`failed_expectation_ids` 和 findings 覆盖集合派生 summary；
- `attribution_status` 只使用 `complete/partial/unresolved/not_applicable`；
- 确定性生成前端可直接展示的 `summary_text`、`is_complete` 和 `is_formal_attribution`；`summary_text` 只拼接已审查文本，不另行总结；
- 项目 `normalize_result()` 后重新执行公共校验，防止恢复 Reviewer 已拒绝的 finding；
- 不尝试用确定性代码判断 evidence 是否足以证明 conclusion，该判断交给独立 Reviewer。
- `AttributeResult.summary` 只由已通过 Reviewer 的 findings、`unresolved_reason`、`failed_expectation_ids` 和覆盖集合确定性派生；EvidenceRef.summary 只复制 Finalization 后同一次主输出的引用理由；不得新增独立 summary LLM。

#### Task 6：更新存储、API、前端和下游消费

- Context Registry 保存完整静态/动态材料；Context Store 和 trace 持久化新的 AttributeResult、EvidenceRef；session audit 按现有调试/运行记录机制保存，不混入 AttributeResult；
- API、CLI、table view 和前端改为读取 `findings`、`unresolved_reason` 和派生 summary；面向文字展示继续统一读取 `summary.summary_text`，无需自行调用 LLM 或拼装 finding；
- 删除对 `root_cause_hypothesis`、`suspected_locations` 和 `evidence_strength` 的新写入依赖；
- Check/Cluster 如需归因文本，读取 findings 的 conclusion；不得在下游重新拼装 hypothesis；
- 后续 Attribution Change Spec 以 findings 和 EvidenceRef 为输入，按真实缺陷生成长期协议和 changes；
- 旧结果保留 legacy 读取能力，不与新结果混算完成率。

#### Task 7：迁移项目 Attribute 扩展

- 保留 `ProjectAttribute.build_context()`、`probes()`、`normalize_result()` 等现有项目扩展节奏，避免改动 Mock/Judge 公共协议；
- 将项目 probes/runtime checks 的事实结果注册为当前 case 动态 ContextUnit；
- 删除项目中直接构造 `ExpectationAttribution`、填充 suspected location 或提高 evidence strength 的逻辑；
- 项目 `normalize_result()` 只能做字段规范化、排序、去重或删除/收缩结果；不得新增 EvidenceRef、finding、conclusion 或引用理由；
- ContextUnit 继续以静态业务源码、配置、契约和知识资料为主，动态部分只保存当前 case 事实；
- 项目 Tool 返回原始可观察结果，不直接返回“根因已确认”的模型式结论；
- evals scaffold 生成最小 Attribute baseline 时自动接入 ContextUnit、Tool、动态材料注册和 evidence finalization，不生成逐 expectation 归因模板。

#### Task 8：建立代表 trace 验收

- 使用既有代表问题建立稳定 fixture：QA provided output、client_search 城市能力、marketting stage unknown、deerflow planning/clarification、intent expected 缺失、Judge/Attribute 结构化失败；
- 验证同一真实缺陷影响多个 expectation 时只生成一个 finding；
- 验证独立且都已确认的缺陷可以生成多个 findings；
- 验证“某文件缺陷很多但未证明与当前 gap 有关”不能进入 findings；
- 验证 Tool/source/probe/replay 结果自动注册为动态 ContextUnit，但不会自动成为 EvidenceRef；
- 验证协议基于现有 ContextRun.loaded_ids 返回 `id/name/description` 列表，不新增选择 ID 或目录 schema；
- 验证主 Attribute 只有在完成调查后才选择候选材料，并在现有 `load_context_units` 重新加载后先自审暂定结论，再生成 conclusion 和引用理由；
- 验证 name/description 和调查记忆只用于候选选择，未重新加载完整内容的材料不能进入 evidence；
- 验证 Finalization 自审可以收缩或删除 finding，并且整个 session 最多回退 Investigation 一次；回退后仍不足则 unresolved；
- 验证只有当前主 Attribute Run 在 Investigation 中已 Load、并在当前 Finalization 中重新 Load 成功的 ContextUnit 才能物化 EvidenceRef；
- 验证每次进入 Finalization 只允许一次成功批量 Load 并复用 Context policy；超限时整体失败而不截断，允许缩参重试，或回到 Investigation 生成聚焦 dynamic ContextUnit；
- 验证 content_ref 内容发生变化并与 Registry source_hash 不一致时拒绝物化 EvidenceRef；
- 验证 EvidenceRef.summary 保存模型 reason、location 保存 ContextUnit ID、payload 固定为空，且 Reviewer 能重新 Load 完整材料；
- 验证模型提交不存在、未在 Investigation/Finalization Load 或跨 executor Run 的 context_unit_id 时被确定性门禁拒绝；
- 验证 Reviewer 可以质疑 evidence 并要求补证，且 Reviewer 输出不含 evidence 字段；
- 验证 Reviewer prompt/context 聚焦 evidence 对 conclusion 的证明力，不重复承担可由代码完成的 ID/hash/case 验真；
- 验证 Reviewer 初始上下文不包含未使用 ContextUnit、完整主执行对话或全部 Tool audit；
- 验证 EvidenceRef.summary 和 AttributeResult.summary 都不会启动独立 LLM；
- 验证 `summary_text` 逐字包含按稳定顺序排列的已通过 finding conclusions，并在末尾逐字包含非空 `unresolved_reason`；删除或收缩 finding 后可由代码重新派生，不残留被拒绝结论；
- 验证 complete、partial、unresolved、not_applicable 四条路径的 `summary_text`、`is_complete` 和 `is_formal_attribution`，以及 API、CLI、table view、前端仍能直接展示文字；
- 验证第二轮仍不通过时删除 finding，而不是降为 hypothesis；
- 验证部分定位和完全无法定位时都只保留一个 `unresolved_reason`；
- 验证 `tests/test_protocols.py`、`tests/test_context_runtime.py`、`tests/test_vnext_mock_case_protocol.py` 和 Attribute 端到端代表 trace，确保 Attribute schema 改造不破坏 Mock/Judge/Context 链路。

### 2.3 主要代码落点

| 文件/模块 | 一次性职责 |
|---|---|
| `impl/core/schema/attribute.py` | 定义公共 AttributionFinding/AttributeResult；保留私有 AttributeLLMOutput，不增加 EvidenceUse 或 AttributeDraftFinding。 |
| `impl/core/schema/evidence.py` | 原有 EvidenceRef 字段保持不变；补充 Attribute 场景字段语义与测试。 |
| `impl/core/schema/normalize.py` | 新 schema 归一化与 legacy 只读兼容。 |
| `impl/core/attribute.py` | 新主输出、按缺陷汇总 Prompt、unresolved 路径。 |
| `impl/core/attribute_protocol.py` | Investigation/Finalization 阶段控制、单次回退预算、私有引用声明到内嵌 EvidenceRef 的物化、确定性门禁、Reviewer loop 和最终裁剪。 |
| `impl/core/attribute_environment.py` | 动态 ContextUnit 注册、现有 loaded_ids 的 id/name/description 视图、Investigation/Finalization Load 状态和 hash 校验装配。 |
| `impl/core/attribute_reviewer.py` | `passed/issues[target, problem]` 和独立审查。 |
| `impl/core/context/*` | 静态初始化、case 动态注册、Load hash 记录和 Registry source_hash 读取；不修改现有 ContextUnit schema。 |
| `impl/core/pipeline.py` | 将当前 trace/Judge、执行环境和最终 evidence/result 串联。 |
| `impl/core/summary.py` | 从 Reviewer 通过后的 conclusions、unresolved_reason、failed_expectation_ids 与 findings 覆盖集合派生 summary_text 和状态字段。 |
| `impl/core/context_store.py` | 持久化新结果和 EvidenceRef，保证 run/case 精确加载。 |
| `impl/projects/*/attribute.py` | 迁移项目 facts、probes、runtime checks 和 normalize。 |
| API/CLI/frontend/check/cluster | 消费 findings、unresolved_reason 和新 summary。 |
| `.agents/skills/evals/` | 新项目 baseline 自动接入和代表 trace 验收。 |
| `tests/` | schema、动态 ContextUnit、evidence finalization、review loop、legacy、代表 trace 和跨项目回归。 |

### 2.4 推荐实施顺序

```text
1. 新 schema 与 legacy reader
2. 动态 ContextUnit、分阶段 Load 记录和 run/case/session 隔离
3. 主 Attribute Investigation/Finalization、自审回退和新输出
4. Reviewer 新输出与两轮 loop
5. 确定性门禁和 summary
6. 项目 Attribute 迁移
7. API/CLI/frontend/check/cluster 迁移
8. 代表 trace 验收与默认切换
```

schema、动态 ContextUnit 和 evidence finalization 必须先完成，否则主 Attribute 与 Reviewer 无法串起“调查材料—暂定结论—选择重载—自审核证—最终结论”。默认切换必须在代表 trace 验收之后，不以单元测试通过代替实际归因质量验证。

### 2.5 验收标准

改造完成必须同时满足：

- 新结果不再出现 `ExpectationAttribution`、`root_cause_hypothesis`、`suspected_locations` 或 `evidence_strength`；
- 每个 finding 都按真实缺陷组织，并可以覆盖一条或多条 `not_fulfilled` expectation；
- 没有经过 Reviewer 的 finding 不进入最终结果；
- Tool/source/probe/replay 取得的材料先进入 ContextUnit，不因注册或 Load 自动成为 evidence；
- 主 Attribute 调查完成后才选择候选 ContextUnit；name/description 和调查记忆只用于选择，Finalization 必须重新加载完整材料并自审暂定结论后才生成 conclusion 与引用理由；
- Finalization 是主 Attribute 内部阶段，不是额外 Reviewer；发现缺证时整个 attribution session 最多回退 Investigation 一次；
- EvidenceRef 只能由当前主 Attribute Run 在 Investigation 已 Load、并在当前 Finalization 重新 Load 成功的 ContextUnit 经确定性后处理产生；
- EvidenceRef 复用现有字段：`summary` 是模型 reason，`location` 是 ContextUnit ID，`metadata.source_hash` 是被引用版本；
- EvidenceRef 直接内嵌到 finding；AttributeResult 不存在顶层 evidence ledger；session audit 可以保存未使用材料和分阶段 Load 记录；
- Reviewer 可以质疑现有 evidence 和要求补充事实，但输出没有 evidence 或修复方案字段；
- Reviewer 的首要审查问题是 evidence 是否足以证明 gap 由 finding 所述缺陷造成；ID/hash/case 等机械验真由代码门禁完成；
- EvidenceRef.summary 和 AttributeResult.summary 都不启动独立 LLM 调用；
- `summary.summary_text` 可被 API、CLI、table view 和前端直接展示，且只由已通过 Reviewer 的 conclusions 与 `unresolved_reason` 确定性拼接；
- `summary.is_complete` 只对应 complete，`summary.is_formal_attribution` 只对应至少一个最终 finding；
- 无法定位时 findings 为空，并提供一个整体 `unresolved_reason`；
- 部分定位时保留已确认 findings，并提供一个整体 `unresolved_reason`；
- 无关代码坏味道、缺陷较多的文件或普通配置异常不能在缺少 gap 连接证据时形成 finding；
- Mock/Judge 输入协议和项目 evals 构建节奏不因本次 Attribute schema 改造发生非必要变化；
- 新结构允许后续 draft 优化使用更复杂的内部调查算法，但最终仍收敛为同一个 AttributeResult。

### 2.6 非目标

- 不修改 `BusinessExpectation`、`FulfillmentAssessment`、`GapItem` 或 `JudgeResult` 的公共语义；
- 不要求每种 evidence 使用相同字段或相同验证方法；
- 不向公共 schema 新增统一 selector、excerpt、顶层 content_hash、context_unit_id 或 reason 字段；私有模型引用声明中的 context_unit_id/reason 不持久化；
- 不把 EvidenceRef 数量、Tool Call 数量或 Reviewer passed 简化成自动真理分数；
- 不为 Attribute 引入公共因果图、claim graph、confidence、strength 或 hypothesis；
- 不要求所有归因都定位到源码文件或函数；
- 不让 Reviewer 生成第二套 evidence、修复方案或 next action；
- 不要求 baseline 一次性解释所有 gap；
- 不把未验证结论以低置信度形式保留在正式结果；
- 不在本次迁移中自动实施或提交任何业务系统修复；
- 不自动 commit 本文档或后续代码改动。
