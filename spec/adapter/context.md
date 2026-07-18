# 动态证据上下文治理协议

本文定义 verifier 中 Mock、Judge、Attribute 等模型角色共用的动态上下文治理协议，并记录当前仓库迁移到该协议所需的一次性改造任务。

# 第一章：Spec 标准

## 1. 目标

上下文不是历史消息的简单拼接，而是某个模型角色在完成当前任务时可以使用的受治理证据集合。

本协议的目标是：

- 最大化有效信息密度，不损失完成当前任务所必需的信息；
- 将完整事实存储与模型本次可见上下文分离；
- 支持按需加载大体积或低频证据，而不是预先塞入全部内容；
- 让 Mock、Judge、Attribute 复用同一套选择、预算、加载和审计机制；
- 由公共层统一治理证据，由项目扩展层声明项目语义；
- 复用 Agno 的运行时依赖和工具能力，但不把上下文所有权交给 Agno 自动 Memory/History；
- 保证每项模型可见信息都有来源、选择原因和可追溯指针。

本协议不以减少 token 为唯一目标。压缩不得删除仍有效且无法从其他已选证据恢复的信息；超出直接注入预算的有效证据必须进入可按需加载目录，而不是静默丢弃。

## 2. 核心概念

### 2.1 Evidence

Evidence 是上下文治理的最小事实单元。它可以来自 Case、Intent、Live Request、Extract Output、Raw Response、RunTrace、Reference、Judge、Attribute 工具结果、项目文档或代码定位结果。

```python
@dataclass(frozen=True)
class ContextEvidence:
    evidence_id: str
    source_kind: str
    source_ref: str
    path: str
    value: Any
    turn_index: int | None = None
    created_at: str = ""
    content_hash: str = ""
    tags: list[str] = field(default_factory=list)
    sensitivity: str = "normal"
```

约束：

- `evidence_id` 在一次 RunTrace 内稳定且唯一；
- `source_ref + path` 必须能定位回原始事实；
- `value` 保留原始类型，不预先改写成自然语言总结；
- Evidence 不包含模型对事实的推测；
- 同一事实可以被多个角色选择，但不能复制成互不关联的来源；
- secret、鉴权信息和与任务无关的个人数据不得仅因存在于 Request 中就成为可见 Evidence。

### 2.2 ContextRequest

ContextRequest 描述某次模型调用需要解决什么问题，而不是直接携带全部上下文。

```python
@dataclass(frozen=True)
class ContextRequest:
    project_id: str
    trace_id: str
    role: Literal["mock", "judge", "attribute"]
    objective: str
    phase: str
    turn_index: int | None = None
    required_capabilities: list[str] = field(default_factory=list)
    direct_budget: int = 0
```

字段含义：

- `role` 决定证据可见边界；
- `objective` 是当前调用的具体任务，例如“判断模拟用户是否继续”或“判断输出是否满足 reference”；
- `phase` 区分同一角色内部的步骤，例如 `infer_intent`、`decide_continue`、`judge_result`、`locate_cause`；
- `required_capabilities` 声明本次必须覆盖的证据能力，不直接指定某个具体字段；
- `direct_budget` 是直接注入区的软预算，不是有效信息的删除上限。

ContextRequest 禁止携带最终 verdict、attribution 结论或其他本阶段尚未产生的答案。

### 2.3 ContextBundle

ContextBundle 是公共上下文层针对一次 ContextRequest 产生的受治理结果。

```python
@dataclass
class ContextBundle:
    core_evidence: list[ContextEvidence]
    evidence_catalog: list[ContextEvidenceSummary]
    omitted_evidence: list[ContextOmission]
    selection_trace: list[ContextSelectionEvent]
    direct_size: int
    budget_exceeded: bool = False
```

四个区域的职责：

