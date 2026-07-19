# Trace v2：Request-first 交互执行协议

本文定义 verifier 中 Mock、Live 与 Trace 的长期交互协议，并记录当前仓库迁移到该协议所需的一次性改造。

# 第一章：Spec 标准

## 1. 目标

协议以现实中可观测的用户行为为起点：业务系统能够直接接收的是 Live Request，而用户真实意图通常不可直接观测。执行入口必须以首轮 Live Request 为必填输入；用户意图是可选的用户模型，既可以由 Mock 正向生成，也可以从已有 Request 反向推断。

协议同时支持两种合法来源：

```text
模拟生成：User Intent → Live Request → execute_live
现实观测：Live Request → infer User Intent（按需）→ 多轮交互
```

两条路径在执行入口汇合，不允许将 Live Request 嵌入 Intent 作为隐式传输通道。

## 2. 分层职责

### 2.1 Mock 层

Mock 扮演有限认知的真实用户，负责：

- 根据场景生成用户模型；
- 根据用户模型生成首轮 Live Request；
- 在缺少显式用户模型时，从首轮 Live Request 反推有限的用户模型；
- 在每轮响应后进行轻量级继续/停止判断；
- 仅在决定继续后构建下一轮 Live Request。

`infer_user_intent` 是所有多轮项目必须实现的协议方法。因为 execute_live 允许 intent 缺失，多轮实现必须具备仅从合法首轮 Request 建立用户模型的能力。单轮项目不要求实现该方法。

Mock 不读取 Reference、Judge、Attribute、系统内部完成标准或其他评估答案。

### 2.2 Live 层

Live 负责一次完整的系统交互执行：

- 接收必填的首轮 Live Request；
- 校验并投递每轮 Request；
- 从原始响应提取符合 EXTRACT_OUTPUT_SCHEMA 的每轮 Output；
- 单轮项目在首轮后结束；
- 多轮项目协调 Mock 的意图反推、继续判断与后续 Request 构建；
- 返回最后一轮有效的 EXTRACT_OUTPUT_SCHEMA。

`deliver_turn` 仍表示一次业务调用；`execute_live` 表示一次完整交互，两者不可混同。

### 2.3 Trace 层

Trace 通过 TraceContext 记录实际发生的事实：

- 初始用户模型（如果存在）；
- 每轮实际投递的 Live Request；
- 每轮 Raw Response 与 Extract Output；
- 每轮状态、错误、耗时和降级事实；
- 每次继续/停止决定；
- 最终停止原因与安全上限触发情况。

Trace 不推断业务是否满足用户目标；Judge 基于完整 RunTrace 进行评估。

### 2.4 Case 层

Case 是持久化和跨层数据载体。首轮 Live Request 必填，Intent 可选；二者是并列事实，不互相嵌套。

```text
MockCase.intent        可选用户模型
MockCase.live_request  已生成或已观测的首轮请求
```

## 3. 用户模型

长期协议继续使用 `MockIntentOutput`。它表示 Mock 用户模型的结构化产物；无论由 Mock 正向生成还是从 Request 反向推断，都必须遵守同一 schema。

```python
@dataclass
class MockIntentOutput:
    user_intent: str
    query: str
    user_context: dict[str, Any] = field(default_factory=dict)
    system_understanding: str = ""
    scenario: str = ""
```

字段含义：

- `user_context`：用户身份、背景、经验与当前处境；
- `system_understanding`：用户主观上对当前被测业务 `<project>` 的了解，允许有限、不完整或错误；这里的“系统”专指用户正在使用的业务产品或 Agent，不是 verifier 测评系统；
- `user_intent`：用户希望达到的实际目标；
- `query`：用户最初表达；
- `scenario`：当前 `<project>` 内部的业务交互场景，不是项目名。项目名由 `project_id` 单独表达；例如 `project_id=deerflow` 时，scenario 可以是 `clarification`；

`MockIntentOutput` 禁止包含：

