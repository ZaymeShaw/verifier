# 场景扩展评估轴：核心对象与人类操作流程（v4）

范围不变：只在 `llm_probe` 内，复制轴1/轴2作为试验轴，不动生产链路。

v4 = v3 的结构 + 对照现有代码后的收敛。结构层面 v3 全部保留；改动的是 v3 标为"示例"的填值、存放位置，以及几处和现有代码顶牛的假设。

---

## 0. 本版采用的决定（一眼可否决）

| # | 决定 | 来源 |
|---|---|---|
| D1 | 场景轴（框）存进 capability 预设条目的 `axes` 列表；不再有 `eval_axes.json` | 讨论 §2 |
| D2 | 对照不落盘：批量 / 全链路里新链路作为判后 pass 挂在旧轴2旁边（预设有启用的框才跑），结果随 run 一起进 summary 页第 14 列；`live.html` 单步页另有「扩展轴试验」按钮 | 讨论 §1、§三 |
| D10 | 每个 AxisResult 必须带 `summary`（一句话 + 逐格 items）；怎么产出由 `run()` 定，两个内置轴从判结论的同一次模型调用里提取（复用 `summary_from_fulfillment` / `carrier_text`），不另调模型 | 讨论 §二 |
| D11 | 框就是开关：预设没有启用的框 → 生产零额外调用、结果零变化；启用了 → run 多一个 `eval_axes` 键，其余键和 `run_status` 不变 | 讨论 §三 |
| D12 | 扩展轴自己的 LLM 外壳：每次调用实际命中的端点/模型记进 `usage`（`llm_model` / `llm_endpoint` / `llm_attempts`）；模型策略走类型化配置 `eval_axes.model_policy`（`.env` 用 `EVAL_AXES_MODEL_POLICY` 覆盖）：`any` 按公共路由回退，`same_model` 只允许与角色策略同名模型的端点（中转站可不同），同模型都不可用则该轴 `failed` 不换模型顶替。只作用于扩展轴新建的客户端，生产 `LlmClient` / `LlmRouter` 不改，健康/冷却状态仍与生产共享 | 实测发现两条分歧是路由回退换了模型 |
| D3 | carryability 的输入只有 fulfillment 输出的三个字段，**没有** `answer`（协议红线） | `spec/alg/capability_carrier.md` §5 第 6 条 |
| D4 | 轴类型新增 `verdict_scope ∈ {axis, item}`；carryability 是 `item` 级，轴级 `verdict` 为 null | 旧协议"单位是期望，不折叠" |
| D5 | carryability 的枚举用归位值 `做不了 / 做错了 / 说不清`；模型原始 `carry` 留在 output | 报表/收件箱/完整性规则都按 placement 写 |
| D6 | `run()` 内部实现方式由轴自己定：复用、继承、复制都合法；协议只管输入、输出、状态 | 用户原则 |
| D7 | fulfillment 的 `run()` 复制 `LlmProbeJudge.build_context` 并复用 core `judge_trace()` / `finalize_judge_result()`；carryability 的 `run()` 继承 `TextCarrier` 覆盖取边界的方法，复用 `place()` | D6 的具体落点 |
| D8 | `limits` 首版是声明 + 事后记录；只有 `tool_calls` 硬限（现有 `tool_call_limit`） | 现有 LLM 客户端能力 |
| D9 | 试验的 LLM 调用统一用 `axes-` 前缀的 trace_id，`caller` 标签暂不区分 | 后续完善 |

---

## 1. 一句话模型

> **开发者写"轴类型"**（一个 adapter 文件），一次性定义枚举、依赖、筛选、信息来源、流程；**场景配置者只写描述**，在 capability 预设里给该场景加一个框、选类型、启用；**运行器**在依赖满足、筛选命中时发动每个轴，每轴独立落一条结果。

核心对象 4 个：

| # | 对象 | 谁创建 | 什么时候创建 | 存在哪 |
|---|---|---|---|---|
| ① | **轴类型 AxisType** | 开发者 | 写代码时，一个类型写一次 | `impl/projects/llm_probe/eval_axes/adapters/*.py`，不存 JSON |
| ② | **场景轴 ScenarioAxis** | 场景配置者 | 在预设编辑器里"添加轴" | `impl/data/llm_probe/capability_map.json` → `<预设>.axes[]` |
| ③ | **样本 Sample** | 评测执行者 | 试验时现场 live 一次 | 内存里的 `RunTrace`，不落盘 |
| ④ | **轴结果 AxisResult** | 运行器 | 每个样本 × 每个启用轴跑完 | 试验响应，页面渲染，不落盘 |

