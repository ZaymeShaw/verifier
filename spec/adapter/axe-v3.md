# 场景扩展评估轴：核心对象与人类操作流程

范围不变：只在 `llm_probe` 内，复制轴1/轴2作为试验轴，不动生产链路。

本文分两部分看：**结构**（现在冻结）和**填值**（标注"示例"，实现时按现有轴1/轴2真实行为填）。

---

## 1. 一句话模型

> **开发者写"轴类型"**（一个 adapter 文件），一次性定义枚举、依赖、筛选、信息来源、流程；**场景配置者只写描述**，把类型启用到某个场景；**运行器**在依赖满足、筛选命中时发动每个轴，每轴独立落一条带枚举结论的结果。

核心对象只有 4 个：

| # | 对象 | 谁创建 | 什么时候创建 | 存在哪 |
|---|---|---|---|---|
| ① | **轴类型 AxisType** | 开发者 | 写代码时，一个类型写一次 | `llm_probe/eval_axes/adapters/*.py` |
| ② | **场景轴 ScenarioAxis** | 场景配置者 | 在资料页给某场景启用类型时 | `data/llm_probe/eval_axes.json` |
| ③ | **样本 Sample** | 评测执行者 | 发起试验时选定 | 现有样本存储 |
| ④ | **轴结果 AxisResult** | 运行器 | 每个样本 × 每个启用轴跑完 | 试验运行记录 |

---

## 2. 三个问题，三个字段

上一版把"依赖"当成一个包袱什么都往里装。本版拆开：每个字段只回答一个问题，**三个都是轴类型的属性，不是场景的属性**。

| 字段 | 回答的问题 | 取值 | 不满足时 |
|---|---|---|---|
| `depend_on` | 谁必须先跑完 | 轴名列表 | 上游未 `succeeded` → 本轴 `blocked` |
| `trigger_when` | 哪些样本需要判 | 样本筛选条件 | 不命中 → 本轴 `not_applicable` |
| `inputs` | 判的时候看什么信息 | 信息来源列表 | 必填来源缺失 → 本轴 `failed` |

三者的关系：

- `trigger_when` 的条件可以看样本字段，也可以看上游轴的 `verdict`
- `inputs` 的来源可以是样本字段，也可以是上游轴 `output` 里的**具体字段**（不是整份结果，更不是 trace）
- **凡在 `trigger_when` 或 `inputs` 里引用到的轴，必须出现在 `depend_on` 里**——加载时校验
- `depend_on` 里的轴如果两边都没引用，是纯排序依赖，加载时给警告（通常意味着多余）

一个轴依赖另一个轴，只有两种正当理由：**筛选**（只有上游判成某值的样本才值得判本轴）→ `trigger_when`；**信息**（本轴要读上游的产出）→ `inputs`。两个都不成立，就不该有依赖。

---

## 3. 你关注的每个东西放在哪

| 你关注的 | 放在哪个对象 | 谁填 | 能否被场景特化 |
|---|---|---|---|
| 轴类型 | ① `type_id` | 开发者 | 否 |
| 流程实现 | ① `run()` | 开发者 | 否 |
| 枚举值 | ① `verdict_enum` | 开发者 | 否（改枚举 = 新类型） |
| 枚举值描述 | ① `verdict_enum[].description` | 开发者 | 否；场景想补充含义写进 `description` |
| 依赖哪些轴 | ① `depend_on` | 开发者 | 否 |
| 哪些样本要判 | ① `trigger_when` | 开发者 | 否（首版不开放，见 §9） |
| 判时看什么信息 | ① `inputs` | 开发者 | 否 |
| 场景描述 | ② `description` | 场景配置者 | 是——这是场景层唯一实质内容 |
| 是否启用 | ② `enabled` | 场景配置者 | 是，默认 false |
| 结论 | ④ `verdict` ∈ 该类型枚举 | 运行器 | — |
| 跑没跑成 | ④ `status` | 运行器 | — |

