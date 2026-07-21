# Attribute 归因协议与最小改造方案

本文定义 Attribute 的长期协议和从当前实现迁移到高质量 baseline 的一次性任务。目标是在不重构 Mock、Judge、Attribute 共用协议体系的前提下，让 evals 接入新项目时自动形成一个证据驱动、会主动调查、能够诚实降级的归因 baseline，并为后续 draft 优化保留空间。

本文只有两章：第一章是长期协议；第二章是当前差异和一次性改造任务。

## 第一章：Spec 标准——长期 Attribute 协议

### 1.1 目标与成功标准

Attribute 是 Judge 发现 business gap 后、实施修复前的最后一个诊断环节。它的目标不是生成听起来合理的原因，而是使用当前可达环境中的真实证据，将问题尽量定位到开发者能够采取行动的位置。

baseline 采用以下成功标准：

- Judge 已 fulfilled 时不制造失败根因；
- 只有现象证据时，只陈述现象和当前可观察位置；
- 项目环境已有能够区分原因的源码、配置、ContextUnit、runtime check 或 Tool 时，Attribute 必须主动使用，不能直接停在 Judge 结论；
- 环境确实不可达时，明确说明当前最多证明到哪里、还缺什么，不能伪造业务内部原因；
- 归因结果必须能解释为什么推荐修改某个业务位置，而不是只列出一组候选原因；
- 一个未参与调查的开发者能够根据结论继续修复或明确补齐哪类诊断能力。

Attribute 不承诺在信息不可得时找到真实根因。协议保证的是：可验证时继续验证，不可验证时不把推测包装成结论。

### 1.2 兼容性边界

baseline 保持当前三层协议和 evals 动态发现机制：

- `pipeline.attribute(project_id, trace, judge_result)` 仍是公共入口；
- `ProjectAttribute` 仍是项目层基类；
- `build_context(trace, judge_result)` 仍是唯一必须实现的 Attribute 扩展点；
- `probes()` 和 `normalize_result()` 继续作为可选扩展点；
- 最终仍返回现有 `AttributeResult`；
- scaffold 和协议合规检查仍从 `@abstractmethod` 动态发现项目必须实现项；
- 不要求 Mock、Judge、Check、Cluster、API 或前端理解新的 Attribute 领域对象。

baseline 不新增 `Investigator`、`InvestigationRuntime`、通用因果图、Claim 网络、Spec Store 或新的公共成熟度状态。

需要做的协议层修改仅限：在现有模板方法内部增加能力装配、调查迭代和独立 Review，不改变公共入口、抽象方法和返回类型。

### 1.3 公共数据流

公共 schema 流转保持不变：

```text
RunTrace + JudgeResult
  → ProjectAttribute.build_context()
  → probes/runtime_checks
  → 公共层装配 ContextUnit Tools、公共技术 Tools、项目 Tools
  → Attribute 主执行产生 AttributeLLMOutput
  → normalize 为 AttributeResult
  → 独立 Reviewer 审查
  → 必要时再执行一轮 Attribute 主执行
  → validate + normalize
  → 最终 AttributeResult
```

Reviewer 的输出只在协议内部流转：

```text
passed: bool
issues:
  - reviewed_claim: 被审查的归因结论
    problem: 该结论存在的具体证据或推导问题
    evidence: Reviewer 自己核查得到的原始引用
```

它不是项目 schema，不进入 `AttributeResult`，不要求前端消费。Review Run、Tool Call 和 issue 可以作为审计记录保存到现有 Agno/Context Store。

### 1.4 Attribute 可使用的调查环境

ContextUnit 和项目 Tool 是调查加速器，不是 Attribute 的信息边界。Attribute 主执行和 Reviewer 都拥有以下三层环境。

#### 当前 case 输入

- 当前 `RunTrace`、`JudgeResult`、actual、expected/reference；
- verifier 可观察的 execution trace 和原始 EvidenceRef；
- 当前轮已经发生的 Agno Tool Call 和原始 Tool Result。

Verifier `RunTrace` 只能证明 verifier 发出、接收和转换了什么。除非业务系统显式暴露内部日志、trace 或状态，不得把它解释为业务内部 trace。

#### 项目扩展能力

- 项目通过 `project.yaml` 和 `context_adapter.py` 注册的业务 ContextUnit；
- 项目 `build_context()` 提供的 runtime check、边界说明和少量当前 case 信息；
- 项目 `VerifiableTool`，例如业务重放、字段能力查询、日志/状态读取和项目模拟器；
- 已有 adapter comparison、semantic equivalence、canonical rule 和验证入口。

