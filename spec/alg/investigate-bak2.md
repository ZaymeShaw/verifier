# Investigate：Draft 前置项目调查与固化协议

本文定义 verifier Draft 探索层中的 Investigate 步骤。

Investigate 不是新的 Role、独立 Skill、运行时 Agent 或平行优化框架。它是现有 Draft 四层流程中，在修改候选 `role.py` 前执行的核心调查工作：由 Codex、Claude Code 等工程型 AI 围绕当前 Role 和 objective 理解真实业务项目，取得可追溯材料，形成必要调查产物与验证能力，并把可复用结果固化给 Draft Role 和 Agno runtime。

Investigate 的执行过程不受本协议约束。AI 可以在对应 Role 的材料权限内搜索源码、阅读文档、调用业务 API、分析 trace、编写临时脚本或进行人工交互。本协议只约束调查结束后必须交付什么、产物采用什么格式、如何被 Draft 固化和验证。

---

# 第一章：Spec 标准——最终长期协议

## 1.1 在现有 Draft 中的位置

沿用 Draft 已有四层，不增加第二套生命周期。对用户暴露的主要阶段收敛为 Investigate、Solidify、Draft Loop 和 Promote：

| Draft 层 | 主要动作 | Skill 命令 | 实际执行主体 | 确定性边界 |
|---|---|---|---|---|
| 探索层 | Investigate | `/draft investigate` | Harness AI（Codex、Claude Code） | 自由调查，但必须输出标准调查包 |
| 固化层 | Solidify | `/draft solidify` | Harness AI（Codex、Claude Code） | 按现有协议和项目扩展点实现候选代码 |
| 执行层 | Draft Loop | `/draft loop` | Draft Skill 调度协议运行、目标评估和 Harness AI 修订 | 持续数据驱动迭代，直到满足要求或停止 |
| 积累层 | Promote | `/draft promote` | verifier 协议代码，用户授权 | 按固定映射确定性晋升，不由 AI 临场选择文件 |

Draft Loop 内部包含不同性质的动作：

```text
协议 Run/Test → 确定性运行 current/draft 并保留原始事实
算法、归因和用户评估 → 提供目标相关信号
Draft Skill 按 config.review → 综合判断是否满足要求
Harness AI 修订 → 深化 Investigate 或调整 Solidify 产物
```

Draft Skill 是统一控制面。Run/Test 和 Promote 必须调用项目协议提供的确定性入口；目标判断和候选修订由当前 Draft Harness AI 完成，但不得重写协议产生的原始结果。额外 Draft Reviewer 不是默认角色；项目确有需要时可以作为 `review` 的可选评估来源。它不改变 Attribute 等 Role 自身运行时协议中已有的 Reviewer。

Investigate 是探索层的核心步骤，不负责：

- 定义新的 Mock、Judge、Attribute 等公共 Role；
- 改变现有 RoleResult、EvidenceRef、ContextUnit 或 Tool 公共协议；
- 约束 Codex、Claude Code 内部采用何种调查算法；
- 在每个 runtime case 中重新分析整个业务项目；
- 自动修改 production、提交代码或执行 promotion。

Draft 继续以现有配置作为整轮稳定输入：

- `project_id`；
- `role`；
- `objective`；
- `material`；
- `mock_source`；
- `review`；
- `max_iterations`；
- `report_path`。

## 1.2 用户控制方式

Investigate 由 Draft Skill 统一控制，不新增 `/investigate` Skill 或 verifier HTTP API。

长期命令语义：

```text
/draft start --project <id> --role <role> --mode interactive|managed
/draft status
/draft investigate [补充方向]
/draft continue [补充方向]
/draft solidify
/draft loop
/draft switch --mode interactive|managed
/draft stop
/draft promote
```

这些是 Draft Skill 的交互语义，可以由自然语言触发，不要求实现为 CLI parser。

`/draft test` 可以保留为诊断命令，只运行一次协议测试而不自动修改候选。`/draft review` 不作为默认命令；用户要求额外审查时，可以临时调用可选 Draft Reviewer。正常路径固定为：

```text
/draft investigate → /draft solidify → /draft loop → /draft promote
```

### 半交互模式

AI 可以持续调查并在有意义的检查点展示：

- 新发现的目标相关事实、边界或链路；
- 原始材料和实验；
- 已否决路径；
- 未决问题；
- 准备固化的 Context、Tool 和 Role 调整。

用户明确执行 `/draft solidify` 或等价指令前，不写候选 Role 和正式候选能力。

### 全托管模式

Skill 可以在 Draft 配置和预算内连续调度 Investigate、Solidify 和 Draft Loop，但：

- 只能写入隔离的 `draft/` 区域；
- 达到停止条件必须诚实报告 blocker；
- 不得自动 promotion；
- 不得通过修改冻结数据或 review 标准宣布成功。

全托管只改变调度方式，不改变执行主体：AI 仍不能用自由脚本替代 Loop 内的协议运行，也不能绕过用户确认调用协议 Promote。

## 1.3 公共流程与 Role 注入点

所有 Role 共用同一条 Draft 主流程、调查包 schema 和 promotion 模型，不为 Attribute、Judge、Mock 等复制不同的工作流。

Role 差异只在现有扩展点注入：

| 环节 | 公共机制 | Role 特异内容 |
|---|---|---|
| Investigate | 调查包目录、Manifest、EvidenceRef、ToolRequirement 和 artifacts 索引 | 调查目标、材料权限，以及 Evidence/Tool/artifact/unresolved 各自的有效性标准 |
| Solidify | 调查产物转 ContextUnit/VerifiableTool/候选 Role 的流程 | 读取对应 Role 协议和权限后，产出 `draft/<role>.py`；不另设 Role 专属固化阶段或 schema |
| Draft Loop | frozen Current、相同数据运行、按 objective/review 判优、max_iterations | 调用现有 Role runner、result schema、comparator 和 ROLE.md 验收原则；不另设 Role 专属 Loop |
| Promote | 用户确认、固定路径映射、一致版本与回滚 | 当前被晋升的 Role 文件及其实际依赖资产 |

从流程和新增 schema 看，只有 Investigate 需要显式按 Role 分包：不同 Role 调查的问题、可见材料和产物语义确实不同。Solidify、Draft Loop 和 Promote 都复用公共阶段，不复制流程或数据结构；其中 Solidify 和 Loop 继续消费同一份 Role 调查契约，Promote 只处理实际候选文件及依赖。

因此不新增 Attribute/Judge 专属 Manifest、SolidifyResult 或 Loop schema。现有 `.agents/skills/draft/<role>/ROLE.md` 是 Role 调查要求、材料权限、固化约束和判优要求的真相源；公共 spec 只规定阶段交接和不可违反的门禁。

### 1.3.1 固定 schema，不按 Role 派生 schema

Role 差异采用“固定公共 schema + 固定 Role 调查契约”，不采用 `AttributeInvestigationManifest`、`JudgeInvestigationManifest` 等继承或联合类型：

```text
DraftConfig.role
  → 选择 .agents/skills/draft/<role>/ROLE.md
  → ROLE.md 约束本轮允许的材料、必须回答的问题和必需产物
  → Harness AI 仍输出同一个 InvestigationManifest
  → Solidify 与 Draft Loop 继续按同一 ROLE.md 消费和审核
```

选择固定 schema 的原因是：Role 的差异主要是调查语义，而不是传输机制。每个 Role 都需要来源引用、验证能力、文件产物和未决问题；真正不同的是这些内容应该证明什么。若为每个 Role 建 schema，新增 Role、调整调查策略或出现项目特例都会迫使公共协议升级，反而限制调查上限。

Role 准则也不能由模型在每个 case 临场生成。ROLE.md 提供跨项目稳定的 Role 调查契约，`DraftConfig.objective/material/review` 只在该契约内补充当前项目和当前轮次要求。模型可以自由扩展调查文件，但不能自行改写材料权限或成功标准。

### 1.3.2 Role 调查契约