- `live_request`；
- Reference 或预期答案；
- Judge/Attribute 信息；
- 系统真实能力边界或内部完成标准；
- Trace、Raw Response 或运行日志。

生成 `system_understanding` 时只能使用真实用户可能接触的信息，例如被测 `<project>` 的产品名称、入口说明、用户既往使用经验和已经看到的业务回复。不得把 verifier、Judge、Evaluation、内部工具链或项目真实能力答案写入用户认知。

## 4. execute_live

### 4.1 定位

`execute_live` 是一次完整用户交互的统一执行入口，不是 Mock 构建入口，也不是单次 API 投递函数。

### 4.2 签名

```python
def execute_live(
    initial_request: REQUEST_SCHEMA,
    ctx: TraceContext,
    intent: MockIntentOutput | None = None,
) -> EXTRACT_OUTPUT_SCHEMA:
    ...
```

约束：

- `initial_request` 必填，并在第一次投递前通过 REQUEST_SCHEMA 校验；
- `intent` 可选，不得为了满足签名而编造；
- `ctx` 是事实记录器，不是业务输入；
- Case、Reference、Judge、Attribute 与前端对象不得进入 execute_live；
- execute_live 不重新生成或覆盖 initial_request。

### 4.3 单轮流程

```text
initial_request
→ validate REQUEST_SCHEMA
→ deliver_turn
→ extract_output
→ validate EXTRACT_OUTPUT_SCHEMA
→ ctx.record_turn
→ return output
```

单轮执行不要求存在 Intent。Intent 可供 Trace 与后续评估使用，但不是调用业务系统的前置条件。

### 4.4 多轮流程

```text
initial_request
→ deliver_turn
→ extract_output
→ resolve intent（仅当 intent 缺失）
→ decide_next_action
   ├─ stop：结束
   └─ continue
       → build_next_request
       → deliver_turn
       → extract_output
       → 重复判断
```

首轮 Request 始终以 execute_live 入参为准。后续 Request 必须基于用户模型和已经发生的交互事实逐轮生成，不允许预先生成完整多轮请求序列。

## 5. Intent 的生成与反推

### 5.1 正向生成

模拟场景按以下顺序构造执行输入：

```text
build_user_intent(scenario)
→ MockIntentOutput
→ build_initial_request(intent)
→ REQUEST_SCHEMA
→ execute_live(initial_request, ctx, intent)
```

### 5.2 从 Request 反推

反推函数的协议签名为：

```python
def infer_user_intent(
    initial_request: REQUEST_SCHEMA,
) -> MockIntentOutput:
    ...
```

输入必须是已通过项目 REQUEST_SCHEMA 校验的首轮 Live Request，输出必须通过 MockIntentOutput schema 校验。当调用方只有 initial_request 时：

- 单轮执行可以不推断 Intent；
- 只有多轮用户模拟需要继续时，才调用轻量 `infer_user_intent(initial_request)`；
- 原始用户意图推断只能依据首轮 Request 中的用户可见信息，不得使用系统后续回答反向改写；
- REQUEST_SCHEMA 提供结构和字段说明，项目声明提供用户表达字段映射；
- Token、鉴权、session、内部 config 等传输字段不得作为用户意图证据；
- 无证据的 user_context 与 system_understanding 保持空值，禁止补齐式编造；
- 推断结果只能表达 Request 中有证据支持的用户认知和意图。

当信息不足以形成可靠用户模型时，多轮交互停止并记录 `intent_unavailable`，不得虚构用户继续运行。

多轮项目必须实现该签名，不得依赖 execute_live 调用方一定提供 Intent。协议层分别校验输入 REQUEST_SCHEMA 和输出 MockIntentOutput；项目实现负责理解自身 Request 中哪些内容能够支持用户意图推断。

协议层通过抽象基类强制该要求：

```python
class MultiTurnInteractiveMock(ABC):
    @abstractmethod
    def infer_user_intent(
        self,
        initial_request: REQUEST_SCHEMA,
    ) -> MockIntentOutput:
        """从合法首轮 Request 反推有限用户模型。"""
        raise NotImplementedError
```