项目已有 canonical 判断标准时，Attribute 和 draft 必须复用，不得另造冲突 comparator。

#### 公共技术探索能力

协议层自动提供，不要求每个项目提前把所有调查路径制作成 Tool：

- 从 `ProjectSpec`/`project.yaml` 声明的业务源码根目录读取和搜索文件；
- 搜索、读取和检查代码、配置、schema、prompt、路由、依赖和业务文档；
- 受控 Shell、临时脚本和沙箱局部模拟；
- JSON/YAML/日志/diff 等无业务语义的结构检查；
- Context Store、Agno Run 和原始 Tool Result 查询；
- 项目明确允许时的只读 HTTP/API 查询。

公共技术工具允许模型发现项目没有预先登记的新调查路径。例如 Reviewer 可以从 stage 名称反向搜索源码、读取真实 label mapping，并用临时脚本复现分类函数。

所有公共能力仍受工作区、网络、生产权限、副作用、预算和超时约束。“不受预定义 ContextUnit/Tool 限制”不表示可以绕过授权；外部业务环境不可达时必须承认边界。

### 1.5 ContextUnit 的职责

ContextUnit 负责按需发现和加载已经存在、来源可核查的业务系统信息，重点包括：

- 业务源码、配置、接口契约和数据模型；
- 字段、单位、枚举、规则、异常和降级语义；
- 项目业务边界与系统责任说明；
- 项目日志、内部 trace、会话或状态的可加载引用；
- 重放器、模拟器和诊断入口的说明；
- 后续主执行需要重新加载的 Reviewer Tool Result。

不得把未验证根因、模型总结、Context Search query、相似度候选或其他 case 结论注册成权威业务知识。

`JudgeResult` 和 verifier `RunTrace` 是当前 case 的直接输入，不是业务知识库主体。只有某个原始片段需要跨 Review Run 重新加载时，才使用 trace/case 隔离的 `content_ref`。

Context Search 只用于发现，候选描述不是证据；只有 Load 后的权威内容才能支持结论。Reviewer 新发现的文件、配置或 Tool Result 可以直接作为 EvidenceRef，只有下一轮需要重新发现时才注册动态 ContextUnit。

### 1.6 Tool 的职责与接入

公共技术 Tool 处理通用探索；项目 Tool 处理只有业务项目知道如何连接或解释的动作。

项目 `build_context()` 可以继续使用当前键：

```python
{
    "tools": [...],
    "tool_call_limit": 4,
    "runtime_checks": {...},
    "user_prompt_extras": {...},
    "targets_override": [...],
}
```

baseline 应尽量避免项目覆盖完整 system prompt。项目差异优先放在业务 ContextUnit、runtime check 和真实 Tool 中，`user_prompt_extras` 只保留当前 case 边界或无法放入权威资料的少量说明。

公共层负责：

- 将 `GuardedContextTools.search_context_units/load_context_units` 注入现有 Agno Attribute Run；
- 将 `VerifiableTool` 通过 `build_agno_tools()` 统一桥接；
- 对缺失 execute function、非法 schema 和不支持对象 fail-fast，不得静默忽略；
- 保存每次 Tool Call 的名称、选择理由、入参、实际输出、错误、耗时和原始结果引用；
- 将工具失败解释为调查能力受限，而不是业务根因。

项目不需要为每个源码文件或配置分别制作 Tool。只有操作需要业务连接方式、鉴权、参数语义或专用解释时才补项目 Tool。

### 1.7 Attribute 主执行的默认调查节奏

协议不固定因果图、DFS 数据结构或项目业务链。默认主执行遵循一个有界、深度优先的调查节奏：

```text
1. 检查 Judge 是否提供可用 business gap、expected 和 actual
2. 找到当前证据能够证明的首个实际偏差，不把 Judge 文本当根因
3. 提出当前最可能改变修复位置的解释
4. 说明该解释与最强竞争解释之间缺少什么区分证据
5. 优先 Search/Load 业务 ContextUnit；需要新事实时调用公共或项目 Tool
6. 新证据只能强化、推翻、增加必要分支，或证明当前仍无法区分
7. 深入到证据能够支持的可修复位置；无法深入时停止在可观察边界
8. 输出最小 AttributeResult，不通过罗列候选原因伪装调查深度
```

