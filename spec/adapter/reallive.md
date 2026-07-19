# RealLive 真实调用证据协议

本文定义 verifier 中 `RealLive` 的长期协议，并记录当前仓库迁移到该协议所需的一次性改造任务。

本文遵循现有 Live 协议，不新建与既有职责重复的 schema：

- 请求继续使用项目 `live_schema.REQUEST_SCHEMA`；
- 评测输出继续使用项目 `live_schema.EXTRACT_OUTPUT_SCHEMA`；
- 每轮事实继续写入 `RunTrace.turn_records`；
- 原始响应继续使用 `raw_response`；
- 项目辅助派生信息继续使用 `project_fields`；
- 只新增现有协议缺失的公共 `LiveExchange` schema，并通过 `live_exchanges` 保存真实传输事实。

# 第一章：Spec 标准

## 1. 目标与适用范围

本协议适用于所有执行类型为 `RealLive` 的单轮和多轮项目。

核心要求：

1. 一个 RealLive Turn 表示一次真实业务调用；
2. 一个 Turn 可以包含一个或多个真实物理交换（Live Exchange）；
3. Turn 的 `request` 必须符合项目 `REQUEST_SCHEMA`，并由核心业务 exchange 真实传导到 Live 系统；
4. `raw_response` 必须来自 Live 系统真实返回，不能由 adapter 本地拼装；
5. `extracted_output` 必须与本轮真实 exchange 同源对齐，并符合 `EXTRACT_OUTPUT_SCHEMA`；
6. 实际发送和收到的内容必须由调用边界自动记录，不能依赖项目自行声明；
7. 多轮是多个真实 Turn 的有序组合，每个 Turn 分别满足上述要求。

真实性由实际调用证据保证，不通过增加另一套业务 schema 保证。

## 2. 复用现有 Live Schema

### 2.1 REQUEST_SCHEMA

`live_schema.REQUEST_SCHEMA` 继续作为项目 Live 请求的唯一 schema：

```python
REQUEST_SCHEMA = <项目真实 Live 请求 dataclass>
```

它描述项目一次业务调用的核心请求结构。Mock 生成的 `live_request`、Live 每轮的 `request` 和调用前校验必须使用同一份 schema。

`REQUEST_SCHEMA` 约束的是 Turn 的业务 request，不是该 Turn 中每个物理 exchange 的 request。创建会话、健康检查、轮询状态和读取消息等辅助 exchange 可以具有各自的真实请求形状。

约束：

- adapter 不得在通过校验后静默丢弃请求字段；
- adapter 不得用项目默认值无声覆盖 request 中已有字段；
- 如果协议允许字段映射，映射必须显式、确定且可测试；
- request body、URL path、query 和 header 的传输位置由项目声明，但不因此复制一份请求 schema；
- 核心业务 exchange 的实际发送内容必须能与本轮 `request` 对照，差异必须有明确的 transport mapping 解释；
- 辅助 exchange 不要求符合 `REQUEST_SCHEMA`，但仍必须原样进入 `live_exchanges`。

例如 DeerFlow 的 `REQUEST_SCHEMA` 已经对齐：

```text
POST /api/threads/{thread_id}/runs/wait body
```

因此不需要新增 DeerFlow 请求 schema。`thread_id` 位于 URL path，可以来自运行时会话状态；body 仍严格使用已有 `REQUEST_SCHEMA`。

### 2.2 EXTRACT_OUTPUT_SCHEMA

`live_schema.EXTRACT_OUTPUT_SCHEMA` 继续作为 Output 和 Reference 的共同格式：

```python
EXTRACT_OUTPUT_SCHEMA = <项目评测输出 dataclass>
```

约束：