每个 `.agents/skills/draft/<role>/ROLE.md` 必须使用相同章节声明：

| 章节 | 作用 |
|---|---|
| `Investigation objective` | 当前 Role 调查要解决什么问题，明确不以产物数量代替效果 |
| `Material boundary` | 可以读取、不得读取和缺失时必须停止的材料 |
| `Questions to resolve` | 调查包必须回答的核心问题，不规定 AI 的具体搜索顺序 |
| `Evidence requirements` | 哪些来源可作为该 Role 的调查依据、应证明什么，以及不可证明什么 |
| `Tool requirements` | 哪类事实需要执行验证、验证能力的有效性标准，以及哪些只需静态 Context |
| `Artifact requirements` | 哪些复杂内容必须固化为文件、文件形状，以及允许缺失的条件 |
| `Solidify usage` | 调查产物应如何落为 ContextUnit、VerifiableTool 和候选 Role |
| `Draft loop review` | 如何判断调查和固化是否真正改善该 Role，而不是只增加内容 |

这些章节是 Harness AI 和 Draft Skill 的执行准则，不新增运行时 dataclass。公共 validator 只检查 Manifest、路径、引用和 Tool 入口；Role 语义是否满足由 Draft Skill 按 ROLE.md、objective 和 review 审核。

Role 契约约束的是整个公共调查包，而不只是 `artifacts`：

| 公共载体 | Role 契约必须规定的语义 |
|---|---|
| `EvidenceRef` | 哪类真实来源允许使用、引用需要精确到什么程度、该材料对当前 Role 能支持和不能支持什么 |
| `ToolRequirement` | 哪个关键判断必须靠执行验证、结果如何区分不同解释、保真与失败边界是什么 |
| `artifacts` | 哪些关系或长内容无法只靠引用表达，因而必须固化为可复用文件，以及文件格式 |
| `unresolved_reason` | 缺少哪项 Role 所需材料或能力时必须收缩调查结论或阻断 Solidify |

因此 `artifacts` 只是复杂调查内容的文件索引，不是 Role 差异的唯一承载方式。可以用 `EvidenceRef` 或 `ToolRequirement` 清楚表达的内容，不得为了凑齐 Role 产物再复制成一份固定 Markdown。

## 1.4 Investigate 的不可或缺产物

调查结束后必须形成当前 Role 的调查包。所有 Role 至少交付：

1. `overview.md`：AI 对当前 Role 所需项目信息的解释；
2. `EvidenceRef`：文档、输入输出、源码、API、trace、实验或其他真实材料引用；
3. `ToolRequirement`：当前 Role 需要的验证能力，包括已实现和待实现项；
4. `artifacts`：Role 契约要求和项目额外产生的文件；
5. `unresolved_reason`：当前仍无法确认的部分。

Manifest 中各列表允许为空，但 ROLE.md 要求的内容不可用空列表蒙混；缺失项必须在 `unresolved_reason` 中说明原因和影响。Attribute 要求业务执行 Mermaid、关键串联点和必要的 replay/probe；Judge、Mock、Live 使用各自有意义的来源、验证能力和可选 artifacts，不能为了套模板而生成 Attribute 式内部链路图。

各 Role 的必需产物与验证逻辑见 1.7；公共层不再给出一份以 Attribute 为默认的调查清单。

调查包允许包含其他项目特有产物，但扩展内容必须通过 manifest 登记，不能成为只有生成者知道的隐式文件。

## 1.5 调查包目录

候选调查结果固定保存在：

```text
impl/projects/<project>/draft/investigation/
└── <role>/
    ├── manifest.json
    ├── overview.md
    └── docs/
        └── <role-defined>         # ROLE.md 要求或项目确有需要的扩展材料

impl/projects/<project>/draft/tools/
└── <verification_tool>.py

impl/projects/<project>/draft/context_builders/
└── <role>_investigation.py
```

各文件职责：

- `manifest.json`：调查包的机器入口，由 `InvestigationManifest` 序列化产生；
- `overview.md`：当前 Role 看到的项目边界、关键结论、调查范围和未知项；
- `docs/`：对应 ROLE.md 要求，或无法合理放入 `overview.md` 的大型扩展材料；公共层不预设其子目录；
- `draft/tools/*.py`：真正可导入、可执行的 `VerifiableTool`；
- `draft/context_builders/<role>_investigation.py`：在固化阶段将当前 Role 调查文档注册为 Draft ContextUnit，不参与调查本身。

调查包按 Role 隔离，避免权限和语义污染。经验证后，真正稳定且允许跨 Role 共享的业务事实可以晋升为带权限的项目 ContextUnit；通用 Tool 可以晋升到正式 `tools/`。其他 Role 只能通过正式 Context/Tool 权限复用，不能直接读取另一个 Role 的整个候选调查包。

## 1.6 Schema

### 1.6.1 `InvestigationManifest`

调查阶段只新增一个顶层产物 schema：

```python
from dataclasses import dataclass, field

from impl.core.schema.evidence import EvidenceRef


@dataclass
class InvestigationManifest:
    schema_version: int
    project_id: str
    role: str
    source_revision: str

    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    tool_requirements: list["ToolRequirement"] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    unresolved_reason: str = ""
```

字段消费关系：

| 字段 | 内容 | 下一阶段如何使用 |
|---|---|---|
| `schema_version` | manifest 格式版本 | validator 选择解析规则 |
| `project_id` | 真实业务项目身份 | 阻止跨项目误加载 |
| `role` | 本调查包服务的 Role，如 `attribute`、`judge` | 选择对应 ROLE.md，并阻止候选 Context/Tool 越权跨 Role 注入 |
| `source_revision` | 本次调查对应的项目 commit、版本或内容 hash | 判断调查是否过期 |
| `evidence_refs` | 输入输出、函数、API、文档、trace 和实验等来源引用，以开放 `kind` 区分 | Role 导航、Solidify 选路和 Review 核对 |
| `tool_requirements` | 调查确认需要的验证能力；实现可能已存在，也可能仍待 Solidify 完成 | Solidify 复用、包装或新建 VerifiableTool |
| `artifacts` | `相对路径 → 用途`，登记 ROLE.md 必需产物和项目扩展产物 | 保持公共 schema 稳定，并让 Solidify、Review 和 promotion 找到实际文件 |
| `unresolved_reason` | ROLE.md 要求但无法确认的材料、问题或验证能力 | 限制 Draft 结论与 promotion 范围 |

`overview.md` 的位置由调查包目录协议固定，因此不在 manifest 重复保存路径。其余文件全部登记到 `artifacts`，具体文件形状由 1.7 和对应 ROLE.md 决定。真实来源统一使用已有 `EvidenceRef`，通过开放 `kind` 区分，不再为不同 Role 创建平行字段。

公共 validator 只负责 schema、Role 身份、路径、引用真实性和可执行入口等结构事实。调查语义是否完整由 manifest 的 `role` 选择对应 ROLE.md 判断；例如 Attribute 可以要求业务 trace、关键函数/API 和验证 Tool，而 Judge 不应被迫读取内部实现。ROLE.md 要求但当前无法获得的材料或能力必须写入 `unresolved_reason`。`InvestigationManifest` 不存储候选 Role 改法、current/draft 分数或 Review 结论，这些继续由现有候选文件、Draft Loop 的协议运行事实和 DraftReport 承担。

### 1.6.2 `ToolRequirement`

Investigate 需要表达“应该有什么验证能力”，包括当前还没有实现的 Tool。为避免把不可执行对象伪装成 `VerifiableTool`，调查包使用一个与 `VerifiableTool` 核心字段对齐、但可序列化的 requirement：

```python
from typing import Any


@dataclass
class ToolRequirement:
    tool_id: str
    description: str
    applicable_scenario: str
    parameters: dict[str, Any]

    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    implementation: "ToolImplementationRef | None" = None
    implementation_gap: str = ""
```

前四个字段与现有 `VerifiableTool` 对齐。`ToolRequirement` 不包含 `execute_fn`：Callable 不能可靠序列化，而且 `execute_fn=None` 的对象不能被 loader 误认为已经可执行。

