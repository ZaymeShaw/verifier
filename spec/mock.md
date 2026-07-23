好的，mock agent 不适合塞在 adapter 里，它应该是一个**独立的协议模块**，有自己的 schema、API 和构建流程。

## Mock Agent 协议设计

### 一、Schema（`impl/core/schema/mock.py` 已有雏形，需要扩展）

```python
# mock agent 的输入：构建单条 case 的约束
class MockBuildSpec:
    project_id: str
    scenario: str                    # 使用的场景
    requested_intent: str            # 调用方已确定的具体意图；存在时是事实来源
    intent_labels: list[str]         # 可用意图标签
    required_fields: list[str]       # 必填的 input 字段
    ready: list[str]                 # 已就绪的字段（mock agent 的产出）
    template: str | None             # seed 模板（可选）
    live_context: dict | None        # 上轮 live 输出（多轮场景）

# mock agent 的输出：一条构建好的 mock case
class MockBuildResult:
    case_id: str
    input: dict                      # query、turns、user_intent 等用户侧输入
    expected_intent: str | None      # 期望意图
    scenario: str
    metadata: dict
    # 注意：没有 output，没有 reference
```

### 二、API 接口

mock agent 的输入输出不通过 adapter 内部方法，而是通过独立的 API 路由：

```
POST /api/mock/build_intent
  input:  MockBuildSpec
  output: MockBuildResult

POST /api/mock/build_interaction
  input:  MockBuildResult + live_context (上一轮 trace)
  output: MockBuildResult (补充了下一轮 query/turns)
```

HTTP 请求中的 `requested_intent` 与 `intent_labels` 分开透传：前者是本次具体事实合同，后者只是可用意图类别。

**为什么做成 API：**
- mock agent 可以是 LLM 驱动的，调 API 时 pipeline 内部可以调 LLM 生成用户输入
- 与 adapter 解耦：adapter 只负责"把 mock case 转成 live request"，不负责"构建 mock case"
- 便于测试和独立迭代

### 三、Mock Agent 的实现形态

不一定是 LLM，可以是三层 fallback：

```
1. 规则驱动（确定性）
   - 从 seed JSON 读模板，填变量
   - 多轮交互：根据 spec 的 turn_expectations 按规则补充字段

2. LLM 驱动（生成式）
   - 输入 spec + scenario + requested_intent（可选）+ intent_labels
   - 让 LLM "扮演用户"，生成自然语言 query
   - 多轮交互：LLM 拿到上一轮 live 输出，生成下一轮追问

3. 混合模式
   - 意图构建用 LLM 生成 query 文本
   - 交互构建用规则驱动（更可控）
```

### 四、与 Pipeline 的关系

当前 pipeline 调用链：
```
pipeline.mock_cases(project_id)
  → adapter.build_mock_cases()
    → 读 JSON 文件
    → normalize_mock_case()
```

改造后：
```
pipeline.mock_cases(project_id)
  → mock_agent.build(project_id)
    → 读 spec + seed 模板
    → 构建意图（规则/LLM）
    → 应用 ready 契约过滤
    → 输出 MockBuildResult[]
  → normalize_mock_case()  ← 只做 dict→dataclass 转换
```

### 五、关键协议约束

1. **mock agent 的输出只能包含 `input` 侧的字段**，禁止包含 `output` 和 `reference`
3. **多轮交互的 mock agent 必须拿到真实的 live trace 上下文**，不能凭空生成
4. **mock agent 不负责 case 的 `expected_quality` 或 `status`**，那是评估侧的字段，mock agent 只是"扮演用户"





---------



这两个问题问得很准，本质上是在问 mock agent 和 live 系统之间的**接口契约**。

## 1. 怎么固化输入结构，保证对接 live 系统

**mock agent 不直接对接 live 系统。adapter 是它们之间的翻译层。**

```
mock agent 输出（标准化结构）
  ↓
adapter.build_request(case)  ← 把 mock case 转成 live 能理解的请求
  ↓
live 系统
```

**固化的是 mock agent 输出的标准结构，不是对接 live 的细节：**

- mock agent 产出的 `input` 是**项目语义层**的字段（`query`、`user_intent`、`turns` 等），与 live 系统的 API 形状无关
- adapter 负责把语义层字段翻译成 live API 的请求体（`adapter.build_request` 已经在做这件事）
- mock agent 不需要知道 live API 的 endpoint、method、请求体格式

**所以 mock agent 的输入结构固化在 `MockBuildSpec` 上：**

```python
class MockBuildSpec:
    project_id: str           # 找哪个 adapter
    scenario: str             # 用哪个场景
    requested_intent: str     # 调用方已确定的具体意图，不得混入 intent_labels
    intent_labels: list[str]  # 可用的意图标签
    required_input_fields: list[str]  # input 必须包含哪些字段（query、turns 等）
    # 没有 api 相关字段，没有 live 请求格式
```

