-------


你说得对。我前一版的设计方向错了——把 adapter 代码当权威，live_schema 从它派生，这是本末倒置。

正确的方向是：

**live_schema 是权威源头，adapter 和 mock_agent 都向它对齐。**

这意味着：

1. **live_schema 是契约**：定义"这个项目的 live 输入长什么样、输出长什么样、字段名和类型是什么"。它不依赖任何代码，只描述业务事实。

2. **adapter.build_request 必须符合 live_schema**：adapter 的职责是把 case.input 翻译成 live_schema 要求的形状。如果 adapter 翻译出来的东西不符合 live_schema，adapter 就是错的，需要修正。

3. **mock_agent 产出必须符合 live_schema**：mock_agent 生成的 case.input，经过 adapter 翻译后，必须符合 live_schema 的 `normalized_request` 形状。

4. **live 直接输入也必须符合 live_schema**：前端文本框、CLI --input、导入池等手动输入，经过 adapter 翻译后同样要符合 live_schema。

5. **校验顺序**：live_schema → 校验 adapter 产出 → 校验 mock_agent 产出 → 校验手动输入。schema 是对的，其他都是实现。

**那 live_schema 本身怎么保证正确？**

- 它应该来自**业务需求文档**（如 `application.md`、`judge_boundary.md`）、**原项目 API 文档**（如 `source_readme`、`source_config`）和**人工确认**
- 不是从代码提取出来的，而是**代码应该符合它**
- 如果 adapter 代码和 live_schema 不一致，改 adapter，不改 schema

**但当前四个 live_schema 是我手工从 adapter 逆向抄的，这本身就不对。** 要让它成为权威，需要：

- 对照原项目的 API 文档、field_definitions 等 source 材料，确认每个字段的业务含义
- 人工确认字段是否完整、类型是否正确
- 然后反过来校验 adapter 的 build_request 是否产生符合 schema 的输出

**当前状态：live_schema 有，但权威性未建立。** 需要你确认它是否正确，之后才能用它做强制校验。要我现在对照原项目材料逐一确认四个 live_schema 吗？



-------

对，这是补充 live_schema 权威性的关键来源。除了业务文档和人工确认，还可以从两个客观源提取：

**1. 原项目源代码（业务服务侧）**

原项目仓库（如 `source_project` 指向的 marketing-planning、llm_client_search 等）里有真实的 API 定义：
- 请求体的 dataclass / pydantic 模型 / schema 定义（如 `app/schemas/request.py`、`app/schemas/intent.py`）
- 路由处理函数的参数解构（`@app.post(...)` 里 `request: XXXModel`）
- 这些是 live API 形状的**第一手权威**，比 verifier 的 adapter 更接近真相

从原项目源码提取 live_schema 的形状约束，能让 schema 直接锚定到业务服务自己的契约定义，而不是 verifier 这边的二手翻译。

**2. 项目调用 API 的实际响应（运行时观测）**

- 调用真实 live API，抓取请求体和响应体
- 从多次真实调用的样本中归纳字段集合、类型、必填/可选、嵌套结构
- 这能捕获到文档/源码没写但实际会出现的字段（如某些 optional 字段、错误分支返回的结构）

**整合到 live_schema 校验流程：**

| 源 | 作用 | 可信度 |
|---|---|---|
| 原项目源码的 schema 模型 | 定义字段名、类型、必填 | 最高（业务服务自己的契约） |
| 真实 API 调用样本 | 补充可选字段、实际响应形状 | 高（运行时事实） |
| 业务文档（application.md / judge_boundary.md） | 字段业务含义、边界 | 中（人工维护，可能滞后） |
| verifier adapter 代码 | 实现层翻译，需向 schema 对齐 | 低（它是结果不是源头） |

**校验机制相应升级：**
- live_schema 从原项目源码的 schema 模型自动提取（或人工对照源码确认）
- adapter.build_request 产出的 normalized_request 与 live_schema 校验，不符则改 adapter
- 真实 API 响应与 live_schema 的 EXTRACT_OUTPUT_SHAPE 校验，发现未声明字段则补 schema
- 这样 live_schema 真正成为连接"业务服务真实形状"和"verifier 实现"的权威桥梁

当前四个 live_schema 是从 verifier adapter 逆向抄的，要建立权威性，最稳的路径是回到原项目源码（marketting-planning 的 `app/schemas/`、llm_client_search 的 config/field_definitions 等）重新提取。




-----


## live_schema 对齐全景

### 输入对齐（REQUEST_SHAPE）

| 角色 | 环节 | 要求 |
|---|---|---|
| mock_agent | 第二步 `build_live_request` | 按 REQUEST_SHAPE 产出 live 请求体 |
| adapter | `build_request` → `_live_request_body` | 翻译成 REQUEST_SHAPE |
| 前端 | `live.html` 文本框 | 用户手动输入也应按 REQUEST_SHAPE |
| CLI | `--input` | 应校验是否匹配 REQUEST_SHAPE |
| api-check | 请求体构造 | 按 REQUEST_SHAPE 构造 curl |

### 输出对齐（EXTRACT_OUTPUT_SHAPE）