三种调查结果统一使用这个 schema：

1. 已有可直接调用的 `VerifiableTool`：`implementation` 指向现有 module/factory；
2. 已有 Python 函数、脚本或 API，但尚未包装：`evidence_refs` 指向底层材料，`implementation=None`，`implementation_gap` 说明 Solidify 需要包装；
3. 完全缺失但调查确认必要：证据说明为什么缺少该能力无法验证，`implementation=None`，`implementation_gap` 说明需要新建。

例如，已有脚本但尚不能被 Agno 直接调用：

```python
ToolRequirement(
    tool_id="client_search.condition_replay",
    description="重放条件构造过程并返回中间字段",
    applicable_scenario="区分字段识别失败与后处理丢失",
    parameters={"type": "object", "properties": {}},
    evidence_refs=[EvidenceRef(
        ref_id="condition-replay-script",
        kind="source",
        location="scripts/replay_condition.py",
        summary="可作为 execute_fn 的底层实现",
    )],
    implementation=None,
    implementation_gap="需要在 Solidify 中包装为 VerifiableTool",
)
```

Solidify 不要求实现所有设想。它必须判断 requirement 是否是当前候选 Role 的必要能力：必要的则复用、包装或新建；仍无法实现的保留 `implementation=None`，并由 Review 判断其是否阻断目标结论。

### 1.6.3 `ToolImplementationRef`

Tool 不能只用 `list[str]` 表示。manifest 必须能定位到实际代码及其构造入口：

```python
@dataclass
class ToolImplementationRef:
    tool_id: str
    module_path: str
    factory: str
```

例如：

```json
{
  "tool_id": "client_search.condition_replay",
  "module_path": "../tools/condition_replay.py",
  "factory": "build_condition_replay_tool"
}
```

约束：

- `module_path` 必须指向项目内真实 Python 文件；
- `factory` 必须可导入和调用；
- factory 必须返回现有 `VerifiableTool`；
- Tool 的 `description`、`parameters`、`execute_fn` 和运行边界继续由 `VerifiableTool` 定义，不在 manifest 重复；
- Tool 必须实际执行并返回 `ToolResult`，不能只读取一段说明然后宣布结论；
- “未来应该做一个 Tool”不是 `ToolImplementationRef`；它必须保留为 `implementation=None` 的 `ToolRequirement`，并说明 implementation gap。

### 1.6.4 `EvidenceRef` 的边界

现有 `EvidenceRef` 足以承担函数、API、文档和原始 trace 的来源引用，但不足以承担整个调查包。

在 Investigate 中：

- `ref_id`：调查包内稳定引用 ID；
- `source`：来源系统或材料类型；
- `kind`：`input/output/reference/source/function/api/document/trace/replay/test` 等开放字符串；
- `summary`：AI 对材料作用的解释，不视为原始事实；
- `location`：真实文件、符号、endpoint、trace 或结果文件位置；
- `payload`：仅保存小型且可 JSON 序列化的原始值；大型内容必须保存在文件或来源系统；
- `metadata`：保存 source revision、hash、trace identity、读取范围等。

只有能够回到真实 `location` 或可信原始 `payload` 的 EvidenceRef 才允许进入 manifest。无法追溯的 AI 描述只能写在 Markdown 中并标为未确认。

EvidenceRef 是“来源引用”，不是 ContextUnit、Tool、链路图或调查结论本身。

## 1.7 各 Role 的调查逻辑与专属产物

本节规定当前 Role 应当怎样使用公共调查包。它不增加 Role 专属 dataclass：来源进入 `evidence_refs`，验证能力进入 `tool_requirements`，确实需要保留的长内容或结构图进入 `artifacts`，无法完成的部分进入 `unresolved_reason`。差异由 `role` 和对应 ROLE.md 决定，而不是全部塞进 `artifacts`。

### 1.7.1 Attribute：调查业务系统为何产生 gap

Attribute 的目标是把 Judge 已确认的 business gap 定位到有证据支持、可指导修复的业务机制。它不是寻找“看起来缺陷很多”的文件，也不要求强行收敛到唯一根因；当多个机制或修复入口都能解释问题时，必须说明各自证据、作用范围和仍未区分的部分。

#### 1.7.1.1 两层调查边界

Attribute 存在两层性质不同、但必须串联的调查：

```text
Draft Investigate（项目级、Harness AI）
  → 理解业务系统、证据入口和验证能力
  → 形成业务链路、EvidenceRef、ToolRequirement 和必要扩展文档
  → Solidify 为项目 Context/Tool/draft/attribute.py
        ↓
runtime Investigation（case 级、Agno Attribute）
  → 针对当前 not_fulfilled gap Search/Load/Tool
  → 形成和验证当前 case 的事实材料
  → Finalization 自审、EvidenceRef 物化、Reviewer 审核
```

Draft Investigate 不直接产出某个 case 的 `AttributionFinding`，也不能把离线项目结论注册为权威根因。它的交付目标是：一个不了解项目细节的 runtime Attribute 能发现相关业务材料、调用真实验证能力，并诚实判断当前 case 最多能证明到哪里。

#### 1.7.1.2 输入与归因范围

项目调查必须先理解 Attribute 的真实输入和输出边界：

- 从 Judge 的 `not_fulfilled` gap 和当前业务输入输出出发；
- `fulfilled` 不产生失败归因，`not_evaluable` 不产生业务缺陷 finding；
- Judge reasoning 只是调查起点，不能自动成为业务内部原因证据；
- 归因按真实缺陷组织，一个缺陷可以覆盖多条 expectation，不为每条 expectation 编写占位原因；
- 当前无法覆盖的 gap 进入一个整体 `unresolved_reason`，不输出 weak/medium hypothesis；
- 项目级调查只能规划证据入口，具体 EvidenceRef 必须来自当前 case 实际加载和 Finalization 重载的材料。

Manifest 中的 `evidence_refs` 只审计 Draft Investigate 使用了哪些真实项目来源，不是 runtime finding 的 evidence，也不得自动复制到 `AttributionFinding`。

#### 1.7.1.3 业务执行链

Attribute 项目调查必须：

- 区分业务系统 trace 与 verifier 自身的 Run/Judge/Attribute trace；
- 沿业务系统实际执行路径深入到关键串联函数、配置、模型/API 边界或其他可控机制；
- 使用 replay、probe、局部执行、对照或业务 API 检查验证关键判断；
- 说明证据为什么支持当前机制，以及为什么不能被会导向不同修复的主要竞争解释同样解释；
- 不要求唯一“首个根因”：多个机制或介入位置都可能合理修复时，保留真实分支并说明各自适用范围；
- 只深入与 business gap 和修复决策有关的路径，不把周边代码坏味道、普通异常或缺陷较多的文件列入主链。

Attribute 的必需业务链路产物统一放在 `docs/traces/`：

```text
docs/traces/<flow>.mmd   # Mermaid 文本真相源
docs/traces/<flow>.md    # 节点、函数/API、证据和观察边界
```

`.mmd` 必须使用稳定节点 ID，只描述从源码、业务 trace、API 或实验中确认的节点和边；推测关系在配套 Markdown 标记为 provisional。`.svg/.png` 只是派生预览，不能替代文本源。

每个 `<flow>.md` 至少包含：

```markdown
# Flow: <flow id and name>

## Business gap and scope
## Source business traces

## Node: <same node id as Mermaid>
- Responsibility:
- Input / output:
- Key functions / configuration / APIs:
- Evidence refs:
- Available verification tools:
- Observation boundary:

## Propagation and alternative repair paths
## Provisional or unresolved parts
```

`docs/traces/` 是 Attribute 专属的固定文件形状，不是公共目录能力。图和配套文档用于表达“业务请求怎样经过关键串联点传播”，而不是代替来源或验证：节点和边必须引用 manifest 中的 `EvidenceRef`，需要执行确认的关系必须关联 `ToolRequirement`。无法取得业务内部 trace 时，必须明确静态调用关系只能证明结构，不能伪装成真实执行路径。