"两个轴定义"的关系：① 是代码里的方法，是下拉框里的**选项**；② 是某个场景选了一个选项之后填出来的**框**。只有 ② 是数据。

---

## 2. 三个问题，三个字段

三个字段都是**轴类型的属性**，场景不能改：

| 字段 | 回答的问题 | 取值 | 不满足时 |
|---|---|---|---|
| `depend_on` | 谁必须先跑完 | 类型名列表 | 上游未 `succeeded` → 本轴 `blocked` |
| `trigger_when` | 哪些样本需要判 | 对上游 `verdict` 的条件 | 不命中 → 本轴 `not_applicable` |
| `inputs` | 判的时候看什么信息 | 信息来源列表 | 必填来源缺失 → 本轴 `failed` |

- `trigger_when` 首版只有一种形态：`When(axis=<类型名>, verdict_in=[...])`，只能引用 `verdict_scope=axis` 的上游。样本字段筛选留待有需求再开。
- `inputs` 的来源是 `sample.trace`（整份 RunTrace）或 `axis.<类型名>.output` 的**具名字段**。轴1本来就看全 trace（`build_judge_evidence_view(trace)`），所以它声明整份；轴2不看 trace，所以它一个 sample 来源都没有——隔离靠"不声明"，不靠 prompt 叮嘱。
- 凡在 `trigger_when` 或 `inputs` 里引用到的类型，必须出现在 `depend_on` 里——加载时校验。

---

## 3. 你关注的每个东西放在哪

| 你关注的 | 放在哪个对象 | 谁填 | 能否被场景特化 |
|---|---|---|---|
| 轴类型 | ① `type_id` | 开发者 | 否 |
| 流程实现 | ① `run()` | 开发者 | 否 |
| 枚举值 | ① `verdict_enum` | 开发者 | 否（改枚举 = 新类型） |
| 枚举落在哪一级 | ① `verdict_scope` | 开发者 | 否 |
| 枚举值描述 | ① `verdict_enum[].description` | 开发者 | 否；场景想补充含义写进 `description` |
| 依赖哪些轴 | ① `depend_on` | 开发者 | 否 |
| 哪些样本要判 | ① `trigger_when` | 开发者 | 否 |
| 判时看什么信息 | ① `inputs` | 开发者 | 否 |
| 场景描述 | ② `description` | 场景配置者 | 是——场景层唯一实质内容 |
| 是否启用 | ② `enabled` | 场景配置者 | 是，默认 false |
| 结论 | ④ `verdict`（axis 级）或 `output` 内逐项（item 级） | 运行器 | — |
| 跑没跑成 | ④ `status` | 运行器 | — |

---

## 4. 人类什么时候做什么

```
[开发者]              [场景配置者]             [评测执行者]          [所有人]
写一次                每个预设一次             每次试验              看结果

写 AxisType           预设编辑器里"添加轴"：    live.html：          同页并排
 - type_id             - 选类型                 发一次 live          - 旧轴1 vs 新 fulfillment
 - verdict_enum        - 写 description         点"判定"（旧链路）    - 旧轴2 vs 新 carryability
 - verdict_scope       - enabled=true           点"扩展轴试验"（新）  - 差异可解释？
 - depend_on
 - trigger_when
 - inputs
 - output_fields
 - limits
 - run()
```

### 4.1 开发者：定义一个轴类型（写一次）

两个内置类型按现有代码的真实行为填。**这些不再是示例。**