- `extracted_output` 的输入事实必须全部来自本轮 `live_exchanges` 中真实记录的 response、status 或 error；
- 字段选择、重命名、结构展开、真实数组计数和多响应合并等确定性转换允许使用；
- 使用 LLM 提取时允许结果存在非确定性，不要求重新执行得到逐字相同的 `extracted_output`；
- 无论使用确定性代码还是 LLM，`extract_output` 的实际输入都只能是公共层从本轮标记为业务输出的 exchange response 生成的 `raw_response`；
- LLM 只能理解、归纳或结构化来源内容，不能补充来源中不存在的业务事实；
- 不得从 Reference、fixture、预期结果、模型推测或无证据默认值补齐输出；
- 不得用 request 中的信息冒充 Live 系统输出；
- Output 与 Reference 必须使用相同 schema 和相同展示格式；
- Trace 中的原始 Live 响应不要求符合 `EXTRACT_OUTPUT_SCHEMA`；
- 不新增 `LIVE_OUTPUT_SCHEMA` 或其他与原始响应重复的公共 schema；
- adapter 的本地辅助整理不能冒充 Live 原始响应。

### 2.3 原始响应不新增业务 Schema

Live 系统可能返回单个响应、流式事件或一次业务调用中的多个 HTTP 响应。原始响应的职责是保真留存，不要求所有项目统一成新的业务 schema。

项目仍通过现有接口完成：

```text
raw_response
→ extract_output(raw_response)
→ EXTRACT_OUTPUT_SCHEMA
```

如果一次业务调用需要组合多个真实响应才能提取输出，组合关系通过 `live_exchanges` 表达，辅助计算结果可以进入现有 `project_fields`；不得构造一个看似由服务端返回的伪 `raw_response`。

## 3. 复用并补充 turn_records

`RunTrace.turn_records` 继续作为每轮 Live 调用的事实容器。RealLive 每轮的标准字段为：

```python
{
    "turn_index": int,
    "request": REQUEST_SCHEMA,
    "live_exchanges": list[LiveExchange],
    "raw_response": list[Any],
    "extracted_output": EXTRACT_OUTPUT_SCHEMA,
    "project_fields": dict[str, Any],
    "call_status": str,
    "runtime_ms": int | None,
    "error": str | None,
    "validation": list,
    "execution_trace": list,
}
```

现有字段职责不变：

- `request`：本轮符合 `REQUEST_SCHEMA` 的请求；
- `raw_response`：公共层从本轮真实 Exchange 中生成的有序业务原始响应列表；
- `extracted_output`：符合 `EXTRACT_OUTPUT_SCHEMA` 的评测输出；
- `project_fields`：adapter 的项目辅助信息；
- `call_status/error`：本轮执行状态和错误；
- `validation/execution_trace`：schema 校验和执行诊断。

新增的公共 schema 只有 `LiveExchange`。`live_exchanges` 保存该 schema 的列表；`raw_response` 是公共层从其中所有 `contributes_raw_response=True` 的真实 response 按 sequence 生成的列表。

## 4. live_exchanges

### 4.1 定位

必须区分：

```text
RealLive Turn     = 一次真实业务调用
Live Exchange     = 该业务调用中的一次真实物理传输
```

一个 Turn 可能只包含一个 Exchange，也可能依次创建会话、发起任务、轮询或读取消息而包含多个 Exchange。`live_exchanges` 按实际发生顺序记录本轮全部物理交换。

Exchange 是否承载 Live Request 与是否贡献业务 Raw Response 是两个独立维度，不能合并成 `primary/support`：

- `/runs/wait` 可能承载 `REQUEST_SCHEMA`，但它的响应未必是最终业务输出；
- `/messages` 的请求不符合 `REQUEST_SCHEMA`，但它的响应可能需要进入 `raw_response`；
- 创建 thread 或健康检查可能两个标记都为 false。

`LiveExchange` 是公共协议 schema，不是项目业务 schema。所有 RealLive 项目复用同一个 dataclass：

```python
@dataclass(frozen=True)
class LiveExchange:
    exchange_id: str
    sequence: int
    transport: str
    method: str
    url: str
    carries_live_request: bool = False
    contributes_raw_response: bool = False
    request_headers: dict[str, Any] = field(default_factory=dict)
    request: Any = None
    status_code: int | None = None
    response_headers: dict[str, Any] = field(default_factory=dict)
    response: Any = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
```

字段含义：

