# Investigate：Draft 前置项目调查与固化协议

本文定义 verifier Draft 探索层中的 Investigate 步骤。

Investigate 不是新的 Role、独立 Skill、运行时 Agent 或平行优化框架。它是现有 Draft 四层流程中，在修改候选 `role.py` 前执行的核心调查工作：由 Codex、Claude Code 等工程型 AI 理解真实业务项目，分析业务 trace，定位关键函数与核心 API，构建必要验证 Tool，并把可复用结果固化给 Draft Role 和 Agno runtime。

Investigate 的执行过程不受本协议约束。AI 可以搜索源码、阅读文档、调用业务 API、分析业务 trace、编写临时脚本或进行人工交互。本协议只约束调查结束后必须交付什么、产物采用什么格式、如何被 Draft 固化和验证。

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

Draft Skill 是统一控制面。Run/Test 和 Promote 必须调用项目协议提供的确定性入口；目标判断和候选修订由当前 Draft Harness AI 完成，但不得重写协议产生的原始结果。独立 Reviewer 不是默认角色；项目确有需要时可以作为 `review` 的可选评估来源。

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

`/draft test` 可以保留为诊断命令，只运行一次协议测试而不自动修改候选。`/draft review` 不作为默认命令；用户要求额外审查时，可以临时调用可选 Reviewer。正常路径固定为：

```text
/draft investigate → /draft solidify → /draft loop → /draft promote
```

### 半交互模式

AI 可以持续调查并在有意义的检查点展示：

- 新发现的业务链路；
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
| Investigate | 调查包目录、Manifest、EvidenceRef、ToolRequirement、Markdown/Mermaid 格式 | 调查目标、材料权限、必须回答的问题、哪些 trace/证据/Tool 有意义 |
| Solidify | 调查产物转 ContextUnit/VerifiableTool/候选 Role 的流程 | 读取对应 Role 协议和权限后，产出 `draft/<role>.py`；不另设 Role 专属固化阶段或 schema |
| Draft Loop | frozen Current、相同数据运行、按 objective/review 判优、max_iterations | 调用现有 Role runner、result schema、comparator 和 ROLE.md 验收原则；不另设 Role 专属 Loop |
| Promote | 用户确认、固定路径映射、一致版本与回滚 | 当前被晋升的 Role 文件及其实际依赖资产 |

从流程和新增 schema 看，只有 Investigate 需要显式按 Role 分包：不同 Role 调查的问题、可见材料和产物语义确实不同。Solidify、Draft Loop 和 Promote 都复用公共阶段，不复制流程或数据结构；其中 Solidify 和 Loop 只是调用现有 Role 扩展点，Promote 只处理实际候选文件及依赖。

因此不新增 Attribute/Judge 专属 Manifest、SolidifyResult 或 Loop schema。现有 `.agents/skills/draft/<role>/ROLE.md` 是 Role 调查要求、材料权限、固化约束和判优要求的真相源；公共 spec 只规定阶段交接和不可违反的门禁。

## 1.4 Investigate 的不可或缺产物

调查结束后必须形成当前 Role 的调查包。所有 Role 至少交付：

1. `overview.md`：AI 对当前 Role 所需项目信息的解释；
2. `EvidenceRef`：核心文档、源码、API、业务 trace、实验或其他真实材料引用；
3. `ToolRequirement`：当前 Role 需要的验证能力，包括已实现和待实现项；
4. `extra_files`：Role 或项目需要的扩展性产物；
5. `unresolved_reason`：当前仍无法确认的部分。

是否必须产生 Mermaid trace、关键串联函数、核心 API、内部代码或 replay/probe，由对应 ROLE.md 决定，不能把 Attribute 的内部诊断方式强制给所有 Role。

例如：

- Attribute 默认要求业务系统 trace、关键函数/API、内部配置和可区分原因的 replay/probe；
- Judge 默认要求用户意图、业务期望、可观察输出、acceptance criteria 和外部 comparator，不能因调查方便默认读取内部实现；
- 未来 Mock 可关注输入协议、场景空间、合法约束和样本覆盖；
- 未来 Live 可关注 API、鉴权、传输、响应归一化和错误边界。

调查包允许包含其他项目特有产物，但扩展内容必须通过 manifest 登记，不能成为只有生成者知道的隐式文件。

## 1.5 调查包目录

候选调查结果固定保存在：