```python
# impl/projects/llm_probe/eval_axes/adapters/fulfillment.py

AXIS_TYPE = AxisType(
    type_id="fulfillment",
    title="能力兑现",
    summary="按场景描述派生期望，逐条判 output_text 是否兑现；整体状态程序派生",

    verdict_scope="axis",
    verdict_enum=[
        Verdict("fulfilled",     "所有 blocking 期望都兑现"),
        Verdict("not_fulfilled", "至少一条 blocking 期望未兑现"),
        Verdict("not_evaluable", "证据缺失（output_text 为空/不可读/HTTP 失败）或无 blocking 期望，无法判"),
    ],

    depend_on=[],
    trigger_when=None,
    inputs=[Input("trace", source="sample.trace")],       # 轴1看整份 RunTrace，与旧行为一致

    # 与 JudgeResult 同名，对照工具可直接 diff
    output_fields=["business_expectations", "fulfillment_assessments", "overall_fulfillment",
                   "reasoning_summary", "evidence", "summary", "expected", "actual",
                   "missing", "wrong", "extra"],
    verdict_path="overall_fulfillment.status",

    scenario_fields=[Field("description", required=True, expand="prompt_load")],
    limits=ExecutionLimits(llm_calls=2, tool_calls=0, seconds=None),   # 1 次 + 至多 1 次 reprompt
    run=run_fulfillment,
)
```

`run_fulfillment` 的流程 = `ProjectJudge.judge_trace` 那层编排的复制：

1. 复制 `LlmProbeJudge.build_context(trace)`，把 `resolve_capability(request)` 换成框里的 `description`（用 `expand_material_uris` 展开，超预算即拒，与旧路径同）。
2. 调 core `judge_trace(spec, trace, user_intent=None, project_judge_context=context)`——能力标准只放在 context 的 `capability`，用户意图由可见请求/对话推断；prompt 拼装、项目文档、槽位资料、上下文治理、结构化输出、自检、reprompt 全部原样。
3. `is_terminal_judge_failure(result)` 为真 → `status=failed`，`output` 保留诊断。
4. 复制 `LlmProbeJudge.normalize_result`（填 `actual` / `expected`），再 `finalize_judge_result` 程序派生 `overall_fulfillment.status`。
5. `verdict = output.overall_fulfillment.status`。

```python
# impl/projects/llm_probe/eval_axes/adapters/carryability.py

AXIS_TYPE = AxisType(
    type_id="carryability",
    title="承载性",
    summary="对轴1未达成的 blocking 期望逐条判：受治理能力空间承载得了（做错了）还是承载不了（做不了）",

    verdict_scope="item",
    verdict_enum=[
        Verdict("做不了", "能力边界资料自认承载不了；≠ 职责外"),
        Verdict("做错了", "能力边界证实承载得了，但这次没做对"),
        Verdict("说不清", "承载性判不了；必带差在哪儿（口径分歧/空间未受治理）和缺料"),
    ],
    item_path="placements[].placement",

    depend_on=["fulfillment"],
    trigger_when=When(axis="fulfillment", verdict_in=["not_fulfilled"]),
    inputs=[
        Input("fulfillment", source="axis.fulfillment.output",
              fields=["overall_fulfillment", "business_expectations", "fulfillment_assessments"]),
    ],
    # 没有任何 sample 来源：轴2不看这次交付了什么（协议 §5 第 6 条）

    output_fields=["applicable", "axis1_status", "placements", "errors", "snapshot_id"],
    scenario_fields=[Field("description", required=True, expand="catalog")],
    limits=ExecutionLimits(llm_calls=None, tool_calls=8, seconds=None),  # 每条期望 ≤3 次重试；每次调用 ≤8 次工具
    run=run_carryability,
)
```

`run_carryability` 的流程：

1. `class BoxBoundaryCarrier(TextCarrier)`：覆盖 `_current_boundary()`，返回 `expand_material_uris_with_catalog(description)` 的 `{text, catalog}`；同时覆盖 `_call_llm()`——prompt / 角色 / 工具 / 上限与父类逐行同构，只多传本次试验的 trace_id（D9）并计数 `usage`。`CapabilityCarrierBase` 只锁 `place`，其余方法可覆盖；大资料转目录 + 检索工具的路径与旧轴2完全一致。
2. `report = carrier.place(fulfillment_output)`——门控、逐 blocking NF 期望循环、`map_placement`、错误收集全部原样。运行器的 `trigger_when` 已保证进来的是 NF，`place()` 自己再查一次 `applicable` 是冗余但无害。
3. `errors` 非空 → `status=failed`（旧规则：任一条归位失败整 run 标 error），`output` 保留已完成的 placements 和 errors。
4. 逐项校验 `placements[].placement ∈ verdict_enum`；轴级 `verdict=null`。