- `core_evidence`：完成任务必需或高密度的信息，直接进入模型上下文；
- `evidence_catalog`：未直接注入但仍可能有效的信息索引，模型可通过工具按需加载；
- `omitted_evidence`：确定无效、重复、越权或被更新事实完全覆盖的信息及原因；
- `selection_trace`：选择、去重、降级、目录化和动态加载的完整审计事实。

`omitted_evidence` 只记录元信息和 omission reason，不重复保存被省略的大体积 value；原始值仍由 RunTrace 或其来源保存。

## 3. 分层职责

### 3.1 公共协议层

公共层负责：

- 建立统一 ContextRequest、Evidence、Bundle 与审计 schema；
- 从通用 Case/Trace/Run 结构抽取 Evidence；
- 执行角色权限过滤、去重、覆盖关系判断、预算分配和动态目录生成；
- 提供统一的 `load_context_evidence` 工具；
- 将 ContextBundle 接入 LLM 调用；
- 记录本次实际注入和动态加载了哪些证据；
- 对上下文缺失、越权、来源失效和预算异常进行结构化报错。

公共层不理解某个业务字段的具体含义，不硬编码项目字段名、scenario 或业务完成规则。

### 3.2 项目扩展层

每个项目负责声明：

- Request 中哪些路径代表用户表达、业务身份、会话连续性和内部 transport 噪声；
- Output 中哪些路径代表主回复、未满足事项、阶段状态、业务结果和错误；
- 哪些字段跨轮不可变，哪些字段由新一轮覆盖，哪些字段需要累积；
- 哪些动态 dict 路径必须由 fixture 验证；
- 项目知识、代码和工具证据如何建立索引；
- 项目敏感字段及其角色可见范围。

项目扩展层不得自行拼接完整 Prompt、复制公共去重算法或绕过角色权限。

### 3.3 Agno 运行层

Agno 负责：

- 在一次 Agent run 前解析动态 dependencies；
- 向模型提供公共层生成的直接上下文；
- 暴露按需加载工具；
- 执行模型和工具调用。

Agno 不负责决定 Evidence 是否有效、哪个角色能看到什么、何时发生事实覆盖或哪些内容应进入目录。这些属于 verifier 公共上下文层。

### 3.4 Trace 与 ContextStore

RunTrace 保存完整业务执行事实。ContextStore 保存每次 LLM 调用实际看到的上下文、响应和上下文选择审计。

二者不可互相替代：

- RunTrace 回答“系统实际发生了什么”；
- ContextStore 回答“模型当时看到了什么以及为什么”。

模型上下文裁剪不得反向改写 RunTrace。

## 4. 项目上下文声明

每个项目在以下位置提供声明：

```text
impl/projects/<project_id>/context_schema.py
```

模块导出 `CONTEXT_SCHEMA`：

```python
CONTEXT_SCHEMA = ProjectContextSchema(
    request=EvidenceShape(
        primary=["user_text"],
        identity=["session_id", "org_id", "user_id"],
        cumulative=["history"],
        replaceable=["user_text"],
        internal=["token", "trace_id", "ts"],
        sensitive=["token"],
    ),
    output=EvidenceShape(
        primary=["robot_text"],
        unresolved=["missing_fields"],
        state=["stage"],
        errors=["errors"],
    ),
)
```

长期 schema 至少支持以下语义类别：

- `primary`：本对象最能表达业务含义的字段；
- `identity`：跨轮持续但通常不进入模型自然语言上下文的调用身份；
- `cumulative`：历史累积字段；
- `replaceable`：后值可覆盖前值的状态字段；
- `unresolved`：尚未解决且会影响下一步的事项；
- `state`：业务阶段或状态；
- `errors`：业务错误；
- `internal`：transport、运行和调试字段；
- `sensitive`：必须脱敏或禁止进入模型的字段。

字段路径语法复用 `show_schema` 的受限路径协议。静态 dataclass 路径必须 schema-valid；动态 dict 路径必须 fixture-valid。

