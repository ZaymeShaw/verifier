# Agno-first 动态上下文协议

本文规定 verifier 中 Mock、Judge、Attribute、Check 及项目扩展算法如何在 Agno 中按需发现、加载和使用上下文。目标不是把所有信息塞进 Prompt，而是在不越权、不丢失有效信息的前提下，以尽可能低的上下文成本获得足够证据。

本文只定义上下文知识库相关协议。RunTrace、LiveExchange、Live Request、Extract Output、Judge 和 Attribute 等业务对象仍遵循各自既有协议。

# 第一章：Spec 标准

## 1. 目标与边界

### 1.1 目标

上下文系统必须同时满足：

1. **高信息密度**：默认只给模型任务、角色和少量必需信息；完整内容按需加载。
2. **动态发现**：模型可以把一个任务拆成多个信息需求，一次发现并加载多条有用 ContextUnit。
3. **角色隔离**：Mock、Judge、Attribute、Check 只能检索其职责允许的信息；语义相关性不能突破权限边界。
4. **项目扩展**：公共信息由公共层接入，项目稳定知识可配置，项目动态对象由项目 Adapter 接入。
5. **可验证效果**：当业务效果不好时，能通过对照实验判断是否由上下文缺失、召回、选择或组装不合理导致。
6. **Agno-first**：Session、Run、Tool 调用和 Knowledge/VectorDb 能力优先交由 Agno；verifier 只补充 Agno 不负责的治理与路由边界。

### 1.2 非目标

本协议不：

- 重建一套 Agent、Session 或 Tool 框架；
- 用上下文知识库替代原始业务事实存储；
- 将完整 Trace、Raw Response 或代码无差别复制进向量库；
- 承诺仅靠语义检索就能保证算法效果；
- 允许项目通过 Prompt、配置或自建检索链绕过公共权限控制。

## 2. 最小概念集

协议只公开两个上下文 schema：

- `ContextUnit`：模型最终加载的一份完整信息；
- `ContextUnitRecord`：Registry 中用于保存、过滤、检索和解析该信息的持久记录。

其余对象均不是新的公共 schema：

- Context Policy 是配置；
- Policy 解析结果是一次 Run 内部的不可变值；
- Search 结果是 Tool 的瞬时 JSON；
- 向量条目是数据库内部派生记录；
- 上下文调试信息写入 Agno Run metadata；
- 注册逻辑由公共 Adapter、项目配置和项目 Adapter 承担。

不得再为这些中间状态新增 `ContextUnitSummary`、`ContextSearchHit`、`ContextRegistration`、`EffectiveContextPolicy` 或 `ContextAssemblyAudit` 等公共领域对象。

## 3. ContextUnit 与 ContextUnitRecord

### 3.1 ContextUnit

```python
class ContextUnit:
    id: str
    name: str
    description: str
    content: str
```

字段语义：

- `id`：稳定唯一标识，选择、加载、引用和效果实验均以它关联；
- `name`：短名称，帮助人和模型快速识别；
- `description`：高密度说明，描述内容、适用任务、边界及可回答的问题；
- `content`：完整信息，只有模型明确加载后才进入上下文。

ContextUnit 不携带 project、trace、role、operation、权限、向量分数、存储位置或生命周期。这些属于 Registry 与运行时治理层。

`description` 必须让模型在不读取 `content` 的情况下判断“这条信息是否可能帮助当前任务”，但不能把完整内容复制进描述。推荐包含：

- 这是什么；
- 覆盖哪个对象、阶段或时间范围；
- 能解决什么问题；
- 明确不包含什么或何时不适用。

### 3.2 ContextUnitRecord

```python
class ContextUnitRecord:
    id: str
    name: str
    description: str
    content: str | None
    content_ref: str | None

    project_id: str
    scope: str
    roles: list[str]
    unit_type: str
    source_type: str
    status: str
    tags: dict[str, str]
```

约束：

- `id/name/description` 与加载后的 ContextUnit 一致；
- `content` 与 `content_ref` 必须且只能填写一个；
- 没有稳定外部来源的信息使用 `content`；
- 已存在于 RunTrace、LiveExchange、Agno Run、项目文件或工具结果存储中的信息使用 `content_ref`；
- `content_ref` 只是延迟加载位置，不代表所有信息必须拥有外部引用；
- `roles/scope/status/unit_type/source_type/tags` 仅参与确定性过滤和鉴权；
- Registry 可以内部保存 hash、更新时间和索引状态，但不得因此扩张公共 schema。

### 3.3 Record 与 Unit 的关系