#### 4.1.1 carryability 的依赖（已按代码定）

v3 列的 A/B/C 三种情况，代码对应的是 **C 减 `answer`**：

| 项 | 代码依据 |
|---|---|
| `depend_on=["fulfillment"]`、`trigger_when=not_fulfilled` | `place_not_fulfilled_payload`：`applicable = overall_fulfillment.status == "not_fulfilled"` |
| 读 `business_expectations`（含 `blocking`）+ `fulfillment_assessments` | 同上：过滤 blocking 且逐条 status 为 `not_fulfilled` 的期望 |
| 每条期望喂模型的字段 | `TextCarrier._expectation_text`：`expectation_id / user_intent / expected_outcome / acceptance_criteria` |
| 不读 `answer` | system prompt 原文"不看这次交付了什么"；`verdict_for(expectation)` 只收期望 |

#### 4.1.2 `run()` 内部怎么实现，由轴自己定

协议只固定三件事：拿到的输入（`inputs`）、交回的输出（`output_fields` + 枚举）、状态语义（§6）。`run()` 里用什么方法完成判定不受限：

- 复用现有函数（fulfillment 复用 core `judge_trace`）；
- 继承现有类改一个入口（carryability 继承 `TextCarrier`）；
- 整段复制再改（将来某个轴需要不同流程时）；
- 全新写（多阶段、逐断言核实、程序检查）。

这就是"扩展轴的实施方式不固定，按轴的判定需求定"的落点。两个内置轴选复用/继承，是因为目标是**和旧轴等价**，代码越少越不容易漂。

### 4.2 场景配置者：在预设编辑器里加框

位置：`资料页 → capability 预设 → 编辑某预设 → 新增一节「扩展评估轴（试验）」`。经典的加减框：

```
┌ 扩展评估轴（试验）────────────────────────────────────────┐
│ ┌ 轴 1 ──────────────────────────────────────── [删除] ┐ │
│ │ 类型  [能力兑现 fulfillment ▾]      启用 [x]           │ │
│ │ 描述  ┌────────────────────────────────────────────┐ │ │
│ │       │ 用户拿它办的事：……  {material://…}          │ │ │
│ │       └────────────────────────────────────────────┘ │ │
│ │ 只读：枚举 fulfilled/not_fulfilled/not_evaluable ·     │ │
│ │       不依赖其他轴 · 所有样本都判 · 读整份 trace        │ │
│ └──────────────────────────────────────────────────────┘ │
│ ┌ 轴 2 ──────────────────────────────────────── [删除] ┐ │
│ │ 类型  [承载性 carryability ▾]       启用 [x]           │ │
│ │ 描述  ┌────────────────────────────────────────────┐ │ │
│ │ 只读：枚举 做不了/做错了/说不清 · 依赖 fulfillment ·     │ │
│ │       仅 fulfillment=not_fulfilled 时判 · 读期望，不读回答│ │
│ └──────────────────────────────────────────────────────┘ │
│ [+ 添加轴]                                                 │
└────────────────────────────────────────────────────────────┘
```

- 类型下拉只列注册表里的类型，且排除本预设已用过的（一个预设每种类型只一个）。
- 描述文本框复用现有的 `{material://}` 引用插入和校验。
- 新建 fulfillment 框时预填旧字段 `capability` 的文字，carryability 预填 `boundary`——省得重敲，也让对照时两边描述一致。之后两边各自独立编辑，互不影响。
- 只读区从 `/api/eval_axes/types` 拿类型声明渲染。

存下来（`capability_map.json`，旧字段一个不动）：

```json
"policy_search": {
  "capability": "……",
  "boundary":   "……",
  "service":    {"url": "…", "method": "POST", "timeout_seconds": 60},
  "mock_body":  {"…": "{query}"},
  "axes": [
    {"type": "fulfillment",  "enabled": true, "description": "……{material://llm_probe/policy-capability}"},
    {"type": "carryability", "enabled": true, "description": "……{material://llm_probe/policy-boundary}"}
  ]
}
```

旧链路只读 `capability` / `boundary`，新运行器只读 `axes`。将来干掉旧链路 = 删这两个字段 + 删旧代码。