项目声明只描述语义和权限，不声明任意评分函数，也不执行项目代码。

## 5. 角色可见边界

### 5.1 Mock

Mock 只模拟有限认知的真实用户。允许看到：

- MockIntentOutput；
- 实际 Live Request 中用户可见或用户产生的部分；
- 各轮 Extract Output 中用户可见的业务回复、当前状态和错误；
- 项目对终端用户公开的产品信息。

Mock 禁止看到：

- Reference；
- Judge 结果、评分标准和 blocking expectations；
- Attribute 结果、代码根因和内部修复建议；
- 仅服务端可见的鉴权、内部 config、运行日志和 Raw Response；
- 被测系统真实能力答案或内部完成标准。

### 5.2 Judge

Judge 允许看到：

- 用户 Intent 与首轮/多轮实际 Request；
- Extract Output 与 Reference；
- 判断正确性所需的业务执行证据；
- 稳定的评判标准和项目 evaluation 约束。

Judge 默认不直接读取完整 Raw Response、内部代码和历史 Attribute 结论。只有当项目声明某项评判能力必须依赖原始证据时，才通过目录按需加载。

### 5.3 Attribute

Attribute 允许看到：

- Judge 已确认的实际差距；
- 与差距相关的 Request、Output、Raw Response、Execution Trace；
- 项目代码、工具和局部链路验证证据；
- 已执行工具的结构化结果。

Attribute 不得把未加载的代码或工具结果当成已验证事实，也不得使用无关 case 的历史归因补当前结论。

### 5.4 Check 与其他角色

新增角色必须先在公共角色策略中声明可见来源和禁止来源，不能仅通过 caller 字符串自动获得全部上下文。

## 6. 信息密度算法

### 6.1 定义

有效信息是满足以下任一条件的 Evidence：

- 完成当前 objective 必需；
- 改变模型可作出的合法判断或下一步动作；
- 证明某个结论的来源；
- 表达仍未解决的约束、冲突或错误；
- 是按需加载其他证据所必需的索引。

无效信息包括：

- 与当前 role/objective 无关的字段；
- 空值、格式性包装和无语义 transport 噪声；
- 已被相同来源、相同路径的更新事实完全覆盖且不存在冲突的旧值；
- 与已选 Evidence 完全相同的重复值；
- 越权、敏感或来源无法验证的信息；
- 模型生成但没有证据支持的补齐内容。

信息密度不以“字符越短越好”定义，而以单位直接上下文中有效、互补、可行动且可追溯的信息比例定义。

### 6.2 确定性选择流程

公共算法按以下顺序执行：

```text
collect evidence
→ enforce role visibility
→ normalize atomic units
→ remove empty and transport noise
→ exact deduplicate
→ resolve superseded state
→ preserve conflicts and unresolved facts
→ satisfy required capability coverage
→ select high-density direct context
→ index remaining effective evidence
→ expose on-demand loader
→ record selection trace
```

每一步都必须是可测试、可解释的确定性操作。不得调用额外模型生成上下文摘要，也不得使用与项目 fixture 绑定的关键词规则。

### 6.3 覆盖与冲突

只有同时满足以下条件，旧 Evidence 才能被标记为 `superseded`：

- 同一来源语义路径；
- 项目声明该路径为 replaceable；
- 新 Evidence 的 turn_index 或版本更晚；
- 新旧事实不存在需要 Judge/Attribute 观察的冲突。

以下信息不得因“已有更新值”而删除：

- 用户目标或约束发生变化的事实；
- 未解决事项的出现、消失和重新出现；
- 错误状态变化；
- Judge 需要比较的实际值与 Reference；
- Attribute 需要定位的前后链路差异。

### 6.4 直接上下文优先级

在角色权限允许的前提下，直接上下文按以下词典序优先级选择：