#### 1.7.1.4 EvidenceRef、ToolRequirement 与 ContextUnit 规划

项目调查必须为 runtime Attribute 设计可发现、可加载、可验证的环境，而不是把项目知识复制成一段长 Prompt。

ContextUnit 规划必须区分：

- 静态 ContextUnit：业务源码、配置、schema、prompt、契约、数据模型、枚举规则和系统责任边界，项目初始化时注册；
- 动态 ContextUnit：当前 case 的 Tool、source reader、probe、runtime check、replay 或 simulation 原始结果，产生后按 project/trace/case/session 隔离注册；
- `name/description` 必须足以帮助主 Attribute 发现材料，但 Search 命中、注册或 Load 均不自动等于 evidence；
- 大型材料使用 `content_ref` 或受控加载，保留 source revision/hash 和权限；
- 未验证根因、模型总结、相似度候选和其他 case 结论不得注册为权威业务知识。

Attribute 的 `Evidence requirements` 必须要求 `EvidenceRef` 覆盖与目标 gap 相关的业务源码/配置/schema/prompt、业务文档与接口契约、真实业务 trace/日志/状态、业务 API 或实际实验。每个引用必须能返回原始材料并说明来源版本；Judge reasoning、verifier trace、AI 总结和“某文件看起来问题很多”不能成为业务内部机制的证明。`summary` 只是材料用途说明，不增加材料本身的证明力。

Attribute 的 `Tool requirements` 必须盘点：

- 已有且必须复用的 canonical comparator、adapter comparison、runtime check 和正式 VerifiableTool；
- 已有函数、脚本或 API，但仍需 Solidify 包装的能力；
- 为区分主要竞争解释而缺失、需要新建的 replay/probe/simulation；
- 每项能力的输入、原始输出、适用 business gap、可区分内容、保真/权限/副作用边界和失败语义；
- 公共技术能力与必须由项目实现的业务连接能力边界。

上述盘点直接进入 `ToolRequirement[]`，不强制再复制成单独的能力文档。项目不需要为每个文件制作 Tool。静态资料进入 ContextUnit；需要执行动作取得当前事实，或者涉及业务鉴权、参数语义和专用解释时，才形成 VerifiableTool。Tool 失败只能说明调查能力受限，不能自动成为业务根因。若某项目确有复杂能力矩阵，可额外写入文档并由 `artifacts` 登记，但该文档不是公共门禁。

#### 1.7.1.5 Draft 数据边界

代表 case 属于现有 Draft Loop 的 `mock_source`、iteration data 和 frozen revision，不是新的调查 artifact。Attribute 的 iteration 数据宜覆盖：

- 一个 fulfilled 对照，验证 Attribute 不制造失败原因；
- 一个有可达证据的 not_fulfilled case，验证能够深入到可修复机制；
- 一个证据不足或 not_evaluable case，验证会 unresolved 而不是猜测。

Investigate 可以在 `overview.md` 中解释为什么现有数据足以或不足以覆盖调查目标，但不得复制 case 答案，也不新增一份平行的代表 case artifact。promotion-only unseen case 继续由冻结数据协议管理，不写入调查包或向 Harness AI 暴露。

#### 1.7.1.6 runtime 证据闭环准备

Solidify 后的环境必须能支持 Attribute 的运行时协议，但 Investigate 不重复定义运行时 schema 和轮次。具体以 `spec/alg/attribution-schema.md` 为真相源。项目调查只需确保：业务资料可以按权限固化为可发现、可加载的 ContextUnit；需要取得当前事实的能力能够固化为 Tool；Tool 原始结果可以注册为当前 case 的动态 ContextUnit；运行时 EvidenceRef 能回到这些真实材料。

Reviewer 权限也不由调查包另造机制：它可以直接审核主 Attribute 已引用 EvidenceRef 对应的 ContextUnit 全文；对于未引用资源，只看到可用 ContextUnit、Tool 和 source resource 的 name/description 目录。Reviewer 不调用 Tool、不主动展开目录资源，只质疑现有 evidence 是否足以支持 finding，并要求主 Attribute 补充现有或尚待建设的证据。Investigate 的责任是让这些候选证据与能力可被发现，而不是预写 Reviewer 的结论。

#### 1.7.1.7 Solidify 与 Draft Loop 验收

Attribute Solidify 必须完成以下映射：

```text
docs/traces/* + 必要 artifacts + EvidenceRef
  → 按主题、按权限、按需加载的静态 ContextUnit 或受控来源

ToolRequirement[]
  → 复用、包装或新建 VerifiableTool，并登记 ToolImplementationRef

调查策略与项目接缝
  → draft/attribute.py，继续遵循现有 Attribute 协议和公共证据门禁
```

候选 `draft/attribute.py` 必须实际使用已固化 Context/Tool，不得只把调查结论复制进 system prompt。Attribute Draft Loop 除公共 current/draft 门禁外，还必须检查：

- 是否只调查 Judge 已确认的 gap，并按真实缺陷合并 expectation；
- 是否实际调用环境中能够区分原因的 Context/Tool，而不是停在 Judge 文本；
- finding 是否被有用证据支持，而不是只引用真实但无关的材料；
- 是否避免把无关代码坏味道、首个可见异常或 verifier trace 写成业务机制；
- 多个修复入口或竞争解释是否被正确区分、并保留证据允许的范围；
- Finalization 和 Reviewer 是否能促使结论收缩、补证或 unresolved；
- frozen Current/Draft 上定位准确性和修复可行动性是否实质改善，iteration case 无退化；
- promotion-only unseen case 无退化，且不存在 case ID、样本专属值或历史字段组合硬编码；
- Tool/Context 调用、两轮 Review 和 token/时间成本是否在项目预算内。

### 1.7.2 Judge：调查外部业务验收边界

Judge 的目标是从用户和业务消费者视角，正确提取业务期望并判断可观察结果是否满足。它不调查业务系统内部执行链，也不能因为知道内部实现缺陷就把外部结果判为失败。

Judge 调查必须：

- 理解用户意图、业务术语、输出契约、reference 和下游消费要求；
- 明确 fulfilled、not_fulfilled 与 not_evaluable 的边界；
- 识别哪些验收标准可以直接从输出观察，哪些需要外部业务 comparator 或 reference；
- 使用正常、失败和信息不足对照检查误判与漏判；
- 默认不读取内部源码、内部 trace 或 Attribute 候选调查包。

Judge 的 `EvidenceRef` 应指向用户输入、可观察业务输出、reference、外部业务契约或可公开验收规则，并明确每项材料支持哪个验收边界；内部源码、内部 trace 和 Attribute 结论默认不是 Judge 证据。需要执行验证时，`ToolRequirement` 登记 semantic comparator、外部业务 API 检查或输出协议校验，并说明它如何改变 fulfilled/not_fulfilled/not_evaluable 判断。

Judge 没有强制文件名。可在 `overview.md` 清楚表达时不新增 artifact；业务契约或状态边界较大时，才可登记 `docs/business-contract.md`、`docs/acceptance-boundaries.md` 等长文档。Solidify 将所需材料注册为 Judge 可见 ContextUnit，并让候选 `draft/judge.py` 使用这些标准；不得把 Attribute 的业务执行链作为 Judge 证据。

### 1.7.3 Mock：调查有效场景空间

Mock 的目标是生成合法、有业务意义、能暴露目标能力差异且不过拟合现有 case 的输入。它调查的是“应该测什么以及什么输入成立”，不是业务系统为何失败。

Mock 调查必须：

- 理解输入协议、业务实体、字段约束、状态前提和禁止组合；
- 找出 objective 相关的场景维度、边界值、组合关系和缺失覆盖；
- 区分合法难例、无效输入和不应进入当前项目范围的场景；
- 不读取或反推 promotion-only unseen case 的答案；
- 用 schema validator、约束检查或最小业务调用确认样本可执行。

