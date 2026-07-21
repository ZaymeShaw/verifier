# Investigate Trace：业务链路 Artifact 增强协议

本文是 `spec/alg/investigate.md` 的增量规范，只增强 Attribute 调查包中业务 trace artifact 的信息形状与可校验性。

本文不得修改或复制 Investigate 主流程。发生歧义时，以 `spec/alg/investigate.md` 为准：仍然只有 InvestigationManifest 一个顶层调查产物 schema，仍然通过现有 `artifacts` 索引调查文件，仍然由 ROLE.md 区分 Role 语义，并沿用既有 Investigate → Solidify → Draft Loop → Promote 流程。

---

# 第一章：Spec 标准——最终长期协议

## 1.1 目标与边界

当前 Attribute 的 `.mmd + .md` 已能保存业务链路和调查说明，但仅靠节点名称和自然语言表格，容易出现以下问题：

- 节点名称存在，却没有说明该节点实际接收和产生什么；
- 多个阶段都写成 `conditions`，无法判断数据在哪一步首次发生偏差；
- Markdown 写了 Tool/EvidenceRef 名称，但名称不存在或引用错位；
- 源码中存在某个变量，被误当成当前 case 已观察到该变量；
- Solidify 看过大量组件说明，却没有得到足以支持候选设计的业务数据链。

本协议在现有 Attribute trace artifact 中增加一个结构化 sidecar，使业务节点、阶段数据、边和已有来源/验证能力可以被机器校验。

它不负责：

- 新增或修改 InvestigationManifest 字段；
- 创建独立 Trace 阶段、Trace Role 或 Trace runtime；
- 替代现有 Mermaid、Markdown、Operational index 或 Investigation procedure；
- 规定 Solidify 必须如何编写候选 Role、注册 ContextUnit 或调用 Tool；
- 把项目级业务链路直接当作当前 case 的 AttributionFinding；
- 把 verifier 自身 RunTrace、Judge reasoning 或历史 attribution 画成业务系统节点。

## 1.2 建立在现有调查包上的文件形状

现有调查包和 Manifest 保持不变：

```python
@dataclass
class InvestigationManifest:
    schema_version: int
    project_id: str
    role: str
    source_revision: str
    evidence_refs: list[EvidenceRef]
    tool_requirements: list[ToolRequirement]
    artifacts: dict[str, str]
    unresolved_reason: str = ""
```

Attribute 的一组业务链路仍位于既有 `docs/traces/` 下。本协议只在同名 `.mmd + .md` 旁增加 `.trace.json`：

```text
impl/projects/<project>/draft/investigation/attribute/
├── manifest.json
├── overview.md
└── docs/traces/
    ├── <flow>.mmd
    ├── <flow>.md
    └── <flow>.trace.json
```

三个文件全部通过现有 `InvestigationManifest.artifacts` 登记：

```json
{
  "artifacts": {
    "docs/traces/client-search-parse.mmd": "Attribute business execution topology",
    "docs/traces/client-search-parse.md": "Attribute trace operational guide",
    "docs/traces/client-search-parse.trace.json": "Structured node, data and edge index for the same trace"
  }
}
```

不增加 `trace_graph_paths`、`trace_artifacts` 或其他 Manifest 字段。validator、Solidify 和 Review 继续从 `artifacts` 取得实际文件。

只有 Attribute ROLE.md 要求业务链路时，才要求同名三件套。其他 Role 继续按自身 ROLE.md 选择有意义的 artifact，不得被迫生成 Attribute 式 TraceGraph。

## 1.3 同一 Trace artifact 的三种视图

`.mmd`、`.md` 和 `.trace.json` 共同表达同一组已调查事实，但分别承担不同职责：

| 文件 | 现有/新增 | 职责 |
|---|---|---|
| `<flow>.mmd` | 现有 | 保存业务拓扑和关键条件分支，便于人类与 AI 快速理解链路 |
| `<flow>.md` | 现有 | 保存节点解释、How to use、Operational index、Investigation procedure、来源边界和 unresolved 说明 |
| `<flow>.trace.json` | 新增 sidecar | 用稳定 ID 记录节点输入、输出、边上传递的数据及 EvidenceRef/ToolRequirement 引用，供 validator 和 Harness AI 精确读取 |