所有多轮项目 Mock 必须继承该抽象协议并实现方法；未实现的项目在实例化或项目 check 阶段失败，不能等到运行中再静默降级。单轮 Mock 协议不声明该抽象方法。

## 6. 多轮用户决策

### 6.1 行为顺序

每轮响应后必须先判断是否继续；只有决定继续后才能构建下一轮 Request。

```text
observe latest output
→ decide_next_action
→ continue ? build_next_request : stop
```

### 6.2 决策输入

决策输入限定为：

```python
@dataclass
class MockInteractionTurn:
    turn_index: int
    live_request: dict[str, Any]
    extract_output: dict[str, Any]
    status: str
    error: str | None = None
```

协议传参继续使用 `accumulated_output: dict`，其标准形状为：

```python
{
    "turns": list[MockInteractionTurn],
    "current_turn": int,
    "safety_max_turns": int,
}
```

不传入 Raw Response、完整 RunTrace、Reference、Judge、Attribute、运行日志或内部执行事件。

输入长度必须受控：Intent 始终保留；最近轮次优先保留完整 Request/Output；超过上限时按声明字段做确定性裁剪，不调用额外模型生成长摘要。

### 6.3 决策输出

```python
@dataclass
class MockContinueDecision:
    action: Literal["continue", "stop"]
    stop_reason: Literal[
        "",
        "goal_satisfied",
        "user_abandons",
        "perceived_no_progress",
    ] = ""
```

要求：

- 使用最低可用 reasoning effort；
- 使用严格结构化输出和很小的输出 token 上限；
- 不输出自由文本长解释；
- 判断模拟用户的主观行为，不判断系统客观上是否符合 Evaluation；
- `continue` 表示目标尚未满足，但交互仍有实质进展，例如获得了新信息、新结果或问题范围正在收敛；证据不足以停止时也应继续；
- `goal_satisfied` 表示用户从可见结果主观认为目的已达到；
- `user_abandons` 表示用户明确不愿继续；
- `perceived_no_progress` 表示经过持续交互后长期没有实质进展，例如反复询问相同问题、连续失败，且没有新增有效信息、结果或目标收敛；不得仅因为尚未交付最终结果或仍在进行合理澄清而使用该状态。

### 6.4 后续 Request

```python
def build_next_request(
    intent: MockIntentOutput,
    accumulated_output: dict[str, Any],
) -> REQUEST_SCHEMA:
    ...
```

它保留现有 Intent + accumulated_output 的输入形式。`decide_next_action` 使用相同两个入参；accumulated_output 的标准结构仅包含各轮 live_request、extract_output、status/error 以及当前轮次和安全上限。只有 action 为 `continue` 时才调用，输出必须通过 REQUEST_SCHEMA 校验。

## 7. 最大轮数与停止原因

最大轮数仅是安全熔断，不是正常用户停止策略。长期协议名称为 `safety_max_turns`，默认建议值为 12，项目可在合理范围内覆盖。

协议层停止原因包括：

- `goal_satisfied`；
- `user_abandons`；
- `perceived_no_progress`；
- `intent_unavailable`；
- `safety_max_turns`；
- `live_error`。

达到安全上限不能标记为用户目标完成；Trace 和前端必须显式展示 `safety_max_turns`。

## 8. Request 与 Intent 的映射规则

Intent 和 Request 是并列对象，映射允许双向发生，但不得互相嵌套：

```text
Intent → build_initial_request → Request
Request → infer_user_intent → MockIntentOutput
```

规则：

- Request 是 execute_live 的客观权威输入；
- Intent 是用户行为模型，允许缺失或推断；
- 同时存在时保留两者，不重新覆盖 initial_request；
- 不允许通过 `intent.live_request`、metadata 私有字段或其他旁路传递 Request。

## 9. Trace 要求

RunTrace 至少记录：

- `intent`（如果存在或成功反推）；
- `initial_request` 和每轮实际 Request；
- 每轮 Extract Output；
- 每轮继续/停止决定；
- `stop_reason`；
- `final_output_turn`；
- `completion_status`。