mock agent 只保证产出的 `input` 包含 `required_input_fields`，adapter 拿到后自己去翻译。

## 2. 不同项目的 mock 如何适配？mock 是适配层吗？

**mock agent 不是适配层，也不应该是。**

理由：

| 层 | 职责 | 对 live 的了解 |
|---|---|---|
| **mock agent** | 扮演用户，生成用户侧输入 | 零了解 |
| **adapter** | 翻译用户输入为 live 请求 | 深度了解 |
| **live 系统** | 执行请求 | 自己 |

mock agent 的"扮演用户"能力是**通用的**：
- 不管是 client_search 还是 marketting-planning，用户的 query 都是自然语言
- 不管是单轮还是多轮，用户的行为都是"说一句话"→"看系统回什么"→"补充"→"重新说"
- 意图标签、场景枚举是 project spec 提供的，不是 mock agent 需要适配的

**那不同项目的差异怎么处理？通过 `MockBuildSpec` 传递项目特征，而不是让 mock agent 自己适配：**

```python
# client_search 的 spec
MockBuildSpec(
    project_id="client_search",
    scenario="multi_condition_and",
    intent_labels=[],  # client_search 没有意图标签，有 query 就够了
    required_input_fields=["query"],
)

# marketting-planning 的 spec
MockBuildSpec(
    project_id="marketting-planning",
    scenario="clarification",
    intent_labels=["premium_growth", "customer_growth", ...],
    required_input_fields=["query", "turns", "expected_stage", "expected_path_types"],
    live_context={...},  # 多轮场景需要上轮 live 输出
)
```

mock agent 拿到 spec 后，按 spec 约束生成 input，不关心 live 系统长什么样。**适配是 adapter 的活，mock agent 只扮演用户。**




--------


你这个思路是对的，我之前把问题想复杂了。

**核心简化：mock 系统直接产出 live 能吃的输入，不经过 adapter 翻译。**

这样 mock agent 扮演用户时，直接产出 live API 需要的请求体形状，跳过中间的"语义提取/翻译"环节。

**两种分工模式：**

1. **只做意图模式** — mock agent 只产意图侧的语义字段（`query`、`expected_intent`），适用于简单 live 系统或不需要复杂请求构造的场景。adapter 做轻量形状映射。

2. **直接对接 live 模式** — mock agent 直接产出 live 请求体，适用于复杂 live 系统（marketting-planning 的 SSE、结构化参数抽取）。mock agent 内部可以调 LLM 把"用户自然语言"转成"live 结构化请求"，这一步本来就是 mock 扮演用户的一部分。

**为什么这样更合理：**

- mock agent 扮演用户，本来就要理解"用户想做什么"并表达出来。对复杂 live 系统，"表达成 live 能理解的结构化请求"就是 mock agent 的工作，不是额外的翻译层。
- adapter 退化为纯粹的协议层（endpoint、method、timeout、鉴权），不再承担语义提取。
- mock 和 live 直接对接，少一层间接，少一处需要 LLM 的地方。

**接口契约相应调整：**

mock agent 的 `MockBuildSpec` 要带上 live 请求的形状约束（必填字段、参数结构），mock agent 按这个形状产出。`ready` 契约仍然管 output/reference 的归属，不变。

所以你的方向更干净：mock 系统直接对接 live，意图那步可选。adapter 只管协议不做翻译。





--------


你的两点都对，我接受。

## 1. 不是二选一，而是固定两步

mock agent 的构建流程是固定的两步，不是两种模式：

**第一步：用户基础意图构建**
- 输入：project spec、scenario、可选的 requested intent、intent labels
- 输出：意图侧的语义字段（query、expected_intent、user_intent 等）
- 这一步是"用户想做什么"的表达，与 live 形状无关

当 `requested_intent` 非空时，它是调用方已经确定的事实合同；`user_intent` 必须保持语义等价，`query` 只能自然改写，不得补造缺失事实。它不是可选意图类别，因此不得复制到 `intent_labels`。

**第二步：根据意图 + live 上下文构建每轮 live 交互输入**
- 输入：第一步的意图 + 上一轮 live 的 trace 输出
- 输出：live 能直接吃的请求体形状
- 这一步是"用户意图如何转成 live 这一轮要收到的输入"，多轮场景下逐轮构建

对于标准 `input.messages` 聊天请求，第二步只能做形状映射，必须复用第一步的 query 作为最后一条 user message，不能再次改写用户原话。

两步串行，都做。简单项目第二步可能退化成轻量映射，复杂项目第二步需要把意图展开成 live 结构化请求，但流程不变。

## 2. 项目专属 live schema 放 `impl/projects/<project>/schema.py`

合理，而且比塞在 adapter 里更干净。理由：