`ContextUnitRecord` 是注册、存储、检索和权限治理形态；`ContextUnit` 是实际提供给模型的使用形态。二者不是两份相互独立的业务数据，也不是两个都需要项目实现的对象。

```text
业务事实
  -> 公共/项目 Adapter 构建 ContextUnitRecord
  -> register_context_unit(record)
  -> Registry 保存 Record，Vector Index 保存可检索信息
  -> search_context_units(queries) 只返回候选 id/name/description
  -> 模型选择一个或多个 id
  -> load_context_units(ids) 读取并校验 Record
  -> 根据 Record.content 或 Record.content_ref 取得完整内容
  -> 返回 ContextUnit{id, name, description, content}
  -> ContextUnit 进入当前 Agno Run
```

加载不是把 Record 原样暴露给模型。公共 Loader 必须：

1. 按 ID 从 Registry 读取 ContextUnitRecord；
2. 使用本次 Run 已解析的 Policy 再次校验 role、scope、operation、status、type 和预算；
3. `content` 非空时直接读取；
4. `content_ref` 非空时调用对应公共或项目 Content Loader，从权威来源解析完整内容；
5. 校验内容仍与 Record 指向的来源一致；
6. 只向模型返回 `id/name/description/content` 组成的 ContextUnit。

因此项目扩展层通常只负责把项目事实适配为 ContextUnitRecord，以及在项目特有 `content_ref` 无法由公共层解析时提供 Content Loader；项目不负责自行构造或注入最终模型上下文。

### 3.4 单元粒度

一条信息在满足以下条件时适合作为独立 ContextUnit：模型可能单独需要它，而不需要同时加载其所属的整个大对象。

应拆分：

- 多轮 Trace 中可独立理解的交互轮次；
- 大型项目文档中用途不同的章节；
- 一次运行中相互独立的错误、工具结果或证据段；
- Judge、Attribute 需要分别核验的事实链。

应合并：

- 离开彼此无法解释的小碎片；
- 长期总是共同被检索和加载的重复单元；
- 只增加 Token、不改变任务判断的信息。

## 4. 存储与 Agno 托管边界

### 4.1 三类存储

1. **Agno 角色 Session 数据库**
   - Mock、Judge、Attribute、Check 使用各自数据库；
   - 同一 Trace 使用相同关联主键；
   - 同角色重跑复用原 Session，并以新 Run 覆盖当前有效判断；
   - Agno 托管 messages、runs、session state 和工具调用历史。

2. **Context Registry（SQLite）**
   - 按项目共享，不按角色重复建库；
   - 权威保存 ContextUnitRecord；
   - 根据 `id` 幂等注册、更新、失效；
   - 负责 `content/content_ref` 解析和加载时再次鉴权。

3. **Context Vector Index（本地持久化）**
   - 按项目共享，同一 ContextUnit 只保存和生成一次向量；
   - 保存 `id`、`name + description` 的 embedding 以及检索过滤字段；
   - 阿里 Embedding 服务只生成向量，不承担 verifier 数据存储；
   - 第一版使用 SQLite 持久化向量和过滤字段，通过 SQL 先过滤，再计算相似度 Top-K；
   - 数据规模需要时可替换向量数据库，但不得改变本协议接口。

完整内容仍以原始权威存储为先。向量索引不保存完整 content，不成为事实源。

角色隔离不通过复制 Registry 或向量实现，而由 ContextUnitRecord 的治理字段和本次 Run 的 Policy 实现。同一条 ContextUnit 可以被多个角色合法复用，但每个角色只能检索和加载其 Policy 允许的范围。

### 4.2 角色数据库与 Trace 关联

不同角色分库是隔离边界，不用同一 Session 混合多角色历史。公共关联字段至少包含：

- `project_id`；
- `trace_id`；
- `case_id`；
- `role`；
- `operation`；
- `run_id`。

跨角色关联通过 `trace_id/case_id` 完成，不通过共享 Session 完成。

### 4.3 重跑

同一角色、同一 Trace 重跑：

- 保留原 Session 和可审计历史；
- 新建 Run；
- 旧判断退出“当前有效结果”；
- 只属于旧判断的动态 ContextUnit 标记失效，不进入新 Run 的检索空间；
- 原始 Trace、Exchange 和业务事实不得因重跑被篡改。

## 5. ContextUnit 注册

### 5.1 三种接入方式

ContextUnit 的注册不使用通用 YAML 事件 DSL。注册来源按稳定性分为三类：

