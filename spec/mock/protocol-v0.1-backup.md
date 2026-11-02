# Mock 交互协议 spec（草案 v0.1）

> 状态：草案，供实现前评审。未改任何代码。
> 来源：本目录四份讨论记录（`discussion-20260907-*.md`），本文是其决定的收敛版；讨论记录中与本文冲突处以本文为准。
> 阅读顺序：不需要先读讨论记录，本文自足；想知道"为什么这么定"再回看讨论记录。

---

## 0. 一句话

评测系统不再扮演用户。评测系统提供一个**会话（Session）**——被动地把用户方消息转给 live、把 live 响应推回用户方、把全过程记成 trace；由一个可替换的**驱动器（Driver）**扮演用户去消费这个会话。评测系统只拥有"测什么"（seed、预算）、"记录"（trace）和"评判"（judge）。

---

## 1. 目标与非目标

### 1.1 目标

- 把多轮交互中"谁拥有循环"从评测进程翻转到用户方，使用户方可以是进程内 LLM、脚本、生产日志回放、外部进程、真人。
- 允许用户方持有私有状态、允许意图在会话中漂移。
- 生产数据（request 形状、含或不含响应的多轮 transcript）作为一等输入直接进入，不要求先翻译成"用户原话"。
- 用户原话到 API 请求体的翻译必须确定性、不经 LLM、可自动校验，杜绝改偏原意。
- 用户方故障与被测系统故障在 trace 与统计口径上严格分离。
- 现有三个多轮项目零行为变化迁移。

### 1.2 非目标（本次不做，见第 10 节）

- judge 如何消费带轮次的意图列表。
- 多轮 provided（live 侧响应由数据提供而非执行）。
- A2A 兼容层。
- 离线 case 池路径（`ProjectMock.generate_mock_case`）的重构；仅补 seed 层级标签。
- 单轮路径 `_execute_single_turn` 的任何改动。

---

## 2. 角色与归属

| 角色 | 拥有什么 | 不拥有什么 |
|---|---|---|
| **评测系统**（Session + 调度） | 测什么（seed 分布、画像采样策略）、预算、trace 记录、judge | 用户何时说话、说什么、何时停 |
| **Driver**（用户方） | 用户私有状态、意图（含推断与漂移）、每轮表达、停止决定 | 请求体形状、live API 知识 |
| **项目 adapter** | 原话 ↔ 请求体的确定性互转、live 历史字段格式、live 调用 | 任何语义推断、任何 LLM 调用（在本协议涉及的方法内） |

---

## 3. 三层与双向映射

用户输入存在三个层级，**每一层都是合法入口**，协议定义层间的双向映射：

```
意图 (intent)  ←→  原话 (utterance)  ←→  请求 (request)
```

| 方向 | 意图 ↔ 原话 | 原话 ↔ 请求 |
|---|---|---|
| 向下（生成） | **Driver**，允许 LLM。`utterance_from_intent` | **adapter**，确定性。`request_from_user_message` |
| 向上（推断/提取） | **Driver**，允许 LLM。`intent_from_transcript` | **adapter**，确定性。`user_message_from_request` |

对应现有代码：向下左列 = `build_user_intent` / `MockAgent.next_turn`；向上左列 = `MockAgent.infer_user_intent`；向下右列 = 各项目 `build_next_request` 的槽位填充；向上右列 = 各项目 `extract_mock_message`。四者已存在，本协议只做归位。

---

## 4. 协议 A：会话协议（Driver ↔ Session ↔ live）

### 4.1 生命周期

```
open(seed_prefix?, mode?, budget) → [send / events]* → close(stop_reason)
```

- Session 由评测系统创建，绑定一个项目的 live 与 adapter。
- Session 是**被动**的：只在收到用户方消息时调用 live；只在 live 返回时推事件；只在预算超限时主动关闭。
- 一个 Session 对应一条 `RunTrace`。

### 4.2 用户方 → Session 的消息

