# 扩展评估轴方案审核说明

日期：2026-09-05  
用途：提交给其他评审者复核当前扩展评估轴方案。本文区分“用户已明确回答”“代理提出的建议”“仍待审核的问题”，不把方案文档中的示例或代理推断当成用户确认。

## 1. 审核范围与背景

当前主文档为 `spec/adapter/axe.md`。目标是在 `llm_probe` 内建设扩展评估轴试验体系：

- 复制现有轴1、轴2的专属逻辑，形成扩展体系内的新版轴1、轴2；
- 暂不启用新版轴1、轴2到生产链路；
- 继续保留现有生产轴1、轴2，作为效果对比基线；
- 允许新增轴类型，并由不同 Adapter 实现不同评估流程；
- 场景可以对同一轴类型填写自己的描述、资料、枚举说明、输入和依赖。

本说明只审查设计理解和协议问题，不实现代码。

## 2. 用户已明确回答的事项

### 2.1 轴1的整体枚举值

用户明确确认：

> “第一点确实你说的对，应该是 fulfilled、not_fulfilled、not_evaluable”

因此，扩展体系中的新版轴1如果要复制现有轴1语义，整体结论应先沿用：

```text
fulfilled
not_fulfilled
not_evaluable
```

`met / partial / not_met` 不能继续作为新版轴1整体结论的默认示例，除非之后另行定义其与现有轴1三态及逐条 expectation 结果的关系。

这项回答只确认轴1三态；不等于用户已经确认了其他枚举、聚合规则或全部配置细节。

## 3. 用户提出的问题与当前解释

### 3.1 `inputs` 的定位

用户询问：

> “第二点我不太确定，我先问问这两（inputs、depend_on）的定位分别是啥？”

最小解释是：

```text
inputs：本轴运行时实际拿哪些输入，以及这些输入从哪里来
```

典型来源包括：

```text
sample.request
sample.answer
sample.context
material.<资料引用>
```

`inputs` 解决的是“取数/信息获取”问题。它应回答：

- Adapter 能看到哪些样本字段？
- 每个输入在 Adapter 中叫什么名字？
- 输入来自样本、资料，还是上游轴？
- 可选输入缺失时如何处理？

### 3.2 `depend_on` 的定位

最小解释是：

```text
depend_on：本轴执行前需要等待哪些轴，以及是否需要读取这些轴的结果
```

它解决的是“执行关系”问题。至少要区分：

1. 等待上游轴完成；
2. 是否读取上游轴输出；
3. 上游轴必须处于什么状态；
4. 上游结果是否进一步决定本轴是否发动。

需要注意：这只是两个字段的职责解释，不代表用户已经确认了某一种字段合并方式。

目前仍有两种待审核的配置表达方式：

```yaml
# 方案 A：上游结果在 inputs 中绑定，depend_on 只表达等待/触发
inputs:
  fulfillment: axis.fulfillment.output
depend_on:
  - axis: fulfillment
    require: succeeded
```

或：

```yaml
# 方案 B：上游结果绑定并入 depend_on
inputs:
  request: sample.request
depend_on:
  - axis: fulfillment
    require: succeeded
    read_output: true
    output_as: fulfillment
```

`output_as` 是代理提出的设计建议，不是用户已经确认的结论。交给评审者时应重点比较两种表达是否足够清楚、是否会产生重复声明和信息泄露问题。

## 4. 关于 `depend_on` 和 `trigger_when` 的当前状态

用户的理解是：

> “第三点我理解depend_on是依赖的轴？trigger就是轴的结果？”

需要纠正为：

```text
depend_on：声明依赖哪个轴以及等待/读取关系
trigger_when：对已得到的上游状态或结果进行条件判断
```

例如：

```yaml
depend_on:
  - axis: fulfillment
    require: succeeded
    read_output: true
    trigger_when:
      verdict_in: [not_fulfilled]
```

这里：

- `fulfillment` 是依赖的轴；
- `verdict=not_fulfilled` 是上游轴已经产生的结果事实；
- `trigger_when` 是“只有该事实满足条件时才发动本轴”的规则；
- `trigger_when` 本身不是结果。

用户同时明确表达了保留意见：

> “但是确实依赖的这个东西为啥是这样定，和不合理似乎还是有待商榷的其实”

因此，下列内容目前都不能写成已确认：