1. **公共 Adapter 代码**
   - 接入协议层标准对象；
   - 例如 RunTrace、LiveExchange、Live Request/Output、Judge gap、Attribute result、可复用 Agno 历史；
   - 由公共层保证稳定 ID、类型、scope、roles 和内容引用正确。

2. **项目配置**
   - 接入稳定、声明式的项目知识；
   - 例如项目文档、字段定义、公开能力、固定规则、代码根目录；
   - 配置只能缩小适用范围，不能扩张角色权限或解除禁止项。

3. **项目 Adapter 代码**
   - 接入只有项目知道如何解析的动态对象；
   - 例如 DeerFlow workflow node、message event、gateway response、client_search 阶段结果；
   - 项目 Adapter 产出 ContextUnitRecord，统一调用公共注册入口，不能直接写 Registry 或 Vector Index。

这样既避免把类型与权限安全交给任意 YAML，又保留项目动态数据所需的表达能力。

### 5.2 非实时项目知识初始化

非实时、相对稳定的项目知识必须通过人工触发的项目初始化注册，不得在每次 Mock、Judge、Attribute 或 Check 运行时重新扫描、生成描述或调用 Embedding：

```bash
python -m impl.context init --project deerflow
```

初始化范围由项目配置声明，典型内容包括 Live Schema、字段定义、公开能力、固定规则、项目文档和需要长期检索的代码说明。

```text
读取项目配置
  -> 公共/项目 Adapter 扫描稳定知识
  -> 构造 ContextUnitRecord
  -> 必要时生成 name/description
  -> 调用 Embedding
  -> 写入该项目共享的 Registry 和 Vector Index
```

description 的生成优先级为：

1. 项目配置显式提供；
2. Adapter 根据标准结构化字段确定性生成；
3. 只有大型非结构化内容无法确定性描述时，才在该初始化命令中调用 LLM；
4. 运行时 Search/Load 不得临时调用 LLM 生成或重写 description。

为避免重复成本，Registry 内部只需维护最小缓存信息，不扩张 ContextUnitRecord 公共 schema：

- `source_hash`：判断权威来源内容是否变化；
- `description_hash`：判断既有 description 是否可复用；
- `embedding_model`：判断向量是否需要按新模型重建。

再次手工初始化同一项目时：

- `source_hash` 未变化：复用 description 和 embedding；
- 来源内容变化：重新生成受影响单元的 description 和 embedding；
- 只修改 scope、roles、status 等治理字段：只更新 Registry 和索引过滤字段，不重新 Embedding；
- Embedding 模型变化：只重建向量，不重新生成 content；
- 本次配置已删除的稳定知识：将对应旧 Record 标记失效。

本协议不设计自动增量初始化、后台文件监控或复杂初始化状态机。稳定知识明显变化后，由项目维护者再次手工运行初始化命令。

### 5.3 动态注册入口

```python
register_context_unit(record: ContextUnitRecord) -> None
```

公共入口必须：

1. 校验 schema、`content/content_ref` 二选一和角色边界；
2. 按 `id` 幂等写 Registry；
3. 对 `name + description` 生成 embedding；
4. 更新 Vector Index；
5. 当源对象失效或重跑时同步撤销索引可见性。

它不是“增量初始化”。它只处理运行过程中已经产生并确认成立、后续可能复用的业务事实。

同一稳定 ID、相同内容的重复事件必须直接复用既有 Record 和 embedding；不得重复调用 Embedding。

### 5.4 注册时机

注册不是在启动时把所有可见数据一次性转成 ContextUnitRecord，也不是每次 Tool 调用后无条件注册。判断标准是：**后续模型是否可能需要独立发现并加载这份已经成立的信息**。

| 信息类型 | 注册时机 | 示例 |
|---|---|---|
| 稳定项目知识 | 人工运行项目初始化命令时 | Live Schema、字段定义、公开能力、固定规则 |
| 已完成的标准业务事实 | 原始对象成功完成并写入权威存储后 | LiveExchange、某轮 Live Request/Output |
| 跨轮需要复用的历史 | 当前轮完成且事实被确认有效后 | Mock 用户认知、历轮用户可见交互 |
| 诊断证据 | Tool 结果确认有跨步骤、跨轮次或审计价值时 | 错误日志、代码定位结果、接口验证结果 |
| 当前 Run 的临时结果 | 默认不注册，直接使用 Tool Result | 一次性搜索结果、临时中间状态 |
| 失败、不完整或被撤销的对象 | 不注册，或将既有 Record 标记失效 | 未完成 Exchange、无效响应、重跑覆盖的旧判断 |

生命周期要求：