`.trace.json` 是这组 artifact 的机器可读结构索引，但不是新的 Investigate 顶层真相源。Manifest 仍是调查包入口；EvidenceRef 仍是来源引用；ToolRequirement 仍是验证能力契约；`.mmd/.md` 仍按原 ROLE.md 被 Solidify、ContextUnit 和 runtime Attribute 消费。

三个文件不得互相冲突：

- Mermaid 不得出现 JSON 中不存在的业务节点或边；
- JSON 中的节点必须在 Mermaid 和 Markdown 中可找到；
- Markdown 不得独立新增未登记的业务节点、阶段数据或 Tool/EvidenceRef；
- Markdown 可以增加背景、示例、调查解释和使用方式，但这些文字不会自动升级为结构事实或当前 case 证据。

## 1.4 TraceGraph artifact schema

Trace sidecar 使用 dataclass 规定文件形状。它是 `artifacts` 内部的文件格式，不是新的阶段结果或 RoleResult。

```python
@dataclass
class TraceGraph:
    graph_id: str
    scope: str
    nodes: list[TraceNode]
    edges: list[TraceEdge]


@dataclass
class TraceNode:
    node_id: str
    responsibility: str
    input_data_ids: list[str]
    outputs: list[TraceData]
    evidence_ref_ids: list[str]


@dataclass
class TraceData:
    data_id: str
    description: str
    schema_ref: str = ""
    evidence_ref_ids: list[str] = field(default_factory=list)
    tool_requirement_ids: list[str] = field(default_factory=list)
    observation_gap: str = ""


@dataclass
class TraceEdge:
    source_node_id: str
    target_node_id: str
    transferred_data_ids: list[str]
    condition: str = ""
    evidence_ref_ids: list[str] = field(default_factory=list)
```

不增加 ObservationBinding、TraceFinding、TraceTool、SolidifyHandoff 或 TraceUsageResult。

### 1.4.1 TraceGraph

| 字段 | 语义 |
|---|---|
| `graph_id` | 当前调查包内稳定且唯一的业务链路 ID，通常与文件 basename 一致 |
| `scope` | 图实际覆盖与明确不覆盖的业务边界 |
| `nodes` | 当前业务边界内的关键处理节点 |
| `edges` | 节点之间真实存在的数据传递和条件分支 |

`scope` 不能只写项目名。例如：

```text
覆盖自然语言查询进入 parse API 后，经 Router、规则/模型解析、条件校验和响应后处理形成 ParseApiResponse 的链路；不覆盖下游客户结果集搜索。
```

图不要求覆盖整个仓库。它应围绕可跨 case 复用的业务执行边界深入，而不是把目录、类和函数机械转换成调用图。

### 1.4.2 TraceNode

TraceNode 表达一个稳定的业务处理或决策边界。

- `node_id` 在图内唯一；
- `responsibility` 说明该节点进行的业务转换或决策；
- `input_data_ids` 引用图内由某个节点唯一输出的 TraceData；
- `outputs` 定义该节点新产生的 TraceData；
- `evidence_ref_ids` 引用 Manifest 中证明该节点及责任真实存在的 EvidenceRef。

入口数据由明确入口节点产生。例如 `REQUEST` 输出 `request.query`，后续节点引用该 data_id。不得写无法解析的自由字符串输入。

无效 responsibility：

```text
处理请求并执行核心逻辑。
```

有效 responsibility：

```text
根据规范化 query 和候选 conditions 选择 L1/L2/L4 分支，并输出 matched_level 与 selected_branch。
```

### 1.4.3 TraceData

TraceData 是业务链路中真实存在的阶段数据。它解决“只有节点名、不知道节点产出什么”的问题。