Mock 的 `EvidenceRef` 应指向输入协议、业务实体规则、字段约束、真实可用样例或可执行性结果，不得引用或反推 promotion-only unseen 答案。需要稳定生成或校验时，`ToolRequirement` 登记 generator、schema/constraint validator 或最小可执行性检查，并说明它验证的是合法性、覆盖维度还是业务可执行性。

Mock 没有强制文件名。场景空间可以在 `overview.md` 说明；只有内容复杂时，才通过 `artifacts` 登记 `docs/input-contract.md`、`docs/scenario-space.md` 等文件。Solidify 将规则固化为 Mock 可见 ContextUnit、Tool 和候选 `draft/mock.py`；不得把具体迭代 case 答案固化为生成规则。

### 1.7.4 Live：调查真实调用与观察边界

Live 的目标是可靠调用真实业务系统，并把业务响应、基础设施失败和不可观察状态清楚分开。它调查的是接口和观测契约，不承担 Judge 的业务满足判断或 Attribute 的根因分析。

Live 调查必须：

- 理解 endpoint、鉴权、请求字段、超时、重试、响应结构和错误协议；
- 明确原始业务响应如何规范化为 verifier 可消费的 RunTrace；
- 区分业务失败、网络/权限/限流失败和未知状态；
- 使用健康检查或最小真实调用确认环境可达，不能用 fallback 假造成功。

Live 的 `EvidenceRef` 应指向 API 文档、真实请求响应、鉴权/错误协议或基础设施观测记录，并保留环境和时间边界。需要执行验证时，`ToolRequirement` 登记 health check、最小真实调用或响应归一化检查，并明确失败表示业务失败、基础设施失败还是仍不可判断。

Live 没有强制文件名。接口与观察边界可以在 `overview.md` 说明；内容复杂时，才通过 `artifacts` 登记 `docs/api-contract.md`、`docs/observation-boundary.md` 等文件。Solidify 将这些能力固化到正式项目 API/Tool/Context 扩展点和候选 Live 实现，不生成业务根因或 Judge 结论。

### 1.7.5 新增 Role

新增 Role 时沿用同一个 Manifest，并增加对应 ROLE.md、候选实现和 current/draft runner。ROLE.md 分别规定其 EvidenceRef、ToolRequirement、artifact 和 unresolved 标准。只有出现所有 Role 都需要、且无法由这四类公共载体表达的新交接信息时，才允许升级公共 schema；单个 Role 的新调查方法只修改 Role 契约及其使用的公共载体，不升级 Manifest。

## 1.8 调查要求

### Role 契约优先

Investigate 必须先读取 `DraftConfig.role` 对应的 ROLE.md，再决定调查对象：

- 不得因为某类材料容易取得，就越过当前 Role 的 `Material boundary`；
- 不得用另一个 Role 的材料代替当前 Role 的 `Evidence requirements`、`Tool requirements` 或 `Artifact requirements`；
- 不得把 ROLE.md 未要求的字段数量、文件数量或 Tool 数量当成完成度；
- `objective/material/review` 可以收窄或补充本轮调查，但不能放宽 Role 权限或降低 Role 成功标准。

### 深度优先

调查应沿当前 Role 的核心问题深入到足以指导 Solidify，而不是罗列项目资料：

- 优先解决会改变候选 Role 设计或验证结论的关键未知项；
- 新材料必须强化、推翻或收缩当前理解，不能只增加背景数量；
- 调查深度必须足以确定下一步如何 Solidify，无法达到时明确 blocker；
- 每个 Role 的深挖对象、分支条件和停止边界以 1.7 及对应 ROLE.md 为准。

公共协议只要求：每个关键结论能回到 EvidenceRef，无法验证的部分进入 `unresolved_reason`，不得用宽泛背景资料冒充调查完成。

### 初始化与更新

- 新项目初始化：按对应 ROLE.md 调查目标相关对象、关键边界、必需产物和基础验证能力；
- 存量项目更新：读取已有调查包，只重查 source revision 变化和当前 objective 相关部分；
- 调查包来源版本变化时标记过期，但不在项目启动时自动调用 AI 重写；
- 初始化和更新都由用户手动触发 Draft。

## 1.9 Schema 流与固化

完整数据流：

```text
现有 DraftConfig
  project_id / role / objective / material / mock_source / review
        ↓
/draft investigate：Harness AI 自由调查业务项目
  按 <role>/ROLE.md 使用允许的 source / trace / API / experiment
        ↓
项目调查包
  InvestigationManifest
  overview.md
  artifacts：Role 要求的文档、链路图或其他文件
  EvidenceRef source anchors
  ToolRequirement
    ├── existing ToolImplementationRef
    └── implementation gap
        ↓
/draft solidify：Harness AI 按协议实现候选
  validate manifest
  将调查文档落为 Draft ContextUnit 注册实现
  复用、包装或新建 Draft VerifiableTool
  为可执行 requirement 填入 ToolImplementationRef
  实现 draft/<role>.py 使用 Context 和 Tools
        ↓
/draft loop：Draft Skill 持续调度
  冻结 production Current、objective、review 和 iteration cases
  verifier 协议代码先运行 Current，确认目标 gap
  每轮在相同条件下运行 frozen Current / Draft revision N
        ↓
  收集 Role 专属算法评估、真实实验和用户反馈
        ↓
  Draft Skill 判断 Draft 是否被证明优于 frozen Current 且无退化？
    ├── no：Harness AI 深化 Investigate 或修改 Solidify 产物
    │        → 协议重新运行 → 重新评估
    ├── blocked：记录 blocker 并停止
    └── yes：运行 promotion-only checks 并再次按 review 判断
        ↓
用户确认 /draft promote：verifier 协议代码
  deterministic file mapping and regression
```

这条流只新增 `InvestigationManifest`、必要的 `ToolRequirement` 和薄代码引用 `ToolImplementationRef`。Solidify 的输出就是现有项目协议认识的候选文件，并将 requirement 的实现入口补回 manifest；不新增 `SolidifyResult`、`CandidateArtifact`、单轮 `TestResult` 或 `ReviewResult` 作为顶层阶段概念。Draft Loop 内部继续使用现有 RoleResult、原始运行记录、检查结果和 DraftReport。

### ContextUnit 固化

调查包不能整体无条件塞入一次 Prompt。`draft/context_builders/<role>_investigation.py` 应按主题注册：

- `overview.md` → 项目调查导航 ContextUnit；
- 每项 `artifacts` → 按用途注册为独立 ContextUnit 或受控资源；
- 大型文档或链路图 → 使用独立 ContextUnit 或 `content_ref`，不在启动时展开；
- `manifest.json` → 构建和审计输入，不直接当作业务证据。

ContextUnit 的 `name/description` 必须让 Role 能判断何时加载，并带上与现有权限模型一致的 Role 可见性。调查资料用于导航和判断，不因被加载就自动证明当前 case 的结论。

### Tool 固化

- 已有可直接使用的 VerifiableTool：验证 requirement 与现有 Tool 的 ID、description、parameters 和行为一致后复用；
- 已有 Python 函数、脚本或 API：它们作为 EvidenceRef 指向的底层材料，由 Solidify 包装成 `draft/tools/` 中的 VerifiableTool；
- 完全缺失的能力：Solidify 根据 requirement 新建 VerifiableTool，无法实现则保持 implementation 为空；
- 新建或包装后的 Tool 写入 `draft/tools/`，并将 `module_path + factory` 填入 requirement 的 `implementation`；
- Draft Role 只使用当前权限允许且已成功注册的 Tool；
- Draft Loop 的协议运行只允许候选 Role 使用 `implementation` 非空、可以成功导入的 requirement；
- Tool 失败必须暴露为 failed/error，不能伪装为 succeeded 或 inconclusive；
- Tool 名称、description 和实际行为必须一致。

### Tool 与 ContextUnit 的边界

“当前不能直接调用”不意味着应该转成 ContextUnit：