- 稳定项目知识只由人工项目初始化读取项目配置后注册或更新；
- 协议对象由公共生命周期事件触发公共 Adapter；
- 项目动态对象只有在项目 Adapter 能确认它已成为可复用事实时才注册；
- 当前 Tool 的即时返回可以直接供同一 Run 使用，不需要先经过 Registry；
- 已注册来源发生变更、撤销或重跑覆盖时，必须同步更新 Record 和索引可见性；
- 不得从未完成对象、模型猜测或前端展示文本反向伪造 ContextUnitRecord。

不得自动把所有字段、日志或 Tool 输出都注册为 ContextUnit。

## 6. Policy：确定性权限与预算

### 6.1 定位

Context Policy 只回答：某个 `role + operation + project_id` 在本次 Run 中**允许、必须、禁止和最多加载什么**。它不负责语义相关性判断，也不决定最终加载哪条候选。

Policy 至少表达：

- allowed / forbidden roles、scopes、unit types、source types；
- mandatory unit selectors；
- candidate 数量、加载条数和 Token 预算；
- 当前 project、trace、run 的可见范围。

运行时统一解析：

```python
policy = context_policy.resolve(
    role=role,
    operation=operation,
    project_id=project_id,
    trace_id=trace_id,
    run_id=run_id,
)
```

解析结果只是本次 Run 内部不可变值，不定义为 `EffectiveContextPolicy` 公共 schema。Search、Load、mandatory 解析、Prompt 组装和结果校验必须共享这一份值。

权限必须执行两次：Search 先使用 Policy 将 project、role、operation、scope、type 和 status 固化为检索范围，再在该范围内计算向量相似度；Load 根据候选 ID 取得 Record 后，使用同一份 Policy 再次鉴权，通过后才可解析完整 content。即使模型猜到或从历史获知禁止单元 ID，也不能绕过 Load 鉴权。

### 6.2 多层配置

Policy 可以由公共默认、Role、Operation、Project 和 Run 限制组成。合并原则是限制性合并：

- 下层可缩小范围或预算；
- 项目可声明项目特有 unit type、source type 和 mandatory 单元；
- 下层不得解除上层 forbidden；
- Run 临时配置不能跨角色、跨项目或跨 Trace 扩权。

同一角色允许有多个 operation。Mock 至少区分 intent inference、continue decision、next request build；Judge 和 Attribute 也可按项目任务细分 operation。核心必需信息和预算随 operation 变化，而非按角色永久固定一套上下文。

### 6.3 典型角色边界

- Mock：只能使用用户可见的项目认知、Intent、历轮 Live Request 和 Extract Output；不得看到 Reference、Judge、Attribute 或系统内部实现。
- Judge：可使用 Request、Output、Reference、真实 Exchange 和判定规则；不得读取与当前 case 无关的其他 Trace。
- Attribute：可使用 Trace、Exchange、Judge 结论、项目代码、日志和诊断工具结果；仍受 project/trace 边界限制。
- Check：可使用协议、项目配置、代码和验证结果；不能凭借检查角色读取无关业务数据。

## 7. 多需求检索与多单元加载

### 7.1 唯一运行主链

```text
角色算法开始(role, operation, project_id, trace_id, task)
  -> Runtime 解析本次 Policy
  -> 加载 mandatory ContextUnits
  -> 首次 Prompt 仅包含任务、角色、mandatory 内容和受限 Tools
  -> 模型把任务拆成 1..N 个信息需求
  -> search_context_units(queries=[...])
  -> Runtime 在固定 Search Scope 中逐 query 检索
  -> 合并、去重并保留各需求的候选覆盖
  -> 模型按 matched_queries 选择 0..N 个 selection_ref
  -> load_context_units(unit_refs=[...])
  -> Runtime 整批鉴权、解析和预算校验
  -> 多个完整 ContextUnits 返回同一 Run
  -> 模型可继续调用业务 Tools、再次检索或输出结果
```

### 7.2 多需求搜索

```python
search_context_units(
    queries: list[str],
    top_k_per_query: int | None = None,
) -> list[dict]
```

模型先把任务拆为多个独立、可单独理解的信息需求，而不是只写一个过宽查询。例如 Attribute 可同时提出：

- “第三轮真实 Raw Response 错误 错误类型 发生位置”；
- “familyrelation 字段 提取逻辑 关系约束”；
- “gateway 404 路由配置 匹配规则”。