**配置者的边界**：能写描述、能启用、能加减框；不能改枚举、依赖、筛选、取数、流程、上限。

### 4.3 评测执行者：批量自动带上，单步页按钮对照

**批量 / 全链路（summary 页）**：不需要任何额外操作。旧轴2是挂在 `pipeline._run_payload` 里的判后 pass，新链路挂在它旁边：预设有启用的框就跑，结果挂 `run["eval_axes"]`，经 `compact_run` → `table_view.eval_axes_summary` 进表格第 14 列「扩展轴（试验）」（滚动框，每轴一块，每格 = 枚举值 + 理由）和 xlsx 导出。重跑 / 补跑一条 case 就是重算 judge + 裁决 + 扩展轴，没有挂在旧 run 上的状态要维护。同一行里「Score / Judge」「裁决」是旧结果，新列是新结果——批量级对照顺手就有。

core 不 import 项目代码：`impl/core/eval_axes.py` 按项目名声明式装载 `impl.projects.<id>.eval_axes.run_for_trace`（与轴2 `capability_provider` 同一装载方式），项目没有这个模块什么都不发生。扩展轴任何失败只落 `run["eval_axes"]["error"]`，不碰 `run_status` / JudgeResult / 裁决。

**单步页（live.html）**：
1. 选 case，点「发送」得到 `currentTrace`（调一次被测服务）。
2. 点「判定」——旧链路：轴1结果 + 面板里的轴2归位（现有按钮，不改）。
3. 点「扩展轴试验」——新链路：把**同一个** `currentTrace` 发给 `/api/eval_axes/run`，新面板独立渲染，旁边就是旧面板。「统一全链路」走 `_run_payload`，自动带上。

不落盘。被测服务得在线；每次都是新鲜一跑，模型有波动，"复制等价"按"结论一致或差异可解释"判，不按逐字节。启用框以后每条 case 会跑旧 judge 一次、新 fulfillment 一次（再加各自的轴2），模型调用翻倍是对照期的固有成本，干掉旧链路那天回到一倍。

---

## 5. 运行器：固定五步，不做通用 DAG

对每个 样本 × 轴，按 `depend_on` 拓扑序：

```
1. enabled?                              否 → status=disabled
2. depend_on 里的轴全部 succeeded?        否 → status=blocked（trigger_decision 记上游实际状态）
3. trigger_when 命中?                     否 → status=not_applicable
4. 按 inputs 声明逐项取数                 必填缺失 → status=failed
   （sample.trace / 上游 output 的具名字段，只给声明的字段）
5. run()                                  → status=succeeded | failed
   axis 级：verdict ∈ verdict_enum（仅 succeeded 时非空）
   item 级：output 内 item_path 的每个值 ∈ verdict_enum；verdict=null
   output 的键集 == output_fields
```

第 2、3 步的求值结果和第 4 步实际取到的来源，都记进 AxisResult。每次试验用一个 `axes-<uuid>` 的 trace_id，所有 LLM 调用记录和 `execution_trace_ref` 都挂在它上面。

第 5 步之后还有一道：**判了就必须能解释**。`run()` 返回的 `summary`（一句话 `text` + 逐格 `items[{key, value, reason}]`）为空 → 与枚举越界同样落 `failed`。没跑成的轴由运行器填 `summary.text`（`未启用` / `上游未成功：fulfillment=failed` / `fulfillment=fulfilled，不在筛选范围 […]，不判` / 错误原文）；adapter 若在失败时交了已完成部分的逐格结果（如轴2部分归位），保留作诊断。

---

## 6. 轴结果：每轴一条，不合并

