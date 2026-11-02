# Mock 交互协议 spec（草案 v0.2）

> 状态：草案，供实现前评审。阶段 0 已完成（见 `stage0-task.md` 3.5 节）。
> 来源：本目录讨论记录（`discussion-2026090{7,8}-*.md`），本文是其决定的收敛版；讨论记录中与本文冲突处以本文为准。
> v0.2 变更：协议 B 由"评测系统下发任务"改为"探索侧 harness 主动拉、回归侧评测系统推"；阶段 3/4 改为工具化与 harness skill；新增导出硬约束与回放分叉处理。v0.1 备份见 `protocol-v0.1-backup.md`。
> 阅读顺序：不需要先读讨论记录，本文自足；想知道"为什么这么定"再回看讨论记录。

---

## 0. 一句话

评测系统不再扮演用户，也不再下发"扮演用户"的任务。评测系统提供一个**会话（Session）**——被动地把用户方消息转给 live、把 live 响应推回用户方、把全过程记成 trace——并把它以标准工具的形式暴露出去。**探索**由独立的 **harness**（外部 agent 进程）主动拉取 Session 自由进行，产出自动落成可复现的 mock 数据集与发现台账；**回归**由评测系统用确定性的 `ReplayDriver` 推着录好的 case 重跑。评测系统只拥有"工具与预算"、"记录"（trace）和"评判"（judge）。

---

## 1. 目标与非目标

### 1.1 目标

- 把多轮交互中"谁拥有循环"从评测进程翻转到用户方，使用户方可以是外部 agent（harness）、脚本、生产日志回放、真人。评测系统内不保留任何 LLM 扮演用户的代码。
- 允许用户方持有私有状态、允许意图在会话中漂移。
- 探索（找 live 做不好的场景）由 harness 以最高自由度进行；每条会话自然落成多轮 `RunTrace` 与可回放的 seed case，无需 harness 额外操作。
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
| **评测系统**（Session 工具 + 回归调度） | Session 工具、预算强制、trace 记录、导出候选 case 文件、judge 工具、回归回放（`ReplayDriver`） | 用户何时说话、说什么、何时停；探索什么 |
| **harness**（探索侧用户方，外部 agent） | 探索方向与策略、用户私有状态、意图（含推断与漂移）、每轮表达、停止决定、发现台账 | 请求体形状、live API 知识、`session_id` 的生成 |
| **用户**（通过探索页） | 给 harness 的方向性输入：覆盖目标、关注场景、策略偏好（参考，非任务） | — |
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
| `declare_intent` 列表 | `intent_history: [{turn_index, user_intent, user_context, source}]`，性质为 Mock Driver 的私有真值标签，只服务用户模拟、探索诊断和离线校准；正常 Judge 不读取。judge 从可见请求/对话自行推断，结果写在 `BusinessExpectation[*].user_intent` |
| Driver 停止决定 | `turns[].continue_decision`（沿用） |
| 归责 | `stop_reason` + 新增 `driver_health: {status, error, budget_usage}`；现 `interaction_controller_status/_error` 作为其别名保留至阶段 5 |
| 回放分叉 | 回归重放时新增 `diverged_at_turn: int | null`（见 5.3） |

### 4.10 导出硬约束

每条会话 `close` 后由 Session **自动**导出（不依赖用户方额外操作），且必须同时产出两样：

1. **完整多轮 `RunTrace`**（`execution_mode = interactive_intent`，含 `turn_records` / `conversation_transcript` / `conversation_summary` / `stop_reason`）——供现有多轮 trace 视图与 judge 使用。前端多轮展示因此无需改动。
2. **`level: transcript` 的 seed case**（单轮会话为 `level: request`）——以 `MockCase` 形态追加进候选文件
   `impl/data/<project>/mock_cases-<run_id>.json`（同 id 覆盖，无 run_id 则 `mock_cases-adhoc.json`），
   用户审后手动拷入 `mock_cases.json`，供回归回放。