```text
需要执行动作并取得当前事实 → Solidify 为 VerifiableTool
需要加载静态资料、项目知识或链路说明 → 注册为 ContextUnit
```

API 文档、业务标准、场景说明、链路图和源码说明属于 ContextUnit；调用 API、执行 comparator、replay 或运行脚本获取当前事实属于 VerifiableTool。某个 Role 是否把 ToolResult 注册成动态 ContextUnit，由该 Role 的运行时协议决定；静态 ContextUnit 不能替代执行验证。

### Role 固化

候选 `impl/projects/<project>/draft/<role>.py` 必须继续遵循现有 Role 协议。Investigate 不规定候选算法具体写法，但候选实现必须明确使用已经固化的 ContextUnit 和 Tool，而不是只把调查结论复制进 Prompt。

Solidify 是 Harness AI 的工程判断阶段，而不是从 manifest 到代码的机械生成器。它负责判断哪些调查资料值得注册为 ContextUnit、哪些 Tool 应复用或整理、候选 Role 应怎样使用这些能力；其最终交付物仍必须完全落在现有 Draft 文件和项目扩展点中。

## 1.10 Draft Loop

Draft Loop 是持续的数据驱动优化过程，不是一次 Test 后接一次最终 Review。

```text
冻结 Current、objective、review 和 iteration cases
→ 运行 Current，确认 objective 对应的真实 gap
→ 协议在相同条件下运行 frozen Current / Draft revision N
→ 收集多源评估
→ Draft Skill 判断 Draft 是否真正优于 frozen Current 且无退化
   ├── 调查不足 → 补充 Investigate
   ├── 候选实现不足 → 修改 Solidify 产物
   ├── 协议或环境失败 → 暴露 blocker
   └── Draft 被证明更优 → promotion-only checks
→ 重新运行，直到满足要求或停止
```

### Frozen Current

Loop 开始前必须形成不可变的 Current baseline：

- 固定 production Role 和配套项目资产的 revision；
- 固定 objective、config.review 和 iteration cases；
- 运行 Current 并记录 objective 对应的真实 gap；
- Current 没有可观察 gap 时，不通过制造 Draft 差异宣布优化成功，应停止并报告 objective 已满足或当前数据无法暴露问题；
- 整轮 Loop 只更新 Draft revision，不更新 Current；
- project revision、objective、review 或 iteration cases 实质变化时，必须建立新 revision，旧比较失效。

### 协议运行

Loop 中的运行由 verifier 协议代码负责：

- current/draft 使用相同冻结数据和业务环境；
- Current 始终来自 Loop 开始时冻结的 production baseline；
- validator 检查 manifest、artifact 路径、实际登记的 Mermaid、Tool factory、Context 和 Role 协议；
- 保存两侧原始 RoleResult、异常、Context Search/Load 和 Tool Call；
- 不输出通用“draft 更优”结论；
- Harness AI 不得用自由脚本替代这一正式运行，也不得重写原始结果。

### 多源评估

每轮可以同时消费：

- 项目 comparator、runtime check、schema 和协议检查；
- Role 专属算法评估，例如 Attribute 归因准确性或 Judge 业务判断；
- Role 允许的实验、probe、comparator 和真实 ToolResult；
- 用户对结果、业务要求和问题优先级的反馈。

这些评估不要求使用同一种算法，但都必须针对固定 objective/review，并能回到协议运行事实、真实实验或明确的用户判断。Draft Skill 结合这些信号作出本轮判断；可选 Draft Reviewer 只在项目配置或用户明确要求时作为额外信号，不形成默认第二角色。它与 Attribute runtime 协议中用于审核 finding/evidence 的必经 Reviewer 不是同一个概念。字段更多、文本更长、Tool 调用更多或 confidence 更高不能单独证明改善。

### Current/Draft 判优驱动回环

这里的 `review` 首先指 DraftConfig 中用户定义的评估原则，不是固定 Reviewer Agent。Draft Skill 根据协议事实、真实实验、项目评估和用户反馈逐条比较 frozen Current 与 Draft，并根据结果调度：

- manifest 或 ROLE.md 要求的调查材料、链路、接口、验证路径不成立 → Investigate；
- ContextUnit、VerifiableTool、候选 Role 或固化使用方式有问题 → Solidify；
- loader、数据、协议运行或基础设施失败 → protocol/infrastructure blocker；
- Draft 与 Current 基本相同 → 不算成功，继续下一轮或 blocker；
- Draft 改善部分目标但引入其他可见退化 → 不算成功，继续下一轮；
- 证据不足以比较 → 补充 Investigate、评估或验证能力；
- Draft 在 objective/review 下实质优于 Current，且 iteration cases 无可见退化 → promotion-only checks。

普通 Loop 的成功停止条件只有一个：

```text
Draft proven better than frozen Current under objective/config.review
AND no visible regression on iteration cases
```

字段更多、文本更长、结构更复杂、Tool 调用更多、confidence 更高或“看起来不弱于 Current”都不能替代目标相关的实质改善。Draft 只与 Current 相同不能 promotion；无法证明更优时应继续或诚实 blocked。

每轮判断重点包括：

- 调查是否遵守 ROLE.md 的材料权限并回答其核心问题；
- artifacts 中的关键关系是否有 EvidenceRef 或真实实验依据；
- Tool 是否真正满足 ToolRequirement 并验证声称的机制；
- 候选 Role 是否实际使用固化的 Context 和 Tool；
- 是否存在 case hardcode、fallback、标准漂移或权限越界；
- 未实现 requirement 或 unresolved 是否限制当前结论。

### 交互与全托管

- 半交互模式：每轮评估后暂停并展示原始差异、review 判断和遗留问题，由用户选择继续 Investigate、Solidify、Loop 或停止；
- 全托管模式：Skill 在 `max_iterations` 和预算内自动路由并继续运行；
- 用户对原 objective 的澄清可以进入下一轮；实质改变 objective、冻结数据或 review 标准必须创建新 revision，使旧比较失效。

### 数据边界与 Promotion 判断

- iteration cases 参与 Loop；
- unseen cases 只在普通 Loop 满足要求后用于 promotion-only checks，不得逐轮泄露给 Harness AI；
- promotion-only check 或最终 review 判断失败时，不得静默把 unseen case 加入 iteration 数据；若用户决定用其继续优化，必须显式建立新的数据 revision；
- 达到 `max_iterations`、预算上限、连续无新信息或环境阻塞时，输出 blocker，不降低标准宣布成功。

只有 Draft 按 objective/review 被证明优于 frozen Current、iteration cases 无可见退化、unseen promotion check 无可见退化、协议检查通过且最终 review 判断无阻断问题，才进入 ready-to-promote。

## 1.11 Promotion 与长期位置

`/draft promote` 属于 verifier 协议代码，必须在用户明确确认后执行。AI 可以生成 Review 和 promotion 建议，但不能临场决定复制哪些文件。协议按固定映射将候选调查包和候选能力作为一致版本晋升：

```text
impl/projects/<project>/draft/investigation/<role>/
→ impl/projects/<project>/investigation/<role>/

impl/projects/<project>/draft/tools/
→ impl/projects/<project>/tools/

impl/projects/<project>/draft/context_builders/ 中稳定注册逻辑
→ 项目正式 Context 注册机制

impl/projects/<project>/draft/<role>.py
→ impl/projects/<project>/<role>.py
```

晋升后的 `investigation/<role>/` 是该 Role 已验证的项目知识真相源之一；正式 ContextUnit 从该目录加载稳定内容。Tool 继续由正式 Tool loader 注入。下一轮同 Role Draft 从已晋升调查包开始增量更新，不从零重新理解项目。

若某项事实或 Tool 经验证后应被多个 Role 使用，promotion 可以将其放入正式项目 Context/Tool 公共位置，并显式配置各 Role 权限；不能通过让一个 Role 直接读取另一个 Role 的候选调查包实现共享。

如果只晋升 Role 而未晋升其依赖的调查 Context 或 Tool，promotion 必须失败。回滚也必须恢复 Role、Context 和 Tool 的一致版本。