```yaml
# axis 级示例
run_id: axes-3f9c…
case_id: …
scenario_id: policy_search           # = capability_ref
axis_id: fulfillment                 # = type_id
type_id: fulfillment
verdict_scope: axis
status: succeeded                    # disabled|blocked|not_applicable|succeeded|failed
title: 能力兑现
verdict: not_fulfilled
verdict_description: "至少一条 blocking 期望未兑现"
summary:                             # 复制旧轴1：text = summary_from_fulfillment 的 reason；items = 每条期望的 status + 证据
  text: "not_fulfilled · blocking=[按年龄筛选] · 输出缺少年龄条件"
  items:
    - {key: 按年龄筛选, value: not_fulfilled, reason: "无年龄条件 | age<30", blocking: true}
trigger_decision: {depend_on_satisfied: true, trigger_when_matched: null}
inputs_used: {trace: sample.trace@<trace_id>}
output: {business_expectations: […], fulfillment_assessments: […], overall_fulfillment: {…}, …}
usage: {llm_calls: 1, tool_calls: 0, elapsed_ms: 8421,
        llm_model: gpt-5.6-luna, llm_endpoint: fallback1, llm_attempts: 1, llm_failed_attempts: 0, model_policy: any}
config_fingerprint: sha256(type + enabled + description 展开后正文)
implementation_fingerprint: sha256(adapter 文件 + 其声明复用的文件)
execution_trace_ref: axes-3f9c…
```

```yaml
# item 级示例
axis_id: carryability
verdict_scope: item
status: succeeded
verdict: null                        # item 级没有轴级单值
summary:                             # 复制旧轴2：text = "裁决"列原文 carrier_text；items = 每条归位 + 理由
  text: "$做不了\n按姓名精确检索（…）\n\n$说不清\n返回生效日期（…；缺…）"
  items:
    - {key: 按姓名精确检索, value: 做不了, reason: …, carry: no}
    - {key: 返回生效日期, value: 说不清, reason: "…；差在哪儿：空间未受治理；缺料：…", carry: undecidable}
trigger_decision:
  depend_on_satisfied: true
  trigger_when_matched: {axis: fulfillment, verdict: not_fulfilled}
inputs_used:
  fulfillment: axis.fulfillment.output[overall_fulfillment, business_expectations, fulfillment_assessments]@axes-3f9c…
output:
  applicable: true
  axis1_status: not_fulfilled
  placements:
    - {expectation_id: 按姓名精确检索, placement: 做不了, carry: no, reason: …, citations: […], recognition: boundary_statement}
    - {expectation_id: 返回生效日期,   placement: 说不清, carry: undecidable, gap_kind: 空间未受治理, missing_material: …}
  errors: []
  snapshot_id: 1a2b…
usage: {llm_calls: 2, tool_calls: 3, elapsed_ms: 15210}
```

状态规则（写死，不由配置者碰）：

| 情况 | status | verdict / output |
|---|---|---|
| fulfillment 模型调用失败或输出校验失败（`llm_call_failed` / `llm_output_validation_failed`） | `failed` | verdict null；output 保留诊断 |
| fulfillment 正常返回，含 `not_evaluable` | `succeeded` | verdict = 三态之一 |
| carryability 任一条期望归位失败（重试耗尽、引用核验不过、工具失败） | `failed` | output 保留已完成 placements + errors |
| carryability 全部归位 | `succeeded` | 逐项 placement |
| 上游 `failed` / `blocked` / `not_applicable` / `disabled` | `blocked` | trigger_decision 记上游状态 |
| 上游 verdict 不在 `verdict_in` | `not_applicable` | — |

`not_evaluable` / `说不清` 是"判了，判不出"，进 verdict/output；`failed` 是"没跑成"，进 status。二者不混。

---

## 7. 加载期校验（读预设 `axes` 时）

| 规则 | 级别 |
|---|---|
| `type` 必须在注册表里 | 错误 |
| 一个预设内同一 `type` 只允许一个 | 错误 |
| `description` 非空，`{material://}` 引用合法（按类型的 `expand` 方式展开成功） | 错误 |
| `depend_on` 引用的类型必须在本预设内已启用 | 错误 |
| `depend_on` 不得成环 | 错误 |
| `trigger_when` 引用的类型必须是 `verdict_scope=axis`，且 `verdict_in` 的值都在其 `verdict_enum` 里 | 错误 |
| `inputs` 引用的上游字段必须在上游类型的 `output_fields` 里 | 错误 |
| `trigger_when` / `inputs` 引用的类型必须在 `depend_on` 里 | 错误 |
| `depend_on` 里的类型在 `trigger_when` 和 `inputs` 中均未被引用 | 警告 |

保存时（`capability_store.validate_entry`）只校形状：`axes` 是列表、每项 `type` 是标识符、`description` 非空且不超长、引用合法、`type` 不重复。类型是否已注册不在 core 里查——core 不 import 项目代码。

---

