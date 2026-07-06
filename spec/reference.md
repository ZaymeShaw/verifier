对，这是从 mock_agent 角色边界推出的必然结论。

## 推理链

mock_agent 的角色边界是**扮演用户** → 它能合法产出的只有"用户侧的东西"：用户意图、用户与 live 系统交互时给出的 live 输入。

output 和 reference 都**不是用户侧的产物**：
- **output** 是 live 系统（被测业务）对该用户输入的真实响应 —— 这是系统侧的事实，不该由扮演用户的 agent 凭空捏造。
- **reference** 是对"这个输入下系统应当产出什么"的标准答案 —— 这是评估侧的事实，更不该由用户扮演者产出。

所以现在 mock_agent 在 ready 阶段被迫兼任 output/reference 生产者，是**角色越界**：它本来只是用户模拟器，却在 ready 模式下被当成"既当用户、又当系统、又当出题人"。

## 正确的职责划分

- **mock_agent**：只产用户侧产物（意图 / live 输入）。无论常规还是 ready 阶段，它的产出域不变。
- **output**：由**被测 live 系统本身**产出（真实调用），或由某个扮演 live 系统的轻量级模块产出（当 ready 需要预固化时）。本质是"系统侧响应"，生产者必须是系统侧角色。
- **reference**：由 **judge agent**（或某个评估侧的轻量级生成模块）按 live_schema 产出。本质是"评估侧标准答案"，生产者必须是评估侧角色。

## 与第 1、2 点的关系

这正是第 1 点（reference 改由 judge 产）和"mock 不产 output"的统一原则：**ready 阶段需要预固化的事实，按其语义归属回各自的角色域去生产，而不是全压给 mock_agent**。mock_agent 的 ready 职责应收缩到"只把用户侧输入固化好"，output/reference 的预固化分别推给系统侧和评估侧的模块。

也就是说，ready 不是一个"mock 什么都产"的开关，而是一个"各角色按各自域提前固化事实"的时序标记。



----------


好的，三点分叉都明确了。

## 分叉确认后的实现规划

### 1. output 生成策略

两层策略：
- 有 live 可调 → 调真实 live，产出就是系统真实响应
- 没 live → 按 live_schema 的 output 形状构造（类似系统扮演，但输入是 live_schema 而非 case 数据）

这样 mock_agent 彻底不碰 output，output 的生成方要么是真实系统，要么是按 schema 构造的系统扮演模块。


----------
1。无论何时，reference都要与live schema保持一样的形状，只能说output其实也要与live schema保持形状所以他们会一样，仅此而已

2。我疑惑你现在judge为什么会有两次调用？ 

3。 judge我建议还是用同一套需求模版（部分prompt的形式？），输入有没有actual/reference，
  输出有没有reference/fullfilled，大的逻辑保持一致（评估的思路），小的输入输出具体要有什么通过模版来约束，从而实现一个judge
  agent复用在不同地方产出功能相似结构略有差异的东西 3。 关于judge
  agent产出上结构可能存在的差异化，你看看是否会在judge相关schema上有所影响

 基于我们已经对齐的原则，我给一个实现规划。先说清楚结构,再落到代码改动点。

## 总体结构

把 ready 阶段从"mock_agent 全包"改成**多角色按域固化**:

```
ready 阶段触发时:
  ├─ mock_agent      → 只产 用户意图 / live 输入 (用户侧)
  ├─ live_system     → 产 output (系统侧) — 调真实 live 或系统侧模块
  └─ judge / 评估侧  → 产 reference (评估侧) — 按 live_schema 产出
```

ready 不再是"mock 什么都产"的开关,而是"各角色按各自域提前固化事实"的时序协调器。

## 落地步骤

### 第 1 步:抽出生成接口,明确归属

新增/抽象三个轻量生成入口,各自归位:

- `generate_user_input(...)` → mock_agent(用户侧,意图/live 输入)
- `generate_live_output(...)` → 系统侧模块(真实 live 调用,或系统扮演模块)
- `generate_reference(...)` → judge 评估侧(按 live_schema 产出)

mock_agent 体内只保留第一个。

### 第 2 步:改 pipeline 的 ready 分发逻辑

现在 `pipeline.py:545` 附近"reference 在 ready → mock_agent 产出,写入 case.reference"的逻辑要拆:

- ready 含 output → 走 `generate_live_output`,写入 `case.output`
- ready 含 reference → 走 `generate_reference`,写入 `case.reference` / `trace.reference_contract`
- 用户输入始终走 mock_agent

### 第 3 步:reference 生成对齐 live_schema

`generate_reference` 的契约:产出时强制按 live_schema 的 reference shape,不允许凭空形状。把 `_check_judge_reference_with_live_schema` (judge.py:443, 现在只记日志)升级为**生成时强约束**——产出即校验,不合规就重试/阻断,而不是事后 pass。

### 第 4 步:废弃 actual 对齐

`_align_reference_shape` (judge.py:474) 和 `_generated_expected` 里取 `output_shape = trace_extracted_output(trace)`(即 actual shape)的那套逻辑删除/改写。reference 形状来源从 actual 切换到 live_schema。judge 判定时直接用已固化的 schema-shaped reference,不再反向塑造 expected。