1. 当前 objective 的必需证据；
2. 未解决目标、缺失字段、冲突和错误；
3. 最新用户行为与最新系统业务回复；
4. 影响当前判断的跨轮有效约束；
5. 结论的最短充分来源证据；
6. 可加载证据的索引；
7. 已被后续事实覆盖的历史状态；
8. transport 与运行噪声。

同一优先级中优先选择能够覆盖更多 required_capabilities、且与已选 Evidence 重复更少的条目。

### 6.5 预算与不丢失原则

`direct_budget` 是软预算。算法达到预算后：

- 仍有效但非必需的 Evidence 进入 `evidence_catalog`；
- 模型可以通过 `load_context_evidence` 按 evidence_id、tag、turn 或 capability 加载；
- 必需 Evidence 不得被截断成失去业务语义的片段；
- 所有仍必需 Evidence 都无法放入预算时，允许 `budget_exceeded=True`，并完整注入必需集合；
- 不允许为了满足 token 指标静默删除有效信息；
- 不允许使用不可追溯的模型摘要替代原始证据。

大字段可以生成确定性 preview，但 preview 必须附原始 evidence_id 和完整加载入口。Preview 只允许采用结构化字段选择、固定头尾窗口或项目声明的主字段，不进行语义改写。

## 7. 动态加载协议

公共层提供统一工具：

```python
def load_context_evidence(
    evidence_ids: list[str] | None = None,
    tags: list[str] | None = None,
    turn_indexes: list[int] | None = None,
    capability: str = "",
) -> ContextLoadResult:
    ...
```

约束：

- 工具只能访问当前 ContextRequest 已授权的 evidence catalog；
- 不能通过猜路径读取 catalog 外的文件、Trace 或其他 case；
- 返回项继续携带 evidence_id、source_ref、path 和 value；
- 每次加载记录到 selection_trace 和 ContextStore；
- 同一 evidence 重复加载时返回稳定结果，并标记 cache hit；
- 加载失败必须显式返回 `not_found`、`forbidden`、`source_changed` 或 `budget_blocked`；
- 工具返回不能包含 Judge/Attribute 尚未授权的答案。

Mock 的轻量继续判断默认不开放自由检索，只允许加载项目声明的用户可见证据。Judge 与 Attribute 可根据职责开放更广目录。

## 8. Agno 集成边界

### 8.1 采用的能力

长期实现复用 Agno：

- `dependencies`：在每次 run 前动态解析 ContextBundle；
- `add_dependencies_to_context` 或等价显式消息注入：加入公共层已经选择好的 core_evidence；
- tools：暴露 `load_context_evidence`；
- RunContext：向工具传递当前授权目录和 trace identity。

公共上下文层必须在 Agno 注入之前完成权限和信息密度治理。不得把完整 RunTrace 作为 dependency 后再要求模型自行筛选。

### 8.2 默认关闭的能力

评测角色默认保持：

```text
db/session persistence       off
add_history_to_context       off
user memory                  off
agentic memory               off
automatic session summary   off
cross-session search         off
```

原因：

- 每个 case 必须相互隔离；
- 自动历史可能把其他步骤或其他 case 的答案带入当前判断；
- 自动 Memory/Summary 的生成和更新不受 verifier 证据协议约束；
- 同一信息若同时由 Agno history 和 ContextBundle 注入，会重复占用上下文并产生冲突版本。

若未来某个非评测产品角色需要持久会话，必须另行定义 session scope、冲突优先级和审计协议，不能复用 Mock/Judge/Attribute 默认配置直接开启。

### 8.3 单一上下文所有权

一次评测 LLM 调用只能有一个上下文治理所有者：verifier ContextProvider。

Agno 负责装载和执行，不得在 ContextProvider 之外自动增加 history、memory、knowledge references 或 session state。若某项 Agno 能力被启用，必须作为 ContextProvider 的显式 EvidenceSource 注册，并进入同一 selection trace。

## 9. 公共接口

长期公共接口为：