| 字段 | 语义 |
|---|---|
| `data_id` | 图内唯一、带阶段语义的 ID |
| `description` | 该阶段数据的业务含义 |
| `schema_ref` | 可选的真实源码类型、OpenAPI/JSON Schema 指针或文档锚点 |
| `evidence_ref_ids` | Manifest 中支持该数据真实存在的 EvidenceRef ID |
| `tool_requirement_ids` | Manifest 中能够获取或验证该数据的 ToolRequirement ID |
| `observation_gap` | 当前无法从已有业务 trace、API、实验或 Tool 取得该数据时，说明缺失边界 |

同类数据在不同阶段必须使用不同 ID：

```text
l4.raw_response
l4.converted_conditions
router.validated_conditions
endpoint.filtered_conditions
response.conditions
```

不得全部简写为 `conditions`。否则 Solidify 和 runtime Attribute 无法判断遗漏发生在模型生成、解析转换、Router 校验还是 endpoint 过滤。

`schema_ref` 没有真实依据时必须留空，不能让 AI 发明完整 schema。

`tool_requirement_ids` 只是对现有 ToolRequirement 的引用，表示该能力可以观察或验证什么；它不规定 Solidify 必须采用该工具或采用何种实现。

`observation_gap` 是 TraceData 的局部说明，不替代现有 Manifest `unresolved_reason`：

- TraceData 记录具体哪个阶段数据当前不可观察；
- ToolRequirement `implementation_gap` 记录验证能力为何尚不可执行；
- Manifest `unresolved_reason` 汇总这些缺口对整个调查包和后续结论范围的影响。

### 1.4.4 TraceEdge

TraceEdge 表达数据如何从一个节点进入另一个节点。

- `source_node_id`、`target_node_id` 必须引用当前图中的节点；
- `transferred_data_ids` 必须引用 source 已产生或接收、且 target 声明为输入的数据；
- `condition` 只在存在条件分支时填写真实业务条件；
- `evidence_ref_ids` 引用证明该转移或条件存在的 EvidenceRef。

示例：

```python
TraceEdge(
    source_node_id="router",
    target_node_id="l4_parser",
    transferred_data_ids=["request.normalized_query", "router.candidate_conditions"],
    condition="no confirmed deterministic condition and L4 fallback enabled",
    evidence_ref_ids=["router-pipeline"],
)
```

业务流程可以有回路，不强制为 DAG；但回边必须有真实条件与来源，不能因绘图方便制造循环。

## 1.5 与既有 EvidenceRef、ToolRequirement 的关系

TraceGraph 只保存 ID，不复制原始源码、trace payload、Tool 描述或实现：

```text
InvestigationManifest
├── evidence_refs[]
├── tool_requirements[]
└── artifacts[]
      ├── <flow>.mmd
      ├── <flow>.md
      └── <flow>.trace.json

TraceGraph artifact
├── node.evidence_ref_ids ───────────→ Manifest.evidence_refs
├── data.evidence_ref_ids ───────────→ Manifest.evidence_refs
├── data.tool_requirement_ids ───────→ Manifest.tool_requirements
└── edge.evidence_ref_ids ───────────→ Manifest.evidence_refs
```

职责保持不变：

- EvidenceRef 指向真实源码、函数、API、文档、业务 trace、replay 或实验；
- ToolRequirement 描述已有或待实现的验证能力；
- TraceGraph 把这些现有材料组织到具体业务节点和阶段数据上；
- ContextUnit 继续承载 Solidify 后可供 runtime Role 发现和加载的静态项目知识。

EvidenceRef summary 只是材料的使用理由。引用了某段源码，只能证明机制定义存在；除非另有当前业务 trace、API、replay 或 probe，它不能证明该机制在当前 case 中执行并产生了某个值。

对于必要但尚不可执行的验证能力，继续使用现有：

```python
ToolRequirement(
    implementation=None,
    implementation_gap="deployed API and current business trace do not expose this value",
)
```

TraceData 可以引用该 tool_id 并填写 observation_gap。这是在既有 ToolRequirement 上增加可定位性，不增加新的 Tool 协议。

## 1.6 Mermaid 与 Markdown 的既有要求保持不变

### Mermaid

继续遵循现有 Attribute ROLE.md：Mermaid 保存已确认业务执行链，必须展开 objective 所需的实际分支、匹配、捕获、转换和后处理节点。

