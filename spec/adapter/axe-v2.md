# 场景扩展评估轴：核心对象与人类操作流程（重写版）

先回应你的三条：

1. **数学抽象那篇作废。** 它把"轴类型 / 场景实例 / 依赖 / 结果"翻译成 S、A、K、P、T，翻译完信息量为零，反而把你关注的字段全部藏进了符号里。不再维护。
2. **上一版设计稿的问题**：把你关注的东西拆散塞进了通用词里——枚举值藏在 `output_schema`，发动时间藏在 `inputs` 和 `after` 两处，获取信息藏在 `input_schema` + binding，场景描述藏在 `config_schema`。名词是对的，但没有一个地方把它们并排列出来。
3. 下面按"人什么时候做什么"和"核心对象有哪几个、每个对象里放什么"重新写。范围不变：只在 `llm_probe` 内，复制轴1/轴2 作为试验轴，不动生产链路。

---

## 1. 一句话模型

> **开发者写"轴类型"（一个 adapter 文件），场景配置者在资料页把轴类型实例化成"场景轴"并写特化描述和依赖，运行器在样本到位、依赖满足时发动每个轴，每轴独立落一条带枚举结论的结果。**

核心对象只有 **4 个**，其他都是附属：

| # | 对象 | 谁创建 | 什么时候创建 | 存在哪 |
|---|---|---|---|---|
| ① | **轴类型 AxisType** | 开发者 | 写代码时，一个类型写一次 | `llm_probe/eval_axes/adapters/*.py` |
| ② | **场景轴 ScenarioAxis** | 场景配置者 | 在资料页给某场景添加轴时 | `data/llm_probe/eval_axes.json` |
| ③ | **样本 Sample** | 评测执行者 | 发起试验时选定 | 现有样本存储 |
| ④ | **轴结果 AxisResult** | 运行器 | 每个样本 × 每个启用轴跑完 | 试验运行记录 |

---

## 2. 你关注的每个东西放在哪

这是本文最重要的一张表。

| 你关注的 | 放在哪个对象 | 谁填 | 能否被场景特化 | 说明 |
|---|---|---|---|---|
| **轴类型** | ① AxisType.`type_id` | 开发者 | 否 | 一个 adapter = 一个 type_id，如 `fulfillment`、`carryability` |
| **Adapter 实现（流程）** | ① AxisType.`run()` | 开发者 | 否 | 单次 / 多阶段 / 逐项核实，随类型走 |
| **枚举值** | ① AxisType.`verdict_enum` | 开发者 | **否**（改枚举值 = 新类型） | adapter 代码按这套值产出，所以必须在类型层固定 |
| **枚举值描述（默认）** | ① AxisType.`verdict_enum[].description` | 开发者 | — | 该值的通用判定含义 |
| **枚举值描述（特化）** | ② ScenarioAxis.`verdict_notes` | 场景配置者 | **是** | 只能补充/覆盖描述文字，不能增删值 |
| **每轴获取什么信息** | ① AxisType.`needs` 声明 + ② ScenarioAxis.`inputs` 绑定 | 开发者声明 / 配置者绑定 | 绑定可变，需求不可变 | 类型说"我要 request、answer、上游 X 的 output"；实例说"从哪拿" |
| **场景描述（特化）** | ② ScenarioAxis.`description` | 场景配置者 | 是 | 注入 adapter prompt 的场景标准，支持 `{material://...}` |
| **依赖 depend_on** | ② ScenarioAxis.`depend_on` | 场景配置者 | 是 | 列出依赖哪些轴、要求它们到什么状态、要不要读它们的 output |
| **发动时间** | 由 ② `depend_on` + `trigger_when` **推导**，运行器执行 | 场景配置者 | 是 | 不单独存"时间"，存的是条件；条件满足即发动 |
| **是否启用** | ② ScenarioAxis.`enabled` | 场景配置者 | 是 | 新增默认 false |
| **结论** | ④ AxisResult.`verdict` ∈ 该类型枚举 | 运行器 | — | 外加 `status`（succeeded/blocked/failed 等）区分"判出来了"和"没跑成" |

上一版把"依赖"拆成 `inputs.source=axis` 和 `after` 两个概念，太绕。**本版合并为一个 `depend_on`**，一条依赖项同时说清三件事：依赖谁、等到什么状态、读不读它的输出。

---

## 3. 人类什么时候做什么

