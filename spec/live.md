# Live 模块完整方案

## 一、live 的本质：业务系统在评测系统中的具现化

live 不是 verifier 自己的组件，它是**被测业务系统在评测系统中的具现化**。verifier 不能直接操作业务系统，于是用 live 环节作为业务系统的代理接入点——业务系统的真实行为通过 live 环节进入 verifier，变成可观测、可判定的事实。

正因如此，live 环节的输入输出**必须与业务系统对应的 live_schema 严格对齐**：

- **输入对齐 REQUEST_SHAPE**：业务系统真实接受什么形状的请求，live_schema 的 REQUEST_SHAPE 就描述什么形状，live 环节构造的 normalized_request 必须符合它。这是"业务系统能识别的请求"在评测侧的具现。
- **输出对齐 EXTRACT_OUTPUT_SHAPE**：业务系统真实返回什么形状的响应，live_schema 的 EXTRACT_OUTPUT_SHAPE 就描述什么形状，live 环节提取的 extracted_output 必须符合它。这是"业务系统的响应"在评测侧的具现。

live 环节对外只做一件事：**输入 case，产出符合契约的输出，连同调用过程的原始事实一起塞进 trace**。调用方不关心环节内部怎么拿到输出的，只关心 trace 里有了 live 这段的事实。

---

## 二、内部四种投递方式

四种方式是"业务系统具现化"的不同形态——取决于业务系统是否可调、是否有预制响应、调用是否成功。它们对外不可见，共享入口、产同一种事实原件：

1. **真实调用**：业务系统可调，直接接业务系统，从原始响应提取符合契约的输出。
2. **provided**：业务系统不可调或无必要调，case 自带预制输出，直接取。
3. **fallback**：业务系统不可达，调用失败，构造失败事实。
4. **stub**：业务系统不可调且无预制输出，让模型按契约扮演业务系统产出。

差异只在"输出从哪来"——即业务系统以何种方式被具现化。其余处理（请求构造、响应提取、校验、落形）是同一套协议，不因具现化方式不同而分叉。

---

## 三、schema 校验：验证契约对业务系统的描述是否准确

live 环节复用契约校验器，校验输入输出是否与 live_schema 对齐。但**校验目标与其他模块相反**：

- 其他模块（mock_agent、judge、case_pools 等）校验失败 → 实现层错了，改实现。
- live 环节校验失败 → **先怀疑契约对业务系统的描述错了**。因为业务系统是客观事实，live_schema 是对它的描述，描述与事实不符错在描述。

两端校验，不对称：

- **请求端**（normalized_request 构造完、发出前）：请求是 verifier 自己构造的，校验失败时有**双向怀疑**——请求构造逻辑错了，或契约本身写错了。怀疑链：请求构造 → 契约。
- **输出端**（extracted_output 提取完）：输出直接来自业务系统（或预制响应），是客观事实，校验失败时**单向怀疑契约**——契约描述与业务系统真实形状不一致。这才是反向验证的主战场。

**校验失败必须报错，但不阻断调用**：

- 必须报错：不报错没人知道契约有问题，校验失去意义。报错方式可以是 trace 诊断字段、stderr 警告、前端标记，要让问题显形。
- 不阻断调用：阻断就拿不到真实响应，没法判断"契约写错了还是这次调用是异常分支"。不阻断才让事实进来，用事实对照契约定位问题。
- 报错是对人的，让人看到问题；不阻断是对流水线的，让证据链完整。

副作用边界：校验失败可以改诊断字段，但**不能改调用状态、不能改输出内容、不能改 fallback 触发条件**。校验与 fallback 正交：校验失败不触发 fallback；fallback 时输出端校验跳过。

---

## 四、差异化下沉项目

协议层（分支决策、fallback、trace 落形、校验语义、多轮装配）**永不下放**——这些是"业务系统具现化"的通用协议，不因哪个业务系统而不同。

项目只贡献具现化动作的差异：怎么调这个业务系统、怎么取预制响应、请求体怎么翻译、流式响应怎么解帧。协议层按项目能力探测决定走哪个分支。

无项目实现时走默认通用调用。纯预制输出项目只实现"取预制响应"，不实现"调真实系统"。

---

## 五、与现有模块的关系

- **adapter 保留**输出语义：请求构造（case → normalized_request）、响应提取（原始响应 → 符合 EXTRACT_OUTPUT_SHAPE 的扁平输出）、事实落形、ready 判定。这些是"业务系统语义的翻译"，不是投递动作。
- **adapter 交出**投递动作：具体调用方式、请求体翻译、取预制响应、解帧。这些是"怎么接业务系统"的差异化动作，搬到项目 live 实现。
- **pipeline 保留**：`live_run` 入口和编排逻辑（judge、attribute、cluster），入口内部委托给 live 模块。
- **pipeline 交出**：协议级投递逻辑（请求构造调度、调用调度、事实落形调度、校验调度），搬进 live 模块。
- **不动**：契约本身（live_schema）、stub 兜底、通用 HTTP 调用。

---

## 六、不变量

1. live 输入输出都符合 live_schema（REQUEST_SHAPE / EXTRACT_OUTPUT_SHAPE），塞进 trace 后字段和值语义不变。
2. 入口签名不变。
3. 四种投递方式的触发条件不变。
4. 校验失败必报错但不阻断调用，不改业务字段、不触发 fallback。
5. 新增项目只改自己的投递实现和契约，公共协议不动。


请实现impl/core/live.py作为通用层，及impl/projects/<project>/live.py作为项目自定义实现层


----------

> live_schema 的字段完全由项目定义；多轮协议只规定“多轮场景的 schema 内部有一个承载轮次序列的字段”，通常叫 `turns`，但每轮 item 的业务字段不固定。

重新描述如下。

---