```yaml
# 三种用户消息（UserMessage），同一会话内可混用
- type: request
  payload: <REQUEST_SCHEMA>          # 原样透传，adapter 只做 user_message_from_request 提取原话进 transcript
- type: text
  text: str                          # adapter 经 request_from_user_message 确定性翻译
- type: action
  name: str                          # 对应真实产品中的按钮/选择等结构化动作
  params: dict                       # adapter 做一对一字段映射，不做语义推断

# 一种控制消息：Driver 把它正在扮演的用户的真实目标记为标签
- type: declare_intent
  user_intent: str
  user_context: dict
  source: seeded | adopted_from_inference | drifted
  # seeded：来自 seed.intent；adopted_from_inference：Driver 为继续行动自行推断并据此行动；drifted：会话中改变目标。
  # 可多次发送。Session 追加记录为带轮次的列表，不加工。
  # 这是模拟世界中的"真值标签"，不是给 judge 的推断输入——judge 自行从可见行为推断意图（见 4.9、10）。
  # Driver 有真实目标则记，没有则不记；不得为了填空而推断一个。

# 一种终止消息
- type: stop
  stop_reason: goal_satisfied | user_abandons | perceived_no_progress
```

### 4.3 Session → 用户方的事件

```yaml
- event: session.opened      { session_id, budget, transcript_prefix }
- event: live.response       { turn_index, extracted_output, raw_response? }   # 每轮一次
- event: live.stream         { turn_index, chunk }                             # 可选，live 支持流式时才有
- event: live.error          { turn_index, error, recoverable }
- event: session.closed      { stop_reason, completion_status, driver_health }
```

用户方**只看到用户可见信息**：`extracted_output`（及可选 `raw_response`）。不暴露 `execution_trace`、`validation`、`project_fields` 等评测内部事实。

### 4.4 Session 交给 adapter 的 `session_state`

adapter 的 `request_from_user_message(message, session_state)` 收到的只读状态：

```yaml
session_id: str                # Session 分配，adapter 只搬运
turn_index: int
transcript:                    # 到目前为止的全部轮次（含 seed 前缀）
  - role: user      | content: str | request: dict
  - role: assistant | content: str | extracted_output: dict
last_request: dict | null      # 上一轮实际发出的请求体（继承 thread_id 等用）
```

### 4.5 seed 前缀与 `mode`

`open` 时可带 transcript 前缀（来自生产数据）：

- `mode: replay`：Session 把前缀中每个 request 依次真实打到 live，得到**当前** live 的响应，再交给 Driver 继续。前缀中的历史响应仅作为 `transcript_prefix` 提供给 Driver 参考。
- `mode: context`：前缀不执行；Session 把前缀放入 `session_state.transcript`，由 adapter 在拼下一轮请求体时注入 live 的历史字段。**要求 adapter 声明 `supports_history_injection = True`**，否则 Session 拒绝 `open` 并明确报错，**不得静默降级为 replay**。

### 4.6 预算（评测系统强制执行）

```yaml
budget:
  max_turns: int                     # 替代现 safety_max_turns
  turn_wait_timeout_ms: int          # 等用户方下一条消息的墙钟
  session_timeout_ms: int            # 整会话墙钟
  token_limit: int | null            # 用户方 LLM 成本上限（可选，由 Driver 自报）
```

任一超限，Session 单方面关闭，`stop_reason` 取对应预算值（见 4.7），trace 照常落盘。

### 4.7 `stop_reason` 枚举（按归责方分组）

| 归责 | 值 | 说明 |
|---|---|---|
| 用户决定 | `goal_satisfied` / `user_abandons` / `perceived_no_progress` | Driver 发 `stop` 时给出（沿用现值） |
| 预算 | `max_turns` / `session_timeout` / `driver_timeout` / `driver_budget_exceeded` | Session 强制关闭。`max_turns` 替代现 `safety_max_turns` |
| Driver 故障 | `driver_error` | Driver 崩溃、发出非法消息、协议违约 |
| adapter 故障 | `adapter_error` | 翻译违反第 6.2 节约束、request schema 校验失败等。替代现 `request_build_error` |
| live 故障 | `live_error` | 沿用现值 |
| 遗留 | `intent_unavailable` / `decision_error` | 仅 `LegacyMixinDriver` 内部产生，阶段 5 删除 |

统计口径：**只有"用户决定"和"live 故障"两组计入 live 质量指标**；预算、Driver 故障、adapter 故障三组进入独立的 `driver_health` 指标，不污染 live 评判。

### 4.8 `completion_status`

- `completed`：由用户决定停止。
- `incomplete`：由预算或 Driver/adapter 故障停止，且至少有一轮有效 live 输出。
- `failed`：没有任何一轮有效 live 输出。