```text
时间线 ────────────────────────────────────────────────────────►

[开发期]            [配置期]                 [试验期]              [验收期]
 开发者              场景配置者                评测执行者            开发者+配置者
 写 AxisType         在资料页添加场景轴          选场景+冻结样本        看新旧对照
 - type_id           - 选类型                   发起试验              - 复制等价?
 - 枚举值+默认描述    - 写场景描述               看每轴结果            - 场景描述是否够用?
 - needs（要什么）    - 补枚举特化描述                                  - 枚举是否够用?
 - 产出什么           - 填 depend_on
 - run() 流程         - 绑定 inputs
                     - enabled=true
```

### 3.1 开发者：定义一个轴类型（写一次）

在 `adapters/` 下新建一个文件，填齐下面这个结构。这就是你说的"轴类型 adapter，不同场景允许不同实现"中的"实现"部分。

```python
# impl/projects/llm_probe/eval_axes/adapters/fulfillment.py

AXIS_TYPE = AxisType(
    type_id="fulfillment",
    title="能力兑现",
    summary="核对回答是否兑现了场景声明的能力，逐条期望对账。",

    # ── 枚举值：类型层固定，adapter 代码按这套值产出 ──
    verdict_enum=[
        Verdict("met",           "全部期望被兑现"),
        Verdict("partial",       "部分期望被兑现，存在遗漏或偏差"),
        Verdict("not_met",       "核心期望未兑现"),
        Verdict("not_evaluable", "证据不足或问题不在能力范围内，无法判定"),
    ],

    # ── 需要什么信息：类型层声明，实例层只负责绑定来源 ──
    needs=[
        Need("request", kind="sample_field", required=True),
        Need("answer",  kind="sample_field", required=True),
        Need("context", kind="sample_field", required=False),
        # 本类型不依赖任何上游轴
    ],

    # ── 场景可特化的配置字段：实例层填 ──
    scenario_fields=[
        Field("description", "本场景的能力标准（旧 capability 语义）", required=True),
        Field("show_schema",  "期望展示结构", required=False),
    ],

    # ── 产出什么（除 verdict 外的方法专属输出）──
    output_fields=["expectations", "assessment", "rationale", "citations"],

    # ── 默认发动条件：无依赖，样本到位即发 ──
    default_depend_on=[],

    limits=ExecutionLimits(llm_calls=..., tool_calls=..., seconds=...),  # 按旧轴1实际值
    run=run_fulfillment,   # 复制旧轴1的流程：构建上下文 → 判定 → 自检 → 收尾
)
```

```python
# impl/projects/llm_probe/eval_axes/adapters/carryability.py

AXIS_TYPE = AxisType(
    type_id="carryability",
    title="承载性",
    summary="对轴1未达成/部分达成的期望做归位：是否属于本服务边界内应承载的内容。",

    verdict_enum=[
        Verdict("in_scope_missed",   "属于服务边界内，回答本应承载但没承载"),
        Verdict("out_of_scope",      "不属于服务边界，未承载合理"),
        Verdict("mixed",             "多条期望归位不同，见 placements"),
        Verdict("undecidable",       "边界描述或引用不足以归位"),
    ],

    needs=[
        Need("answer",      kind="sample_field", required=True),
        # 关键：声明依赖上游轴的输出，并且要哪个类型
        Need("fulfillment", kind="axis_output", required=True, accepts_type="fulfillment"),
    ],

    scenario_fields=[
        Field("description", "本场景的服务边界说明（旧 boundary 语义）", required=True),
    ],

    output_fields=["placements", "rationale", "citations", "unresolved"],

    # 默认发动条件：等一个 fulfillment 轴 succeeded，且其 verdict 为 partial/not_met 才发
    default_depend_on=[
        Dependency(type="fulfillment", require="succeeded",
                   read_output=True,
                   trigger_when={"verdict_in": ["partial", "not_met"]}),
    ],

    limits=...,
    run=run_carryability,  # 复制旧轴2：逐期望核实 → 引用重试 → 归位 → 完整性约束
)
```

**开发者的边界**：只写类型，不写场景。类型里不出现 `policy_search` 这种场景名。

### 3.2 场景配置者：在资料页添加场景轴

资料页路径：`资料页 → 选场景 → 扩展评估轴（试验）→ 添加轴`。

表单只有 6 块，顺序就是填写顺序：