| 角色 | 环节 | 要求 |
|---|---|---|
| mock_agent | 产 `output`（ready 含 output 时） | 按 EXTRACT_OUTPUT_SHAPE |
| mock_agent | 产 `reference`（ready 含 reference 时） | 按 EXTRACT_OUTPUT_SHAPE |
| **live 系统** | 真实 API 返回 → `adapter.extract_output` | 按 EXTRACT_OUTPUT_SHAPE |
| **judge** | 产 `reference`（ready 不含 reference 时） | 按 EXTRACT_OUTPUT_SHAPE |
| judge | 消费 `output`（读 trace.extracted_output） | 按 EXTRACT_OUTPUT_SHAPE 解析 |
| judge | 消费 `reference`（采信 case.reference） | 按 EXTRACT_OUTPUT_SHAPE 解析 |
| attribute | 对比 expected vs actual | 两者形状一致才能 diff |
| frontend_view | reference_panel / output_panel | 取字段按 EXTRACT_OUTPUT_SHAPE |
| check | 校验一致性 | 按 EXTRACT_OUTPUT_SHAPE |
| table_view | 表格列提取 | 按 EXTRACT_OUTPUT_SHAPE |
| case_pools | 持久化 | 按 EXTRACT_OUTPUT_SHAPE |
| api-check | schema_check | 按 EXTRACT_OUTPUT_SHAPE 校验 |

# live_schema 校验器类设计思路

## LiveSchema 校验器 — 思路方案

### 一、定位

每个 `impl/projects/<pid>/live_schema.py` 里有一个**校验器实例**，命名带 `Live` 标识（如 `LiveSchemaCheck`），作为该项目的"live 形状守门人"。

- **返回值**：`True` / `False`（简单直接，调用方一行判断）
- **调用方式**：`load_live_schema(pid).check.<method>(data)`
- **逻辑收口**：所有字段名、必填判定、类型规则都在 `live_schema.py`，调用方零字段名知识

### 二、四个校验面

| 方法 | 校验对象 | 校验依据 |
|---|---|---|
| `request(data)` | live 请求体 | `REQUEST_SHAPE` |
| `output(data)` | adapter 提取后的输出 / mock_agent 产出的 output | `EXTRACT_OUTPUT_SHAPE` |
| `reference(data)` | case.reference / judge 产的 reference | `EXTRACT_OUTPUT_SHAPE`（与 output 同形状） |
| `case(case)` | 一条完整 mock case | 按 ready 协议决定校验范围 |

### 三、校验维度（全过才 True）

1. **形状对齐**：expected vs actual 的字段集合，missing/extra 任一存在则 False。可选字段（`?` 后缀）缺失不算 missing。
2. **类型对齐**：shape 的 value 是类型描述符（`"string"`/`"list"`/`"dict"`/`"str?"`/`"list[dict]"`），校验 actual 值的基本类型匹配，不做深度递归。任一不符则 False。

### 四、必填 vs 可选

`REQUEST_SHAPE` / `EXTRACT_OUTPUT_SHAPE` 字段值带 `?` 后缀算可选，其余必填。校验器内部解析，调用方不感知。

### 五、case 方法的 ready 感知

`case` 方法按 ready 协议决定校验范围：
- `output` 在 ready → 必须有 output 且 `output(case.output)` 为 True
- `output` 不在 ready → 不能有 output（有就 False）
- `reference` 同理

ready 协议和形状校验在 `case` 方法里闭环。

### 六、多轮形状

`live_schema` 定义的是**单轮**形状（`REQUEST_SHAPE` / `EXTRACT_OUTPUT_SHAPE`）。多轮在 trace 层用 `List[单轮形状]` 包起来，不单独定义多轮 schema。mock_agent 产多轮 case 时，input.turns 是 `List[REQUEST_SHAPE]`，ready 含 output 时产出 `List[EXTRACT_OUTPUT_SHAPE]`。校验时按单轮形状逐个校验。

### 七、形状权威

`REQUEST_SHAPE` / `EXTRACT_OUTPUT_SHAPE` 既是文档又是可执行契约。改 schema 自动影响所有校验点，新增项目只改自己的 `live_schema.py`，公共代码零改动。

### 八、不锁定的部分

- 具体挂载在哪个函数的哪一行（函数名会演化）
- 失败处理怎么记（字段名会变）
- 校验内部实现细节（dict 比较、类型描述符解析）
- 不引入 `CheckResult` 之类的中间结构（已简化成 bool）

**核心原则：思路层面对齐，实现细节留给落地时按当时代码现状决定。**

-----

如果多轮项目就是：

- `REQUEST_SHAPE` 描述单轮 live 输入的形状
- `EXTRACT_OUTPUT_SHAPE` 描述单轮 output 的形状
- trace 层用 `List[REQUEST_SHAPE]` 和 `List[EXTRACT_OUTPUT_SHAPE]` 包起来

mock_agent 产多轮 case 时，input.turns 是 `List[REQUEST_SHAPE]`，ready 含 output 时产出 `List[EXTRACT_OUTPUT_SHAPE]`。校验逻辑也按单轮形状校验，trace 层遍历 list 逐个校验。

这样定义清晰：live_schema 永远是"单轮交易的形状"，多轮是 trace 层的复用。




--------


所以这些涉及到到输出要按特定形状（最经典的live schema形状输出的，都要在prompt中明确指明，我建议你做一个同一个格式转换模块啥的，大家共用，可以注入到prompt中，有需求的引入这个模块让输出遵循输出






--------


live schema本身正确性如何校验
1. live系统