---

## 4. 人类什么时候做什么

```
时间线 ───────────────────────────────────────────────────▶

[开发者]              [场景配置者]           [评测执行者]        [所有人]
写一次                每个场景一次           每次试验            看结果
                                                                 
写 AxisType：         资料页启用类型：       选场景+冻结样本集   对照页
 - type_id             - 选类型              发起扩展轴试验      - 结论合理?
 - verdict_enum        - 写 description                          - 依赖/筛选行为对?
 - depend_on           - enabled=true                            - 与旧轴差异可解释?
 - trigger_when
 - inputs
 - output_fields
 - limits
 - run()
```

### 4.1 开发者：定义一个轴类型（写一次）

在 `adapters/` 下新建一个文件，填齐下面的结构。**结构冻结；字段里填的值是示例**，实现时对照现有轴1/轴2填。

```python
# impl/projects/llm_probe/eval_axes/adapters/fulfillment.py

AXIS_TYPE = AxisType(
    type_id="fulfillment",
    title="满足度",
    summary="判断回答是否满足了请求的核心期望",

    # 枚举与现有轴1一致
    verdict_enum=[
        Verdict("fulfilled",     "回答满足了请求的核心期望"),
        Verdict("not_fulfilled", "存在未满足的核心期望"),
        Verdict("not_evaluable", "缺少判定所需信息，无法判定"),
    ],

    depend_on=[],                # 不依赖任何轴
    trigger_when=None,           # 所有样本都判
    inputs=[
        Input("request", source="sample.request"),
        Input("answer",  source="sample.answer"),
        Input("context", source="sample.context", required=False),
    ],

    output_fields=["expectations", "assessment", "rationale", "citations"],   # 示例
    scenario_fields=[Field("description", required=True)],
    limits=ExecutionLimits(llm_calls=..., tool_calls=..., seconds=...),        # 示例，按旧轴1上限填
    run=run_fulfillment,         # 复制旧轴1流程
)
```

```python
# impl/projects/llm_probe/eval_axes/adapters/carryability.py

AXIS_TYPE = AxisType(
    type_id="carryability",
    title="可承载",
    summary="判断未满足的请求是否本应由该系统承载",

    # 枚举与现有轴2一致
    verdict_enum=[
        Verdict("yes",         "能承载"),
        Verdict("no",          "不能承载"),
        Verdict("undecidable", "缺少判定所需信息，无法判定"),
    ],

    # ---- 以下三项为示例，按现有轴2实际行为填，见 §4.1.1 ----
    depend_on=["fulfillment"],
    trigger_when=When(axis="fulfillment", verdict_in=["not_fulfilled"]),
    inputs=[
        Input("answer",             source="sample.answer"),
        Input("unmet_expectations", source="axis.fulfillment.output.expectations"),
    ],
    # --------------------------------------------------------

    output_fields=["placements", "rationale", "citations", "unresolved"],     # 示例
    scenario_fields=[Field("description", required=True)],
    limits=ExecutionLimits(...),
    run=run_carryability,        # 复制旧轴2流程
)
```

**开发者的边界**：只写类型，不写场景。类型里不出现 `policy_search` 这种场景名。

#### 4.1.1 carryability 的依赖怎么填

取决于现有轴2实际怎么跑，三种情况结构都能表达：

| 现有轴2实际行为 | `depend_on` | `trigger_when` | `inputs` 里的轴引用 |
|---|---|---|---|
| A. 独立判，不看轴1 | `[]` | `None` | 无 |
| B. 只在轴1不满足时跑，但判时不读轴1输出 | `["fulfillment"]` | 保留 | 无 |
| C. 只在轴1不满足时跑，且读轴1列出的未满足条目 | `["fulfillment"]` | 保留 | 保留 |

示例按 C 写。若实现时发现是 A，两轴脱钩，依赖机制在首版两个轴上不接线——这不是问题，字段和运行器逻辑留着，等真出现有依赖的轴再验证。不为演示功能固化假依赖。