- 所有依赖都必须等待上游 `succeeded`；
- 多个依赖必须全部满足；
- 只支持 `verdict_in`；
- `depend_on` 中必须同时承载输入绑定；
- 触发条件只允许读取某一种上游状态。

这些是首版实现候选规则，应该由评审者继续审查其合理性。

还要区分：调度器为了判断触发条件而读取上游的 `status/verdict`，不等于下游 Adapter 自动可以读取上游完整 output 或 execution trace。调度控制信息和模型输入权限是两层边界。

## 5. 关于上一轮“第四点”的状态

上一轮代理提出的第四个问题是：

> 多个逐条结果如何聚合为一个轴级 verdict？例如部分承载、部分不可判定、部分执行失败时，`mixed`、`undecidable`、`failed` 的优先级如何确定？

用户反馈：

> “第四点我没看懂你在说啥”

这表示用户尚未对该问题形成意见，也没有确认任何聚合方案。该问题需要用具体例子重新解释后再请评审者判断。

当前不能把下面任何一种规则当成既定设计：

```text
只要有一条失败，整轴 failed
只要有 yes 和 no，就一定 mixed
只要有 undecidable，就一定 undecidable
由 LLM 再做一次整体汇总
```

## 6. 现有轴2语义的事实纠正

上一轮代理曾给出过错误示例：

```text
carry=yes  → out_of_scope
carry=no   → in_scope_missed
```

这与当前代码和协议不符，必须在评审时明确标注为代理错误，而不是用户要求或文档差异。

现有实现 `impl/core/capability_carrier.py:412` 的实际映射是：

```text
轴1 not_fulfilled 且 carry=no  → 做不了
轴1 not_fulfilled 且 carry=yes → 做错了
carry=undecidable               → 说不清
```

现有协议还明确：

- 轴2只对轴1的 `not_fulfilled` 期望运行；
- 轴2判定的是能力空间是否承载得了；
- “做不了”不等于职责外；
- “做错了”是轴1未达成且能力空间承载得了；
- 资料或工具失败不能伪装成业务上的“说不清”；
- 轴2不能查看本次交付内容，也不能回写轴1结论。

因此，新版轴2如果以复制旧轴2为目标，必须先逐项保留这些语义，再讨论是否增加场景层的展示性轴级枚举。

## 7. 当前已经可以认为稳定的设计方向

以下方向已经有足够共识，可以作为实现前提：

1. 一个 `AxisType` 对应一套 Adapter 方法；
2. 场景通过 `ScenarioAxis` 选择类型并填写特化配置；
3. 场景特化至少包括描述、资料、枚举说明、输入绑定、依赖和发动条件；
4. 不同轴类型允许拥有不同的执行流程；
5. 同一 Adapter 不应因为场景名称不同而偷偷变成另一套代码方法；
6. 新版轴1、轴2在扩展体系内部复制实现；
7. 旧生产轴1、轴2不改动，继续作为基线；
8. 运行结果必须记录轴、场景、输入、触发原因、状态、结论、引用、时间和消耗；
9. 生产链路不因扩展轴试验而隐式双跑或自动切换。

## 8. 提交给评审者的核心问题

请重点复核以下问题，而不是重新讨论整体方向：

1. `inputs` 是否只负责信息来源，`depend_on` 是否只负责执行关系？上游 output 绑定应放在哪一处，如何避免重复声明？
2. `depend_on` 是否同时表达等待、读取和触发，还是应拆成多个字段？哪种对人类配置更清楚？
3. 调度器可读取的 `status/verdict` 与下游 Adapter 可读取的 output 是否需要严格分层？
4. `trigger_when` 应支持哪些最小条件，如何避免变成任意表达式系统？
5. 轴2的逐条结果是否需要轴级 verdict？如果需要，聚合规则如何保证确定性，并保持旧轴2语义？
6. 类型层固定枚举值、场景层只补充枚举描述，是否足以同时保证稳定性和场景灵活性？
7. 新版轴1是否完全沿用 `fulfilled / not_fulfilled / not_evaluable`，逐条结果如何承载部分达成信息？

## 9. 结论

当前不是“方案方向未定”，而是“核心方向已定，几个协议细节需要外部复核”。

已确认的关键点只有轴1三态及整体架构方向；`inputs`/`depend_on` 的最终字段组织、依赖条件设计、`trigger_when` 的能力边界和逐条到轴级结果的聚合规则仍属于待审核内容。

## 10. 用户最新补充后的重新复核

用户进一步说明：