待检索项应写成紧凑检索词组合，而不是任务改写或宽泛主题。每条至少保留一个任务原文中的具体关键词，并按实际存在的未知点补充以下一种信息：实体定义/别名/隐含属性、条件实现表示、范围边界/转换、枚举/值映射、跨对象组合约束。不得凭空增加任务没有涉及的存储、权限、状态或其他条件。

查询可以包含用于发现的同义词、别名或待验证假设，但查询文本本身不是权威证据。模型只能依据显式加载后的 ContextUnit 内容或其他权威输入形成最终判断。

实现过程：

1. Runtime 根据已解析 Policy 固化 Search Scope；模型不能提交 scope、role、project 或权限过滤条件；
2. Runtime 对 queries 去空、去重并保持首次出现顺序，然后检查查询预算；
3. 查询文本批量调用阿里 Embedding；
4. 每个 query 在本地索引中分别取 Top-K；单 query 的内部检索深度由 `top_k_per_query` 控制，不得被最终候选总预算截成更小的值；
5. 先按 query 顺序为每个有结果的信息需求保留一个候选，再按跨查询相关性补足剩余候选；
6. 同一 ContextUnit 可覆盖多个 query，只占一个候选位并保留全部 `matched_queries`；
7. 若顺序覆盖因候选预算不足而失败，Runtime 应在已召回候选中做有界的共享候选覆盖恢复；只有确实不存在预算内覆盖组合时才明确失败，不得静默丢弃部分信息需求；
8. Tool JSON 返回 `selection_ref/id/name/description/matched_queries`，不返回完整 content；`selection_ref` 是本 Run 内的短暂引用，不是新的公共 schema 或持久 ID；
9. 模型按 `matched_queries` 检查每个原子需求是否有直接回答，严格区分主体与关联对象等字段归属差异，并逐字复制 `selection_ref` 交给 Load，不得缩写或重新生成长 ID；
10. `candidate_limit` 限制可供模型比较的摘要候选池，`load_limit` 限制最终加载的完整内容，两者是不同阶段的预算。不得仅因完整内容最多加载 8 条，就把多 query 的摘要候选池也截为 8 条；
11. 模型可从候选中选择多条，也可一条都不选。

Search 是受限 Agno Tool，不是数据库 schema。它查询 Registry 对应的本地 Vector Index。

### 7.3 批量加载

```python
load_context_units(unit_refs_or_ids: list[str]) -> list[ContextUnit]
```

加载必须：

- 优先将本 Run Search 返回的 `selection_ref` 解析为稳定 ID；公共 API 仍可接受精确稳定 ID；
- 按解析后的稳定 ID 去重并保持首次出现顺序；
- 对整批 ID 再次检查 role、scope、status、type 和累计预算；
- 并行解析可独立的 `content_ref`；
- 任一单元越权、失效或无法解析时整批失败，不返回半批内容；
- 成功后一次返回多条完整 ContextUnit；
- 超大内容通过预先拆分的子单元处理，不静默截断。

模型可以在同一 Agno Run 中交替调用 Context Search/Load 和项目业务 Tools。即时 Tool Result 可直接用于当前推理；持久复用时再走注册链。

### 7.4 角色算法中的接入时点

Context Runtime 在每个角色 operation 开始时接入，但不要求运行前一次性组装全部上下文：

1. operation 开始，Runtime 解析本次 Policy；
2. 自动加载少量 mandatory ContextUnit；
3. 首次调用模型；
4. 模型根据当前任务判断缺失的一个或多个信息需求；
5. 模型按需 Search、批量 Load，或调用业务 Tool；
6. 信息仍不足时可继续一轮 Search/Load；
7. 模型输出角色结果，Runtime 保存 `context_debug`。

因此“接入 Context Runtime”不等于“把知识库全部注入角色 Prompt”。mandatory 之外的信息只有在当前 operation 实际需要时才加载。

## 8. 信息密度与 Prompt 组装

### 8.1 首次上下文

首次 LLM 输入只包含：

- 当前角色与 operation；
- 当前任务；
- 当前 case/trace 的最小身份信息；
- Policy 规定的 mandatory ContextUnits；
- Search/Load Tools 的简短使用说明；
- 当前 operation 必需的业务 Tools。

不得默认拼入完整历史、完整 Trace、完整项目文档或全部工具结果。

### 8.2 候选与完整内容分离

路由阶段只使用 `name + description`。只有模型选择的单元才加载 `content`。因此选择付出的上下文成本由少量高密度候选描述组成，而不是候选全集的完整文本。

### 8.3 预算

预算至少覆盖：

- 单次 query 数量；
- 每个 query 的候选数；
- 融合后的总候选数；
- 单次和累计加载单元数；
- ContextUnit 累计 Token；
- Tool 调用次数。