本协议额外要求：

- 节点 ID 与 TraceGraph node_id 一致；
- 边标签至少能识别主要 transferred_data_ids；
- condition 分支使用与 TraceEdge 一致的业务语义；
- 不得仅画 `INPUT → ROUTE → CORE → OUTPUT` 通用模板。

### Markdown

继续保留现有三个章节，不删除、不改名：

- `How to use this trace map`；
- `Operational index`；
- `Investigation procedure`。

Operational index 继续承担 runtime Attribute 的可读导航作用。为使其与 TraceGraph 对齐，每个关键节点至少展示：

| Node | Enter when / trace signal | Input data IDs | Output data IDs | Observe or verify | What it can support | Boundary / next step |
|---|---|---|---|---|---|---|

Markdown 可以写比 JSON 更丰富的调查解释，但涉及节点、阶段数据、EvidenceRef 或 ToolRequirement 时必须使用已登记 ID。无法证实的内容明确写 provisional 或 unresolved，不得用自然语言绕过 sidecar 的引用校验。

## 1.7 生成与调查准则

本协议不规定 Codex、Claude Code 的调查实现过程或文件生成顺序，只约束最终 artifact：

1. 先确定真实业务范围，再保留关键处理节点；
2. 每个节点说明输入、输出和业务责任；
3. 每个关键节点、数据和边都能回到现有 EvidenceRef；
4. 每个 Tool 引用都能回到现有 ToolRequirement；
5. 数据粒度足以区分会导向不同修复的主要业务阶段；
6. 当前不可观察的数据明确标出 observation_gap；
7. 不在图中预写 root cause、修复方案或冻结 case 答案；
8. 不把 verifier 自身 trace 当作业务系统 trace；
9. 源码版本、部署版本或 API 环境不一致时保持 unresolved；
10. 图可以不完整，但不能用无依据节点伪装完整。

## 1.8 沿用现有 Solidify 消费流程

不增加 TraceGraph 专属 Solidify loader、固定输入字段或 handoff schema。

Solidify 继续执行 `spec/alg/investigate.md` 已定义的流程：

```text
读取 InvestigationManifest
  → 按 artifacts 读取当前 Role 调查文件
  → 按 ROLE.md 审核调查是否足以支持 objective
  → 决定哪些资料注册为 ContextUnit
  → 按 ToolRequirement 复用、包装或新建 VerifiableTool
  → 实现候选 draft/<role>.py
```

对于 Attribute trace artifact，Solidify 应将同名 `.mmd + .md + .trace.json` 作为一组调查材料阅读，但调查包不规定其具体实现选择。

Solidify 可以：

- 将 `.md/.mmd` 按现有 context builder 注册为 Attribute 可见 ContextUnit；
- 把 `.trace.json` 作为设计时结构索引、受控资源或 `content_ref`；
- 根据已有 ToolRequirement 复用、包装或新建 Tool；
- 只固化与 objective 有关的稳定知识，而不让每个 runtime case 展开整个调查包。

Solidify 也可以选择其他符合现有协议的实现，只要候选确实使用固化后的 Context/Tool，而不是把离线调查结论复制进 prompt。

若 TraceGraph 暴露关键 observation gap，Solidify 按现有流程判断：返回 Investigate、实现对应 ToolRequirement，或让候选在该范围输出 unresolved。这个判断不写回调查包成为施工指令。

## 1.9 沿用现有 Draft Loop 与 Attribute Review

不增加 Trace 专属 Loop、comparator、顶层结果或公共门禁 schema。

Draft Loop 继续运行冻结 Current/Draft、采集原始结果，并按照 Attribute ROLE.md 的既有 review 标准判断候选是否更准确且无退化。TraceGraph 只让现有审核能够更具体地检查：

- finding 是否连接到正确业务节点和阶段数据；
- EvidenceRef 是否真的支持对应节点、数据或边；
- 当前事实是否区分了模型生成、转换、校验、过滤等竞争位置；
- observation gap 尚未补齐时，候选是否错误地产生确定根因；
- L2 的工具和链路是否被错误套到 L4 或其他项目路径；
- 候选使用的 ContextUnit/Tool 是否来自现有 Solidify 产物，而非 prompt 中的硬编码结论。

