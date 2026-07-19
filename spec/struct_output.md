## 结构化输出方案

### 背景

当前 LLM 输出没有强制约束，模型可以产出结构正确但内容为空的假货（`expected: {}`、`conditions: []`），事后校验只能挡不能防。`schema.md` 要求 schema 是标准不是摆设，所有数据流对接点必须对齐。

### 原则

**1. 结构化输出是强制标准**

`shape_prompt.py` 重构为 `structured_output.py`，作为所有 LLM 调用的唯一输出约束入口。不再让各角色各自拼中文文案。

**2. 所有 LLM 调用都必须传 output schema**

只要调 `complete_json` 且输出有明确结构，就必须传 `output_spec`。不传属于旧用法，逐步废弃。

### 传参方式

调用方直接给 **dataclass 类型**，协议层自动从 `__annotations__` 或 `model_json_schema()` 提取 JSON Schema：

```python
spec = StructuredOutputSpec.from_dataclass(
    model=SomeOutputShape,       # live_schema 那种 dataclass
    required_nonempty=["expected", "actual_answer"],
)
client.complete_json(system, user, output_spec=spec)
```

协议层内部三件事：
- 从 dataclass 提取 JSON Schema
- 传给 `response_format`（token 级强制）+ 注入 prompt 文案（兜底强化）
- 同一份 schema 事后校验，不合规直接阻断

### 校验阻断

LLM 返回后立刻校验：字段缺失、类型错、空内容（空字符串/空数组/空对象）→ 直接抛异常阻断，不重试，不放行。

### 单一真相源

项目形状定义一次（dataclass），所有调用方引用它，schema 和校验用同一份，不漂移。





--------
1。 EXTRACT_OUTPUT_SHAPE这些本质也是来源于live schema的吧 
2。一般来说就是去取live schema的东西，如果实在有个性化需求，就提前构建好放在impl/core/schema/或者impl/projects/<project>/schema/*下面，然后拿来用

对，两条都对。

**1. EXTRACT_OUTPUT_SHAPE 本质来源就是 live schema。** 它描述的是 live 系统产出什么形状，judge 的 reference / live_stub 的 output 都按这个形状走。来源唯一，不重复定义。

**2. 通用走 live schema，有特定个性化需求的走impl/core/schema/或者 impl/projects/<project>/schema/， 大部分场景直接取 live schema 的 dataclass 就行。如果某个项目有特殊需求（比如 judge 判定时额外需要某些字段），就在 `impl/projects/<project>/schema/` 下定义好，拿来用。这样：
- live schema = 系统侧事实，项目级通用
- impl/projects/<project>/schema/ = 评估侧/模拟侧的特化需求，按项目覆盖
- impl/core/schema/ = 评估侧/模拟侧的通用需求，根据情况使用

和 `spec/reference.md` 里"各角色按各自域提前固化事实"的原则一致——live schema 定义系统产出形状，评估侧如果需要不同的结构，在自己的 schema 目录下声明，不污染 live schema。




------------



## 你这段思路的总结

**1. 项目级 live schema 集中到 `impl/projects/<project>/schema/`**

把当前散在 `live_schema.py` 里的 `EXTRACT_OUTPUT_SHAPE` / `REQUEST_SHAPE` 等形状定义，统一导入到 `impl/projects/<project>/schema/` 下，改成 **dataclass 类型**的形式。也就是说，项目级标准 schema 不再是 `"str"`/`"list"` 这种描述符 dict，而是 dataclass——字段直接用类型注解，作为本项目所有角色引用的单一真相源。

**2. 新增 `JudgeLLMOutput` dataclass**

在 `impl/core/schema/` 下新建一个 `JudgeLLMOutput` dataclass，专门描述 judge 调用 LLM 时应产出的结构。它和现有的 `JudgeResult` 区分开：`JudgeResult` 是 judge 完整结果（含代码派生/注入字段），`JudgeLLMOutput` 只含 LLM 应该产出的字段。它作为 judge 调用 `complete_json` 时传给 `StructuredOutputSpec` 的 dataclass 来源。

**3. 嵌套 dataclass 允许，但内容必须可序列化**

`StructuredOutputSpec` 从 dataclass 提取 JSON Schema 时，支持嵌套 dataclass（比如 `JudgeLLMOutput.business_expectations: List[BusinessExpectation]`，`BusinessExpectation` 又是 dataclass，递归提取成 JSON Schema 的 `properties`/`$defs`）。但有一个硬约束：**嵌套层级里只能包含可序列化的内容**——基本类型（str/int/float/bool）、list、dict、嵌套 dataclass 这些可以；不能再把任意 Python 类、函数、复杂对象塞进 dataclass 字段里。这样保证提取出的 JSON Schema 是干净的、能直接传给 `response_format` 和校验器的标准 schema。

Judge 的 `blocking` 只属于 `BusinessExpectation`，并且是结构化输出必填字段；`FulfillmentAssessment` 不得包含 `blocking`。模型先按用户核心目的、安全底线和项目强契约声明 expectation 是否阻断，再判断对应 assessment。`overall_fulfillment.status` 是公共代码在项目扩展完成后确定性派生的字段，模型输出的同名状态不作为最终结果，也不因状态不同触发 reprompt。




----------


## 你的思路总结

**1. 长期统一，现在先兼容**

`LiveSchemaCheck` 长期应该和 `StructuredOutputSpec` 统一用同一套 dataclass 提取逻辑做校验，但现在先不改，沿用现有的 `_parse_descriptor` 描述符解析。两条线并行一段时间，再逐步合并。

**2. 可选 vs nullable 的映射规则**

- **可缺失字段**（?）：`field(default=None)` 且不放 `required` — 字段可以不出现在 JSON 里
- **nullable 字段**（`|null`）：`Optional[str]` 但仍在 `required` 里 — 字段必须在，但值可以是 `None`

**3. `JudgeLLMOutput` 与 `JudgeResult` 的关系**

`JudgeResult` 持有一个 `JudgeLLMOutput` 字段。LLM 产出后反序列化到 `JudgeLLMOutput`，然后代码派生字段（`trace_id`、`project_id`、`gate_decisions`、`summary` 等）补齐到 `JudgeResult` 的其余字段。职责清晰：LLM 只负责 `JudgeLLMOutput`，代码负责组装 `JudgeResult`。


**4. 全部一起迁移**

4 个项目的 `live_schema.py` 一次性全改，不逐个渐进。把 `EXTRACT_OUTPUT_SHAPE` / `REQUEST_SHAPE` 等形状定义统一迁移到 `impl/projects/<project>/schema/` 下改成 dataclass 类型，一步到位。




-----------

固定schema如何实现动态调整输出内容

同一份  schema，可以根据不同需求，动态传递 required_nonempty + nested_schemas 差异化。实现差异化的llm结构化输出