**不允许**把多轮会话扁平化为单轮 case 导出。

---

## 5. 协议 B：探索（拉）与回归（推）

协议 B 不再是"评测系统下发任务"。它分为两条：探索侧由 harness 主动拉取 Session；回归侧由评测系统推着录好的 case 重放。两侧共用协议 A。

### 5.1 探索侧：harness 拉取

**Session 工具**（阶段 3 已实现：HTTP 路由 `/api/session/*`、`/api/ledger/*` + 无依赖 CLI `python -m impl.harness_cli`，见 `impl/core/session_store.py`、`impl/server/routes.py`；MCP / HTTP+SSE 不是必需）：

```
python -m impl.harness_cli [--server http://127.0.0.1:8022] ...
session open  <project> [--mode text|protocol-fuzz] [--max-turns N] [--pool NAME] [--run-id ID] [--scenario S]
                                                 → session_id（形如 harness-<project>-<hex12>）
session send  <session_id> --text "..." | --action name [--params json]  → live 可见输出（extracted_output）
session send  <session_id> --request <json>      # 仅 --mode protocol-fuzz 下允许，导出时打标签
session intent <session_id> --user-intent "..." [--source seeded|adopted_from_inference|drifted]
session close <session_id> --reason goal_satisfied|user_abandons|perceived_no_progress
                                                 # close 后 Session 自动按 4.10 导出：impl/data/<project>/sessions/<session_id>.json
                                                 # + 候选 case 文件 impl/data/<project>/mock_cases-<run_id>.json（无 run_id 则 adhoc）
session list|get ...
judge <project> <session_id>                     # 可选；对导出的 RunTrace 跑 judge，结果写回导出文件
ledger add|query ...                             # 发现台账，见 5.4；impl/data/<project>/ledger.json
exploration get|list|report ...                  # 领取探索方向 / 批次列表 / 交探索报告，见下
```

会话预算缺省：`turn_wait_timeout_ms=300000`、`session_timeout_ms=1800000`、`max_turns` 取项目 `safety_max_turns`；到限由 reaper 以 4.7 的 budget 组原因关闭并照常导出。

- `session_id` **只能**由 `open` 产生；无 `open` 直接 `send` 报错。case 之间的分割由工具结构保证，不依赖 harness 自觉。
- 默认 `--mode text`：只允许 `text` / `action` 消息，经 adapter 确定性翻译，保证请求体合法。`protocol-fuzz` 需显式开启，其会话在导出与台账中打 `protocol_fuzz` 标签，与"业务场景缺陷"分开统计。
- 评测系统在 Session 层强制 4.6 预算；探索层总预算（会话数、token、墙钟）由启动探索的入口设定，到限即停并交台账。

**探索方向输入**（用户在探索页 `explore.html` 给出，harness 作为参考而非任务；按 `run_id` 存于 `impl/data/<project>/explorations.json`，harness 用 `exploration get <project> <run_id>` 领取，探索结束用 `exploration report` 把报告写回同一条记录）：

```yaml
direction:
  coverage_targets: [scenario...]     # 希望至少覆盖的场景
  focus: str                          # 关注点的自然语言描述
  strategy_hints: [persona | scripted | adaptive-replay | boundary | drift]
  budget: { sessions, tokens, wall_clock_ms }
```

harness 侧策略与工作流以 skill 形式存在：`.claude/skills/harness/SKILL.md`（策略卡见 `references/strategies.md`）。

**harness 探索报告**（探索结束时产出）：

```yaml
run_id: str
sessions: int
findings: <台账快照，见 5.4>
coverage: { scenario: session_count }
budget_usage: { sessions, tokens, wall_clock_ms }
notes: str
```

### 5.2 回归侧：评测系统推

评测系统从 `mock_cases.json` 取 seed，用**确定性** `ReplayDriver` 经协议 A 重放：