审核继续使用现有 RoleResult、Context Load、Tool Call、EvidenceRef、Finalization、Reviewer 和 DraftReport，不新增 TraceUsageResult。

## 1.10 Artifact validator

公共 Investigation validator 仍从 Manifest `artifacts` 遍历文件。发现 `*.trace.json` 时，调用可选 Trace artifact codec 执行增量校验；不修改 Manifest 解析规则。

结构校验包括：

- `.trace.json` 位于当前调查包内并已登记为 artifact；
- 同 basename 的 `.mmd`、`.md` 都存在并已登记；
- graph_id、node_id、data_id 唯一；
- input_data_ids 能解析到图内 TraceData；
- 每个 TraceData 只由一个节点定义为 output；
- edge 的 source、target、transferred_data_ids 均存在；
- edge 传递的数据由 source 产生或接收，且被 target 声明为 input；
- node/data/edge 的 evidence_ref_ids 存在于 Manifest；
- TraceData 的 tool_requirement_ids 存在于 Manifest；
- Mermaid 节点和边、Markdown Operational index 与 JSON 不发生结构冲突；
- 继续执行现有 EvidenceRef revision/hash、Tool import/schema/smoke 和路径边界检查。

结构 validator 不证明：

- 节点是否是当前 objective 的关键边界；
- EvidenceRef 是否具有足够说服力；
- Tool 是否真的观察到它声称的数据；
- observation gap 是否完整；
- 候选是否真正改善归因。

这些仍由 Harness AI 按 Attribute ROLE.md 审核。结构通过只能证明 artifact 可读且引用完整，不能被解释为调查充分。

## 1.11 client_search L4 示例

```python
TraceNode(
    node_id="l4_parser",
    responsibility="调用 L4 模型，解析原始响应并转换为业务 conditions",
    input_data_ids=["request.normalized_query", "l4.prompt_context"],
    outputs=[
        TraceData(
            data_id="l4.raw_response",
            description="本次 L4 模型返回的原始文本",
            evidence_ref_ids=["l4-parser-source"],
            tool_requirement_ids=[],
            observation_gap="当前部署 API、业务 trace 和已有 Tool 均不返回该值",
        ),
        TraceData(
            data_id="l4.converted_conditions",
            description="L4 原始响应经 JSON 解析和字段转换后得到的 conditions",
            schema_ref="",
            evidence_ref_ids=["l4-parser-source"],
            tool_requirement_ids=["client_search.l4_route_replay"],
            observation_gap="该 ToolRequirement 尚未实现，具体 case 仍不可观察",
        ),
    ],
    evidence_ref_ids=["l4-parser-source"],
)
```

该 sidecar 让 Solidify 和 runtime Attribute 知道 L4 至少存在 raw response、converted conditions、validated conditions 和最终 response conditions 等不同观察边界。

在 `l4.raw_response` 和 `l4.converted_conditions` 可观察前，Attribute 可以证明最终响应缺少条件、请求进入 L4 边界以及源码定义了 L4 转换机制；不能据此确定遗漏发生在模型生成、JSON 解析、condition 转换、Router 校验或 endpoint 过滤中的哪一步。

---

# 第二章：Changes——现状差异与一次性改造任务

## 2.1 现状差异

