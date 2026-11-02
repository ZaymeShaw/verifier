# 扩展评估轴的最小抽象

本文只回答一个问题：**人类定义的轴，如何在一个场景中被系统按依赖执行，并产出可比较的结果。**

## 1. 人类真正配置的四类东西

一个场景里的一个轴实例由四部分组成：

```text
轴实例 = 类型选择 + 场景特化 + 输入/资料绑定 + 调度规则
```

- **类型选择**：选择哪个 `AxisType`，也就是使用哪一个 Adapter。
- **场景特化**：填写本场景的轴描述、判定标准、枚举值及枚举值描述。
- **输入/资料绑定**：声明这个轴要读取样本的哪些信息、哪些上游轴结果、哪些资料。
- **调度规则**：声明何时发动，以及是否依赖其他轴。

类型是开发者定义的；场景特化、绑定和调度是资料页由人类填写的。

## 2. 核心对象

### 2.1 轴类型 AxisType

`AxisType` 是一套稳定的评估方法，与具体场景的业务标准分开：

```text
AxisType = {
  type_id,
  adapter_id,
  input_ports,
  config_fields,
  output_contract,
  execution_policy
}
```

- `type_id`：类型标识，例如 `fulfillment`、`carryability`。
- `adapter_id`：该类型对应的 Adapter 实现。
- `input_ports`：该方法允许获取的输入端口。
- `config_fields`：场景必须填写的特化字段。
- `output_contract`：结果必须包含什么。
- `execution_policy`：超时、预算、阶段和重试边界。

新版轴1和新版轴2各自注册为一种 `AxisType`，复制旧轴专属逻辑实现；旧轴1、旧轴2继续独立作为生产基线。

### 2.2 场景轴实例 AxisInstance

人类在 `llm_probe` 的场景资料页中创建的是 `AxisInstance`：

```text
AxisInstance = {
  axis_id,
  type_id,
  enabled,
  description,
  verdict_scale,
  information_bindings,
  material_refs,
  depend_on,
  fire_when,
  order
}
```

字段归属如下：

| 字段 | 人类填写内容 | 作用 |
|---|---|---|
| `axis_id` | 本场景内唯一名称 | 供其他轴引用 |
| `type_id` | 选择轴类型 | 决定使用哪个 Adapter |
| `enabled` | 是否启用 | 决定是否进入本次扩展评估 |
| `description` | 本场景要评估什么、按什么口径 | 轴类型的场景特化 |
| `verdict_scale` | 枚举值及每个值的描述 | 规定本场景的合法结论 |
| `information_bindings` | 样本、上游轴、资料的来源 | 规定 Adapter 能获取什么 |
| `material_refs` | 可使用的资料 | 提供判定依据 |
| `depend_on` | 依赖哪些轴 | 规定数据/时序依赖 |
| `fire_when` | 什么条件下发动 | 规定触发条件 |
| `order` | 同层执行顺序（必要时） | 只表达时序，不自动传数据 |

### 2.3 枚举值 VerdictScale

每个轴实例都必须声明封闭的枚举值：

```text
verdict_scale = [
  { value: fluent, description: "表达自然、连贯、易读" },
  { value: minor_issues, description: "存在轻微不流畅，但不影响理解" },
  { value: not_fluent, description: "明显影响理解或阅读体验" },
  { value: unclear, description: "证据不足，无法可靠判断" }
]
```

`value` 是机器消费的稳定标识，`description` 是该场景的人类判定口径。`unclear` 是强制保留的诚实出口。枚举值属于 `AxisInstance`，不是 Adapter 的硬编码业务结论。

## 3. 系统运行时序

```text
① 人类在 llm_probe 场景页配置 AxisInstance
        ↓
② 系统校验 type_id、枚举值、绑定、depend_on 和 fire_when
        ↓
③ 系统根据 depend_on 构建执行计划
        ↓
④ 到达 fire_when 时，准备该轴声明的输入和资料
        ↓
⑤ 调用对应 Adapter，Adapter 执行自己的评估流程
        ↓
⑥ 校验 Adapter 输出是否符合该轴的 verdict_scale 和结果协议
        ↓
⑦ 保存该轴结果，供声明依赖它的后续轴读取
        ↓
⑧ 汇总本场景所有轴结果；必要时与旧轴基线比较
```

## 4. 依赖、发动时间和信息获取

### 4.1 `information_bindings`：获取什么

每个 Adapter 只能读取在类型端口中声明、并在场景实例中绑定的输入：

```yaml
information_bindings:
  request:  { source: sample, port: request }
  answer:   { source: sample, port: answer }
  axis1:    { source: axis, axis_id: fulfillment, port: result }
  policy:   { source: material, ref: policy-boundary }
```

- `sample`：本次样本的请求、回答、上下文等。
- `axis`：已完成的上游轴结果。
- `material`：资料页选定的资料快照。

未声明的输入不能被 Adapter 读取；绑定缺失属于运行错误或不适用，不能静默补值。

### 4.2 `depend_on`：依赖谁

```yaml
depend_on:
  - axis_id: fulfillment
    relation: result
```

`relation: result` 表示既要等待该轴完成，也允许读取它声明的结果。若只需要等待而不读取结果：

```yaml
depend_on:
  - axis_id: safety
    relation: completion
```

所有依赖边必须构成无环图。下游结果不能回写或改变上游结果。

### 4.3 `fire_when`：什么时候发动

```yaml
fire_when:
  type: axis_result
  axis_id: fulfillment
  values: [not_fulfilled]
```

第一版只允许有限的声明式条件：

- `always`：输入就绪后发动；
- `axis_result`：上游轴结果落在指定值时发动；
- `sample_predicate`：样本元信息满足指定条件时发动。

条件不满足时，轴结果为 `not_applicable`，不调用 Adapter。

## 5. Adapter 的职责边界

Adapter 决定“**怎么评估**”，但不能改变场景协议：

```text
Adapterᵢ(
  description,
  verdict_scale,
  bound_information,
  material_snapshot,
  runtime_policy
) → AxisDecision
```

Adapter 可以采用不同的 prompt、阶段、工具、检索、复核、程序检查和重试流程；但必须：

1. 只读取绑定的信息；
2. 只输出声明过的枚举值；
3. 说明理由并提供可追溯引用（该类型若要求引用）；
4. 在证据不足时使用 `unclear`；
5. 遵守预算、超时和取消边界。

因此，“类型轴”决定方法，“场景轴实例”决定本场景的具体口径，“Adapter”决定执行流程。

## 6. 最小结果协议

```text
AxisResult = {
  axis_id,
  type_id,
  execution_status,
  verdict,
  rationale,
  citations,
  input_refs,
  material_refs,
  timing,
  usage
}
```

其中：

```text
execution_status ∈ {succeeded, not_applicable, failed, timed_out, cancelled}
verdict ∈ verdict_scale ∪ {unclear}
```

`failed` 表示方法没有成功完成；`unclear` 表示方法完成了判断但证据不足；`not_applicable` 表示该轴按触发规则不适用。三者不能混用。

## 7. 当前体系的最小不变量

```text
场景配置决定：评估哪些轴、按什么口径、读什么信息、何时发动
AxisType 决定：使用哪个 Adapter 和哪种方法
Adapter 决定：实际执行流程
公共运行器保证：依赖、边界、预算、结果校验和记录
```

旧轴1/轴2与新版扩展轴1/轴2在同一冻结样本上分别运行。新版链路不调用旧链路；比较器只比较两边已保存的结果。