- `exchange_id`：本次 RunTrace 内稳定且唯一，用于建立输出来源关系；
- `sequence`：本轮内真实发生顺序，从 0 递增；
- `transport`：实际传输类型，例如 `http`、`sse` 或 `websocket`；
- `method/url`：实际访问目标；
- `carries_live_request`：该 Exchange 的实际请求是否承载本轮 `REQUEST_SCHEMA`；
- `contributes_raw_response`：该 Exchange 的真实响应是否进入本轮 `raw_response`；
- `request_headers/response_headers`：脱敏后的真实 headers；
- `request`：发送前最后一刻的真实请求内容；
- `status_code`：真实 HTTP 状态；非 HTTP transport 可以为空；
- `response`：实际收到的原始返回；
- `error`：网络异常或 transport 错误。

流式事件等额外技术事实放入 `request/response` 的真实传输表示或后续兼容扩展字段，不由项目另造平行 exchange 结构。

### 4.2 生成者与接入方

`LiveExchange` 的唯一生成者是公共 `LiveTransport`。项目调用 `transport.get/post/...` 触发真实传输，transport 在发送前后自动捕获事实并创建 Exchange。项目不得直接实例化、补写或修改成功 Exchange。

主要接入方如下：

| 接入方 | 使用方式 |
|---|---|
| 公共 `LiveProtocol` | 校验真实 Request 传导、校验 RealLive 是否实际执行、seal transport，并从贡献输出的 Exchanges 生成 `raw_response` |
| `TraceContext` / `RunTrace` | 将本轮全部 Exchanges 原样写入 `turn_records[*].live_exchanges`，形成持久化调用事实 |
| 前端 Trace | 在完整原始 Trace 中按 Turn 和 sequence 展示请求、响应、状态与错误 |
| Check / 契约测试 | 检查 transport 绕过、请求字段丢失、响应替换、成功但无真实调用、会话连续性等问题 |
| UAT / 故障诊断 | 对照 verifier 与独立直调的 URL、请求体、响应、状态码、顺序和 session/thread |

项目扩展层与 `LiveExchange` 的关系是间接的：

```text
项目 deliver_real 调用 LiveTransport
→ LiveTransport 自动生成 LiveExchange
→ LiveProtocol 校验并生成 raw_response
→ Trace/前端/Check 保存、展示和审计 LiveExchange
```

项目扩展层不以 `LiveExchange` 作为方法入参或返回值；它只使用公共 `LiveTransport` 编排调用，并返回同一个 transport。`extract_output` 也不读取 Exchange，只接收公共层生成的 `raw_response: list[Any]`。

因此 `LiveExchange` 的主要接入位置在公共 LiveProtocol、Trace、前端、Check 和 UAT，而不是每个项目各自实现一套 Exchange 逻辑。

### 4.3 记录机制

`live_exchanges` 必须由公共调用边界自动记录：

```text
adapter 构造 transport 请求
→ 公共 transport 在发送前捕获实际 request
→ 发出真实调用
→ 公共 transport 捕获真实 response/error
→ 自动追加到当前 turn 的 live_exchanges
```

项目 adapter 负责构造请求、选择 endpoint 和解析业务响应；公共 transport 负责记录实际调用事实。

项目声明负责确定各 method/endpoint 的两个标记。公共层必须分别校验：

- 至少一个 `carries_live_request=True` 的 Exchange，且实际请求与 Turn request 的 transport mapping 一致；
- 成功 Turn 至少一个 `contributes_raw_response=True` 的 Exchange，且具有真实 response；
- 两个标记只能附着到公共 transport 实际执行后生成的 Exchange。

项目 adapter 不得：

- 手动构造成功的 `live_exchanges` 作为真实性证明；
- 绕过公共 transport 发出未记录的 RealLive 请求；
- 修改已经记录的 request/response；
- 用 fixture、fallback、stub 或本地对象填充 RealLive exchange；
- 在没有真实 exchange 的情况下把本轮标记为成功。

### 4.4 脱敏

请求和响应中的 token、Cookie、Authorization 和明确声明的敏感信息必须脱敏后进入 Trace。

脱敏只影响安全展示，不得删除影响调用语义的普通字段。前端、Judge 和 Attribute 不得获得未脱敏秘密。

## 5. RealLive 单轮执行

标准流程保持现有 `deliver_turn` 职责：