| 步骤 | 表单块 | 对应字段 | 来源 |
|---|---|---|---|
| 1 | 选类型 | `type` | 下拉，只列注册表里的 type_id |
| 2 | 命名 | `id`、`title` | 自填 |
| 3 | 场景描述 | `description` + 该类型的其他 `scenario_fields` | 按类型动态出字段，支持资料引用 |
| 4 | 枚举特化 | `verdict_notes` | 列出该类型全部枚举值，每个值旁边一个可选文本框"本场景补充说明" |
| 5 | 依赖与信息 | `depend_on`、`inputs` | 按类型 `needs` 出：sample_field 的自动绑定；axis_output 的下拉选本场景内类型匹配的轴 |
| 6 | 启用 | `enabled` | 默认 false |

存下来是这样（`data/llm_probe/eval_axes.json`，YAML 展示）：

```yaml
scenarios:
  policy_search:
    axes:

      - id: fulfillment
        type: fulfillment
        title: 能力兑现
        enabled: true
        description: |
          根据用户问题回答政策内容，保留适用条件和例外。
          评估说明见 {material://llm_probe/policy-capability}
        verdict_notes:
          partial: "政策条文引对但漏掉生效日期，也算 partial"   # 场景特化描述
        inputs:
          request: sample.request
          answer:  sample.answer
          context: sample.context
        depend_on: []                     # 样本到位即发

      - id: boundary
        type: carryability
        title: 承载性
        enabled: true
        description: |
          本服务覆盖公开政策问答，不支持个案审批。
          边界说明见 {material://llm_probe/policy-boundary}
        verdict_notes: {}                 # 用类型默认描述
        inputs:
          answer:      sample.answer
          fulfillment: axis.fulfillment.output
        depend_on:
          - axis: fulfillment
            require: succeeded            # 上游必须成功
            trigger_when:
              verdict_in: [partial, not_met]   # 否则本轴 not_applicable
```

**配置者的边界**：能改描述、依赖、启用；不能改枚举值、不能改流程、不能改上限。想要这些 → 找开发者加类型。

### 3.3 评测执行者：发起试验

1. 选场景、选冻结样本集（先用真实旧回答，不重调被测服务）。
2. 点"运行扩展轴试验"（独立入口，不经过生产 judge）。
3. 看结果页：每个样本 × 每个轴一行，列 = `status / verdict / rationale / citations / 耗时 / 调用数`。
4. 看对照页：同样本上 旧轴1 vs 新 fulfillment、旧轴2 vs 新 carryability。

---

## 4. 运行器：发动时机与信息流（机器视角）

不做通用 DAG，只做下面这个固定流程：

```text
样本 x 到位
  │
  ├─ 遍历本场景 enabled=true 的轴，按 depend_on 排拓扑序（禁循环、禁依赖 disabled 轴）
  │
  ├─ depend_on 为空的轴 ──► 立即发动（可并行）
  │       例：fulfillment
  │       读：inputs 中绑定的 sample 字段
  │       写：AxisResult(fulfillment)
  │
  └─ depend_on 非空的轴 ──► 等待
          例：boundary
          等到：所有 depend_on.axis 进入终态
          检查：
            require=succeeded 的上游失败/blocked/not_applicable ──► 本轴 blocked，不发
            trigger_when 不满足（如 verdict=met）             ──► 本轴 not_applicable，不发
            全部满足                                          ──► 发动
          读：inputs 中绑定的 sample 字段 + 上游 output（只读，只给 output 不给整个 trace）
          写：AxisResult(boundary)
```

"发动时间"不是一个存的字段，而是运行器对 `depend_on + trigger_when` 的求值结果，落在 AxisResult 的 `started_at` 和 `trigger_decision` 里，事后可查为什么发/为什么没发。

---

## 5. 轴结果：每轴一条，不合并

```yaml
run_id: ...
case_id: ...
scenario_id: policy_search
axis_id: boundary
type_id: carryability

status: succeeded            # disabled|waiting|running|succeeded|not_applicable|blocked|failed|cancelled
verdict: in_scope_missed     # 必须 ∈ carryability.verdict_enum；status≠succeeded 时为 null
verdict_description: "属于服务边界内，回答本应承载但没承载"   # 类型默认 + 场景 verdict_notes 合并后的文字

trigger_decision:            # 为什么发动/没发动
  depend_on_satisfied: true
  trigger_when_matched: {verdict_in: partial}

inputs_used:                 # 实际读了什么
  answer: sample.answer@<hash>
  fulfillment: axis.fulfillment.output@<run_id>

output:                      # 方法专属，按类型 output_fields
  placements: [...]
  rationale: ...
  citations: [...]
  unresolved: []

config_fingerprint: ...
implementation_fingerprint: ...
started_at / finished_at / usage: ...
execution_trace_ref: ...
```