### 第 5 步:更新 ready gate 语义

`_reference_ready_from_trace` (judge.py:436) 的语义随之变化:ready 含 reference 不再只是"采信 case reference"的开关,而是"reference 已由 judge 在 ready 阶段固化"的标记。没有 ready 信号的旧 trace,行为是降级(可考虑是否保留 judge 兜底生成,或直接判 not_evaluable)。

## 需要你拍板的几个分叉

1. **output 的系统侧模块**:ready 含 output 时,是调真实 live 系统,还是也要一个"系统扮演"轻量模块(类似 mock 但扮演系统)?这取决于 ready 模式下 live 系统能不能真调。
2. **reference 生成是独立 judge 调用还是复用 judge 判定流程的副产物**:独立调用更干净(职责单一),复用更省一次 LLM 调用但耦合判定。
3. **旧 trace 降级策略**:ready 缺 reference 信号时,judge 是否保留兜底自生成,还是直接 not_evaluable。

这三个点定了,实现路径就唯一了。





-----------


逐一回应：

## 1. reference 与 live_schema 形状一致

明白了。不是"reference 刻意对齐 live_schema"，而是 **output 本身就必须符合 live_schema 的形状**，reference 作为"正确的 output 应该长什么样"的答案，自然也符合 live_schema 的形状。reference 和 actual 形状一致是 output 受 schema 约束的自然结果，不是 reference 主动去对齐 actual。我把这个前提纠正过来。

## 2. judge 为什么会有两次调用

你理解得对，现在确实不应该有两次。我之前的规划里，ready 阶段调一次 judge（只产 reference），判定阶段再调一次 judge（拿 reference 判 actual）。这在你的方案里是不需要的——**judge 始终只调用一次**，在判定阶段。区别只在于输入：

- ready 路径：judge 拿到的 `trace.reference_contract` 已经固化好了（ready 阶段由 judge 侧生成），直接用来对照 actual 做判定。
- 非 ready 路径：judge 拿到的 `trace.reference_contract` 是空的，判定时需要自己先生成 expected 再对照 actual。

所以 reference 的生成不是独立的 judge 调用，而是 **judge 判定流程内部的一个子步骤**（"先理解意图、生成 expected，再对照 actual 判定"）。ready 路径的区别只是这个子步骤的输入已经提前准备好了。

## 3. 同一套 prompt 模板，通过输入/输出约束区分

这个方向正确。judge 的核心逻辑始终是同一套：

```
理解意图 → 拆解 expected → 对照 actual → 判定 fulfillment
```

不同场景下的差异只是输入/输出约束不同：

| 场景 | 输入 | 输出 |
|------|------|------|
| 带 reference 的判定 | 有 actual + 有 reference | 完整判定（fulfillment/expected/gaps） |
| 不带 reference 的判定 | 有 actual + 无 reference | 完整判定（要先自生成 expected） |
| 仅生成 reference（如果有需要） | 无 actual + 有意图 | 只产 expected，不判 fulfillment |

**实现方式**：judge 的 system prompt 保持核心逻辑不变，差异通过 prompt 模板中的**条件块**来控制——模板根据输入参数（has_actual / has_reference）决定注入哪些段落到 prompt 和 output schema 中。不是三套 prompt，而是一套模板 + 条件渲染。

## 4. schema 上的影响

JudgeResult 的 schema 需要考虑：**并非所有字段在所有场景下都有值**。

现状 JudgeResult 的字段是"全量字段"，所有场景都塞同一个结构体。按模板化后，不同场景产出不同字段子集：

- `expected`：带 reference 时来自 reference，不带时 judge 自生成。始终有值，但来源不同。
- `fulfillment_assessments` / `overall_fulfillment` / `missing` / `wrong` / `extra`：仅在"有 actual 可判"的场景下有值。纯 reference 生成场景下为空。
- `actual`：仅在"有 actual 可判"的场景下有值。
- `reference_generation_basis`：区分 expected 的来源（ready_固化 / judge_自生成 / case_提供）。

**schema 层面不需要拆分多个类型**，JudgeResult 本身就有 Optional 字段的容错设计（`Optional[float]`、`field(default_factory=list)` 等）。关键是在 **normalize / validate 逻辑**上做区分：模板化后，不同场景产出的 JudgeResult 在归一化时走不同的校验路径——比如有 actual 时校验 fulfillment 域完整性，纯 reference 生成时不校验那个域。

**可能需要新增的唯一结构**是 judge 调用时的**输入约束描述**（一个轻量的 `JudgeContext` 或直接在调用参数里传 `has_actual: bool` / `has_reference: bool`），让模板知道该渲染哪些段落、要求哪些输出字段。这不算 schema 改动，只是调用参数层面的补充。




--------


对，这个方向最简洁。mock_agent 本身不动，只是在预构建 mock case 的流程中，加两段调度逻辑：

1. **调 live/类live 获取 output**：有 live 就真调，没 live 就用按 live_schema 构造的系统扮演模块
2. **调 judge 获取 reference**：复用 judge 的 prompt 模板，但只要求 expected 相关字段，不做 fulfillment 判定