默认偏向一条领先路径。只有另一个原因或介入位置可能改变修复方案时才展开分支；不影响修复决策的周边异常不进入主结论。

因果分析是默认可用手段，不是公共 schema 或唯一允许的方法。项目或 draft 可以使用状态机、数据溯源、协议违例、统计诊断、形式化验证或其他方法，只要结论仍由真实证据支持。

### 1.8 独立 Reviewer loop

Reviewer 是 Attribute 协议内部的独立执行，不是新的项目角色。项目不实现 Reviewer adapter，也不新增 `_load_reviewer`。

Reviewer 与 Attribute 主执行：

- 拥有相同的源码、文件、ContextUnit、公共技术 Tools 和项目 Tools；
- 受到相同权限、副作用和环境边界约束；
- 使用不同的 Agno Run 和对话上下文；
- Reviewer 不继承主执行的完整历史和自我解释；
- Reviewer 可以自行搜索新技术位置、加载 ContextUnit、调用 Tool、重放或模拟，以证据证明审查问题；
- Reviewer 不受项目预先枚举的 ContextUnit 和 Tool 限制，可以使用公共技术探索能力继续调查。

Reviewer 只指出有证据的问题，不输出下一步行动、调查计划或证据强度上限。典型问题包括：

- 引用不存在、不可加载或只是模型总结；
- 证据只证明现象，却支持了业务内部位置或机制；
- 当前结论无法区分会导致不同修复的竞争解释；
- 存在反证，或独立复现结果与主结论矛盾；
- 环境已有相关证据能力，但当前结论在未验证时写成确定根因；
- 将 verifier trace、stage 名称或 Judge 推理当成业务内部证据；
- 归因位置超出当前系统责任或可观察边界；
- conclusion 超出 expected/actual、ContextUnit 原始材料和实际验证能够证明的范围。

Issue 可以指出“当前结论尚未核对某个可达 ContextUnit、Tool 观测或技术位置，因此关键判断没有成立”，但不规定主执行下一步必须调用哪个函数或采用什么调查顺序。Reviewer 若已自行执行核对，应直接引用其 Tool Result；若尚不能执行，只能把缺少该验证本身作为问题，不能把预期结果写成证据。Attribute 主执行收到 issues 后自行决定如何补证、反驳 Reviewer 或收缩结论。

默认 loop：

```text
build_context + probes（一次）
→ Attribute 主执行第 1 轮
→ Finalization 自审 + 确定性物化 EvidenceRef + normalize
→ 独立 Review 第 1 轮
   ├─ passed：返回
   └─ issues：把 issues 和原始证据引用交回主执行
→ Attribute 主执行第 2 轮，自行决定如何补 Context/Tool/实验或收缩结论
→ Finalization 自审 + 确定性物化 EvidenceRef + normalize
→ 独立 Review 第 2 轮
   ├─ passed：返回
   └─ issues：公共层删除未通过的 findings，并以一个 unresolved_reason 说明审查阻塞
```

默认最多两次主执行、两次 Review。Reviewer 每个 issue 只包含 target 和 problem；可以主动核查，但不在输出中产生 evidence。纯措辞、格式或“可能还可以更好”不得触发重跑。

项目 `normalize_result()` 只能排序、去重、删除或收缩结果，不得新增 finding、conclusion 或 EvidenceRef。公共层必须在项目后处理后再次执行确定性校验。

### 1.9 证据结果边界

公共结果不再暴露 `evidence_strength`、hypothesis 或单独 locations。最终只有 Reviewer 通过的 `AttributionFinding`，每个 finding 直接内嵌由 Finalization ContextUnit 物化的 EvidenceRef；无法证明的内容不降级为弱结论，而是删除 finding 并写入一个整体 `unresolved_reason`。

完整 schema、Finalization 门禁、summary 派生和迁移任务以 `spec/alg/attribution-schema.md` 为唯一真相源。Tool 被调用或材料被注册不自动成为 evidence；只有主 Attribute 在 Investigation 已加载、Finalization 重新加载并给出引用理由的 ContextUnit 才能物化 EvidenceRef。

### 1.10 evals 自动构建 baseline

evals 继续按现有顺序动态发现并填充项目角色，不修改“只补项目层”的原则。Attribute baseline 接在 tools 和 judge 完成之后：