```python
class ContextProvider(Protocol):
    def build(self, request: ContextRequest) -> ContextBundle:
        ...

class EvidenceSource(Protocol):
    def collect(self, request: ContextRequest) -> list[ContextEvidence]:
        ...

class ProjectContextExtension(Protocol):
    def schema(self) -> ProjectContextSchema:
        ...
```

LLM 公共入口接收 ContextRequest，而不是由每个角色自行把大型对象序列化进 user prompt：

```python
def complete_json(
    system: str,
    user: str,
    *,
    context_request: ContextRequest | None,
    trace_id: str,
    output_spec: StructuredOutputSpec,
) -> dict[str, Any]:
    ...
```

`context_request=None` 只允许用于确实没有外部证据的纯结构化生成调用；调用方不得借此绕过角色上下文协议。

## 10. 与多轮 Mock 的关系

Trace v2 的 `accumulated_output` 保持现有函数签名，但其值不再由 Live 层直接拼接完整历史，而由 ContextProvider 为 `role=mock`、`phase=decide_continue/build_next_request` 生成。

```python
def decide_next_action(
    intent: MockIntentOutput,
    accumulated_output: dict[str, Any],
) -> MockContinueDecision:
    ...

def build_next_request(
    intent: MockIntentOutput,
    accumulated_output: dict[str, Any],
) -> REQUEST_SCHEMA:
    ...
```

两个方法的输入输出签名保持不变。`accumulated_output` 必须是 ContextBundle 的公开序列化形状，不允许重新塞入完整 RunTrace，也不允许项目扩展层自行发明另一套累计结构。

多轮 Request 的业务连续性仍由项目扩展层负责：项目以最近一轮合法 Request 为模板，只更新协议允许变化的字段；公共 ContextProvider 负责提供必要事实，但不替项目构造 Request。

## 11. Judge 与 Attribute 的复用

### 11.1 Judge

Judge 的 ContextRequest 至少声明：

```text
role=judge
objective=判断实际交互是否满足用户目标与 Reference
required_capabilities=[intent, actual_output, reference, execution_status]
```

核心区优先包含最短充分的 Intent、Actual、Reference 和失败状态；完整多轮、Raw Response 与非关键 Trace 进入目录。Judge 若发现证据不足，通过工具加载，不得把“未预载”等同于“不存在”。

### 11.2 Attribute

Attribute 的 ContextRequest 至少声明：

```text
role=attribute
objective=定位 Judge 已确认差距的最早失败环节
required_capabilities=[judge_gap, execution_chain, relevant_project_evidence]
```

核心区包含 Judge gap、相关轮次和已有执行证据；代码、完整日志、工具结果进入目录并按定位过程动态加载。Attribute 结论必须引用实际加载的 evidence_id。

### 11.3 角色隔离

Mock、Judge、Attribute 可以复用同一 ContextProvider，但不能复用同一 ContextBundle。每个角色、phase 和调用轮次必须重新执行权限与选择流程。

## 12. 错误与降级

上下文阶段使用稳定错误类型：

- `context_source_error`：证据源读取失败；
- `context_schema_error`：项目声明或路径不合法；
- `context_forbidden`：请求访问越权证据；
- `context_required_missing`：必需 capability 没有证据；
- `context_source_changed`：目录建立后原始来源发生变化；
- `context_budget_exceeded`：必需集合超过软预算；
- `context_load_error`：按需工具加载失败。

处理原则：

- 必需证据缺失时不得用空对象、历史 case 或模型猜测补齐；
- `budget_exceeded` 不是业务失败，但必须记录；
- 越权和来源变化必须阻断对应加载；
- 非必需 EvidenceSource 失败可以继续，但必须进入 selection_trace；
- 上下文错误的原始结构化证据必须进入 ContextStore 和 RunTrace control event。

## 13. 审计协议

每次模型调用至少记录：