- **关注点分离** — adapter 负责协议层（endpoint、method、调用），schema 负责形状定义（live 请求体的字段、类型、必填、参数结构）。现在这些信息散落在 adapter 的 `build_request` 和 project.yaml 里，抽到独立 schema.py 后边界清晰。
- **mock agent 直接消费** — 第二步构建 live 输入时，mock agent 需要知道"live 这一步要什么形状的输入"，这个形状约束就来自项目专属 live schema。mock agent 读 schema.py，按形状产出，不需要 adapter 介入翻译。
- **项目级隔离** — 不同项目 live 形状差异大（client_search 的 query 字符串 vs marketting-planning 的 SSE 多轮结构化参数），各自维护自己的 schema.py，互不污染，新增项目只加文件不改公共代码。
- **可校验** — schema.py 可以定义 live 请求体的 dataclass 或 pydantic 模型，mock agent 产出的请求体能被 schema 直接校验，不合规立刻报错，而不是等到 live 调用失败才发现。

需要注意的一点：`impl/core/schema/` 已经是公共 schema 目录（里面有 normalize.py、fixture 等）。项目专属的 live schema 放 `impl/projects/<project>/schema.py` 是项目级，跟公共 schema 不冲突，命名上也清晰。但如果担心和公共 schema 概念混淆，也可以叫 `impl/projects/<project>/live_schema.py` 让定位更明确。这点可以再定。








live schema本身才是权威，adapter、mock构建都要向他对齐，包括live的直接构建也是要基于它






---------



## ready 协议总结

### 核心定义

`common.ready` 是项目层面的声明，表示"已获取的信息，不用再通过测评系统 trace 生成"。枚举值 `[output, reference]`。

### 三层分工

| 字段 | 在 ready 中 | 不在 ready 中 |
|---|---|---|
| **input**（query/turns/question） | mock agent 产出（永远） | mock agent 产出（永远） |
| **output** | mock agent 产出（模拟 live 结果） | live 系统真实调用产出 |
| **reference** | mock agent 产出（参考答案） | judge agent 生成 |

### 4 个项目配置

| 项目 | ready | mock agent 产出 | live 产出 | judge 产出 |
|---|---|---|---|---|
| client_search | `[]` | input | output | reference |
| marketting-planning | `[]` | input | output | reference |
| marketting-planning-intent | `[reference]` | input + reference | output | — |
| QA | `[output, reference]` | input + output + reference | — | — |

### 关键约束

1. **mock agent 永远产 input**，这是它的基本职责（扮演用户）
2. **ready 是 mock agent 的作用域声明**：ready 里有什么，mock agent 就额外产什么；不在 ready 里的，mock agent 不碰，留给 trace 链的后续环节
3. **output 在 ready 中**：mock agent 与 live 交互获取，不调真实 API，走 provided 模式
4. **reference 在 ready 中**：judge 直接采信 case.reference，不自生成
5. **数据清洗原则**：ready 声明了就产，没声明就不产。mock case 的 `output`/`reference` 字段只应在对应 ready 声明存在时才出现




-------


因为 **output/reference 是 mock agent 模拟的 live 结果和参考答案，它们的形状必须与 live 系统真实产出一致，否则下游 consume 这些字段的环节（judge、attribute、frontend）会读取失败或格式不匹配。**

具体来说：

1. **output 的形状必须与 `live_schema.EXTRACT_OUTPUT_SHAPE` 一致**：因为 output 在 ready 时，mock agent 产出它来模拟 live 系统的结果。下游 judge 和 attribute 读 `trace.extracted_output` 时，不会区分这个 output 是 mock agent 产的还是 live 系统真实产的。如果 mock agent 产的 output 字段名或类型与 live 系统不一致，judge 的 prompt 里就会出现错位——比如 QA 的 judge 期望 `actual_answer` 字段，mock agent 产了 `answer` 就会导致 judge 误判。

2. **reference 的形状必须与 `live_schema.EXTRACT_OUTPUT_SHAPE` 中对应的 reference 结构一致**：因为 reference 在 ready 时，judge 直接采信 `case.reference` 而不自生成。如果 mock agent 产的 reference 形状与 judge 期望的契约不一致，judge 在做 fulfillment assessment 时无法对齐——比如 mpi 的 judge 期望 `reference.intent` 是一个合法的 intent label，mock agent 如果产了 `{"intent": "expected_intent: customer_portrait"}` 这种格式异常的字符串，judge 就无法正确匹配。

3. **本质原因：ready 协议的"就绪"意味着 mock agent 替代了 trace 链的对应环节。** 如果 mock agent 替代 live 产出 output，那 output 的形状必须和 live 真实产出一样；如果 mock agent 替代 judge 产出 reference，那 reference 的形状必须和 judge 生成的契约一样。否则"就绪"就失去了意义——下游环节拿到的是不兼容的数据，还不如让它们自己生成。

**所以 mock agent 产出 output/reference 时，必须参照 live_schema 定义的形状约束，而不是自由发挥。**





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

实现保持两步职责清晰：MockAgent 在第一步区分固定事实合同与开放场景 Context，在第二步只按 live schema 映射请求；judge 继续负责 expected/reference，不参与改写用户事实。