### 4.9 trace 落点

| Session 事实 | RunTrace 字段 |
|---|---|
| 每轮 request / response / extracted_output | `turns[]`（沿用 `TraceContext.record_turn`） |
| 用户原话（`user_message_from_request` 提取或 `text` 消息原文） | `turns[].mock_message` |
| `declare_intent` 列表 | 新增 `intent_history: [{turn_index, user_intent, user_context, source}]`，性质为模拟用户的真值标签（对应今天 `case.user_intent` 的角色）；`mock_intent` 暂取最后一条并携带 `source`，保持 judge 现状。judge 的推理意图是另一个东西，今天散在 `BusinessExpectation[*].user_intent`，显式化见第 10 节 |
| Driver 停止决定 | `turns[].continue_decision`（沿用） |
| 归责 | `stop_reason` + 新增 `driver_health: {status, error, budget_usage}`；现 `interaction_controller_status/_error` 作为其别名保留至阶段 5 |

---

## 5. 协议 B：驱动协议（评测系统 → Driver）

### 5.1 任务（DriverTask）

```yaml
task_id: str
project_id: str
session_endpoint: <进程内对象 | HTTP+SSE URL>
seed:
  level: intent | utterance | request | transcript
  # 按 level 恰有一项：
  intent:     { user_intent, user_context, scenario }
  utterance:  { text, scenario? }
  request:    <REQUEST_SCHEMA>
  transcript: { turns: [...], mode: replay | context }
persona: dict | null            # 评测系统采样出的用户隐变量（专业度、耐心、目标清晰度、披露策略、是否漂移…）
budget: <同 4.6>
```

`seed.level` 决定 Driver 的起手：
- `intent`：向下生成首句原话。
- `utterance`：直接发 `text`；需要意图时自行向上推断。
- `request`：直接发 `request`；拿到首轮响应后向上推断意图并 `declare_intent`，之后用 `text`/`action` 继续。
- `transcript`：Session 按 `mode` 处理前缀；Driver 从前缀推断意图并 `declare_intent`，之后继续。

### 5.2 报告（DriverReport）

```yaml
task_id: str
final_intent: { user_intent, user_context, source } | null   # Driver 最终持有的真实目标标签；无则 null，不得推断补造
stop_reason: <用户决定组之一> | null                  # null 表示不是 Driver 主动停的
turns_sent: int
tokens_used: int | null
notes: str                                            # 用户视角自述，可选
```

### 5.3 参考 Driver

| Driver | 说明 | 阶段 |
|---|---|---|
| `LegacyMixinDriver` | 包住现有 `MultiTurnInteractiveMock` 四回调，含 `_has_visible_goal_evidence` 原样搬入，保证零行为变化 | 1 |
| `PersonaDriver` | 持有私有状态；每轮一次 LLM 同时决定"继续否"与"说什么"；输出原话 | 3 |
| `ScriptedDriver` | 按预写脚本发原话（现 `policy_search` 的 `next_query` 路径收敛于此） | 3 |
| `ReplayDriver` | 读生产日志用户轮次按协议 A 重放，live 分叉时少量 LLM 适配 | 4 |
| 外部 Driver 示例 | 独立进程经 HTTP+SSE 消费 Session | 4 |

---

## 6. adapter 契约

### 6.1 新增扩展点（多轮项目必须实现，**仅此一个**）

```python
def request_from_user_message(self, message: UserMessage, state: SessionState) -> dict:
    """text/action → REQUEST_SCHEMA。确定性，不经 LLM。"""

def user_message_from_request(self, request: dict) -> UserMessage:
    """REQUEST_SCHEMA → text/action。即现有 extract_mock_message 的升级，与上者互逆。"""

supports_history_injection: bool   # 能否把 state.transcript 注入请求体的历史字段（决定 mode: context 是否可用）
```

`history_from_transcript` 之类把 transcript 转成 live 历史字段格式的逻辑，是 adapter **内部**功能函数，不是协议扩展点，协议不关心其存在与命名。

### 6.2 三道自动约束（协议层 + `check_adapter_compliance.py` 强制）