mock_agent 自己继续产用户意图和 live 输入，output 和 reference 通过调度外部角色获取，整体流程变成：

```
mock case 预构建:
  ├─ mock_agent 产用户意图 + live 输入
  ├─ 如果 ready 含 output → 调 live / 类live → 拿 output
  └─ 如果 ready 含 reference → 调 judge（仅生成模式）→ 拿 reference
```

这样改动集中在 mock 预构建的调度层，mock_agent 自身逻辑不变，judge 加一个轻量的"仅生成 expected"模式（同一套 prompt 模板 + 条件块），整体干净。




--------


理解了，你把 reference 的输入拆成了三类。让我把这个 schema 完整说清楚：

## reference 的输入形状（三类）

### 1. live 输入（形状 = live schema 的 `REQUEST_SHAPE`）
- 模拟给 live 系统的输入，judge 需要看到完整请求体才能理解上下文
- 比如 QA 的 `{"input": {"query": "..."}, "metadata": {...}, "scenario": "...", "data_quality_flags": null}`

### 2. 别的项目信息
- `scenario`（场景）
- `expected_intent`（意图标签，如果项目有）
- 项目评估文档：`evaluation` / `judge_standard` / `judge_boundary`
- 这些告诉 judge "在这个项目这个场景下，标准答案应该满足什么评估标准"

### 3. live schema 的输出形状（`EXTRACT_OUTPUT_SHAPE`）—— 仅格式，无具体内容
- 指导 judge 产出 expected 的结构：字段名 + 类型
- 比如 QA 的 `{"actual_answer": "string"}`
- 这是个"模板"，告诉 judge "你的 expected 必须长成这个形状"，不包含具体答案内容

## reference 的输出形状

- 就是 `EXTRACT_OUTPUT_SHAPE` 的实例化——按第 3 类输入给的格式，填入具体的标准答案内容
- QA 的例子：`{"actual_answer": "重疾险理赔流程一般包括..."}`

## 关键洞察

**第 3 类输入（EXTRACT_OUTPUT_SHAPE）是 reference 输入和输出的桥梁**——它既作为输入告诉 judge"产出格式"，又决定了 reference 最终的输出形状。这保证 reference 形状天然和 live schema 对齐，不需要额外整形。

## 当前实现的缺口

当前 `generate_reference` 的 prompt 缺了第 3 类——没有显式注入 `EXTRACT_OUTPUT_SHAPE` 告诉 judge"你的 expected 必须按这个格式产出"。这正是 judge 偶发产出 `expected:{}`（空）的根因——它不知道 expected 该长什么样。

**其他你可能要思考的点**：第 3 类的 `EXTRACT_OUTPUT_SHAPE` 应该标注"仅格式无具体内容"，避免 judge 把 shape 当成内容直接抄进去（比如产出 `{"actual_answer": "string"}` 这种占位符）。需要在 prompt 里明确区分"这是格式模板"和"你要填的是真实标准答案"。




--------

有个问题现在，reference的结构，都不是固定好的，但是实际上他们内部应该要写成对应项目的live schema，然后在llm构造的时候传进去，但是现在好像没法直接这样搞，那怎么办？

## 方案：嵌套 StructuredOutputSpec

### 核心思路

`StructuredOutputSpec` 本身支持嵌套 —— `nested_schemas` 的 value 类型从 `dict` 改为 `StructuredOutputSpec`，形成递归结构。这样 `expected` 的子结构约束和顶层输出用的是**同一套约束体系**，不区分对待。

### 改动点

**1. `StructuredOutputSpec` 加字段**

`nested_schemas: dict[str, StructuredOutputSpec]`，键是字段名，值是对该字段的结构化约束。`from_dataclass` 支持传入这个参数。

**2. `render_output_constraint` 递归展开**

渲染顶层输出格式时，遇到 `nested_schemas` 就递归调用自己，把子 spec 的 json_schema 和 required_nonempty 展开到对应字段的约束文案里。生成的效果类似："字段 `reference` 必须符合以下结构：{递归渲染的子 spec}"。

**3. 构造时加载项目 live_schema**

在 judge 和 attribute 的 output_spec 构造点，动态加载项目的 `ExtractOutput` dataclass，用 `StructuredOutputSpec.from_dataclass` 包成子 spec，塞进 `nested_schemas` 的  `expected` 键。如果项目没有 dataclass 就跳过，不阻断。

**4. enforce 不动**

返回后的强校验仍然只验顶层字段存在性和非空，不递归校验子结构。因为 enforce 的职责是"阻断完全跑偏的输出"，深层字段校验成本高、误杀风险大，交给 prompt 约束和后续 `live_schema_check` 做事后校验。

### 效果

- judge 和 attribute 的 LLM prompt 里会明确告诉模型：`expected`  内部必须符合项目 live_schema 定义的结构
- 不改动任何现有 dataclass（`JudgeLLMOutput` 的 `expected: Any` 保持不变）
- 如果未来有多层嵌套需求，直接 `nested_schemas` 里再套 `nested_schemas`，天然支持