```text
impl/projects/<project>/draft/investigation/
└── <role>/
    ├── manifest.json
    ├── overview.md
    ├── traces/
    │   ├── <flow>.mmd
    │   ├── <flow>.md
    │   └── <flow>.svg             # 可选派生预览，不是真相源
    └── docs/
        └── <project-specific>.md  # 可选大型补充材料

impl/projects/<project>/draft/tools/
└── <verification_tool>.py

impl/projects/<project>/draft/context_builders/
└── <role>_investigation.py
```

各文件职责：

- `manifest.json`：调查包的机器入口，由 `InvestigationManifest` 序列化产生；
- `overview.md`：项目边界、核心链路概览、关键结论、调查范围和未知项；
- `traces/*.mmd`：业务链路图的文本真相源；
- `traces/*.md`：解释图中节点，关联函数、API、Tool、原始材料和观察边界；
- `traces/*.svg`：供前端或人工查看的派生图，删除后可以重新生成；
- `docs/*.md`：无法合理放入 overview 或 trace 说明的大型扩展材料；
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

    trace_ids: list[str] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    tool_requirements: list["ToolRequirement"] = field(default_factory=list)
    extra_files: dict[str, str] = field(default_factory=dict)

    unresolved_reason: str = ""
```

字段消费关系：

| 字段 | 内容 | 下一阶段如何使用 |
|---|---|---|
| `schema_version` | manifest 格式版本 | validator 选择解析规则 |
| `project_id` | 真实业务项目身份 | 阻止跨项目误加载 |
| `role` | 本调查包服务的 Role，如 `attribute`、`judge` | 选择对应 ROLE.md，并阻止候选 Context/Tool 越权跨 Role 注入 |
| `source_revision` | 本次调查对应的项目 commit、版本或内容 hash | 判断调查是否过期 |
| `trace_ids` | ROLE.md 要求的链路 ID；每个 ID 固定对应 `traces/<id>.mmd` 和 `traces/<id>.md` | 注册当前 Role 可见的链路 ContextUnit 并生成可视化 |
| `evidence_refs` | 函数、API、文档、业务 trace 和实验的来源引用，以 `kind` 区分 | Role 导航、Solidify 选路和 Review 核对 |
| `tool_requirements` | 调查确认需要的验证能力；实现可能已存在，也可能仍待 Solidify 完成 | Solidify 复用、包装或新建 VerifiableTool |
| `extra_files` | `相对路径 → 用途`，登记项目特有调查文件 | 保留扩展性并纳入 Review/promotion |
| `unresolved_reason` | 无法确认的链路、资料或验证能力 | 限制 Draft 结论与 promotion 范围 |

`overview.md` 和 `traces/` 的位置由调查包目录协议固定，因此不在 manifest 重复保存路径。关键函数、核心 API、核心文档和业务 trace 统一使用已有 `EvidenceRef`，通过 `kind` 区分，不再创建四套平行字段。

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
- Tool 必须实际执行并返回 `ToolResult`，不能只读取一段说明然后宣布根因；
- “未来应该做一个 Tool”不是 `ToolImplementationRef`；它必须保留为 `implementation=None` 的 `ToolRequirement`，并说明 implementation gap。

### 1.6.4 `EvidenceRef` 的边界

现有 `EvidenceRef` 足以承担函数、API、文档和原始 trace 的来源引用，但不足以承担整个调查包。

在 Investigate 中：

- `ref_id`：调查包内稳定引用 ID；
- `source`：来源系统或材料类型；
- `kind`：`source/function/api/document/business_trace/replay/test` 等开放字符串；
- `summary`：AI 对材料作用的解释，不视为原始事实；
- `location`：真实文件、符号、endpoint、trace 或结果文件位置；
- `payload`：仅保存小型且可 JSON 序列化的原始值；大型内容必须保存在文件或来源系统；
- `metadata`：保存 source revision、hash、trace identity、读取范围等。

只有能够回到真实 `location` 或可信原始 `payload` 的 EvidenceRef 才允许进入 manifest。无法追溯的 AI 描述只能写在 Markdown 中并标为未确认。

EvidenceRef 是“来源引用”，不是 ContextUnit、Tool、链路图或调查结论本身。

## 1.7 业务 Trace 格式

对应 ROLE.md 要求链路产物时，统一采用下面的文本格式。它是可复用的调查产物格式，不代表每个 Role 都必须调查业务系统内部链路。

### 1.7.1 Mermaid 是文本真相源

业务链路使用 Mermaid flowchart 或 sequence diagram 表达：

- `.mmd` 保存节点和边的源代码；
- 节点 ID 在同一项目中保持稳定；
- `.md` 使用与 Mermaid 一致的节点 ID 做详细解释；
- `.svg`、`.png` 只用于展示，不能替代 `.mmd`；
- Agno、Codex、Claude Code 等 AI 消费 `.mmd` 或 Markdown 源码，不依赖图片理解。

Mermaid 是文本式图语言，适合直接嵌入 Markdown并表达流程图、时序图。Graphviz DOT 和 D2 也能表达文本图，但本项目默认采用 Mermaid，避免增加新的渲染语言和依赖：

- Mermaid syntax：<https://mermaid.js.org/intro/syntax-reference.html>
- Graphviz DOT：<https://graphviz.org/doc/info/lang.html>
- D2：<https://d2lang.com/>

### 1.7.2 最小链路图

```mermaid
flowchart LR
    request["用户请求"]
    parser["输入解析"]
    decision["业务决策"]
    downstream["下游业务 API"]
    response["结果返回"]

    request --> parser
    parser --> decision
    decision --> downstream
    downstream --> response