1. **往返不变式**：`user_message_from_request(request_from_user_message(m, s)) == m`，逐字符相等。协议层每轮断言，违反即 `adapter_error`。
2. **禁 LLM**：LLM 客户端替换为一调用即抛异常的桩后，`request_from_user_message` 仍必须成功。
3. **确定性**：同 `(m, s)` 两次调用，剔除声明的易变字段（`trace_id`、`ts`、uuid 类）后结果相等。

### 6.3 允许 / 禁止

允许：文本原样入槽；搬运 Session 分配的会话身份（`session_id` / `thread_id` / `trace_id`）；根据只读 `state.transcript` 拼 `history` / `contexts`；填常量信封字段。

禁止：改写、摘要、拆句、加前缀；从文本推断结构化参数（如把"上个月"解析成日期）；任何 LLM 调用；发明 transcript 中不存在的历史。

### 6.4 三个多轮项目的现状对照

| 项目 | 原话槽位 | 会话身份 | 历史字段 | `supports_history_injection` |
|---|---|---|---|---|
| `policy_search` | `extra_input_params.policySearchParseArgs.query` | `session_id` / `trace_id` | `extra_input_params.args.contexts` | True |
| `marketting-planning` | `user_text` + `extra_input_params.agent_args.message.content` | `session_id` | `history` | True |
| `deerflow` | `input.messages[-1].content` | `config.configurable.thread_id`（服务端持状态） | 无 | False |

三者的后续轮翻译现已是纯 Python，满足 6.2。首轮中 `marketting-planning`、`deerflow` 走 `MockAgent.build_live_request` 的 step2 LLM 路径，协议化后在线会话不再经过它（表达部分归 Driver，传输部分走 6.1），首轮与后续轮同路。

---

## 7. Driver 契约

- 必须遵守协议 A 的消息类型；发出非法消息即 `driver_error`。
- 在 `budget.turn_wait_timeout_ms` 内发出下一条消息或 `stop`，否则 `driver_timeout`。
- 可任意使用 LLM、脚本、外部资源；可持有任意私有状态。
- Driver 持有它所扮演用户的真实目标时（来自 seed、自行推断后据此行动、或会话中漂移），**应**发 `declare_intent` 并标明 `source`；没有真实目标（如纯回放）则不发。**不得为了让 trace 有意图而推断一个**——从可见行为推断意图是 judge 的职责，不是 Driver 的。
- Driver 为自身行动所做的意图推断（如从 request 级 seed 起手时的 `intent_from_transcript`）是 Driver 内部事务，其结果只有在 Driver 据此行动后才以 `source: adopted_from_inference` 记为标签。
- 会话结束后返回 `DriverReport`。

---

## 8. 与现有代码的对照

| 现有 | 去向 |
|---|---|
| `_execute_multi_turn` 的 for 循环 | 拆为 `Session`（open/send/events/close，内持 `TraceContext`）+ Driver 驱动 |
| `MultiTurnInteractiveMock` 四回调 | 阶段 1 由 `LegacyMixinDriver` 包裹；阶段 5 删除 |
| `_has_visible_goal_evidence` | 阶段 1 原样搬入 `LegacyMixinDriver`；阶段 5 删除 |
| `MockAgent.infer_user_intent` / `next_turn` / `decide_next_action` | 迁入 `PersonaDriver`（表达层） |
| `MockAgent.build_live_request`（step2 LLM） | 在线会话不再调用；离线 case 池暂保留 |
| `_preserve_chat_user_query` / `_contains_internal_user_language` | 阶段 5 删除 |
| `extract_mock_message` | 升级为 `user_message_from_request` |
| `safety_max_turns` | 并入 `budget.max_turns` |
| `ctx.set_intent` | 成为 `declare_intent` 的落点，记为带 `source` 的列表；多轮时 `infer_user_intent` 的结果不再以真值身份直接写入 |
| `interaction_controller_status/_error` | 成为 `driver_health` 的别名，阶段 5 删除 |
| `case.input`（REQUEST_SCHEMA） | 视为 `seed.level = request`，合法保留；补层级标签 |
| `ProjectSpec` | 新增 `interaction_driver: legacy \| session` 开关（阶段 1），默认 `legacy` |

---

## 9. 实施阶段与通过条件