- `level: request` / `utterance`：单轮重放。
- `level: transcript`：按录制的用户轮次**逐字**重放；`mode` 见 4.5。
- 评测系统内**不**做 LLM 适配式重放；需要"live 变了就改台词"的属于再探索，归 harness。

### 5.3 回放分叉

多轮 transcript 中每一轮用户消息都是针对录制时 live 的回答说的；live 改版后某轮回答变了，之后录好的用户消息可能不再切题。处理：

- 重放时逐轮比较新响应与录制响应（比较口径由 adapter 的 `extracted_output` 关键字段决定，默认比较用户可见文本与 `stage`），第一处不一致的轮次记入 `RunTrace.diverged_at_turn`。
- judge 只对 `diverged_at_turn` 之前的轮次下结论；之后的轮次作为参考展示。
- 无分叉时 `diverged_at_turn = null`。

### 5.4 发现台账（findings ledger）

harness 的探索记忆与最终交付物之一。每条记录：

```yaml
signature: str            # 失败签名：judge 的 blocking expectation_id + 失败维度（或 harness 自定义）
session_id: str
trigger_summary: str      # 触发方式摘要（用户视角）
realism: high | medium | low   # harness 自评"真实用户会这么干吗"
harness_verdict: fulfilled | not_fulfilled     # harness 作为真实用户的自评
judge_verdict: fulfilled | not_fulfilled | not_evaluable | null
category: live_defect | judge_calibration | protocol_fuzz
```

- 同 `signature` 去重：harness 每次 judge 后先查台账，已有签名不计新发现，促使换方向。
- `harness_verdict` 与 `judge_verdict` 一致 → `live_defect`；不一致 → `judge_calibration`（judge 校准样本，不计入 live 缺陷）。这直接承接"两个意图"的决定：harness 知道真值，judge 只能推断。
- 收敛判据：连续 N 个会话无新 `signature`（N 由探索入口设定）。

### 5.5 Driver 清单

| Driver | 归属 | 说明 | 阶段 |
|---|---|---|---|
| `LegacyMixinDriver` | 评测系统（过渡） | 包住现有 `MultiTurnInteractiveMock` 四回调，含 `_has_visible_goal_evidence` 原样搬入，保证零行为变化 | 1，阶段 5 删除 |
| `ReplayDriver` | 评测系统 | 确定性逐字重放，标 `diverged_at_turn` | 3 |
| harness 策略（persona / scripted / adaptive-replay / boundary / drift…） | harness | 以 skill 形式存在，不是评测系统代码 | 4 |

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
| `marketting-planning` | `user_text` + `extra_input_params.agent_args.message.content` | `session_id` | `history`（业务方从未定义元素格式，现有轮次一律发 `[]`） | False |
| `deerflow` | `input.messages[-1].content` | `config.configurable.thread_id`（服务端持状态） | 无 | False |

三者均已实现 `SessionTranslator`（阶段 3），`scripts/check_adapter_compliance.py` 对每个多轮项目跑 6.2 三道约束。`marketting-planning` 由 v0.1 表中的 True 改为 False：`history` 元素格式没有业务定义，adapter 不能"发明 transcript 中不存在的历史"（6.3），因此 `mode: context` 对它不可用；仅 `policy_search` 支持 context 注入（`contexts` 由 transcript 中的 user 文本逐条拼成）。首轮中 `marketting-planning`、`deerflow` 走 `MockAgent.build_live_request` 的 step2 LLM 路径，协议化后在线会话不再经过它（表达部分归 Driver，传输部分走 6.1），首轮与后续轮同路。

---

## 7. 用户方（harness / Driver）契约

适用于任何消费协议 A 的一方：探索侧的 harness、回归侧的 `ReplayDriver`、过渡期的 `LegacyMixinDriver`。