```text
project.yaml 与业务资料
→ scaffold（动态发现现有协议抽象方法）
→ live_schema / live / mock
→ tools：盘点已有业务诊断能力
→ judge：冻结 expected、actual、business gap 和责任边界
→ context：注册业务源码、配置、契约和边界资料
→ attribute：生成最小 build_context，引用 ContextUnit/runtime checks/Tools
→ representative trace baseline 验证
→ mock-check / run-chain / protocol compliance / regression
```

evals 构建 Attribute 时必须：

- 从 `project.yaml`、source repo、documents、live、judge 和 tools 识别可达证据源；
- 优先复用已有 adapter comparison、runtime check 和 Tool；
- 为源码/配置/业务资料建立 Context Adapter 或 `content_ref`，而不是复制进 Prompt；
- 自动注入公共技术探索 Tools；
- 只有外部系统需要业务连接方式时才生成薄项目 Tool；
- 生成通用 `build_context()`，不把当前样例值、case id 或历史错误组合写入代码；
- 使用至少一个 fulfilled、一个可验证失败、一个证据不足或 not_evaluable case 验证强度和边界；
- 当环境存在可区分原因的能力时，验证 Agno/Context Store 中确有相应 Search/Load 或 Tool Call；
- baseline 只需达到本章标准，进一步项目算法优化进入 draft。

### 1.11 draft 扩展边界

baseline 的 Review loop、ContextUnit 和 Tool 审计是公共质量外壳；具体 Attribute 主执行实现必须可替换，避免协议阻碍后续优化。

v1 默认使用公共 Attribute 主执行。协议允许增加一个**非抽象、默认返回公共实现**的主执行选择 hook，供显式启用的 `attribute_draft` 使用。新增 hook 不进入 scaffold 必填项，不要求存量项目修改，也不能绕过最终 validate 和 Reviewer loop。

draft 可以：

- 使用项目专用 prompt、搜索策略、更多轮内部分析或多 agent；
- 增加项目 Tool、模拟器和 ContextUnit；
- 生成额外的 Attribution Change Spec，包括 Diagnosis、Target Protocol 和 Changes；
- 在冻结 trace/mock 数据上与 baseline 比较并迭代。

draft 不得：

- 自动修改 production Attribute 或公共协议；
- 修改冻结评测数据来制造提升；
- 绕过公共 Reviewer、证据强度校验和 case 隔离；
- 将 case 专属值、字段组合或结论硬编码进 production。

完整 Attribution Change Spec 是可选增强产物，不作为所有项目 baseline 接入的公共返回协议。未来若需要进入 API/前端，应以附加 artifact 引用扩展，而不是改写现有 `AttributeResult` 语义。

## 第二章：Changes——现状差异与一次性改造任务

### 2.1 当前实现与实际问题

当前 `_AttributeProtocol.attribute_failure()` 固定执行：

```text
build_context
→ run_probes
→ 单次通用 LLM
→ validate
→ normalize_result
```

这个模板和返回协议可以保留，主要问题在运行效果：

- 本地 Context Store 曾检查到 142 条 Attribute LLM 记录，其中 10 条失败；
- 其余 132 条有效记录没有实际 tool message 或 assistant tool call；
- 很多结果在只有 Judge/静态上下文时仍自报 strong/high/moderate；
- client_search 有效调用平均约 30k input tokens，marketting-planning 平均约 21k，主要依赖预塞上下文；
- 当前 ContextUnit 已有 Registry、Policy、Search、Load、Adapter 和 Guarded Tools，但尚未接入 Attribute 主链；
- `build_agno_tools()` 对缺失 execute function 的 `VerifiableTool` 会跳过，项目传错工具时可能无声失效；
- 项目 `build_context()` 大量使用 system prompt override、预执行 probe 和项目特例，evals 无法自动形成统一高质量 baseline；
- 当前没有独立 Reviewer，模型可以把“首个可见偏差”直接写成“业务根因”。

### 2.2 代表 trace 的 baseline 目标