`status` 和 `verdict` 分开的原因：`not_evaluable`（判了，判不出）是业务结论进 verdict；`failed`（没跑成）是基础设施状态进 status。旧轴2部分条目失败的语义原样保留在 `output.unresolved`，整轴 status 按旧规则定。

---

## 6. 目录落地

```text
impl/projects/llm_probe/eval_axes/
  types.py            # AxisType / Verdict / Need / Dependency / AxisResult 数据结构
  registry.py         # 显式注册：{"fulfillment": ..., "carryability": ...}
  store.py            # 读写 eval_axes.json，校验：type 存在、枚举 notes 的 key 合法、
                      #   depend_on 目标存在且 enabled、无循环、axis_output 类型匹配
  runner.py           # 拓扑排序、trigger 求值、发动、收结果
  adapters/
    fulfillment.py    # 从旧轴1复制流程，不改措辞
    carryability.py   # 从旧轴2复制流程，不改措辞

impl/data/llm_probe/eval_axes.json
```

复用：Agno / LlmClient / material_tools / 结构化校验 / 上下文记录。不新建第二套底座。

---

## 7. 首版验收

| 项 | 判定 |
|---|---|
| 类型可见 | 资料页下拉能看到 2 个类型，各自枚举值和描述与本文一致 |
| 特化可见 | 场景配置的 description 和 verdict_notes 出现在实际 prompt 与结果的 verdict_description 里 |
| 依赖生效 | fulfillment=met 时 boundary 落 not_applicable；fulfillment failed 时 boundary 落 blocked；均不发 LLM 调用 |
| 信息隔离 | boundary 只拿到 fulfillment 的 output，拿不到其 trace |
| 复制等价 | 冻结样本上，新 fulfillment 的 expectations/assessment、新 carryability 的 placements 与旧链路对照，差异逐条有解释 |
| 生产隔离 | 不进试验入口时，生产轴1/轴2零改动 |

---

## 8. 和上一版的差异（只列会影响你理解的）

- 删掉数学抽象文档。
- `inputs` + `after` 两个依赖概念 → 合并为 `depend_on`（含 `require`、`trigger_when`、是否读 output）。
- 枚举值和枚举描述从 `output_schema` 里提出来，成为 AxisType 的一级字段 `verdict_enum`；场景层新增 `verdict_notes` 做特化。
- 类型的"需要什么信息"从 `input_schema` 改叫 `needs`，并区分 `sample_field` / `axis_output` 两种来源，`axis_output` 必须声明接受的上游类型。
- 结果里新增 `trigger_decision` 和 `inputs_used`，让"什么时候发的、读了什么"可查。
- 明确三个角色的操作边界：开发者管类型/枚举/流程，配置者管描述/依赖/启用，执行者管样本/试验/对照。







--------------------审核

先逐条回应，再给修正后的定义。

## 第一点：枚举改，连带改三处

轴1 `verdict_enum` 改成 `fulfilled / not_fulfilled / not_evaluable`。原稿里连带要改：

- carryability 的默认触发条件：`verdict_in: [partial, not_met]` → `verdict_in: [not_fulfilled]`
- 第 5 节结果示例里的 `trigger_when_matched`
- 第 7 节验收表 "fulfillment=met 时 boundary 落 not_applicable" → `fulfilled`

轴2 的枚举（`in_scope_missed / out_of_scope / mixed / undecidable`）是我起的，我这边没有旧轴2的输出定义，也请你按旧轴2实际语义核一遍。

## 第二、三点：三个字段现在确实缠在一起

重新看原稿，问题不在名词，在于同一件事被说了多遍：

- "读 fulfillment 的 output" 出现了三次：`needs` 里的 `axis_output`、`inputs.fulfillment: axis.fulfillment.output`、`depend_on[].read_output=True`
- "依赖 fulfillment" 出现了两次：`inputs` 里的引用、`depend_on[].axis`
- `trigger_when` 被塞进 `depend_on` 的条目里，暗示"筛选只能看上游结果"，其实筛选也可能只看样本字段

按你的思路拆：运行器在"某样本 × 某轴"上必须回答三个独立问题，一个字段答一个。