### 4.2 场景配置者：在资料页启用轴

资料页路径：`资料页 → 选场景 → 扩展评估轴（试验） → 添加轴`。

表单只有 3 步：

| 步骤 | 表单块 | 对应字段 | 来源 |
|---|---|---|---|
| 1 | 选类型 | `type` | 下拉，只列注册表里的 type_id；本场景已有的类型不可重复选 |
| 2 | 场景描述 | `description` + 该类型其他 `scenario_fields` | 按类型动态出字段，支持 `{material://...}` |
| 3 | 启用 | `enabled` | 默认 false |

页面上**只读展示**该类型的枚举值、依赖、筛选条件、信息来源（从类型声明渲染），让配置者知道这个轴会怎么跑，但不能改。

存下来是这样（`data/llm_probe/eval_axes.json`，YAML 展示）：

```yaml
scenarios:
  policy_search:
    axes:
      fulfillment:                      # key = type_id，一个场景每种类型只一个
        enabled: true
        description: |
          以下场景中"满足"指……
          能力范围见 {material://llm_probe/policy-capability}
      carryability:
        enabled: true
        description: |
          以下场景中"承载"指……
          边界定义见 {material://llm_probe/policy-boundary}
```

**配置者的边界**：能写描述、能启用；不能改枚举、不能改依赖/筛选/信息来源、不能改流程、不能改上限。想要这些 → 找开发者加类型。

### 4.3 评测执行者：发起试验

1. 选场景、选冻结样本集（先用真实旧回答，不重调被测服务）。
2. 点"运行扩展轴试验"（独立入口，不经过生产 judge）。
3. 看结果页：每个样本 × 每个轴一行，列 = `status / verdict / rationale / citations / 耗时 / 调用数`。
4. 看对照页：同样本上 旧轴1 vs 新 fulfillment、旧轴2 vs 新 carryability。

---

## 5. 运行器：固定五步，不做通用 DAG

对每个 样本 × 轴，按下面顺序判定：

```
1. enabled?                              否 → status=disabled
2. depend_on 里的轴全部 succeeded?        否 → status=blocked
3. trigger_when 命中?                     否 → status=not_applicable
4. 按 inputs 声明逐项取数                 必填缺失 → status=failed
   （样本字段 / 上游 output 指定字段）
5. run()                                  → status=succeeded | failed
                                            verdict ∈ verdict_enum（仅 succeeded 时非空）
```

轴的执行顺序由 `depend_on` 拓扑排序得出；无依赖的轴顺序无关紧要。

第 2、3 步的求值结果和第 4 步实际取到的来源，都记进 AxisResult，"为什么没发 / 发的时候看了什么"事后可查。

---

## 6. 轴结果：每轴一条，不合并

```yaml
run_id: ...
case_id: ...
scenario_id: policy_search
axis_id: carryability                  # = type_id
type_id: carryability

status: succeeded                      # disabled|blocked|not_applicable|waiting|running|succeeded|failed|cancelled
verdict: no                            # ∈ carryability.verdict_enum；status≠succeeded 时为 null
verdict_description: "不能承载"        # 来自类型枚举描述

trigger_decision:                      # 第2、3步的求值
  depend_on_satisfied: true
  trigger_when_matched: {axis: fulfillment, verdict: not_fulfilled}

inputs_used:                           # 第4步实际取数
  answer:             sample.answer@<hash>
  unmet_expectations: axis.fulfillment.output.expectations@<run_id>

output:                                # 结构与类型声明的 output_fields 一致
  placements: [...]
  rationale: ...
  citations: [...]
  unresolved: []

config_fingerprint: ...
implementation_fingerprint: ...
started_at / finished_at / usage: ...
execution_trace_ref: ...
```

`status` 和 `verdict` 分开的原因：`not_evaluable` / `undecidable`（**判了，判不出**）是业务结论，进 `verdict`；`failed`（**没跑成**）是基础设施状态，进 `status`。二者不混。旧轴2部分条目失败的语义保留在 `output.unresolved`，整轴 status 按旧规则定。