Trace 中展示的 Input 必须来自实际投递 Request，不得用候选 Case Input 替代。Case 与结果的归位使用稳定 case identity/request key，不使用 Request 内容相等性。

## 10. 错误处理

- initial_request 不符合 REQUEST_SCHEMA：执行前失败，记录 `request_validation_error`；
- Output 不符合 EXTRACT_OUTPUT_SCHEMA：该轮失败，记录 `output_validation_error`；
- Intent 反推失败：多轮停止为 `intent_unavailable`，不得生成虚假用户；
- 决策模型失败：允许一次受控重试，仍失败则停止并记录 `decision_error`；
- build_next_request 失败或不符合 schema：停止并记录 `request_build_error`；
- Live 调用失败：停止为 `live_error`，保留已发生轮次。

## 11. 测试要求

协议测试至少覆盖：

- execute_live 拒绝缺失或非法 initial_request；
- execute_live 不覆盖 initial_request；
- Intent 缺失时单轮仍能执行；
- Intent 缺失时多轮按需反推；
- 反推失败不会编造 Intent；
- MockIntent/UserIntent 不含 live_request；
- scenario 与 project_id 语义独立，scenario 只能取项目内业务场景；
- system_understanding 只描述用户对被测业务 project 的认知，不泄漏 verifier 信息；
- 未实现 infer_user_intent 的多轮 Mock 无法实例化且项目 check 失败；
- 决定 stop 后不再构建或投递 Request；
- 决定 continue 后只构建一轮 Request；
- safety_max_turns 仅作为熔断且停止原因准确；
- 决策输入不包含 Reference/Judge/Raw Response/RunTrace；
- Trace Input 与实际投递 Request 一致；
- case 归位不依赖 Request 内容完全一致。

# 第二章：Changes

## 1. 现状差异

当前仓库与第一章标准存在以下差异：

1. `MockIntentOutput` 包含 `live_request`，混合用户语义与传输请求；
2. `trace_from_live()` 在 SingleTurnCase.input 符合 REQUEST_SCHEMA 时，把 Request 反向写入 `intent.live_request`；
3. 多个项目的 `build_live_request()` 通过读取 `intent.live_request` 实现重放旁路；
4. `execute_live(intent, ctx)` 只接收 Intent，并在内部生成首轮 Request；
5. Fixture 已有 Request 与新生成 Request 缺少显式、并列的传递结构；
6. `MockIntentOutput` 缺少 `system_understanding`；
7. 多轮 `should_stop(transcript, last_result) -> bool` 未接收完整用户模型，且无法表达停止原因；
8. `build_next_request(intent, accumulated)` 与 should_stop 使用不同形状的上下文；
9. deerflow 与 marketting-planning 的 `max_turns()` 固定为 4；
10. 当前停止主要依赖 AI 回复关键词，不是模拟用户的轻量主观决策；
11. 当前 MockNextTurnOutput 只包含 query，不支持独立的继续/停止决策；
12. Trace 尚未完整记录决策结果和安全停止原因。

## 2. Schema Changes

1. 从 `MockIntentOutput` 删除 `live_request`；
2. 增加 `system_understanding`；
3. 将 MockCase.intent 调整为可选字段，MockCase.live_request 保持必填；
4. 新增 `MockInteractionTurn` 与 `MockContinueDecision`，并定义 accumulated_output 标准形状；
5. 为停止原因增加统一枚举；
6. 在 `MultiTurnInteractiveMock` 增加 `infer_user_intent` 的 `@abstractmethod`，由抽象协议和项目 check 双重保证；
7. 更新 normalize、serialize、accessor、fixture 和 schema hook；
8. 历史数据中的 `intent.live_request` 只读迁移到 Case 顶层 `live_request`，不得继续写回 Intent。

## 3. Mock Changes