| Trace | 当前问题 | baseline 应达到的结论 |
|---|---|---|
| QA provided-output 回答遗漏 | 能证明答案缺内容，却把生成机制写成 strong 根因 | 定位到 provided output 内容缺陷；因生成系统不在边界内，不猜 prompt/模型/检索原因 |
| client_search 城市字段 | 从 field definitions 无城市字段推导 ES 根本无城市数据 | 读取配置后继续查询 ES mapping/样本；无查询能力时保留“配置未暴露或数据源无能力”的未决分支 |
| marketting-planning stage=unknown | Trace 证明 intent 输出异常，却并列猜 prompt、模型配置、normalization | 用源码搜索、配置核对和局部重放区分；不能区分时只定位到 intent 可观察边界 |
| deerflow 已交付规划但 stage=clarification | 容易把 stage、提取、工具调用和业务交付混成一个根因 | 复用 raw/extracted integrity、`stage_inference` 和业务边界，区分标签问题、真实流程问题与 Judge 形式要求 |
| intent actual=other 但 expected/internal evidence 缺失 | 仍输出 intent_contract_gate 内部原因 | evidence none/weak，说明缺 reference/internal evidence，不产生正式业务根因 |
| Judge/Attribute LLM 结构化失败 | 评测基础设施失败被写成业务根因 | 只报告评测/调查被阻断，不归因原业务系统 |

这些 trace 必须固化为 baseline 验收起点。验收关注“最多证明到哪里”和“有没有真实调查动作”，不比较文案长短。

### 2.3 一次性改造任务

#### Task 1：冻结 trace baseline

- 从上述类型选择稳定的 RunTrace/JudgeResult/AttributeResult fixture；
- 为每个 fixture 标注 expected、actual、当前最大可证明位置、可用证据源和禁止过度推断；
- 标注环境中已存在的 ContextUnit、公共技术能力和项目 Tool；
- 定义 expected evidence strength；
- 保存 current 输出和 Context Store Tool Call 基线。

#### Task 2：修通 Tool 装配

- 在公共 Attribute 能力装配处识别 Agno Tool 和 `VerifiableTool`；
- 统一通过 `build_agno_tools()` 桥接项目 Tool；
- 将缺失 execute function 从静默跳过改为 fail-fast；
- 修复 client_search 直接传原始 `VerifiableTool` 后未实际调用的问题；
- 保存完整 Tool Call 审计；
- 增加“环境存在相关 Tool、强内部定位却零 Tool Call”的回归门禁。

#### Task 3：接入 ContextUnit 和公共技术 Tools

- 在 `pipeline.attribute()` 或 Attribute 公共装配层建立/复用项目 `ContextRuntime`；
- 初始化 `project.yaml` 配置 ContextUnit 和项目 `context_adapter.py`；
- 按 trace_id/case_id 启动 Attribute ContextRun；
- 把 `GuardedContextTools` 注入现有 LLM Tool 列表；
- 根据 ProjectSpec 授权业务 source repo 的只读搜索/读取；
- 注入受控 Shell、沙箱模拟、结构化文件检查和 Context Store/Agno Result 查询；
- 首次 Prompt 只保留 case 锚点和少量 mandatory 内容，不预载完整项目资料。

#### Task 4：更新默认 Attribute 调查指令

- 将 1.7 的调查节奏写入公共 system prompt；
- 保留现有 `AttributeLLMOutput` 和 `AttributeResult`；
- 要求模型在输出内部位置前实际使用可达证据能力；
- 禁止把 Search 候选、Judge 推理、stage 名称或 verifier trace 当业务根因证据；
- 证据不足时收缩位置和强度，不通过候选列表蒙混。

#### Task 5：实现轻量独立 Reviewer loop

- 在现有 `_AttributeProtocol.attribute_failure()` 内围绕 `_run_llm_attribute → validate → normalize_result` 增加最多两轮循环；
- Reviewer 使用独立 Agno Run 和内部结构化输出；
- Reviewer 注入与主执行相同的 ContextUnit、公共技术 Tools、项目 Tools 和权限；
- Reviewer 可以自行搜索、读源码、调用工具和模拟，但初始上下文不继承主执行历史；
- Reviewer 只返回 `passed/issues`，每个 issue 必须包含 reviewed claim、problem 和原始 evidence；
- issues 交回主执行，主执行自行选择 Context/Tool/实验或收缩结论；
- 第二次 Review 仍失败时，公共层删除无证据内部位置并降级 strength；
- 最终 normalize 后再次执行确定性门禁，防止项目后处理恢复被拒绝结论。

#### Task 6：将 baseline 构建接入 evals