# 多轮 live 方案

## 1. 通用前提

live 的通用规则不变：

> live 输入必须符合项目定义的 `REQUEST_SHAPE`；live 输出必须符合项目定义的 `EXTRACT_OUTPUT_SHAPE`。

这里的 `REQUEST_SHAPE` 和 `EXTRACT_OUTPUT_SHAPE` 永远是项目自己的契约，不由通用协议规定业务字段。

也就是说，协议层不关心字段叫不叫 `query`、`session_id`、`robot_text`、`end_flag`。这些都属于项目 live_schema。

---

## 2. 多轮不是额外外壳

多轮场景不是：

```text
multi_turn = 外层协议 + live_schema
```

也不是：

```text
multi_turn = list[live_schema]
```

而是：

> 多轮场景自己的 `REQUEST_SHAPE / EXTRACT_OUTPUT_SHAPE` 本身就是多轮形状。

多轮形状的核心特征是：schema 内部有一个轮次序列字段，用来承载每一轮输入或输出。

这个字段可以统一约定叫 `turns`。

---

## 3. 单轮和多轮的区别

单轮场景：

```text
REQUEST_SHAPE = 项目定义的一次请求形状
EXTRACT_OUTPUT_SHAPE = 项目定义的一次输出形状
```

多轮场景：

```text
REQUEST_SHAPE = 项目定义的多轮请求形状
EXTRACT_OUTPUT_SHAPE = 项目定义的多轮输出形状
```

其中多轮请求形状里包含：

```python
"turns": [
    <项目定义的单轮输入 item shape>
]
```

多轮输出形状里包含：

```python
"turns": [
    <项目定义的单轮输出 item shape>
]
```

重点是：

> `<项目定义的单轮输入 item shape>` 和 `<项目定义的单轮输出 item shape>` 没有固定字段，由项目 live_schema 决定。

---

## 4. 抽象形式

可以写成抽象形式：

```python
REQUEST_SHAPE = {
    "turns": [
        TURN_REQUEST_SHAPE
    ]
}

EXTRACT_OUTPUT_SHAPE = {
    "turns": [
        TURN_OUTPUT_SHAPE
    ]
}
```

其中：

```python
TURN_REQUEST_SHAPE = 项目定义
TURN_OUTPUT_SHAPE = 项目定义
```

协议只要求：

1. `REQUEST_SHAPE` 里有轮次输入序列；
2. `EXTRACT_OUTPUT_SHAPE` 里有轮次输出序列；
3. 输入轮次和输出轮次按顺序对应；
4. 整个对象仍然是该场景的 live_schema。

---

## 5. project.yaml 的作用

`project.yaml` 只标记某个 scenario 是多轮：

```yaml
scenario:
  interaction: multi_turn
```

这个标记只告诉 live：

> 这个 scenario 要按多轮方式执行。

它不定义字段，不改变 live_schema 的业务内容。

字段仍然全部来自项目 `live_schema.py`。

---

## 6. live 的执行方式

当 scenario 是单轮：

```text
输入对象 -> 调业务系统 -> 输出对象
```

当 scenario 是多轮：

```text
读取 REQUEST_SHAPE 中的 turns
按顺序执行每一轮
每轮产出一个 TURN_OUTPUT
最后组装成 EXTRACT_OUTPUT_SHAPE 中的 turns
```

抽象流程：

```python
outputs = []

for turn_input in request["turns"]:
    turn_output = call_and_extract(turn_input)
    outputs.append(turn_output)

return {
    "turns": outputs
}
```

这里的 `turn_input` 和 `turn_output` 仍然是项目定义的 shape。

---

## 7. mock 的配合

mock 的职责不变：

> 生成符合 `REQUEST_SHAPE` 的输入。

如果是单轮场景，mock 生成单轮 input。
如果是多轮场景，mock 生成包含 `turns` 的 input。

mock 不需要理解额外的多轮外壳，因为多轮结构已经是 `REQUEST_SHAPE` 的一部分。

---

## 8. judge / attribute 的配合

judge / attribute 的职责也不变：

> 判断 `trace.extracted_output` 是否满足当前 case 的评估要求。

单轮时，`trace.extracted_output` 是单轮 output shape。
多轮时，`trace.extracted_output` 是包含 `turns` 的多轮 output shape。

它们不需要处理额外 envelope，因为多轮 output 本身就是 `EXTRACT_OUTPUT_SHAPE`。

---

## 9. trace 落形

trace 仍然只有一条：

```python
trace.normalized_request = <符合 REQUEST_SHAPE 的对象>
trace.extracted_output = <符合 EXTRACT_OUTPUT_SHAPE 的对象>
```

多轮不会拆成多个 trace。
多轮过程就在 `normalized_request.turns` 和 `extracted_output.turns` 里。

已有的 `conversation_transcript`、`multi_turn_state` 可以作为展示辅助，但不是主契约。

---

## 10. 最终定义

一句话：

> 多轮 live 不是新协议，也不是 live_schema 外层包装；它只是某些 scenario 的 `REQUEST_SHAPE / EXTRACT_OUTPUT_SHAPE` 自身采用包含 `turns` 的多轮结构。`turns` 中每一项的字段完全由项目 live_schema 定义，live 只负责按顺序执行并生成同形输出。




------


stub 不是 mock 输入；mock 只负责生成符合 REQUEST_SHAPE 的 input。stub 是系统侧模拟 output 构造器，用于没有真实业务系统输出时，按 EXTRACT_OUTPUT_SHAPE 构造模拟 output。
多轮项目必须以 turns 作为标准主契约字段；normalized_request.turns[i] 与 extracted_output.turns[i] 顺序对应。项目可以自定义turn item 字段，但不能自定义多轮外壳。具体调用动作、session 传递、SSE 解帧由项目实现。