1. 将首轮 Request 构建统一为 `build_initial_request(intent)`；
2. 新增轻量 `infer_user_intent(initial_request: REQUEST_SCHEMA) -> MockIntentOutput`，并分别校验输入、输出 schema；
3. 新增轻量 `decide_next_action(state)`；
4. 保留 `build_next_request(intent, accumulated_output)` 签名，并标准化 accumulated_output 内容；
5. 删除所有项目中 `if intent.live_request is not None` 旁路；
6. 更新 Mock Agent 意图输出 schema，生成 `system_understanding`；
7. 更新下一轮 Prompt：先进行独立短决策，决定继续后再调用 Request 构建；
8. 决策调用配置低 reasoning effort、小 token 上限和严格枚举输出；
9. 项目声明 Request 中的用户表达字段，供 Intent 反推和输入裁剪使用。

## 4. Live Changes

1. 将 execute_live 签名迁移为 `execute_live(initial_request, ctx, intent=None)`；
2. 单轮分支直接投递 initial_request，不再调用 build_live_request；
3. 多轮分支以 initial_request 执行首轮；
4. 多轮 intent 缺失时，在首轮 Request 上执行按需反推；
5. 每轮 Output 后先调用 decide_next_action；
6. 仅 continue 时调用 build_next_request；
7. 将 max_turns 改为 safety_max_turns，并把默认值从 4 调整为 12；
8. 删除 AI 回复完成关键词作为通用停止逻辑；
9. 保持 deliver_turn 的单次请求职责不变。

## 5. Trace 与 Pipeline Changes

1. pipeline 在生成场景中执行 Intent → initial_request 两步 Mock；
2. pipeline 在已有 Request 场景中直接构造 execute_live 入参，Intent 可以缺失；
3. `trace_from_live()` 不再修改 Intent，也不再根据 REQUEST_SCHEMA 把 Case Input 注入 Intent；
4. TraceContext 增加决策与停止原因记录方法；
5. RunTrace Input 始终记录实际 initial_request；
6. Batch 结果通过稳定 case ID/request key 归位，禁止使用请求内容相等性；
7. 前端展示 continue decision 和明确 stop_reason；
8. 历史 Trace 缺少新字段时只读兼容，不回写伪造值。

## 6. 项目 Changes

需要迁移的项目包括：

- QA；
- client_search；
- deerflow；
- marketting-planning；
- marketting-planning-intent；
- core fixture project 与 verifier/data 中对应 fixture。

单轮项目：

- 将 build_live_request 迁移或兼容为 build_initial_request；
- 删除 intent.live_request 读取；
- 验证由 Intent 正向生成的首轮 Request 符合 REQUEST_SCHEMA。

多轮项目：

- 实现 Request 用户表达字段映射；
- 必须实现 `infer_user_intent(initial_request: REQUEST_SCHEMA) -> MockIntentOutput`；
- 通过继承 `MultiTurnInteractiveMock` 的 `@abstractmethod` 在类实例化时强制实现，不允许仅靠文档约定；
- 将 should_stop 关键词逻辑迁移为 decide_next_action；
- 保留 build_next_request 的现有签名，并切换到标准化 accumulated_output；
- 提高 safety_max_turns，并验证正常用例主要由用户决定停止。

## 7. Intent 入参职责影响

本次变更不能机械地删除所有 Intent 入参。需要按方法职责分为三类。

### 7.1 必须改为 Request-first 的方法

- `ProjectLive.execute_live(intent, ctx)` 改为 `execute_live(initial_request, ctx, intent=None)`；
- 单轮 `_execute_single_turn(intent, ctx)` 改为接收 initial_request，不再调用 Mock 构建首轮 Request；
- 多轮 `_execute_multi_turn(intent, ctx)` 改为接收 initial_request 和可选 Intent，首轮先执行 Request，缺 Intent 时调用 infer_user_intent；
- `trace_from_live(live, case, intent=None)` 改为从 Case 分别提取必填 live_request 与可选 intent，不再把 Request 回填 Intent；
- `live._resolve_intent(case, mock)` 不再作为每次执行的必经步骤。已有 Intent 时只做读取/校验；Intent 缺失时，单轮保持为空，多轮交给 infer_user_intent；
- pipeline 的 `live_run`、`run_chain`、batch case 和 interactive case 入口需要传递首轮 Request 与可选 Intent。