```text
request
→ validate REQUEST_SCHEMA
→ 公共层创建本轮 LiveTransport
→ deliver_real(request, transport)
   → 项目只通过 transport 编排真实调用
   → 公共 transport 自动记录 live_exchanges
   → 项目返回传入的同一个 transport
→ 公共层校验 transport 身份并 seal
→ 按 contributes_raw_response 和 sequence 生成 raw_response: list[Any]
→ extract_output(raw_response)
→ validate EXTRACT_OUTPUT_SCHEMA
→ TraceContext.record_turn
→ return extracted_output
```

约束：

- `deliver_turn` 对外仍返回 `EXTRACT_OUTPUT_SCHEMA`；
- `deliver_real` 负责项目特有的调用编排，只能返回公共层传入的同一个 `LiveTransport`；
- Turn 的 `request` 不等于全部 exchange request；它必须被至少一个 `carries_live_request=True` 的 Exchange 完整传导；
- 公共层封存 transport 后统一生成 `raw_response`，项目不能返回或构造 raw response；
- `TraceContext.record_turn` 继续统一收集本轮事实；
- schema 校验、fallback、provided 和 stub 的既有分支职责不因本协议改变；
- provided/stub/fallback 不是 RealLive 证据，不能生成伪造的 `live_exchanges`。

如果请求在到达 transport 前失败，可以没有 exchange，但必须 `call_status=failed`。如果 RealLive 本轮 `call_status=succeeded`，则必须同时存在合法的 request-carrying Exchange 和至少一个具有真实响应的 raw-response-contributing Exchange。

## 6. raw_response 的严格语义

保留现有 `raw_response` 字段，但收紧其语义：

- `raw_response` 由公共协议层生成，不由项目 adapter 手工构造；
- 项目通过 endpoint/transport 声明确定哪些 Exchange 设置 `contributes_raw_response=True`，不能在执行完成后任意选择；
- `raw_response` 类型固定为 `list[Any]`；
- 公共层按 Exchange `sequence` 收集所有贡献响应，不构造项目业务 envelope；
- 单输出响应时列表长度为 1，多输出响应时按真实发生顺序包含多个响应；
- 列表元素必须与对应 Exchange 的 `response` 一致，不允许加入服务端没有返回的业务字段；
- 本地生成的摘要等辅助信息应进入 `project_fields`；从真实来源提取且属于 `EXTRACT_OUTPUT_SCHEMA` 的 reply、状态或工具统计可以进入 `extracted_output`；
- 禁止把 `_normalized_request` 注入响应；
- 禁止把本地拼装 envelope 标记为 `raw_response`。

顶层 `RunTrace.raw_response` 继续作为现有兼容投影。完整逐轮事实以 `turn_records[*]` 为准，真实物理交换以其中的 `live_exchanges` 为准。

推荐运行时接口：

```python
# 项目扩展层：只负责编排，返回传入的同一个 transport
def deliver_real(request: REQUEST_SCHEMA, transport: LiveTransport) -> LiveTransport:
    thread = transport.post(
        "/api/threads",
        json={},
        carries_live_request=False,
        contributes_raw_response=False,
    )
    run = transport.post(
        f"/api/threads/{thread.response['id']}/runs/wait",
        json=request,
        carries_live_request=True,
        contributes_raw_response=False,
    )
    messages = transport.get(
        f"/api/threads/{thread.response['id']}/messages",
        carries_live_request=False,
        contributes_raw_response=True,
    )
    return transport

# 公共协议层：验证、封存、生成 raw_response 并调度提取
returned_transport = project.deliver_real(request, transport)
assert returned_transport is transport
transport.seal()
live_exchanges = transport.exchanges
raw_response = [
    exchange.response
    for exchange in live_exchanges
    if exchange.contributes_raw_response
]
extracted_output = project.extract_output(raw_response)
```

transport 调用可以返回只读响应视图，供项目使用 thread id 等真实返回继续编排下一步调用；但项目不能修改对应 Exchange。`seal()` 后 transport 和全部 Exchange 均不可再追加或修改。

## 7. 多轮 RealLive

多轮执行继续复用现有 `execute_live`、`TraceContext` 和 `turn_records`：

```text
turn 1 request → 真实 Live 调用 → turn 1 record
→ decide continue
turn 2 request → 真实 Live 调用 → turn 2 record
→ ...
```

约束：