| 阶段 | 内容 | 通过条件 |
|---|---|---|
| 0 | 3 个多轮项目各录 golden trace（LLM 录制回放）；trace 比对脚本；补齐 `test_core_live_protocol.py` 对 `stop_reason` × `completion_status` × `interaction_controller_status` 组合的断言 | 同 case 两跑 trace 逐字节一致；多轮相关测试全绿 |
| 1 | 抽 `Session`、定义 `Driver`、写 `LegacyMixinDriver`；`ProjectSpec` 加开关，默认旧路径；trunk 开发 | 开关切新路径，golden trace 逐字节一致 |
| 2 | 预算强制、`stop_reason` 按 4.7 分组、`driver_health`、执行与 judge 解耦为队列 | 人为 hang 住 Driver，会话在预算内关闭、trace 可判、live 指标不受污染 |
| 3 | `PersonaDriver`（先 `policy_search`，再推另两项目）；adapter 实现 6.1，`check_adapter_compliance.py` 加 6.2；`ScriptedDriver` | 同场景 N 跑用户行为有可观测方差；judge 发现旧 Driver 未暴露的问题 |
| 4 | Session 暴露 HTTP+SSE；外部 Driver 示例；`ReplayDriver` | 纯外部进程完成一场多轮会话并产出可判 trace；一份生产日志回放成 trace |
| 5 | 删 `LegacyMixinDriver`、四回调、`_has_visible_goal_evidence`、两个补丁、别名字段 | 全部项目在新路径稳定运行后执行 |

阶段 1 的 Session 消息模型须一次定下 4.2 的全部消息类型（含 `action`、`declare_intent`、`request`），即使阶段 1 只有 `LegacyMixinDriver` 在用其中一部分。

---

## 10. 待办与开放问题

- **两个意图的关系（judge 侧，另开讨论）**。现状：driver 端真值标签（`trace.mock_intent`）与 judge 端推理意图（散在 `BusinessExpectation[*].user_intent`）在多轮时被混在一起——评测进程替 mock 推的工作假设以真值身份传给了 judge（`pipeline.py` 第 572 行附近）。本协议只做 driver 侧修正（`source` 标签、不为填空而推）。judge 侧待议：
  - 把 judge 的推断显式化为 `JudgeResult.inferred_intent`，与 `intent_history` 中的真值标签对比，用于校准 judge、以及在有真值时多判一层"真实目标是否满足"。
  - `mock_intent` 进 judge prompt 时携带来源标签，让 judge 知道这是"模拟用户自报的目标"而非正确答案，防锚定。
  - `intent_history` 多条时取哪条 / 是否分段评判。
  - `MockAgent.infer_user_intent` 留在 driver 侧供其自身行动使用，**不**迁入 judge；judge 走自己的推断。
- **多轮 provided**：Session 两侧（用户方、live 方）均可"提供或执行"的对称性成立；多轮 live 侧 provided 不在前五阶段范围。
- **A2A**：如有外部 agent 需按 A2A 接入，在协议 B 的 HTTP 接口外包薄层即可，不预先实现。
- **离线 case 池**：补 `seed.level` 标签并允许 intent / utterance / transcript 三种新形态；step2 LLM 路径的去留另议。
- **live 流式**：`live.stream` 事件仅在 live 本身支持流式时接入；否则一轮一个 `live.response` 即可。

---

## 11. 决定记录索引

| 决定 | 出处 |
|---|---|
| 两个协议（会话 A / 驱动 B）而非一个；预算归评测系统、行为归 Driver | `discussion-20260907-mock-protocol.md` |
| 五阶段节奏与通过条件；先结构不变行为，再进程内验证，最后对外暴露 | `discussion-20260907-rollout-pacing.md` |
| 阶段 0 按严格版；adapter 翻译确定性纯代码 + 三道约束；意图/表达/传输三层归属；用户消息为联合类型 | `discussion-20260907-adapter-translation.md` |
| 三层皆为入口、双向映射；`request` 级消息与 `transcript` seed；`mode: replay/context`；`declare_intent` 可多次；扩展点仅一个 + 布尔能力；case 池存法修正 | `discussion-20260907-seed-levels.md` |
| 意图分两个：driver 端真值标签（可选、带 `source`、不为填空而推）与 judge 端推理意图（judge 自行推断，今天已隐含在 `BusinessExpectation.user_intent`）；`infer_user_intent` 留在 driver 侧；judge 显式化另议 | `discussion-20260907-two-intents.md` |