### 7.2 仍应以 Intent 为输入的方法

- `build_user_intent(scenario) -> MockIntentOutput` 仍负责生成用户模型；
- `build_initial_request(intent) -> REQUEST_SCHEMA` 仍是模拟生成路径中的 Intent→Request 映射；
- `MockAgent.build_live_request` 及 `build_live_request_from_intent` 可迁移命名为 build_initial_request，但语义仍以 Intent 为输入；
- QA、client_search、marketting-planning-intent 等单轮项目的首轮 Request 构建方法仍接收 Intent，只是不再由 execute_live 内部调用。

这些方法承担的正是 Intent→Request 映射职责，协议变化不应将其改成 Request 输入。

### 7.3 共享标准 accumulated_output 的方法

- `build_next_request(intent, accumulated_output)` 保持签名不变，但 accumulated_output 改为标准受限结构；
- `should_stop(transcript, last_result)` 被 `decide_next_action(intent, accumulated_output)` 替代；
- deerflow 与 marketting-planning 的对应项目实现同步迁移；
- MockAgent.next_turn 改为读取受限 accumulated_output，不能接收完整 Trace 或评估信息。

### 7.4 不属于本次 Intent 协议的同名参数

Judge、Attribute、draft tool 中的 `user_intent: str` 或 `expected_intent` 是评估输入，不是 MockIntentOutput，也不参与 Request 构建。本次不得仅因参数名包含 intent 就修改其签名；只需确保它们从 RunTrace 或显式评估输入读取，不接触 Mock 内部决策。

### 7.5 直接影响文件

一次性迁移至少覆盖：

- `impl/core/live_protocol.py`；
- `impl/core/trace.py`；
- `impl/core/pipeline.py`；
- `impl/core/mock_protocol.py`；
- `impl/core/mock_agent.py`；
- `impl/core/schema/mock.py` 及 normalize/fixture/accessor；
- 五个项目的 mock 实现；
- core live、Mock 协议、batch、fixture、schema hook 与前端相关测试。

## 8. 数据迁移 Changes

1. 扫描 `verifier/data`、项目 fixture 与 core fixture 中的 Intent；
2. 将 `intent.live_request` 提升到 Case 顶层 `live_request`；
3. Intent 缺少 `system_understanding` 时保留空字符串，不从内部文档虚构；
4. 无 Intent 的历史 Case 保持 intent 为空，不为满足 schema 而补造；
5. 数据迁移保持只读旧格式兼容，并为新写入格式禁止 Intent 内 live_request。

## 9. 测试与验收 Changes

1. 更新协议、schema hook、fixture、项目和前端测试；
2. 为单轮项目验证“Request 必填、Intent 可选”；
3. 为多轮项目验证“首轮 Request → Intent 反推 → 决策 → 下一轮 Request”；
4. 验证决策输入长度上限和字段白名单；
5. 验证目标达成、用户放弃、主观无进展、安全上限、Intent 不可用和 Live 错误；
6. 在五个业务项目分别执行真实 UAT；
7. 核对 Trace 中每轮 Request/Output 与业务调用一致；
8. 核对前端不再出现 Input A、Output B 或结果错误归位；
9. 批量回归历史 fixture，确认旧格式可读、新格式不再写入污染字段。

## 10. 迁移顺序

1. 先新增 schema 与兼容读取，不立即删除旧字段读取；
2. 改造 Mock 与 execute_live 新签名；
3. 改造 trace_from_live 与 pipeline 参数传递；
4. 迁移五个项目和 fixture；
5. 切换多轮决策与 safety_max_turns；
6. 更新 Trace/前端展示与批量归位；
7. 完成跨项目回归后，删除 Intent live_request 兼容写入和项目旁路；
8. 最后保留旧数据只读解析，禁止新数据产生旧结构。