```

链路图只描述已经从代码、业务 trace、API 或实验中确认的关系。推测节点必须在配套 Markdown 标记为 provisional，不能与真实执行路径混写。

### 1.7.3 配套 Trace 文档

每个 `<flow>.md` 至少包含：

```markdown
# Flow: <flow id and name>

## Scope and source traces

## Node: <same node id as Mermaid>

- Responsibility:
- Input / output:
- Key functions:
- Core APIs:
- Verification tools:
- Evidence refs:
- Observation boundary:

## Branches and failure points

## Unresolved
```

这里允许使用长篇 Markdown。schema 只索引文件，不把庞大的项目知识强塞进 JSON 字段。

## 1.8 调查要求

### 业务 trace 与 verifier trace

当当前 Role 使用 trace 作出判断时，Investigate 必须区分：

- 业务 trace：被测业务请求在原业务系统中的执行路径、输入、输出、调用和状态变化；
- verifier trace：Mock、Live、Judge、Attribute、Reviewer 等评测链路自己的记录。

业务 trace 用于建立原系统链路。verifier trace 只能说明评测过程发生了什么，不能替代业务 trace 证明业务系统内部原因。

没有业务 trace 时，可以使用真实业务 API、局部函数、项目测试、日志或 replay 补足。仍无法验证时必须写入 `unresolved_reason`，不能把静态调用图包装成已确认运行链路。

### 诊断类 Role 以 DFS 优先

Attribute 等诊断类 Role 应围绕 objective 相关的业务链路深入验证：

```text
业务 gap
→ 相关 trace
→ 关键链路节点
→ 对应函数/API
→ 可用或缺失的验证 Tool
→ 实际执行结果
```

不得通过罗列大量无关文件、普通函数或全项目缺陷代替链路调查。非诊断类 Role 仍需围绕 objective 深入，但具体路径由对应 ROLE.md 规定。

### 初始化与更新

- 新项目初始化：按对应 ROLE.md 调查核心入口、目标相关链路、关键接口和基础验证能力；
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
  Role 要求的 Mermaid trace + trace.md（可选）
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
- 每条 trace 的 `.mmd + .md` → 独立业务链路 ContextUnit；
- 大型核心文档 → 独立 ContextUnit 或 `content_ref`；
- `manifest.json` → 构建和审计输入，不直接当作业务证据。

ContextUnit 的 `name/description` 必须让 Role 能判断何时加载，并带上与现有权限模型一致的 Role 可见性。架构地图用于导航，不因被加载就自动证明当前 case 的根因。

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

API 文档、业务链路图和源码说明属于 ContextUnit；调用 API、执行 replay 或运行脚本获取当前 case 结果属于 VerifiableTool。Tool 的结果可以按现有 Attribute 流程注册为动态 ContextUnit，但静态 ContextUnit 不能替代执行验证。

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
- validator 检查 manifest、路径、Mermaid、Tool factory、Context 和 Role 协议；
- 保存两侧原始 RoleResult、异常、Context Search/Load 和 Tool Call；
- 不输出通用“draft 更优”结论；
- Harness AI 不得用自由脚本替代这一正式运行，也不得重写原始结果。

### 多源评估

每轮可以同时消费：

- 项目 comparator、runtime check、schema 和协议检查；
- Role 专属算法评估，例如 Attribute 归因准确性或 Judge 业务判断；
- replay、probe、反事实实验和真实 ToolResult；
- 用户对结果、业务要求和问题优先级的反馈。

这些评估不要求使用同一种算法，但都必须针对固定 objective/review，并能回到协议运行事实、真实实验或明确的用户判断。Draft Skill 结合这些信号作出本轮判断；可选独立 Reviewer 只在项目配置或用户明确要求时作为额外信号，不形成默认第二角色。字段更多、文本更长、Tool 调用更多或 confidence 更高不能单独证明改善。

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

- trace 是否来自业务系统材料而不是 verifier trace；
- Mermaid 边是否有代码、trace、API 或实验依据；
- 关键函数和 API 是否真的串联业务链路；
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

## 1.12 Role 联动

调查包使用同一 Manifest，但不同 Role 通过各自 ROLE.md 决定调查重点和运行时消费方式。

### Attribute

Attribute Draft 是第一类使用者：

- Investigation 提供业务链路 ContextUnit；
- Trace 节点帮助 Attribute 沿相关路径 DFS；
- 关键函数和 API 帮助它选择真实验证入口；
- VerifiableTool 提供 replay、probe、simulation 或业务 API 检查；
- Attribute runtime 将具体 case 的 Tool 结果注册为动态 ContextUnit；
- Attribute Finalization 只引用实际支持 finding 的材料；
- Attribute Reviewer 审核被引用材料是否真正支持结论，并要求主 Attribute 补证。

项目调查包本身是导航和长期知识，不自动成为具体 case 的 EvidenceRef。只有当前 case 实际加载、执行或观察到的材料，才可按 Attribute 协议进入证据链。

### Judge

Judge Draft 主要消费用户需求、业务期望、可观察输出协议、acceptance criteria、外部业务资料和 comparator。除非项目明确授权且 Judge 协议允许，它不读取业务内部源码、内部 trace 或 Attribute 调查包，避免把实现信息泄露给应从外部判断结果的 Role。

Judge 与 Attribute 可以引用同一份已晋升且权限允许的业务资料或正式 Tool，但各自在自己的调查包中解释其用途；它们不共享候选结论，也不因此采用同一套调查问题。

### 其他 Role

Mock、Live 及未来 Role 继续使用同一 Manifest 和阶段流，只在对应 ROLE.md 增加必要的调查要求、权限和验收标准，不在本文增加平行流程。

## 1.13 停止条件

Investigate 在以下情况停止并报告：

- 已形成与 objective 相称的调查包，可进入 solidify；
- 达到迭代、时间、费用或工具预算；
- 必要业务 trace、服务、源码、权限或数据不可获得；
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
| 业务链路主要用文字描述 | Mermaid `.mmd` + 配套节点文档 | 保留结构、可视化和 AI 可读性 |
| EvidenceRef 可能被当成所有内容的容器 | EvidenceRef 只承担真实来源引用 | 避免引用、知识、Tool 和 ContextUnit 混为一体 |
| 已实现和未实现的 Tool 需求无法统一表达 | ToolRequirement 描述能力，ToolImplementationRef 可选指向真实代码 | Investigate 能记录缺口，Solidify 能确定性补齐 |
| 项目调查与运行时能力没有明确交接 | context builder 注册文档，Tool loader 注册代码，Role 使用两者 | 调查结果才能改善实际 baseline |
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
- 独立 Reviewer 仅作为用户或项目配置启用的可选评估来源，不是默认角色；
- 保留现有 objective、material、mock_source、review 和四层工作流；
- 在每个 `.agents/skills/draft/<role>/ROLE.md` 中补齐该 Role 的调查目标、可见材料、必需产物和验收要求；
- 删除独立 Investigate Agent、Session、Runtime、Adapter 等不必要概念；
- 将本文的调查包和 schema 流同步到 `spec/draft/draft.md`。

### Task 2：实现 schema 与序列化

- 新增 `InvestigationManifest`、`ToolRequirement` 和 `ToolImplementationRef` dataclass；
- 实现 JSON 序列化、反序列化和 schema version；
- 验证 project_id、role、source_revision、trace_ids、EvidenceRef、ToolRequirement、ToolImplementationRef 和 extra_files；
- 大型 EvidenceRef payload 拒绝进入 manifest；
- 不新增调查执行过程的 dataclass 或状态机。

### Task 3：提供调查包模板

- 增加 `manifest.json` 示例；
- 增加 `overview.md` 模板；
- 增加 `.mmd` 业务 flow 示例；
- 增加配套 trace Markdown 模板；
- 公共模板保持同一结构，各 ROLE.md 只声明该 Role 必填的材料类别，不复制 Manifest schema；
- 模板只约束产出格式，不约束 Codex、Claude Code 调查过程。

### Task 4：实现调查包检查器

- 检查 manifest 可以反序列化；
- 检查 manifest role 存在对应 ROLE.md，且目录名、role 字段和 DraftConfig.role 一致；
- 检查所有相对路径存在且不逃逸项目目录；
- 检查 `.mmd` 语法可解析；
- 检查 trace Markdown 覆盖 Mermaid 关键节点；
- 检查 EvidenceRef 可追溯并带 source revision/hash；
- 导入每个 Tool `module_path + factory`；
- 确认 factory 返回 `VerifiableTool`；
- 对 Tool 执行项目提供的最小真实测试；
- 输出错误并阻断 solidify，不通过 fallback 保留伪产物。

### Task 5：接入 Draft Context

- 增加 `draft/context_builders/<role>_investigation.py` 的项目模板；
- 将 overview、trace 和大型文档按主题注册为独立 ContextUnit；
- ContextUnit 使用 `content_ref` 或受控加载，避免启动时全量塞入上下文；
- Draft Role 只能看到正式 Context 加当前候选 Context；
- 当前候选 Context 只来自 `draft/investigation/<role>/`，不得扫描其他 Role 候选包；
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
- 候选 Role 没有使用已声明的关键调查能力时，Review 必须指出。

### Task 8：接入 Loop 判断与协议 Promotion

- Draft Skill 读取 manifest、overview、Mermaid、EvidenceRef、Tool 代码和原始测试结果；
- 按 config.review 和对应 ROLE.md 检查调查材料真实性、关键对象相关性、Tool 验证效力和 objective 改善；
- 半交互模式每轮判断后暂停；全托管模式按未满足项继续循环；
- Harness AI 只生成本轮判断、遗留问题和 promotion 建议，不执行文件晋升；
- 用户或项目配置可选择额外独立 Reviewer，但默认 loop 不依赖它；
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
- 复用或补齐实际 `VerifiableTool`，包括必要 replay/probe；
- 将调查包注册为 Draft ContextUnit 并注入候选 Tool；
- 运行既有失败 trace、正常对照和未见 case；
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
- Role 协议、current/draft、unseen、promotion 和回滚测试；
- frozen Current 不随 Draft revision 变化、基线 gap 和配置 revision 失效测试；
- Draft 相同、局部改善伴随退化、证据不足和真正优于 Current 的四类判定测试；
- Draft Loop 多轮、review 判断路由、用户反馈、max_iterations 和停止条件测试；
- Attribute Reviewer 权限与 evidence 使用测试；
- api-check、前端 summary 和现有 Mock/Judge/Attribute 回归。

## 2.3 主要代码与文档落点

| 路径 | 职责 |
|---|---|
| `spec/alg/investigate.md` | Investigate 长期协议真相源 |
| `spec/draft/draft.md` | 同步现有 Draft 四层中的调查与固化流程 |
| `.agents/skills/draft/SKILL.md` | 统一用户控制面；调度 Harness AI 和协议动作 |
| `.agents/skills/draft/MAP.md` | 指向模板、validator、runner 和 Role 资源 |
| `.agents/skills/draft/reference/` | manifest、overview、Mermaid 和 trace 模板 |
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
4. Mermaid 校验
5. Context builder 固化
6. Tool loader 固化
7. Draft Loop：协议运行、多源评估、按 config.review 判断与修订串联
8. Promotion 与一致回滚
9. Evals onboarding 提示
10. client_search trace 实测
11. api/frontend/全量回归
```

实施必须保持最小修改：先证明现有 Draft loader、ContextUnit 和 Tool 机制能够承担，再补缺失接缝；不得因为 Investigate 引入新的公共 RoleResult、运行时 Reviewer 权限或平行 Draft 框架。