- 每轮 `request` 分别符合项目 `REQUEST_SCHEMA`；
- 每轮 `extracted_output` 分别符合项目 `EXTRACT_OUTPUT_SCHEMA`；
- 每轮分别记录自己的 `live_exchanges`；
- 需要会话连续性的项目必须复用真实 session/thread id；
- session/thread id 必须来自首轮请求、运行时状态或服务端真实响应；
- 不得使用 `case_id`、trace id 或推测值冒充服务端会话 id；
- 不得为了继续多轮而静默创建新的独立会话；
- 多轮聚合、conversation summary 和 stop reason 仍属于 Trace，不进入项目 output schema。

## 8. 分层职责

### 8.1 公共协议层

公共层负责：

- 加载和执行现有 live schema 校验；
- 创建受控 `LiveTransport` 并自动记录 Exchange；
- 校验 `deliver_real` 返回的是传入的同一个 transport；
- seal transport，阻止后续追加或修改；
- 校验 request-carrying 与 raw-response-contributing Exchanges；
- 按 sequence 从贡献响应自动生成 `raw_response: list[Any]`；
- 将每轮 exchange 传给 `TraceContext.record_turn`；
- 保证成功 RealLive 必须具备真实调用证据；
- 统一脱敏和前端 Trace 数据出口；
- 检查项目是否绕过真实性机制。

公共层不理解项目 endpoint、thread 创建方式、业务响应字段或输出提取逻辑。

### 8.2 项目扩展层

项目层负责：

- 定义 `REQUEST_SCHEMA` 和 `EXTRACT_OUTPUT_SCHEMA`；
- 将 request 映射到真实 endpoint 的 path/query/header/body；
- 通过公共 transport 编排项目所需的一个或多个真实调用；
- 维护项目特有的 session/thread 连续性；
- 在 endpoint/transport 声明中标记哪些调用承载 Live Request、哪些响应贡献 Raw Response；
- 返回公共层传入的同一个 transport；
- 从真实 `raw_response` 提取 `extracted_output`；
- 将非原始辅助信息放入现有 `project_fields`。

项目层不得手工构造 `LiveExchange` 或 `raw_response`，不得返回其他 transport，不得绕过受控 transport 发出 RealLive 请求，也不得复制公共 Trace 逻辑或自行证明调用真实性。

### 8.3 RealServiceLive 抽象约束

`deliver_real` 和 `extract_output` 都是 RealLive 项目语义，所有 `RealServiceLive` 项目必须显式实现。公共协议层通过抽象基类在实例化阶段强制：

```python
class RealServiceLive(ProjectLive, ABC):
    @abstractmethod
    def deliver_real(
        self,
        request: REQUEST_SCHEMA,
        transport: LiveTransport,
    ) -> LiveTransport:
        """使用受控 transport 完成项目真实调用，并返回传入的同一个 transport。"""
        raise NotImplementedError

    @abstractmethod
    def extract_output(
        self,
        raw_response: list[Any],
    ) -> EXTRACT_OUTPUT_SCHEMA:
        """只从公共层生成的真实响应列表提取项目评测输出。"""
        raise NotImplementedError
```

约束：

- `deliver_turn`、transport seal、Exchange 校验、`raw_response` 生成和 output schema 校验属于公共协议层，必须保持 final，项目不得覆盖；
- `deliver_real` 不提供返回空 transport、通用 HTTP 猜测或任意响应对象的默认实现；
- `extract_output` 不提供“dict 原样返回”的默认实现；
- 任一抽象方法未实现时，项目 Live 在实例化或项目 check 阶段失败，不能等到运行中再 fallback；
- 方法签名不符合协议时，项目 check 失败；
- `ProvidedOutputLive`、stub 和 fallback 属于不同执行类型，不继承这两个 RealLive 抽象要求，也不得冒充 `RealServiceLive`。

## 9. 验证机制

### 9.1 运行时检查

RealLive 每轮必须检查：

1. request 通过 `REQUEST_SCHEMA`；
2. 至少一个 `carries_live_request=True` 的 Exchange 按 transport mapping 完整承载本轮 request；
3. 所有实际物理请求都已进入 `live_exchanges`；
4. 每次实际响应或错误已进入对应 exchange；
5. `deliver_real` 返回公共层传入的同一个 transport；
6. transport 已 seal，且至少一个 `contributes_raw_response=True` 的 Exchange 具有真实响应；
7. `raw_response` 由公共层按 sequence 从这些 Exchange 自动生成；
8. `extracted_output` 的业务事实与 `raw_response` 同源对齐；
9. `extracted_output` 通过 `EXTRACT_OUTPUT_SCHEMA`；
10. 成功状态与真实 exchange 一致；
11. 多轮会话标识符合项目连续性规则。