| 问题 | 字段 | 值 | 回答为否时 |
|---|---|---|---|
| 要等谁跑完 | `depend_on` | 轴 id 列表 | 上游没成功 → `blocked` |
| 这个样本判不判 | `trigger_when` | 对 sample + 上游结果的谓词 | 谓词为假 → `not_applicable` |
| 判的时候读什么 | `inputs` | needs 槽位 → 数据源 | 源缺失 → `failed`（配置错误） |

### 交汇处怎么划

1. **depend_on 是引用范围，inputs / trigger_when 在范围内取数。** `inputs` 引用了 `axis.X.*`，X 必须在 `depend_on` 里；反过来不成立——可以只等不读（比如只为了上游失败时省一次 LLM 调用）。校验规则：`inputs` 和 `trigger_when` 引用到的 axis id ⊆ `depend_on`，否则存不进去。
2. **trigger_when 和 inputs 都能读上游，但读的东西不同。** `trigger_when` 只能引用 `sample.*` 和 `axis.<id>.verdict | status`（小、用于决定发不发）；`inputs` 只能引用 `sample.*` 和 `axis.<id>.output[.field]`（大、喂给 adapter）。硬约束，不重叠。
3. **trigger_when 比"依赖轴的结果"宽。** 它可以只看样本字段（`sample.context` 非空才判、`sample.tags` 含某标签才判），也可以看上游 verdict，也可以两者组合。所以它是场景轴的一级字段，不挂在 `depend_on` 条目下。
4. **`require: succeeded` 去掉，改成固定规则不配。** 上游任一 `blocked/failed` → 本轴 `blocked`；上游任一 `not_applicable` → 本轴 `not_applicable`；上游全部 `succeeded` → 才算 `trigger_when`。这样 `blocked`（没法判）和 `not_applicable`（决定不判）的边界只由运行器定，配置者碰不到。

### 修正后的场景轴

```yaml
- id: boundary
  type: carryability
  enabled: true
  description: |
    ...
  verdict_notes: {}

  depend_on: [fulfillment]            # 只答"等谁"，轴 id 列表

  trigger_when:                        # 只答"这个样本判不判"
    all:
      - { ref: axis.fulfillment.verdict, in: [not_fulfilled] }
      # 可追加样本条件，如 { ref: sample.context, not_null: true }

  inputs:                              # 只答"读什么"，键 = 类型 needs 的槽位名
    answer:      sample.answer
    fulfillment: axis.fulfillment.output
```

fulfillment 轴则是 `depend_on: []`、`trigger_when: {}`（恒真）、`inputs` 三个 sample 字段。

### 类型侧对应调整

- `needs` 不变，仍是槽位声明：`Need("fulfillment", kind="axis_output", accepts_type="fulfillment")`
- 去掉 `default_depend_on`。类型不知道场景里的轴 id，所以只能给**按槽位名写**的建议触发条件：`suggested_trigger_when = {ref: "$fulfillment.verdict", in: ["not_fulfilled"]}`。配置者在表单里把槽位绑到具体轴后，表单把 `$fulfillment` 替换成轴 id 预填进 `trigger_when`。

### 表单顺序跟着改

5 号块拆成三步，顺序即依赖关系：先选 `depend_on`（下拉只列本场景已有的轴）→ 再填 `trigger_when`（可引用的上游 verdict 下拉只列 depend_on 里的轴）→ 再确认 `inputs`（sample_field 槽位自动同名绑定；axis_output 槽位从 depend_on 里挑类型匹配的轴，唯一时自动填）。

### inputs 仍未定的两处

你说 inputs 不确定，我认为悬而未决的是这两点，其他部分上面的划分已经能站住：

1. **要不要显式存。** 按 `needs` 其实可以全推导：sample_field 同名绑，axis_output 从 depend_on 里按 `accepts_type` 唯一匹配。显式存的好处是结果里 `inputs_used` 可查、以后允许换名（比如 sample 字段叫 `response` 不叫 `answer`）；代价是多一块表单。我倾向存，但表单自动预填、配置者一般不动。
2. **adapter 要不要知道上游 verdict。** 按第 2 条硬约束 inputs 读不到 verdict。目前 carryability 不需要（trigger 只放行 `not_fulfilled`，进来的一定是这个值）。如果以后某个类型确实要区分上游不同 verdict 下的判法，走法应该是上游把该信息写进 `output`，而不是给 inputs 开放 verdict 引用——否则第 2 条约束就破了。