- ContextRequest；
- core evidence IDs；
- catalog evidence IDs；
- omission reason 统计；
- direct_size 与预算；
- 动态加载请求和结果；
- ContextProvider 版本；
- 项目 context schema 版本；
- 最终实际发送给模型的 messages；
- 模型响应、耗时和错误。

不得只保存最终 Prompt 而不保存 Evidence 选择依据；也不得只保存 Evidence ID 而无法复原当时发送的实际内容。

## 14. 测试与验收

### 14.1 公共协议测试

必须覆盖：

- 角色权限矩阵；
- 空值、重复值和 superseded 状态的确定性处理；
- 冲突事实不会被覆盖删除；
- soft budget、catalog 和 budget_exceeded；
- 动态加载授权、缓存与来源变化；
- ContextStore 能重建模型实际输入；
- Agno history/memory/session 默认关闭；
- 不同 case、role、phase 的 ContextBundle 隔离。

### 14.2 项目扩展测试

每个项目必须覆盖：

- context_schema 路径的 schema-valid 或 fixture-valid；
- user-visible/internal/sensitive 分类正确；
- 多轮 identity 与 session 配置保持连续；
- replaceable/cumulative 字段行为符合真实 API；
- 不同 scenario 不被固定默认值污染。

### 14.3 信息密度测试

至少构造以下固定测试：

- 12 轮、每轮含大 Request/Output 的多轮交互；
- 大量重复状态但只有少量变化的交互；
- 早期约束到后期仍有效的交互；
- 中途用户修改目标的冲突交互；
- Judge 需要加载完整 Raw Response 的场景；
- Attribute 需要逐步加载代码与局部链路证据的场景。

验收不只比较 token 数，还必须断言：所有 required capability 可获得、有效历史约束未丢失、无越权证据、结论引用可回溯。

# 第二章：Changes

## 1. 当前实现差异

当前仓库与长期协议存在以下差异：

1. `LlmClient` 直接接收 system/user 字符串，各角色自行序列化上下文；
2. Mock 的 accumulated_output 保存并重复发送全部轮次 Request/Output，没有预算和目录；
3. Judge 与 Attribute 各自构造 Prompt，缺少统一 ContextRequest 和权限矩阵；
4. `context_store.py` 只保存最终 messages/response，不保存证据选择过程；
5. Agno Memory、History、Knowledge 与持久 Session 当前明确关闭，这是正确的隔离基线；
6. Agno dependencies 尚未用于 verifier 动态上下文注入；
7. 现有 `knowledge_base.py` 被禁用，且其定位偏项目知识 RAG，不能直接承担全角色证据治理；
8. show_schema 只服务前端展示，不能直接作为完整 ContextSchema，但字段路径解析器可以复用；
9. deerflow 与 marketting-planning 的下一轮 Request 会重造并覆盖业务身份/配置；
10. 两个多轮项目在 Intent 缺失时硬编码 scenario；
11. Mock 控制阶段错误只留下通用 stop_reason，原始错误没有进入 Trace control event；
12. 当前测试没有覆盖动态加载、上下文权限、长多轮信息密度和项目 Request 连续性。

## 2. 一次性 schema 改造

新增公共 schema：

- `ContextRequest`；
- `ContextEvidence`；
- `ContextEvidenceSummary`；
- `ContextOmission`；
- `ContextSelectionEvent`；
- `ContextBundle`；
- `ContextLoadResult`；
- `ProjectContextSchema` 与 `EvidenceShape`。

扩展 `ContextRecord`：

- 增加 context_request；
- 增加 core/catalog/omitted evidence IDs；
- 增加 selection_trace；
- 增加动态加载记录；
- 增加 provider/schema version；
- 保留现有完整 messages 和 response 字段。

历史 ContextRecord 只读兼容：缺少新字段时按“legacy-untracked-context”读取，不反推或伪造 selection trace。

## 3. 一次性公共层实现