缺少真实交换、请求字段被静默丢弃、响应由本地补造等情况必须显式报协议错误，不能通过 fallback 变成成功。

### 9.2 公共契约测试

使用 transport fake 或本地测试服务断言：

```text
transport 实际收到的 request
== Trace.live_exchanges[i].request

transport 实际返回的 response
== Trace.live_exchanges[i].response
```

同时覆盖：

- 单 exchange 成功；
- 多 exchange 顺序；
- HTTP error、timeout 和网络异常；
- 成功但无 exchange 被拒绝；
- adapter 不能事后修改已记录事实；
- 敏感字段正确脱敏；
- provided/stub/fallback 不冒充 RealLive。

### 9.3 项目契约测试

每个 RealLive 项目必须验证：

- `REQUEST_SCHEMA` 的字段到达正确传输位置；
- carries-live-request Exchange 完整承载本轮 request，其他 Exchange 保持自身真实请求形状；
- request 中已有值不会被默认值无声覆盖；
- 项目返回传入的同一个 transport，公共层负责 seal；
- `raw_response` 由公共层从 contributes-raw-response Exchanges 自动生成；
- `extract_output` 只接收 `raw_response: list[Any]`；
- LLM 提取允许非确定性，但输出事实必须与来源内容对齐；
- 每轮 `extracted_output` 符合 `EXTRACT_OUTPUT_SCHEMA`；
- 多轮项目复用真实会话标识；
- Trace 与 transport fake 捕获内容逐字段一致。

### 9.4 UAT

同一配置分别执行 verifier RealLive 和独立直接调用 Live 系统，并比较：

- endpoint；
- 实际 request；
- 会话标识；
- HTTP 状态；
- 实际 response。

如最终结果不同，必须能够利用 `live_exchanges` 判断是请求、会话、模型、时序还是服务端非确定性导致。不能只比较最终文本，也不能用本地 `project_fields` 证明调用一致。

## 10. 前端展示

前端继续保持：

- Output：完整 `EXTRACT_OUTPUT_SCHEMA`；
- Reference：与 Output 相同 schema 和展示格式；
- Trace：展示完整执行链路。

Trace 核心交互按轮展示 `request` 和用户可见的 `extracted_output`；完整原始 Trace 折叠区按轮展示：

```text
request
live_exchanges
raw_response
extracted_output
project_fields
status/error/validation
```

`live_exchanges` 中必须明确区分实际 request 与实际 response。前端可以折叠或截断展示，但底层 Trace 不得因此丢失事实。

# 第二章：Changes

## 11. 当前现状差异

### 11.1 公共层

当前 `deliver_turn` 已经具备正确的主流程：

```text
validate request
→ deliver_real
→ raw_response
→ extract_output
→ validate output
```

当前 `TraceContext.record_turn` 也已经记录 request、raw_response、extracted_output、project_fields、status 和 error。

真正缺失的是：

- 没有 `live_exchanges`；
- 没有在 transport 边界自动捕获实际请求和响应；
- 公共层默认相信项目返回的任意对象就是 `raw_response`；
- 无法检查 adapter 是否丢弃、覆盖或重构了请求；
- 无法阻止本地拼装对象冒充 Live 原始响应。

### 11.2 DeerFlow

DeerFlow 已经有可复用的：

- `DeerflowApiRequest` / `REQUEST_SCHEMA`；
- `DeerflowTurnOutput` / `EXTRACT_OUTPUT_SCHEMA`；
- `extract_output`；
- 现有 turn record 和前端 Trace 链路。

当前实现偏差是：

- 已有 `REQUEST_SCHEMA` 没有被完整传导到 `/runs/wait`；
- adapter 重构 request body，只保留部分字段；
- thread/session/user/model 等字段可能被忽略或覆盖；
- 每轮无条件创建新 thread，破坏多轮连续性；
- `/runs/wait` 响应被丢弃；
- 读取 messages 后构造本地 `reply/tool_calls/messages` envelope；
- 本地 envelope 被记录为 `raw_response`；
- 部分字段使用 `case_id` 冒充真实 thread id。