| 现状 | 问题 | 增量改造 |
|---|---|---|
| InvestigationManifest 已用 artifacts 索引所有扩展文件 | 不应为 Trace 新增专属 Manifest 字段 | 保持 Manifest 不变，将 `.trace.json` 登记为普通 artifact |
| Attribute 已要求 `.mmd + .md` | 节点输入输出和 ID 引用主要靠自然语言 | 保留现有两类文件，增加同名结构化 sidecar |
| Operational index 已承担使用导航 | 删除或替代会破坏既有 ROLE 契约 | 保留原章节，并补充 input/output data IDs |
| validator 已遍历 artifacts 并检查 Mermaid/Markdown | 无法校验阶段数据和 Tool/EvidenceRef ID | 在现有 artifact 分支中识别并校验 `.trace.json` |
| Solidify 已消费 Manifest、artifacts、Context 和 Tool | 不需要 Trace 专属 loader 或 handoff | 将三件套作为现有 artifact 读取和固化 |
| Draft Loop 已按 Attribute ROLE.md 审核证据和归因 | 不应增加公共 Trace comparator/schema | 把 TraceData 相关判断补入 Attribute review 准则 |
| client_search 图包含较细 L2、较粗 L4 | L4 缺少中间输出边界，导致无依据定性模型错误 | 增量调查 L4、校验和后处理数据，不重写 Investigate 架构 |

## 2.2 Task 1：实现可选 Trace artifact codec

新增一个只负责 `.trace.json` 文件的 codec，例如：

```text
impl/core/schema/investigation_trace.py
```

其中实现：

- TraceGraph、TraceNode、TraceData、TraceEdge dataclass；
- JSON load/dump；
- artifact 内部引用校验。

该模块不修改 InvestigationManifest，不引入新的 stage/result，不参与 AI 调查或 Solidify 决策。

## 2.3 Task 2：扩展现有 artifact validator

在 `impl/core/investigation.py` 遍历 `manifest.artifacts` 的既有逻辑中：

- 对 `*.trace.json` 调用 Trace artifact codec；
- 从当前 Manifest 构造 EvidenceRef/ToolRequirement ID 集合供引用校验；
- 检查同名 `.mmd/.md` 和 JSON 一致性；
- 保留原有 Mermaid 节点覆盖、三个 Markdown 章节、EvidenceRef、Tool smoke 和 source revision 门禁；
- 错误信息定位到 graph/node/data/edge 和具体字段。

不得增加 trace_graph_paths，不得要求公共 loader 扫描未登记文件。

## 2.4 Task 3：增量更新 Draft Attribute 契约和模板

只更新 Trace 相关内容：

- `.agents/skills/draft/attribute/ROLE.md`；
- `.agents/skills/draft/reference/investigation/docs/traces/`；
- `.agents/skills/draft/scripts/validate_investigation.py` 的说明或示例。

保留原有 Mermaid、How to use、Operational index 和 Investigation procedure。新增要求为：

- 同名 `.trace.json`；
- 节点输入/输出 data IDs；
- node/data/edge 的 EvidenceRef 引用；
- TraceData 的 ToolRequirement 引用和 observation gap；
- 禁止从通用组件模板填词；
- 禁止在调查 artifact 中写 Solidify 施工步骤或预设根因。

不修改其他 Role 的 artifact 要求。

## 2.5 Task 4：保持 Solidify 原流程并验证实际读取

不增加 Solidify loader 或结果 schema。更新 Draft Skill 的 Solidify 指引，使 Harness AI 在读取当前 Attribute 的 `artifacts` 时把同名三件套作为一组核对。

Solidify 仍按现有机制：

- 选择需要注册的 ContextUnit；
- 处理 ToolRequirement；
- 实现项目候选 Role 和 Tool；
- 通过 role_assets 声明候选/正式资产；
- 用真实 project loader 验证 Context、Tool 和 Role。

若实现发现 trace artifact 错误或缺少关键业务边界，返回 Investigate 更新现有 artifact；不得创建另一套 Trace 配置或隐藏映射。

## 2.6 Task 5：在 Attribute ROLE review 中检查效果

不修改公共 Draft Loop schema。只在 Attribute review 准则中明确：

- 确定 finding 必须落到有真实 case 证据支持的业务节点/阶段数据；
- 静态 EvidenceRef 不能替代运行事实；
- observation gap 未补齐时必须 unresolved 或收缩结论；
- ToolResult 若声称观察某 TraceData，其 actual/metadata 必须包含对应阶段输出；
- Current/Draft 对比要检查是否减少无依据结论，而不只是输出更长；
- 未覆盖路径不得套用已覆盖路径的结论。