预算耗尽时返回明确错误，由模型在已有信息上完成任务；不得自动扩大窗口或加载全部内容。

本版本只规定必须存在这些硬边界，不固定各角色和 operation 的具体数值。具体预算、动态调整和效果/成本权衡作为后续独立设计议题；在该设计完成前，各 operation 必须使用可配置的保守默认上限，不能以“预算待定”为由取消限制。

## 9. 上下文效果诊断

### 9.1 要解决的问题

这里诊断的是**算法效果是否因为上下文构造不合理而变差**，不是只检查权限错误、加载失败或 Token 超限。

仅记录“检索了什么、加载了什么”不能证明上下文好坏。必须在固定 case 上进行反事实对照。

### 9.2 Current / Oracle Context 对照

对效果不佳的固定 case，至少运行两组：

1. **Current**：使用当前 Policy、检索、选择和组装链路；
2. **Oracle Context**：保持同一模型、Prompt、Tools、角色权限和业务输入，但绕过动态路由，人工或离线程序提供一组充分且仍然合法的上下文。

Oracle Context 不是“所有信息”，更不能越权。例如 Mock 的 Oracle 仍不能包含 Reference、Judge、Attribute 或内部代码。

判断：

- Oracle 显著优于 Current：问题位于上下文注册、检索、候选描述、选择、加载或组装；
- Oracle 与 Current 都差：优先检查模型、Prompt、Tool、业务算法、事实源或目标定义，而不是盲目增加 ContextUnit；
- Current 接近 Oracle：上下文链路已不是主要瓶颈。

### 9.3 定位具体 ContextUnit

确认是上下文问题后，对 Oracle 和 Current 做组合实验：

- **前向增加**：向 Current 逐条或成组增加候选单元；
- **后向消融**：从 Oracle 逐条或成组移除单元；
- **交互组合**：验证单元组合是否共同起效，不能只看单条边际贡献。

示例：

```text
Current         0.45
Current + C     0.70
Current + E     0.52
Current + C + E 0.90
```

这说明 C 有独立价值，E 单独价值有限，但 C+E 存在显著组合价值。不能因为 E 的单条提升小就删除它。

根据实验结果采取动作：

| 观察 | 修复动作 |
|---|---|
| 权威来源有关键事实，但没有对应单元 | 新增 ContextUnit |
| 直接注入有效，但 Search 未召回 | 调整 name、description、粒度或索引 |
| 已召回但模型未选择，直接加载有效 | 改善候选描述、需求拆解或选择指引 |
| 已加载但无收益或造成退化 | 删除、降级为低优先候选或限制 operation |
| 单元只有部分内容有效 | 拆分 |
| 多单元长期共同使用且高度重复 | 合并 |
| 只对特定任务有效 | 收窄到对应 operation |

新增、删除、拆分、合并、描述修改和 Policy 调整都必须走 draft/离线优化：在失败 case 与未参与调优的回归 case 上比较业务效果、Token 和检索路径，改善且无明显退化后再推广。

### 9.4 最小调试记录

为支持复现上述实验，Context Runtime 将最小调试数据写入 Agno Run metadata，不建立独立 Audit schema 或 Agent：

```json
{
  "context_debug": {
    "policy": {},
    "mandatory_ids": [],
    "search_queries": [],
    "query_candidate_coverage": {},
    "candidate_ids": [],
    "candidate_refs": {},
    "loaded_ids": [],
    "prompt_tokens": {},
    "content_hashes": {}
  }
}
```

`query_candidate_coverage` 记录每条规范化查询对应的返回候选 ID，用于区分“模型没有提出信息需求”“提出了但未召回”“召回了但未加载”和“加载后未正确使用”。该记录用于重放 Current、构造 Oracle 对照和进行消融；它本身不负责判断哪条 ContextUnit 有价值。

## 10. 公共层与项目扩展层

### 10.1 公共层负责

- ContextUnit / ContextUnitRecord schema；
- Registry、Embedding、Vector Index；
- 公共协议对象 Adapter；
- Policy 解析及限制性合并；
- guarded Search/Load Tools；
- mandatory 与 Prompt 组装；
- Agno Session/Run 关联；
- `context_debug` 记录与离线实验工具；
- 权限、预算、幂等、重跑和回归测试。

### 10.2 项目扩展层负责

- 稳定项目知识配置；
- 动态项目对象 Adapter；
- 项目特有的 unit type、source type 和 operation；
- 项目角色 Prompt 与业务 Tools；
- Oracle Context 样本或构造规则；
- 项目固定 case 上的效果和退化验证。