- 必须遵守协议 A 的消息类型；发出非法消息即 `driver_error`。
- `session_id` 只从 `open` 获得；一个 case 一个会话，不得跨会话复用。
- 在 `budget.turn_wait_timeout_ms` 内发出下一条消息或 `stop`，否则 `driver_timeout`。
- 可任意使用 LLM、脚本、外部资源；可持有任意私有状态。
- Driver 持有它所扮演用户的真实目标时（来自 seed、自行推断后据此行动、或会话中漂移），**应**发 `declare_intent` 并标明 `source`；没有真实目标（如纯回放）则不发。**不得为了让 trace 有意图而推断一个**——从可见行为推断意图是 judge 的职责，不是 Driver 的。
- Driver 为自身行动所做的意图推断（如从 request 级 seed 起手时的 `intent_from_transcript`）是 Driver 内部事务，其结果只有在 Driver 据此行动后才以 `source: adopted_from_inference` 记为标签。
- harness 在探索结束时产出探索报告（5.1）；`close` 时给出的 `stop_reason` 与 `session intent` 记录即为单会话层面的报告，不再有单独的 `DriverReport`。
- harness 默认只用 `text` / `action`；`request` 级需显式 `protocol-fuzz` 模式。

---

## 8. 与现有代码的对照

| 现有 | 去向 |
|---|---|
| `_execute_multi_turn` 的 for 循环 | 拆为 `Session`（open/send/events/close，内持 `TraceContext`）+ Driver 驱动 |
| `MultiTurnInteractiveMock` 四回调 | 阶段 1 由 `LegacyMixinDriver` 包裹；阶段 5 删除 |
| `_has_visible_goal_evidence` | 阶段 1 原样搬入 `LegacyMixinDriver`；阶段 5 删除 |
| `MockAgent.infer_user_intent` / `next_turn` / `decide_next_action` | 阶段 1 由 `LegacyMixinDriver` 间接调用；其"扮演用户"的职责由 harness skill 承担，阶段 5 删除 |
| `_execute_multi_turn` 的多轮执行与记录骨架 | 保留为 `Session` 核心；harness 每次 `send` 与 `ReplayDriver` 每轮重放均经由它 |
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
| 0 ✅ | 3 个多轮项目各录 golden trace（LLM 录制回放）；trace 比对脚本；补齐 `test_core_live_protocol.py` 对 `stop_reason` × `completion_status` × `interaction_controller_status` 组合的断言 | 同 case 两跑 trace 逐字节一致；多轮相关测试全绿。**已完成**，见 `stage0-task.md` 3.5 |
| 1 ✅ | 抽 `Session`、定义 `Driver`、写 `LegacyMixinDriver`；`ProjectSpec` 加开关，默认旧路径；trunk 开发 | 开关切新路径，六条 golden 逐字节一致（`tests/test_golden_multiturn.py`）。**已完成**：`impl/core/session.py`，`runtime.interaction.driver: legacy\|session` |
| 2 ✅ | 预算强制、`stop_reason` 按 4.7 分组、`driver_health`、执行与 judge 解耦为队列 | 人为 hang 住 Driver，会话在预算内关闭、trace 可判、live 指标不受污染。**已完成**：`impl/core/stop_reasons.py`、`tests/test_session_budget.py` |
| 3 ✅ | Session 工具化（CLI/MCP，5.1）；`close` 自动导出（4.10）进 case pool；judge 工具化；台账（5.4）；adapter 实现 6.1，`check_adapter_compliance.py` 加 6.2；`ReplayDriver` 与 `diverged_at_turn`（5.2、5.3） | 一个外部进程用 CLI 完成一场多轮会话，自动得到多轮 `RunTrace` + transcript seed，前端多轮视图正常显示；该 seed 经 `ReplayDriver` 重放可判。**已完成**（2026-09-10，policy_search 真实 live）：`impl/harness_cli.py` 两轮会话 → `impl/data/policy_search/sessions/harness-policy_search-82669356b2f7.json` + pool `harness-gate3` → summary.html 批量重放 2 轮、`intent_history` 与 `diverged_at_turn=null` 可见、judge `not_fulfilled`；台账 1 条 `live_defect` |
| 4 ✅ | harness skill（探索指令与工作流，含 persona / scripted / adaptive-replay / boundary / drift 策略）；探索页（方向输入 5.1、批次视图与台账展示）；首轮对抗探索 | 一轮探索产出台账与一批可重跑 case；台账中 `live_defect` 类经人工抽检真实性合格；`judge_calibration` 类单独成集。**已完成**（2026-09-10，policy_search 真实 live）：`.claude/skills/harness/`、`explore.html` + `/api/exploration/*` + `exploration get|list|report`；批次 `explore-20260910-01` 6 场会话（persona / boundary / drift）→ 用例池 `harness-explore-20260910-01` 6 条 transcript seed；台账 5 条：`live_defect` 3（后续轮只含数字时丢字段、短句纠正判 UNSUPPORTED）、`judge_calibration` 2（泛化拒绝是否算可补槽；同一 trace 两次 judge 结论相反）。**人工抽检待用户做**：台账 `trigger_summary` 均为用户口语可直接复现 |
| 5 | 删 `LegacyMixinDriver`、四回调、`_has_visible_goal_evidence`、两个补丁、别名字段；`MockAgent` 中扮演用户的 LLM 路径 | 全部项目在新路径稳定运行后执行 |