继续使用现有 Context/Tool/Evidence/Finalization/Reviewer 和 DraftReport 记录，不新增 Trace 使用结果。

## 2.7 Task 6：重新调查 client_search Attribute trace

基于现有 `client-search-parse.mmd/.md` 增量补齐 `.trace.json`，不机械转换现有文字：

- 保留已调查的 Request、Endpoint、Router、L1/L2、L4、Validate、Format、Response 边界；
- 明确 L2 pattern、capture、condition 输出；
- 明确 L4 prompt context、raw response、converted conditions；
- 明确 Router validated conditions；
- 明确 endpoint filtered/date-converted/final response conditions；
- 每个关键节点、数据和 edge 绑定现有 Manifest EvidenceRef；
- 必要的观察能力引用现有或新增 ToolRequirement；
- 没有真实 API/trace/probe 的中间数据保留 observation gap；
- 同步更新 Mermaid 边标签和 Operational index 的 input/output IDs；
- 不在调查 artifact 中预定如何实现 `draft/attribute.py`。

在补齐关键 L4 观察前，旧结论“L4 模型未生成字段”只能作为未区分解释，不能作为已证明 baseline。

## 2.8 Task 7：测试与验收

### Artifact 单元测试

- TraceGraph JSON round-trip；
- node/data/edge 重复 ID；
- input、edge、EvidenceRef、ToolRequirement 悬空引用；
- edge 传递 source 未产生/接收或 target 未消费的数据；
- sidecar 未登记到 artifacts；
- 同名 `.mmd/.md` 缺失或结构冲突；
- 路径逃逸、source revision/hash 和现有 Tool smoke 回归。

### Skill 流程测试

- Investigate 仍只输出现有 Manifest + artifacts；
- 空泛组件图不能通过 Attribute Harness review；
- Solidify 仍走现有 artifacts/Context/Tool 流程；
- 调查包不包含 Solidify handoff 或 root cause；
- observation gap 未补齐时 Draft 不得产出伪确定结论；
- 其他 Role 不受 `.trace.json` 要求影响。

### client_search 实测

至少比较：

- 一个 L2 not_fulfilled case；
- 一个正常 fulfilled 对照；
- 一个 L4 not_fulfilled case；
- 一个因缺少中间观察必须 unresolved 的 case。

保留 Current/Draft 输入输出、业务 trace、Context/Tool audit、EvidenceRef/Finalization 和 Reviewer 结果。验收重点是能否准确区分业务阶段，以及证据不足时是否停止，而不是 TraceGraph 或 finding 的数量。

## 2.9 一次性清理

- 从本 spec 删除 `trace_graph_paths` 及所有 Manifest 修改要求；
- 保留并增强现有 Operational index，不删除原消费契约；
- 不新增 Trace 专属 Solidify loader、Draft Loop 或结果 schema；
- 修正 client_search 调查材料和报告中把 L4 静态机制写成当前 case 已证实原因的内容；
- 检查其他 Attribute 调查包时只迁移真实存在、确有业务价值的 trace，不批量生成空 sidecar；
- 不修改 `spec/alg/investigate.md`；
- 不修改 Mock、Judge、Attribute 的公开结果 schema、Production/Draft 开关或 Promote 协议。

## 2.10 完成标准

本增量改造完成必须同时满足：

1. InvestigationManifest 与现有主流程保持不变；
2. `.trace.json` 仅作为 `artifacts` 中的 Attribute trace sidecar；
3. 原有 `.mmd/.md` 和三个 operational 章节继续有效；
4. 每个关键节点明确输入、输出和来源；
5. 同类数据在不同阶段使用不同 data_id；
6. EvidenceRef、ToolRequirement、unresolved_reason 和 ContextUnit 继续承担原有职责；
7. Solidify 沿用现有 artifact/Context/Tool 流程且不受调查包施工指令约束；
8. Draft Loop 沿用现有协议，只增强 Attribute 语义审核；
9. client_search L4 不再仅凭 prompt/source 推断模型漏生成条件；
10. 未引入平行阶段、Role 专属 Manifest、公共结果 schema 或新的配置真相源。