这些问题应通过遵守现有 schema、记录真实 exchange 和修正 DeerFlow adapter 解决，不新增 DeerFlow 业务 schema。

## 12. 公共层一次性改造

### 12.1 扩展 TraceContext

为 `TraceContext.record_turn` 增加：

```python
live_exchanges: list[LiveExchange] | None = None
```

并原样写入当前 `turn_records`。更新 RunTrace normalizer、访问器、序列化、fixture 和前端 view，保证该字段不会在链路中丢失。

新增的公共 schema 仅为 `LiveExchange`；不新增 `RealLiveTurn`、`NativeOutput`、`DerivedOutput`、`DerivationRecord` 或 `LIVE_OUTPUT_SCHEMA`。

### 12.2 增加受控 transport

提供公共 transport 记录机制，至少覆盖项目当前使用的 HTTP 调用：

- 发送前捕获实际 method、URL 和 request；
- 返回时捕获 status、response 或 error；
- 自动追加到当前轮次 collector；
- 将捕获对象与项目后续可变对象隔离；
- 执行公共敏感字段脱敏。

项目仍决定如何调用业务系统，但 RealLive 路径必须使用该记录机制。

### 12.3 小幅改造 LiveProtocol

- 在每轮开始时创建 exchange collector；
- `deliver_real` 内的公共 transport 自动写入 collector；
- `deliver_real` 返回传入的同一个 transport；
- 公共层校验身份、seal transport，并自动生成 `raw_response: list[Any]`；
- 将扩展点签名统一改为 `extract_output(raw_response: list[Any]) -> EXTRACT_OUTPUT_SCHEMA`；
- 迁移所有项目的 `extract_output`，删除 request 参数及任何 request 回填输出的逻辑；
- 在 `RealServiceLive` 抽象基类上将 `deliver_real` 和 `extract_output` 声明为 `@abstractmethod`；
- 删除公共基类中 `extract_output` 的 dict 原样返回默认实现，RealLive 不允许继承模糊默认行为；
- 增加签名检查和抽象实现检查，未实现或签名不符的项目在实例化/check 阶段失败；
- `_TURN_FACTS` 增加 `live_exchanges`；
- `execute_live` 将其传给 `TraceContext.record_turn`；
- RealLive 成功时校验 exchange 非空；
- 保留现有 `deliver_turn` 返回值和 `extract_output` 扩展点；
- provided/stub/fallback 分支继续独立，不生成伪 exchange。

### 12.4 更新公共消费者

更新：

- RunTrace normalizer 和 accessors；
- show schema 与 frontend view；
- Check/protocol audit；
- JSON/表格导出；
- 公共 schema fixtures 和测试。

Judge 和 Attribute 默认继续使用 `extracted_output`。只有诊断执行失败或核验调用真实性时才按治理规则读取 `live_exchanges`，且只能读取脱敏内容。

## 13. DeerFlow 一次性改造

### 13.1 复用 REQUEST_SCHEMA

- 将现有 `DeerflowApiRequest` 原样传入 `/runs/wait` body；
- 明确 `config.configurable` 中 thread/session/user/model 字段的支持范围；
- 已有 thread id 时复用，缺失时才调用创建 thread；
- 请求 model 优先级必须显式，不能被项目默认值无声覆盖；
- 不支持的字段必须报错，不能接受后丢弃。

### 13.2 记录真实调用

按实际发生情况记录：

```text
GET  /health                                  （若本轮实际调用）
POST /api/threads                             （仅创建 thread 时）
POST /api/threads/{thread_id}/runs/wait
GET  /api/threads/{thread_id}/messages        （若输出提取需要）
```

每次调用成为一个 `live_exchanges` item。不得丢弃 `/runs/wait` 原始响应。

### 13.3 修正 raw_response 与输出提取