> “trigger_when实际指示的是哪些样本要做判定（要给出一个类似筛选样本的东西）。depend_on是该轴依赖哪些轴的结果（所以要指定轴名），inputs这个东西比较复杂，现在我也不太确定”

这使三个概念的首要定位更清楚了：

```text
trigger_when：样本筛选条件，决定本样本是否进入该轴判定
depend_on：轴结果依赖，决定本轴依赖哪些上游轴及其结果条件
inputs：Adapter 实际收到的输入投影，决定把哪些信息以什么名字交给它
```

### 10.1 建议保留 `inputs` 与 `depend_on` 两个字段

它们不是同一个东西，也不应为了简化而合并：

| 问题 | `depend_on` | `inputs` |
|---|---|---|
| 回答什么 | 本轴依赖哪些轴结果 | Adapter 实际拿到哪些信息 |
| 主要消费者 | 调度器 | Adapter |
| 是否建立等待关系 | 是 | 否，单独出现时不建立 |
| 是否决定信息投影 | 可声明结果条件，但不决定传哪些字段 | 是，决定名称和字段/投影 |
| 典型来源 | `axis_id=fulfillment` | `sample.answer`、`axis.fulfillment.output`、资料快照 |

两者可以交汇，但交汇是有明确含义的：

```yaml
depend_on:
  - axis: fulfillment
    require: succeeded
    result_in: [not_fulfilled]

inputs:
  request: sample.request
  answer: sample.answer
  fulfillment_result: axis.fulfillment.output
```

这里 `depend_on` 让运行器先等待并检查 `fulfillment` 的结果；`inputs` 再决定将该结果的哪一部分以 `fulfillment_result` 的名字交给 Adapter。若只需要等待、不需要读取结果，则保留 `depend_on`，不在 `inputs` 中绑定该轴。若 `inputs` 引用了某轴 output 却没有对应 `depend_on`，配置校验应直接拒绝，不应运行时自动猜测。

### 10.2 `trigger_when` 首版应作为样本筛选器

按用户最新理解，`trigger_when` 首版只判断样本及场景元信息，例如：

```yaml
trigger_when:
  sample:
    kind: policy_question
    has_reference: true
```

条件满足，样本进入该轴；条件不满足，结果为 `not_applicable`，不调用 Adapter。

它不应在首版同时承担“依赖轴结果后的条件分支”，否则一个字段会同时表示样本筛选和轴间控制，仍会回到原来的混淆。轴2这种“只在轴1为 `not_fulfilled` 时才运行”的规则，应归入 `depend_on` 的结果条件：

```yaml
depend_on:
  - axis: fulfillment
    require: succeeded
    result_in: [not_fulfilled]
```

这样：

- `trigger_when` 决定这个样本是否属于本轴评估范围；
- `depend_on` 决定上游轴是否完成、结果是否允许本轴发动，以及是否能提供上游 output；
- `inputs` 决定 Adapter 实际看到哪些已绑定信息。

### 10.3 当前 `axe.md` 需要同步修正的地方

`axe.md` 目前仍把 `trigger_when` 嵌在 `depend_on` 示例中，并用 `partial/not_met` 作为新版轴1条件。这与用户已经确认的轴1三态不一致，也没有体现“`trigger_when` 是样本筛选器”的新理解。

在继续实现前，至少应把示例收敛为：

```yaml
trigger_when: <sample predicate>

depend_on:
  - axis: fulfillment
    require: succeeded
    result_in: [not_fulfilled]

inputs:
  request: sample.request
  answer: sample.answer
  fulfillment_result: axis.fulfillment.output
```

首版应使用结构化样本字段筛选，不开放任意表达式。`result_in` 的确切字段名仍可调整，但三种语义必须保持分离。这里的字段组织是当前基于用户补充提出的最小候选方案，不应倒写成用户已经确认了具体 YAML 名称。

### 10.4 目前真正剩下的审核点

在这个新分层下，仍需外部评审的主要问题缩小为三项：

1. `depend_on` 的结果条件是否应该直接写在依赖项中，还是单独设一个轴结果门控字段；
2. `inputs` 对 sample、material、axis output 是否使用同一套绑定格式，还是按来源分组；
3. 轴2的依赖条件应读取新版轴1的整体 `not_fulfilled`，还是读取逐条 expectation 的未达成集合。

这三项是协议细节，不改变“类型轴 + 场景特化 + 样本筛选 + 轴结果依赖 + Adapter 信息输入”的总体方向。