## 8. 目录落地与共享文件触点

```
impl/projects/llm_probe/eval_axes/
  types.py            # AxisType / Verdict / Input / When / Field / ExecutionLimits / AxisResult
  registry.py         # {"fulfillment": AXIS_TYPE, "carryability": AXIS_TYPE}
  validate.py         # §7 加载期校验；读预设 axes → 校验过的 ScenarioAxis 列表
  runner.py           # §5 五步；拓扑排序；trigger_decision / inputs_used / usage / fingerprints
  llm.py              # 扩展轴的 LLM 外壳：记账实际端点/模型 + 模型策略路由视图（D12）
  adapters/
    fulfillment.py    # 复制 build_context + 编排；复用 core judge_trace / finalize_judge_result
    carryability.py   # 继承 TextCarrier 覆盖 _current_boundary；复用 place()
```

新增一个 core 模块：`impl/core/eval_axes.py`——按项目名声明式装载 `run_for_trace`，与轴2 `capability_provider` 同款，core 不 import 项目代码。

共享文件只碰这几处，全是加法：

| 文件 | 改什么 |
|---|---|
| `impl/core/capability_store.py` | `validate_entry` 接受并校验 `axes`（否则保存时被丢） |
| `impl/config.yaml` `impl/core/config_schema.py` `impl/core/config.py` | 新增可缺省的 `eval_axes.model_policy`（默认 `any`）与注册的 `.env` 变量 `EVAL_AXES_MODEL_POLICY`；走既有类型化配置合同 |
| `impl/core/pipeline.py` | `_run_payload` 里紧挨旧轴2加一个判后 pass：`run["eval_axes"] = eval_axes_report(...)`，try 住，不碰 `run_status` |
| `impl/core/table_view.py` `schema/table.py` `schema/normalize.py` | `TraceTableRow.eval_axes_summary`（每轴一条 `{axis_id, title, status, verdict, text, items}`），与 `carrier_placement` 之于"裁决"列同一角色 |
| `impl/server/models.py` `routes.py` `service.py` | `/api/eval_axes/types`、`/api/eval_axes/run`；`compact_run` 透传 `eval_axes` |
| `impl/frontend/materials.html` | 预设编辑器加"扩展评估轴（试验）"加减框 |
| `impl/frontend/live.html` | 加「扩展轴试验」按钮 + 独立结果面板 |
| `impl/frontend/summary.html` `case_pool_export.js` | 第 14 列「扩展轴（试验）」（滚动框 + 逐格）；导出多一列 |
| `tests/test_llm_probe_eval_axes.py` | 新增；复用 `test_llm_probe_text_carrier.py` 的 `_completer` 夹具 |

不碰：`project.yaml`、`config.yaml`、`impl/core/judge.py`、`capability_carrier.py`、`text_carrier.py`、`judge_protocol.py`。不需要：新 artifact family（`capability_map_store` 的校验调的就是 `validate_entry`，自动覆盖 `axes`）、`ALLOWED_STORES`、资料页新 section、样本库、基线库。

复用：Agno / LlmClient / material_tools / 结构化校验 / 上下文记录。角色沿用 `judge` 和 `capability_carrier_mapper`，未注册角色自动回落默认策略，不改配置。

---

## 9. 实施顺序

1. `types.py` / `registry.py` / `validate.py` / `runner.py` + 两个 adapter，单测用确定性假 LLM 跑通"一个 trace → 两个 AxisResult"（不碰共享文件，生产零影响）。
2. `capability_store.validate_entry` 加 `axes`；`validate.py` 从预设读框。
3. 两个端点。
4. `live.html` 按钮 + 面板；`materials.html` 加减框。
5. 用真实模型在 4 个预设上各跑若干 case，人工看新旧对照，差异逐条归到 §11 或归到 bug。
6. 验过之后再谈：批量对照、第三个类型、生产切换。

---

## 10. 首版验收