---

## 7. 加载期校验

| 规则 | 级别 |
|---|---|
| `trigger_when` / `inputs` 引用的轴必须在 `depend_on` 里 | 错误 |
| `depend_on` 引用的轴必须是本场景内已启用的类型 | 错误 |
| `depend_on` 不得成环 | 错误 |
| `inputs` 引用的上游 output 字段必须在上游类型的 `output_fields` 里 | 错误 |
| `trigger_when` 引用的上游 verdict 值必须在上游类型的 `verdict_enum` 里 | 错误 |
| 一个场景内同一 type_id 只允许一个实例 | 错误 |
| `depend_on` 里的轴在 `trigger_when` 和 `inputs` 中均未被引用 | 警告 |

---

## 8. 目录落地

```
impl/projects/llm_probe/eval_axes/
  types.py            # AxisType / Verdict / Input / When / Field / ExecutionLimits / AxisResult
  registry.py         # {"fulfillment": AXIS_TYPE, "carryability": AXIS_TYPE}
  store.py            # 读写 eval_axes.json；校验 type 已注册、描述必填、每场景每类型唯一
  validate.py         # §7 的加载期校验
  runner.py           # §5 五步流程；拓扑排序；记录 trigger_decision / inputs_used
  adapters/
    fulfillment.py    # 复制旧轴1流程，包成类型
    carryability.py   # 复制旧轴2流程，包成类型

impl/data/llm_probe/eval_axes.json
```

复用：Agno / LlmClient / material_tools / 结构化校验 / 上下文记录。不新建第二套底座。

---

## 9. 冻结与留待

**现在冻结（结构）**

- AxisType 的字段集：`type_id` `title` `summary` `verdict_enum` `depend_on` `trigger_when` `inputs` `output_fields` `scenario_fields` `limits` `run`
- ScenarioAxis 只含 `enabled` + `description` + 类型声明的其他 `scenario_fields`
- AxisResult 的字段集，`status` 与 `verdict` 分离
- 运行器五步顺序
- §7 校验规则
- 一个场景每种类型只一个实例，实例名 = 类型名

**留待实现时按现有轴填（值）**

- 两个类型的 `verdict_enum` 描述文字、`output_fields`、`limits` 数值
- carryability 的 `depend_on` / `trigger_when` / `inputs` 按 §4.1.1 三种情况之一填

**明确不做，将来有需求再开**

- `trigger_when` 场景级覆盖：首版不开；出现"同类型在不同场景筛选条件不同"再把它加进 `scenario_fields`
- 同场景多实例：首版不开；出现"同场景跑两套描述的同类型轴"再放开，届时 `depend_on` 升级为实例名，属向前兼容扩展
- 通用 DAG 引擎：不做

---

## 10. 首版验收

| 项 | 判定 |
|---|---|
| 类型可见 | 资料页下拉能看到 2 个类型，枚举值分别为 `fulfilled/not_fulfilled/not_evaluable` 与 `yes/no/undecidable` |
| 特化可见 | 场景配置的 `description` 出现在实际 prompt 里 |
| 场景零结构 | 场景配置文件里除 `enabled`/`description` 外无其他字段 |
| 依赖生效 | 若按 B/C 填：fulfillment=fulfilled 时 carryability 落 `not_applicable`；fulfillment failed 时落 `blocked`；均不发 LLM 调用 |
| 信息隔离 | 若按 C 填：carryability 只拿到 fulfillment output 中声明的字段，拿不到 trace |
| 校验生效 | 构造一个 `inputs` 引用未在 `depend_on` 声明的轴的配置，加载报错 |
| 复制等价 | 冻结样本上，新轴与旧轴的 verdict 一致或差异逐条有解释 |
| 生产隔离 | 不进试验入口时，生产轴1/轴2零改动 |