项目扩展层不得：

- 自建绕过公共 Policy 的上下文拼接链；
- 直接写 Registry 或 Vector Index；
- 通过配置解除公共 forbidden；
- 将 Reference、Judge 或内部实现泄漏给 Mock；
- 为提高召回而默认加载整个项目知识库。

## 11. 验收标准

### 11.1 功能与安全

- ContextUnitRecord 可幂等注册、更新、失效和按 ID 加载；
- inline content 与 content_ref 均可解析，且严格二选一；
- Search Scope 只能由 Runtime 生成，模型无法扩大；
- 多 query 可发现覆盖不同信息需求的多条候选；
- 批量加载可同时返回多条 ContextUnit，并满足整批鉴权和累计预算；
- 不同 project、trace、role、operation 的数据不互相泄漏；
- 重跑保留审计历史，同时旧判断和旧动态单元退出当前结果；
- Agno 业务 Tool 与 Context Search/Load 可在同一 Run 内协作。

### 11.2 算法效果

- 固定失败 case 可重放 Current；
- 可在不改变模型、Prompt、Tools 和角色边界的前提下运行 Oracle Context；
- 可执行单条和组合的前向增加、后向消融；
- 能区分“没有合适单元”“未召回”“未选择”“加载无效”和“非上下文问题”；
- ContextUnit/Policy 变更同时报告业务指标、Token、候选与加载路径；
- 在未参与调优的回归 case 上无明显退化。

# 第二章：Changes

## 1. 现状差异

当前实现与本标准的主要差异：

1. 上下文主要依赖 Prompt 拼接或零散 ContextRecord，缺少统一 ContextUnit 主链；
2. `SemanticVectorDb` 以内存为主，尚未形成持久 Registry + 本地 Vector Index；
3. 搜索多为单 query，尚不能按多个信息需求融合发现多条 ContextUnit；
4. 缺少批量、整批鉴权的 `load_context_units(ids)`；
5. 公共对象、稳定项目知识和动态项目对象的注册职责尚未清晰分层；
6. Context Policy 的 role + operation 解析、限制性合并和共享执行尚不完整；
7. Agno Session、Context Registry 和业务 Trace 的关联尚未统一；
8. 缺少可复现的 Current / Oracle Context / 组合消融效果评估；
9. 调试记录分散，无法稳定重放上下文选择路径；
10. `impl/data/context_store/<project>/` 等旧数据需要只读保留，不能伪造成新 ContextUnit。

## 2. 一次性改造任务

### 2.1 收敛协议与模型

1. 只保留 ContextUnit、ContextUnitRecord 两个公开上下文 schema；
2. 删除或内化 ContextUnitSummary、ContextSearchHit、ContextRegistration、EffectiveContextPolicy、ContextAssemblyAudit 等中间概念；
3. 明确 `content/content_ref` 二选一和稳定 ID 规则；
4. 清理重复的角色上下文拼接路径。

### 2.2 建立存储

1. 新建 SQLite Context Registry；
2. 将现有 SemanticVectorDb 改为本地持久化实现；
3. 使用 `impl/config.yaml` 指向的阿里 Embedding 配置生成向量；
4. 先用 SQL 做 project/scope/role/type/status/tags 过滤，再计算相似度；
5. 建立角色 Agno Session 数据库与 trace_id/case_id 关联；
6. Registry 和 Vector Index 按项目共享，同一 ContextUnit 不因角色不同重复生成向量；
7. 旧 context_store 数据只读保留，不自动迁移为事实。

### 2.3 建立注册链

1. 实现 `python -m impl.context init --project <project_id>` 手工项目初始化命令；
2. 为稳定项目知识提供受限配置和公共/项目 Adapter；
3. 实现 `source_hash/description_hash/embedding_model` 最小缓存，避免重复摘要和 Embedding；
4. 实现 `register_context_unit(record)` 动态事实公共入口；
5. 为 RunTrace、LiveExchange、Request/Output、Judge gap、Attribute result 和稳定历史实现公共 Adapter；
6. 为 DeerFlow 等项目实现动态对象 Adapter；
7. 不实现自动增量初始化、后台扫描或通用 YAML Registration Rules DSL；
8. 增加源对象更新、失效和重跑时的索引同步。

### 2.4 建立运行链