| 项 | 判定 |
|---|---|
| 类型可见 | 预设编辑器下拉能看到 2 个类型；只读区枚举分别为 `fulfilled/not_fulfilled/not_evaluable` 与 `做不了/做错了/说不清` |
| 特化可见 | 框里的 `description` 出现在实际 prompt 里（上下文页可查） |
| 场景零结构 | `axes[]` 每项只有 `type / enabled / description` |
| 依赖生效 | fulfillment=fulfilled 或 not_evaluable 时 carryability 落 `not_applicable`；fulfillment failed 时落 `blocked`；均不发 LLM 调用 |
| 信息隔离 | carryability 的 `inputs_used` 只有 fulfillment output 的三个字段；adapter 拿不到 `output_text`、拿不到 trace |
| 校验生效 | 预设里 carryability 启用而 fulfillment 未启用 → 加载报错；`trigger_when` 引用 item 级类型 → 加载报错 |
| 复制等价 | 同一 trace 上，新 fulfillment 的 `overall_fulfillment.status` 与旧轴1一致或差异可解释；新 carryability 的 placements 与旧轴2面板一致或差异可解释；summary 页同一行里新列的 `text` 与「Score / Judge」「裁决」可直接对读 |
| 有解释 | 每条 `succeeded` 的 AxisResult 都有非空 `summary.text`；逐格 `items` 的 `value` 都在该类型枚举内；没跑成的轴 `summary.text` 说清为什么没发 / 为什么失败 |
| 生产隔离 | 预设没有启用的框：批量 / 全链路 run 的键集与改动前一致，零额外模型调用；启用了：只多 `eval_axes` 键，`run_status` / judge / 裁决不变；扩展轴自身异常只落 `eval_axes.error` |
| 大资料 | boundary 引用超预算资料的预设（如 `client_search`），新 carryability 的调用记录里能看到 `material_*` 工具调用 |

---

## 11. 与旧链路的已知差异（对照时先排除这些）

| 差异 | 旧 | 新 | 为什么 |
|---|---|---|---|
| 轴1执行失败的表达 | `overall_fulfillment.status=not_evaluable` + evidence 标记 | `status=failed`，verdict null | status / verdict 分离（§6） |
| 轴2部分失败的表达 | run 级 `run_status=error` | 轴级 `status=failed`，output 保留 | 同上；语义等价 |
| 描述来源 | `capability` / `boundary` 字段 | 框的 `description` | 新建框时预填，之后独立编辑；对照前确认两边一致 |
| 请求内联覆盖 | `request.capability` / `request.boundary` 优先于预设 | 忽略请求内联，只用框 | 新链路的描述来源唯一；带内联覆盖的 case 对照时标注 |
| 预设没有 boundary | 旧轴2照跑，每条 NF 期望落「说不清 / 未填写能力边界描述」 | 没有 carryability 框，什么都不显示 | 框必须有描述；没有边界就没有承载性可判 |
| 轴2的输入期望文本 | 来自旧轴1本次的期望 | 来自新 fulfillment 本次的期望 | 两条链路各自派生期望，措辞不同是固有的，对照按 placement 分布看 |
| LLM 记录标签 | `caller=judge` / `capability_carrier_mapper` | 同样标签，trace_id 带 `axes-` 前缀 | D9 |
| 上限 | 无轴级上限 | 声明 + 记录，`tool_calls` 硬限 | D8 |

---

## 12. 冻结与留待

**现在冻结（结构）**

- AxisType 字段集：`type_id` `title` `summary` `verdict_scope` `verdict_enum` `verdict_path`/`item_path` `depend_on` `trigger_when` `inputs` `output_fields` `scenario_fields` `limits` `run`
- ScenarioAxis 只含 `type` `enabled` `description`，存在预设 `axes[]`
- AxisResult 字段集；`status` 与 `verdict` 分离；item 级 `verdict=null`；`summary = {text, items[{key, value, reason}]}` 必有
- 判后 pass 的挂载点（`_run_payload`）与隔离合同（D11）
- 运行器五步顺序；§6 状态规则；§7 校验规则
- 一个预设每种类型只一个，实例名 = 类型名

**已按代码填定（值）**

- 两个类型的枚举、`depend_on` / `trigger_when` / `inputs` / `output_fields`、`run()` 的实现方式（§4.1）

**明确不做，将来有需求再开**

- `trigger_when` 的样本字段筛选、场景级覆盖
- 同预设多实例（届时 `depend_on` 升级为实例名）
- 批量对照、结果落盘
- `limits` 硬执行 `llm_calls` / `seconds`（要改共享 LLM 客户端）
- 通用 DAG 引擎