- 保持 Step 0-11 和动态协议发现机制；
- 在 tools 阶段盘点公共技术能力、项目 Tool、runtime check 和业务外部连接缺口；
- 在 judge 完成后注册业务源码、配置、契约和边界 ContextUnit；
- 填充 Attribute stub 时生成最小 `build_context()`，复用已有工具和 Context，而不是生成长项目 prompt；
- 使用 fulfilled、可验证失败、证据不足三类 case 跑 run-chain；
- 检查 Attribute/Reviewer Tool Call、Context Search/Load、证据强度和内部位置来源；
- baseline 未达到 1.1 时，项目接入不标记完成；算法进一步优化转入 attribute draft。

#### Task 7：逐项目迁移

- QA：明确 uploaded/provided-output 边界，将合同/上下文资料注册为 ContextUnit，禁止猜生成服务；
- client_search：接入字段/规则/源码 ContextUnit 和 search/field capability/ES boundary Tool；
- deerflow：复用 raw/extracted integrity 和 stage inference 检查，提供业务源码探索；
- marketting-planning：提供 normalization、intent mapping、session merge 和局部重放入口；
- marketting-planning-intent：复用 reference contract 与 intent gap probe，缺 expected 时强制降级；
- 删除项目对完整 Trace、全部文档和重复 Judge 摘要的默认 Prompt 拼接；
- 不要求一次迁移重写现有项目协议实现。

#### Task 8：保留 draft 替换空间

- 增加非抽象、向后兼容的主执行选择 hook，默认返回公共实现；
- draft 开关关闭时行为与 baseline 一致；
- draft 可以替换主执行算法和添加 Tool/Context，但仍经过公共 Reviewer；
- 使用冻结 fixture 比较 baseline/draft 的定位深度、证据真实性、过拟合和成本；
- 未经人工确认不得 promotion。

#### Task 9：验证与切换

- 运行 adapter compliance、protocol compliance、mock-check 和 targeted run-chain；
- 检查新旧项目无需修改抽象方法即可实例化；
- 检查 fulfilled、not_fulfilled、not_evaluable 和 LLM/tool failure 路径；
- 检查 Reviewer 与主执行上下文隔离但权限/工具等价；
- 检查零 Tool Call、伪 EvidenceRef、跨 case ContextUnit 和 normalize 后提权；
- 对代表 trace 比较 current/baseline，只有 unsupported root cause 明显下降、可达环境中的定位更深且成本可接受时才切换默认实现。

### 2.4 代码落点

| 文件/模块 | 最小修改职责 |
|---|---|
| `impl/core/pipeline.py` | 为 Attribute 装配 ContextRuntime 和公共调查能力，不改变入口/返回类型 |
| `impl/core/attribute_protocol.py` | 保留现有扩展点，在模板方法内部增加两轮主执行/Review 循环和最终门禁 |
| `impl/core/attribute.py` | 更新默认调查 prompt，装配 Tools，保留现有 AttributeResult 生成 |
| `impl/core/attribute_reviewer.py` | 新增内部 Reviewer 调用和 `passed/issues` 结构，不形成项目角色协议 |
| `impl/core/context/*` | 复用 Registry、Policy、Search、Load、Adapter 和 GuardedContextTools |
| `impl/tools/protocol.py` | VerifiableTool 到 Agno Tool 的严格桥接和 fail-fast |
| `scripts/scaffold_project.py` | 不改 Attribute 必填方法；可按项目资料生成可选 context_adapter stub |
| `.agents/skills/evals/` | 在现有接入节奏中增加 Context/Tool 盘点、baseline trace 验证和报告 |
| `impl/projects/<project>/attribute.py` | 继续实现 build_context，逐步移除巨型 prompt，暴露 runtime check 和项目 Tool |
| `impl/projects/<project>/context_adapter.py` | 注册业务系统稳定信息和可延迟读取引用 |
| `impl/projects/<project>/draft/` | 离线优化主执行、Tools 和可选 Attribution Change Spec，不自动进入 production |

### 2.5 非目标

- 不重构 Mock、Judge、Check、Cluster、API 或前端协议；
- 不修改现有 `AttributeResult` 公共字段；
- 不把 Reviewer 建成新的项目角色或 adapter；
- 不要求项目预先把所有源码、配置和调查路径 Tool 化；
- 不把 ContextUnit 建成 verifier trace/Judge 总结知识库；
- 不自动访问未授权生产系统或执行外部写操作；
- 不要求 baseline 对信息不可达 case 输出完整根因；
- 不在 baseline 强制生成 Attribution Change Spec；
- 不跨 case 合并、聚类或复用根因结论；
- 不自动实施、提交、部署或 promotion 任何业务修复。