新增公共模块，职责拆分为：

```text
context_provider.py       构造 ContextBundle
context_sources.py        通用 EvidenceSource
context_selection.py      权限、去重、覆盖、预算算法
context_tools.py          load_context_evidence
context_policy.py         角色权限和 required capability
```

实现顺序：

1. 从 RunTrace/Case/Reference/JudgeResult 抽取稳定 Evidence；
2. 实现角色可见矩阵；
3. 实现空值过滤、精确去重和 replaceable 覆盖算法；
4. 实现 direct soft budget、catalog 和 deterministic preview；
5. 实现受授权目录限制的动态加载工具；
6. 将 selection trace 写入 ContextStore；
7. 将上下文错误写入 RunTrace control event。

不得在第一版引入模型摘要、向量相似度去重或自动学习权重。只有确定性版本建立基线后，才能通过独立 spec 讨论更复杂算法。

## 4. 一次性 Agno 桥接

更新 `project_llm_client` 与 `LlmClient.complete_json`：

1. 接收可选 ContextRequest；
2. 在 Agent run 前调用 ContextProvider；
3. 使用 Agno run dependencies 注入 core_evidence；
4. 向允许动态加载的角色注册 `load_context_evidence` 工具；
5. 通过 RunContext 绑定 trace_id、role 和授权 catalog；
6. 保存 Agno 最终构造的实际 messages 与 selection trace；
7. 继续保持 db、history、memory、session summary 和 cross-session search 关闭；
8. 加入防重复检查，禁止同一 evidence 同时从手写 user prompt 和 dependencies 注入。

桥接期间保留无 ContextRequest 的旧调用兼容，但必须记录 caller，并通过迁移清单逐一消除应该接入而未接入的调用。

## 5. 一次性 Mock 接入

第一阶段只切换 Mock，用它验证公共机制：

1. `infer_user_intent` 使用 `role=mock/phase=infer_intent`；
2. `decide_next_action` 使用 `role=mock/phase=decide_continue`；
3. `build_next_request` 使用 `role=mock/phase=build_next_request`；
4. Live 层不再自行组装全部 accumulated_output；
5. Mock core evidence 保留 Intent、最近用户行为、最新业务回复、仍有效约束和未解决事项；
6. 历史有效 Evidence 进入 catalog；
7. 继续判断默认只使用 core evidence，禁止自由读取 Reference/Judge/Attribute；
8. 下一轮构建只开放用户可见 catalog；
9. 删除两个多轮项目的固定 scenario；无法从 Request 证明时保持空值；
10. 控制阶段异常写入结构化 Trace event。

完成后使用固定假 LLM 验证 ContextBundle，不依赖真实外部模型判断测试是否通过。

## 6. 一次性项目扩展改造

为以下项目新增 `context_schema.py`：

- QA；
- client_search；
- deerflow；
- marketting-planning-intent；
- marketting-planning。

其中多轮项目同时修复 Request 连续性：

### 6.1 deerflow

- 保留上一轮完整 `config.configurable`；
- 按真实 Deerflow API 语义更新 input.messages；
- 禁止缺失 thread_id 时用时间戳伪造身份；
- 明确 messages 是逐轮单消息还是累积消息，并用项目测试锁定；
- scenario 不从项目默认值硬编码。

### 6.2 marketting-planning

- 以上一轮合法 MPApiRequest 为模板；
- 保留 org_id、user_id、token、session_id、application_setting、module_name、model_name 等上下文；
- 按真实 API 语义更新 user_text、history、trace_id、ts 和 extra_input_params.message；
- 删除 eval-user、mock-token、eval-org 等续轮占位值；
- scenario 只来自可证明的 Request 字段或保持空值。

单轮项目只需声明 Request/Output 的证据语义和敏感字段，不增加无用的多轮扩展方法。

## 7. 一次性 Judge 接入

Mock 阶段稳定后：