阶段 1 的 Session 消息模型须一次定下 4.2 的全部消息类型（含 `action`、`declare_intent`、`request`），即使阶段 1 只有 `LegacyMixinDriver` 在用其中一部分。

从评测系统 UI 一键 spawn harness 进程（无人值守探索）属阶段 4 之后的集成，不在本表。

---

## 10. 待办与开放问题

- **Judge 意图隔离已完成**：公开 Judge、RunChain、Batch 协议不接收 `user_intent`；固定 case 默认不持久化私有 intent；`trace.mock_intent` / `intent_history` 不进入 Judge evidence。`MockAgent.infer_user_intent` 留在 Driver 侧供其自身行动使用。以后若用私有真值校准 Judge，应建独立的离线校准步骤，不能把真值喂回被校准的 Judge。
- **多轮 provided**：Session 两侧（用户方、live 方）均可"提供或执行"的对称性成立；多轮 live 侧 provided 不在前五阶段范围。
- **A2A / HTTP+SSE**：harness 走 CLI/MCP 即可；如有外部 agent 需按 A2A 或 HTTP 接入，在 Session 工具外包薄层，不预先实现。
- **judge 结论对齐到轮**：多轮 trace 中"第几轮开始不对"目前不可见；先用 `diverged_at_turn` 与 harness 标注的失败轮次过渡，judge 分段评判与上条"两个意图"合并讨论。
- **前端新增项（均为加法，现有多轮视图不动）**：harness 旁注面板（逐轮 `declare_intent` 与 `source`、发现签名、真实性、`harness_verdict`）；探索批次视图与台账统计；探索页的方向输入。
- **一键 spawn harness**：从评测系统 UI 启动外部 agent 进程的集成方式。
- **探索收敛参数**：harness skill 暂定连续 3 场无新签名即停、缺省 6 场；是否需要评测系统侧强制另议。
- **judge 多轮口径**（首轮探索暴露）：同一 drift trace 两次 judge 结论相反——'中间轮返回错误的可执行结果（SUCCESS）'与'最终轮正确'谁优先；'泛化 UNSUPPORTED 提示'是否算可补槽的澄清。与 §10 第一条'两个意图'合并讨论。
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
| 阶段 0 完成；`cassette.py` 落于 `tests/support/`（测试设施域） | `stage0-task.md` 3.5 |
| mock 探索独立为 harness；协议 B 拆为探索拉 / 回归推；导出硬约束（多轮 `RunTrace` + transcript seed）；台账与 `live_defect` / `judge_calibration` 分类；默认仅 `text`/`action`；回放分叉 `diverged_at_turn`；探索方向由用户在探索页给出；阶段 3/4 改写 | `discussion-20260908-harness-exploration.md` |