## 1.12 停止条件

Investigate 在以下情况停止并报告：

- 已形成与 objective 相称的调查包，可进入 solidify；
- 达到迭代、时间、费用或工具预算；
- ROLE.md 要求的必要材料、服务、权限或数据不可获得；
- 连续调查没有产生新的可验证信息；
- 需要用户决定业务责任或高成本架构方向；
- 调查只能产生推测，无法形成真实 EvidenceRef 或可执行验证能力。

停止不等于成功。无法验证的内容写入 `unresolved_reason`，并说明恢复调查所需条件。

---

# 第二章：Changes——现状差异与一次性改造任务

## 2.1 现状差异

| 当前现状 | 长期协议 | 必要差异 |
|---|---|---|
| Draft 有探索原则，但产物依赖 AI 临场组织 | 固定项目调查包目录和 manifest | 后续 AI 和 runtime 才能稳定复用 |
| 调查结论主要进入自由 Markdown | manifest 只索引不可或缺的产物，大内容仍使用 Markdown | 同时满足机器串联与复杂项目表达 |
| Attribute 业务执行链主要用文字描述 | Attribute 固定使用 Mermaid `.mmd` + 配套节点文档 | 保留结构、可视化和 AI 可读性；Judge、Mock、Live 使用各自专属产物 |
| EvidenceRef 可能被当成所有内容的容器 | EvidenceRef 只承担真实来源引用 | 避免引用、知识、Tool 和 ContextUnit 混为一体 |
| 已实现和未实现的 Tool 需求无法统一表达 | ToolRequirement 描述能力，ToolImplementationRef 可选指向真实代码 | Investigate 能记录缺口，Solidify 能确定性补齐 |
| 项目调查与运行时能力没有明确交接 | context builder 注册文档，Tool loader 注册代码，Role 使用两者 | 调查结果才能改善实际 baseline |
| Role 差异容易只体现在文档清单 | ROLE.md 同时约束 EvidenceRef、ToolRequirement、artifact 和 unresolved 的语义 | 调查标准作用于真实来源与验证能力，而不只是增加文件 |
| 一个项目的不同 Role 调查目标、权限和材料语义不同 | 统一 Manifest，按 `draft/investigation/<role>/` 分包，并由对应 ROLE.md 规定语义 | 隔离候选知识，避免把 Attribute 内部诊断材料泄露给 Judge 等 Role |
| 项目知识缺少候选与正式位置 | `draft/investigation/<role>/` 验证后晋升 `investigation/<role>/` | 支持版本、增量更新和一致回滚 |
| 现有 Draft 大框架已能 current/draft、Review、promotion | 只补 Investigate 产物和固化接缝 | 不建立平行优化框架 |
| Test 和 Review 容易被提升为两个单轮阶段 | Draft Loop 持续调度协议运行、多源评估、按 config.review 判断和 AI 修订 | 对齐原 Draft 的数据驱动自迭代方式 |
| Loop 成功条件可能退化为泛化的 requirements met | 冻结 Current；Draft 被证明实质优于 Current 且无退化才成功 | 保留原 Draft 最核心的判优不变量 |

## 2.2 一次性改造任务

### Task 1：收敛 Draft 文档和 Skill

- 将 Investigate 明确为现有探索层核心步骤；
- 在 `.agents/skills/draft/SKILL.md` 增加半交互、全托管和 `/draft` 控制语义；
- 将主要流程收敛为 Investigate、Solidify、Draft Loop、Promote；
- 明确 Loop 内协议运行由 verifier 代码执行，review 判断/修订由当前 Draft Harness AI 执行，Promote 由用户授权的协议代码执行；
- 额外 Draft Reviewer 仅作为用户或项目配置启用的可选评估来源，不是默认角色；不得替代 Attribute 等 Role 自身的 runtime Reviewer；
- 保留现有 objective、material、mock_source、review 和四层工作流；
- 在每个 `.agents/skills/draft/<role>/ROLE.md` 中按固定八个章节补齐调查目标、材料边界、核心问题、Evidence、Tool、Artifact、Solidify 用法和 Loop review；
- 修正现有 Attribute ROLE.md 与最新 Attribute 协议的冲突：不再以 strong/medium/weak/none 作为正式结果标准，调查不足时进入 unresolved；
- 将 `.agents/skills/draft/SKILL.md` 中“首个偏离点、根因、probe、链路地图”等 Attribute 专属探索方式迁入 Attribute ROLE.md，公共 Skill 改为按 Role 契约调查；
- 同步修正 `.agents/skills/attribute/SKILL.md` 和 `spec/alg/attribute.md` 中旧结果字段、evidence strength 及 Reviewer 自行探索描述，以 `spec/alg/attribution-schema.md` 和当前 Reviewer 权限为准；
- 删除独立 Investigate Agent、Session、Runtime、Adapter 等不必要概念；
- 将本文的调查包和 schema 流同步到 `spec/draft/draft.md`。

### Task 2：实现 schema 与序列化

- 新增 `InvestigationManifest`、`ToolRequirement` 和 `ToolImplementationRef` dataclass；
- 实现 JSON 序列化、反序列化和 schema version；
- 验证 project_id、role、source_revision、EvidenceRef、ToolRequirement、ToolImplementationRef 和 artifacts；
- 大型 EvidenceRef payload 拒绝进入 manifest；
- 不新增调查执行过程的 dataclass 或状态机。

### Task 3：提供调查包模板

- 增加 `manifest.json` 示例；
- 增加 `overview.md` 模板；
- 增加 `docs/traces/` 下的 Attribute `.mmd` 业务执行链示例和配套 trace Markdown 模板；
- 其他 Role 只提供 ROLE.md 中的 EvidenceRef、ToolRequirement 和可选 artifact 示例，不强制创建固定文档；
- 公共模板保持同一结构，各 ROLE.md 声明该 Role 对四类公共载体的语义要求，不复制 Manifest schema；
- 模板只约束产出格式，不约束 Codex、Claude Code 调查过程。

### Task 4：实现调查包检查器

- 检查 manifest 可以反序列化；
- 检查 manifest role 存在对应 ROLE.md，且目录名、role 字段和 DraftConfig.role 一致；
- 检查所有相对路径存在且不逃逸项目目录；
- 对 artifacts 中实际存在的 `.mmd` 检查语法可解析；
- 对 Attribute 每个已登记的 `.mmd` 检查配套 Markdown 覆盖 Mermaid 关键节点；是否缺少必需链路由 Draft Skill 按 Attribute ROLE.md 审核；
- 检查 EvidenceRef 可追溯并带 source revision/hash；
- 导入每个 Tool `module_path + factory`；
- 确认 factory 返回 `VerifiableTool`；
- 对 Tool 执行项目提供的最小真实测试；
- 输出错误并阻断 solidify，不通过 fallback 保留伪产物。

### Task 5：接入 Draft Context

- 增加 `draft/context_builders/<role>_investigation.py` 的项目模板；
- 将 overview 和 artifacts 按主题注册为独立 ContextUnit 或受控资源；
- ContextUnit 使用 `content_ref` 或受控加载，避免启动时全量塞入上下文；
- Draft Role 只能看到正式 Context 加当前候选 Context；
- 当前候选 Context 只来自 `draft/investigation/<role>/`，不得扫描其他 Role 候选包；
- Attribute context builder 按主题注册 `docs/traces/` 和确有必要的 artifacts，不把整个调查包或离线根因结论一次性塞入 Prompt；
- current Role 不得看到未晋升调查内容；
- 关闭 Draft 后 production 行为保持不变。

### Task 6：接入 Draft Tool

- Solidify 按 ToolRequirement 复用、包装或新建 Tool，并为已实现项填入 ToolImplementationRef；
- Draft loader 只根据非空且已校验的 ToolImplementationRef 装配 Tool；
- 复用正式 Tool 与加载候选 Tool 都使用同一 `VerifiableTool` 协议；
- 增加 module_path、factory、tool_id 一致性检查；
- 增加 ToolRequirement 与 VerifiableTool 的 description、applicable_scenario 和 parameters 一致性检查；
- 增加 parameters description、真实执行、失败暴露和 ToolResult 测试；
- implementation 为空的 requirement 不得被 Agno 看见，并由 Review 判断是否阻断目标结论。