1. 将 Judge 手写 Prompt 中的 Intent、Output、Reference 和 Trace 拼接迁移为 ContextRequest；
2. 定义 Judge required capabilities；
3. 默认直接注入最短充分评判证据；
4. Raw Response 和完整多轮进入目录；
5. Judge 使用动态工具加载后必须在结果证据中引用 evidence_id；
6. 移除与 ContextProvider 重复的 Prompt 裁剪和字段猜测逻辑；
7. 验证相同输入在迁移前后 verdict 不退化，且无 Reference 泄漏到 Mock。

## 8. 一次性 Attribute 接入

Judge 稳定后：

1. 将 judge gap、Trace、代码和工具结果注册为 EvidenceSource；
2. 核心区只放差距与最相关执行链路；
3. 代码、日志和局部测试结果按需加载；
4. 每条归因结论必须引用已加载 evidence_id；
5. 工具调用结果进入 catalog 后可被后续步骤加载，但不自动复制全部历史工具输出；
6. 删除与公共 ContextProvider 重复的 tool-result 压缩逻辑；
7. 验证无关 case 的历史归因不会进入当前 bundle。

## 9. 数据与 fixture 迁移

- `impl/data/context_store` 历史文件只读保留；
- 不为历史记录伪造 selection trace；
- 新 ContextRecord 使用版本字段区分协议；
- RunTrace fixture 增加 control event 与 context audit 引用；
- 为每个项目增加 context_schema fixture；
- 大型 Raw Response fixture 只保存一份原件，ContextBundle 使用 evidence_id 引用；
- verifier 根目录 `data` 中的业务 case 不因上下文协议整体重写；
- 只有 schema 字段确实发生变化的 fixture 才迁移，禁止无意义格式化 churn。

## 10. 回归与 UAT 任务

### 10.1 自动化

- 公共 ContextProvider 单元测试；
- 角色权限矩阵测试；
- 五项目 context_schema hook；
- Mock 长多轮信息密度测试；
- deerflow/marketting-planning Request 连续性测试；
- Judge 动态加载完整 Raw Response 测试；
- Attribute 动态加载代码和工具结果测试；
- ContextStore 可重放模型实际输入测试；
- Agno 自动 history/memory 保持关闭的配置测试；
- 不同 case 并发上下文隔离测试。

### 10.2 实际 UAT

按阶段执行：

1. Mock：至少运行一个 6 轮以上交互，检查 Prompt 不随完整 Trace 线性膨胀；
2. Judge：运行需要和不需要 Raw Response 的 case，确认只在后者发生动态加载；
3. Attribute：运行真实失败 case，确认代码与局部链路证据按需加载且结论可回溯；
4. 前端：完整 Trace 保持原样，同时可以查看每个角色的 core/catalog/loaded/omitted 审计信息；
5. 隔离：并发运行两个相同 project 的 case，确认 evidence catalog 和动态加载不串 case。

## 11. 切换与清理

迁移完成的判定条件：

- Mock、Judge、Attribute 均通过 ContextRequest 获取受治理上下文；
- 角色代码不再直接序列化完整 RunTrace；
- Agno 自动 Memory/History 仍关闭；
- 项目字段语义全部来自 context_schema；
- 动态加载与 selection trace 可审计；
- 长多轮没有有效信息丢失，直接 Prompt 不再随完整 Trace 无界增长；
- 两个多轮项目保持真实 Request 连续性；
- 全量测试与真实 UAT 通过。

切换完成后删除：

- 角色内部重复的历史裁剪与 Prompt 拼接代码；
- 未被任何调用使用的旧 knowledge/context 兼容参数；
- 项目层 eval-user、mock-token 等续轮占位构造；
- 固定 scenario fallback；
- 已被 ContextStore v2 替代且无读取方的旧上下文辅助代码。

任何删除必须先通过引用扫描和回归证明不再被前端、报告或历史读取接口使用。