- DeerFlow `deliver_real` 使用传入的公共 transport 完成调用，并返回同一个 transport；
- `/runs/wait` 标记 `carries_live_request=True`；
- 实际构成业务输出的 `/runs/wait`、`/messages` 响应按真实语义标记 `contributes_raw_response=True`；
- 公共层按 sequence 自动生成 `raw_response: list[Any]`；
- 删除 `_normalized_request` 注入响应；
- 删除本地 response envelope；
- 本地整理的 thread、reply、tool call 和状态信息放入现有 `project_fields` 或按 `EXTRACT_OUTPUT_SCHEMA` 进入 `extracted_output`；
- `extract_output(raw_response)` 只接收公共层生成的响应列表，不得读取 request、Reference、fixture 或预期结果；
- 删除 `case_id` 作为 thread id 的证据字段。

### 13.4 修正多轮连续性

- 首轮从 request 或创建 thread 的真实响应确定 thread id；
- 后续轮次复用同一个 thread id；
- thread id 不一致或丢失时停止并显式报错；
- 不得通过创建新 thread 掩盖连续性失败。

## 14. Fixture 与测试迁移

### 14.1 公共 fixtures

增加：

- 单 exchange 成功；
- 多 exchange 成功；
- transport error；
- 成功但无 exchange；
- 请求字段传导；
- 敏感字段脱敏；
- provided/stub/fallback 与 RealLive 证据隔离；
- RealServiceLive 缺少 `deliver_real` 时不可实例化；
- RealServiceLive 缺少 `extract_output` 时不可实例化；
- 两个抽象方法签名不符合协议时 check 失败；
- 多轮会话连续性。

### 14.2 DeerFlow fixtures

增加或更新：

- 复用已有 thread；
- 缺少 thread 时创建并传导真实 id；
- `REQUEST_SCHEMA` body 完整传导；
- request model 不被默认值覆盖；
- `/runs/wait` 与 `/messages` 响应分别保留；
- 多轮复用 thread；
- thread 不一致时失败；
- `extracted_output` 符合现有 `EXTRACT_OUTPUT_SCHEMA`；
- Trace exchange 与 transport fake 逐字段一致。

删除依赖 `_normalized_request`、本地 raw envelope 和 case_id thread id 的旧 fixture 断言。

历史 Trace 只读保留。没有真实 exchange 的历史数据明确展示为“无传输证据”，不得反向补造 `live_exchanges`。

历史 `raw_response` 可能是单个 dict 或其他旧形状，只允许兼容读取和展示；不得把历史单值包装成列表后宣称其已经满足新的 RealLive 真实性协议。

## 15. 迁移顺序

1. 扩展 TraceContext、RunTrace 链路和 fixture，使其支持 `live_exchanges`；
2. 实现公共 transport 自动记录；
3. 小幅改造 LiveProtocol，把 exchange collector 接入现有 turn facts；
4. 迁移 DeerFlow，并完成独立直调对照 UAT；
5. 迁移其他 RealLive 项目；
6. 更新 Check、前端和导出；
7. 执行项目契约测试与全量回归。

迁移期间，尚未接入真实 exchange 记录的项目必须显式显示“传输证据缺失”，不能把现有本地 `raw_response` 当作已经验证的真实响应。

## 16. 完成标准

改造完成必须满足：

- 每轮 request 继续使用现有项目 `REQUEST_SCHEMA`；
- Output 和 Reference 继续使用现有 `EXTRACT_OUTPUT_SCHEMA`；
- 每个成功 RealLive turn 都存在真实 `live_exchanges`；
- 每个成功 Turn 至少有一个完整传导 `REQUEST_SCHEMA` 的 carries-live-request Exchange；
- Trace 中的 exchange request/response 与 transport 实际值一致；
- `raw_response` 不包含 adapter 本地补造字段；
- `raw_response` 是公共层从 contributes-raw-response Exchanges 生成的有序列表；
- `extracted_output` 的业务事实与该 `raw_response` 同源对齐；
- 多轮每一轮都是真实 Live 调用并保持项目要求的会话连续性；
- DeerFlow 完整传导已有请求 schema，不丢弃真实响应；
- provided、stub、fallback 和历史数据不会冒充 RealLive 证据；
- 所有 RealServiceLive 项目都显式实现协议签名一致的 `deliver_real` 和 `extract_output`；
- 没有为了修复真实性问题而新增重复业务 schema 或平行协议。