### Task 7：接入 Draft Role 和 Draft Loop

- solidify 时明确候选 Role 使用哪些调查 Context 和 Tool；
- Loop 开始时冻结 production Current、项目 revision、objective、review 和 iteration cases；
- 先运行 Current 并记录 objective 对应的真实 gap；
- `/draft loop` 调度 verifier 项目协议和 current/draft runner，不由 Harness AI 自由实现正式运行；
- 同一套 Loop 按 DraftConfig.role 选择现有 Role runner、RoleResult、comparator 和 ROLE.md review 规则，不创建 Role 专属 Loop schema；
- 协议运行输出两侧实际 Context/Tool 清单；
- 保存 Context Search/Load、Tool Call、原始 RoleResult 和异常；
- 接入项目算法/comparator、Role 专属评估、真实实验和用户反馈；
- Draft Skill 按 config.review 比较每个 Draft revision 与 frozen Current，并将未满足项路由回 Investigate、Solidify 或 protocol blocker；
- Draft 与 Current 相同、只有局部改善、存在退化或证据不足时均不得成功停止；
- 只使用固定 iteration cases 循环，unseen 只用于 promotion-only checks；
- 落实 max_iterations、预算、无新信息和用户停止条件；
- 候选 Role 没有使用已声明的关键调查能力时，Review 必须指出；
- Attribute runner 额外保存动态 ContextUnit 注册、Investigation/Finalization Load、EvidenceRef 物化和 Reviewer issue/补证事实，用于判断项目调查能力是否真正进入 runtime。

### Task 8：接入 Loop 判断与协议 Promotion

- Draft Skill 读取 manifest、overview、artifacts、EvidenceRef、Tool 代码和原始测试结果；
- 按 config.review 和对应 ROLE.md 检查调查材料真实性、关键对象相关性、Tool 验证效力和 objective 改善；
- 半交互模式每轮判断后暂停；全托管模式按未满足项继续循环；
- Harness AI 只生成本轮判断、遗留问题和 promotion 建议，不执行文件晋升；
- 用户或项目配置可选择额外 Draft Reviewer，但默认 loop 不依赖它；Attribute runtime Reviewer 仍按 Attribute 协议必经执行；
- 协议代码根据固定路径映射生成 promotion 清单；
- 人工确认后由协议代码按一致版本晋升；
- 回滚恢复一致版本；
- source revision 变化时提示更新调查包，不自动调用 AI。

### Task 9：更新 Evals onboarding

- Evals 继续生成可运行 functional baseline；
- onboarding 报告按 Role 指出调查包是否缺失或过期；
- 用户通过 `/draft start ...` 手动初始化或更新调查包；
- 默认 Draft 即使没有预制调查包，也能够使用模板构建 baseline；
- Evals 不在项目启动或普通 case 运行中自动执行 AI 项目调查。

### Task 10：以 client_search Attribute 验收

- 调查 client_search 原业务请求链路，而不是 verifier trace；
- 生成请求解析、规则/RAG、模型解析、条件构造、搜索 API 和响应的 Mermaid 链路；
- 标注真正串联各阶段的函数和核心 API；
- 将上述链路的真实来源登记为 EvidenceRef，将所需执行验证登记为 ToolRequirement；只在内容确实无法放入链路说明或 overview 时增加 artifact；
- 复用或补齐实际 `VerifiableTool`，包括必要 replay/probe；
- 将调查包注册为 Draft ContextUnit 并注入候选 Tool；
- 验证 Tool/source/probe 结果进入动态 ContextUnit，Finalization 只引用已调查并重载的材料；
- 验证 Reviewer 只读取被引用 ContextUnit 全文和其余资源 name/description 目录，不调用 Tool，并能要求主 Attribute 补证；
- 运行既有失败 trace 和正常对照；未见 case 只由 promotion-only protocol 执行，不向 Harness AI 暴露；
- 验证 Attribute 能区分本次输出遗漏、规则未覆盖、Prompt/模型问题、后处理问题和业务服务不可达；
- Draft Loop 满足 config.review 后只形成 promotion proposal，不自动覆盖 production。

### Task 11：测试与回归

- dataclass JSON round-trip；
- manifest version 与非法字段测试；
- 路径逃逸、缺失文件和 source revision 测试；
- Mermaid 解析和节点文档覆盖测试；
- EvidenceRef 真实性与大型 payload 阻断测试；
- ToolRequirement 的三种状态、JSON round-trip 和缺失实现测试；
- Tool module_path/factory/import/VerifiableTool/ToolResult 测试；
- Draft/current Context 和 Tool 隔离测试；
- 不同 Role 候选调查包、Context 和 Tool 权限隔离测试；
- ContextUnit 按需加载与大文档预算测试；
- Attribute 静态/动态 ContextUnit、调查来源可发现性和 ToolResult 动态注册测试；
- Attribute Investigation → Finalization → Reviewer → 补证/收缩的代表 trace 端到端测试；
- Role 协议、current/draft、unseen、promotion 和回滚测试；
- frozen Current 不随 Draft revision 变化、基线 gap 和配置 revision 失效测试；
- Draft 相同、局部改善伴随退化、证据不足和真正优于 Current 的四类判定测试；
- Draft Loop 多轮、review 判断路由、用户反馈、max_iterations 和停止条件测试；
- Attribute Reviewer 权限与 evidence 使用测试；
- DraftConfig.role 选择正确 ROLE.md、未知 Role 阻断、不同 Role 材料权限和必需产物测试；
- api-check、前端 summary 和现有 Mock/Judge/Attribute 回归。

## 2.3 主要代码与文档落点

| 路径 | 职责 |
|---|---|
| `spec/alg/investigate.md` | Investigate 长期协议真相源 |
| `spec/draft/draft.md` | 同步现有 Draft 四层中的调查与固化流程 |
| `.agents/skills/draft/SKILL.md` | 统一用户控制面；调度 Harness AI 和协议动作 |
| `.agents/skills/draft/MAP.md` | 指向模板、validator、runner 和 Role 资源 |
| `.agents/skills/draft/reference/` | 公共 manifest/overview、Role 契约示例，以及 Attribute trace 模板 |
| `.agents/skills/draft/scripts/` | 调查包 validator、协议 Test 和现有 Draft 检查脚本 |
| `impl/core/schema/investigation.py` | 三个 dataclass 和 JSON 边界 |
| `impl/projects/<project>/draft/investigation/<role>/` | 当前 Role 的候选项目调查包 |
| `impl/projects/<project>/draft/tools/` | 候选 VerifiableTool |
| `impl/projects/<project>/draft/context_builders/<role>_investigation.py` | 当前 Role 候选调查 ContextUnit 注册 |
| `impl/projects/<project>/investigation/<role>/` | promotion 后的 Role 项目调查知识 |
| `impl/projects/<project>/tools/` | promotion 后的正式 Tool |
| `tests/` | schema、图、Tool、Context、隔离、runner 和回归测试 |

## 2.4 推荐实施顺序

```text
1. 同步 Draft Skill/spec 边界
2. InvestigationManifest + ToolRequirement + ToolImplementationRef
3. 调查包模板与 validator
4. Role 契约与 Attribute Mermaid 校验
5. Context builder 固化
6. Tool loader 固化
7. Draft Loop：协议运行、多源评估、按 config.review 判断与修订串联
8. Promotion 与一致回滚
9. Evals onboarding 提示
10. client_search trace 实测
11. api/frontend/全量回归
```

实施必须保持最小修改：先证明现有 Draft loader、ContextUnit 和 Tool 机制能够承担，再补缺失接缝；不得因为 Investigate 引入新的公共 RoleResult、运行时 Reviewer 权限或平行 Draft 框架。