1. 实现 `context_policy.resolve(role, operation, project_id, trace_id, run_id)`；
2. 让 mandatory、Search、Load、Prompt 和结果校验共享同一解析值；
3. 实现多 query `search_context_units`、候选融合、去重和需求多样性保护；
4. 实现 `load_context_units(ids)` 的顺序、去重、整批鉴权、累计预算、并行解析和原子失败；
5. 将受限 Search/Load 注册为 Agno Tools；
6. 允许与项目业务 Tools 在同一 Run 中交替调用；
7. 首次 Prompt 改为任务 + mandatory + Tools，不再默认拼入全部历史与 Trace；
8. 确保 Policy 在 Search 固化范围和 Load 读取内容前分别执行一次。

### 2.5 迁移角色与 operation

角色迁移必须渐进实施，顺序为：

1. **Attribute**：先接入 Trace、Exchange、代码、日志和工具结果。它的信息类型最丰富，也最适合验证多需求检索、批量加载、效果提升和 Token 降低；
2. **Judge**：再接入 Request、Output、Reference、真实 Exchange 和判定规则，验证 mandatory、证据边界与结果引用；
3. **Mock**：公共链路稳定后，分别为 `intent_inference`、`continue_decision`、`next_request_build` 定义 Policy，不允许整个 Mock 共用一套固定上下文；
4. **Check 与项目扩展**：最后接入协议、项目配置、代码、验证结果，以及 DeerFlow 等项目特有知识和动态 Adapter。

各项目只补充项目特有知识、Adapter、operation、Prompt 和 Tools，不复制公共 Registry、Search、Load 或 Policy 链路。

### 2.6 首个最小闭环

第一次实施只打通以下路径：

```text
真实 RunTrace / LiveExchange
  -> 公共 Adapter 注册 ContextUnitRecord
  -> Attribute 将定位任务拆成多个 query
  -> Search 返回覆盖不同需求的候选
  -> Attribute 批量加载多个 ContextUnit
  -> 生成归因结果
  -> 使用 Current / Oracle Context 对照验证
```

该闭环必须先回答：

1. ContextUnitRecord 能否从 inline content 或 content_ref 可靠还原完整 ContextUnit；
2. 多 query 是否能发现多条互补而非重复的信息；
3. Attribute 的归因效果是否改善；
4. 输入 Token 和无效内容是否下降；
5. 权限、Trace 对齐和原始证据是否保持不变。

只有这个闭环通过 UAT，才继续迁移 Judge、Mock、Check 和更多项目知识。

### 2.7 建立效果优化闭环

1. 在 Agno Run metadata 写入最小 `context_debug`；
2. 实现固定 case 的 Current 重放；
3. 支持在相同模型、Prompt、Tools 和权限下运行 Oracle Context；
4. 实现单条及组合的前向增加、后向消融；
5. 将结论映射为新增、删除、拆分、合并、描述修改或 operation 收窄；
6. 接入 draft 流程，在失败 case 和独立回归 case 上验证效果、Token 与退化。

## 3. UAT

至少选择 api-check 中覆盖 Mock、Live、Judge、Attribute 的真实 case，并覆盖 DeerFlow：

1. 验证同一任务可拆出多个 query，并发现多条互补 ContextUnit；
2. 验证模型可一次加载多条单元；
3. 验证 Mock 无法搜索或加载 Reference/Judge/Attribute；
4. 验证跨 project、trace、role 和 operation 不泄漏；
5. 验证 inline content、content_ref、失效和重跑；
6. 验证 Current/Oracle 差异能正确区分上下文问题与非上下文问题；
7. 对至少一个 ContextUnit 做组合消融，确认不是只按单条贡献误删；
8. 比较改造前后的业务结果、输入 Token、候选数、加载数和工具调用数；
9. 重复执行同一项目初始化时，未变化知识不重新生成 description 或 embedding；
10. 同一 ContextUnit 被多个角色允许使用时只保存一份向量，但 Search 和 Load 均按各角色 Policy 鉴权；
11. `git diff --check`、相关单元测试、集成测试和 `sh run.sh api-check` 全部通过后再切换默认链路。

## 4. 切换完成标准

- 所有角色通过同一 Context Runtime 获取上下文；
- 公共对象、项目稳定知识和项目动态对象分别通过明确入口注册；
- 不存在绕过公共 Policy 的私有 Prompt 拼接或检索链；
- Registry、Vector Index、Agno Session 和业务 Trace 可通过稳定 ID 追溯；
- 多需求检索、多单元加载、权限隔离和预算控制通过 UAT；
- 上下文效果问题可通过 Current / Oracle Context / 组合消融被定位并进入 draft 优化；
- 旧数据只读保留，切换不依赖伪造迁移数据。
