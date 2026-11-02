# Mock 协议化：实施节奏讨论记录（2026-09-07）

> 状态：讨论记录，未形成决议，未改任何代码。
> 前序：`spec/mock/discussion-20260907-mock-protocol.md`（问题提出与协议 A/B 方案）。
> 本文按对话顺序原文记录，不做改写。

---

## 一、问题提出（用户原话）

这不是一个小的改动，我们应该按什么节奏来做这个事情？

---

## 二、节奏建议（助手原话）

看了几个决定节奏的事实：多轮项目只有 3 个（`policy_search`、`marketting-planning`、`deerflow`），其余 5 个是单轮；多轮循环的行为锁定基本集中在 `tests/test_core_live_protocol.py` 一个文件里；server 层目前没有任何流式/WebSocket 基础。`live_protocol.py` 823 行、`mock_agent.py` 769 行，要动的核心就 `_execute_multi_turn` 那 170 行加 `TraceContext`。

我的建议是分五个阶段，每个阶段有一个明确的"通过条件"，通不过就不进下一阶段。总的节奏原则是：**先把结构改对但行为不变，再在进程内验证新接口能带来多样性，最后才对外暴露网络协议**。理由是网络协议一旦暴露，消息形状就冻结了，最好在进程内迭代两轮再定。

### 阶段 0：先立基线，不写业务代码

在改任何东西之前，为 3 个多轮项目各录一组 golden trace（用现有 mock 跑，把 LLM 调用录下来回放，保证可重复），并写一个 trace 比对脚本。这是后面所有重构的安全网。同时把 `test_core_live_protocol.py` 里对多轮循环的断言过一遍，缺的补上——尤其是 `stop_reason` 各分支、`interaction_controller_status`、`completion_status` 三者的组合。

通过条件：同一 case 跑两次 trace 逐字节一致；23 处多轮相关测试全绿。

这一步看起来像是在拖延，但它决定了后面每一步能不能放心地说"零行为变化"。

### 阶段 1：抽 Session，包 Driver，零行为变化

把 `_execute_multi_turn` 里的循环拆成两块：一个 `Session` 对象（`open / send(user_message) / events / close`，内部持有 `TraceContext`，负责调 `deliver_turn` 和 `record_turn`），一个 `Driver` 接口（`run(session, task) -> DriverReport`）。然后写一个 `LegacyMixinDriver`，它内部拿着现有的 `MultiTurnInteractiveMock` 实例，把四个回调原样翻译成对 Session 的调用。`_has_visible_goal_evidence` 这类评测层替用户改主意的逻辑，这一步**先原样搬进 LegacyMixinDriver**，不删，保证行为等价。

三个项目的 mock 文件一行不动。用 `ProjectSpec` 上加一个开关（比如 `interaction_driver: legacy | session`）切换新旧路径，默认仍走旧路径，在 trunk 上开发，不开长期分支——这个仓库有定期打快照的习惯，长期分支合回来会很痛。

通过条件：开关切到新路径，阶段 0 的 golden trace 逐字节一致。

这阶段是纯重构，规模中等，风险最低，但价值最大：做完之后"谁拥有循环"这个问题就翻过来了。

### 阶段 2：预算与故障归责成为一等公民

在 Session 层加预算：每轮等待用户的墙钟、整会话墙钟、最大轮数、token 上限。新增 `stop_reason` 枚举值 `driver_timeout` / `driver_budget_exceeded` / `driver_error`。把 `interaction_controller_status` 从 trace 里的一个附属字段提升为独立的 `driver_health` 结构，并在 judge 前的统计口径里明确：driver 侧故障不计入 live 质量指标。

这一步顺带解决"mock 卡死 judge 怎么办"：Session 超时单方面关会话，trace 落盘，judge 照常消费。执行和评判的解耦（trace 入队、judge 异步消费）如果 `batch_jobs.py` 现在还是同步串行的，也在这一步改。

通过条件：人为让 driver hang 住，会话在预算内被关闭，trace 可判，live 指标不受污染。

### 阶段 3：在进程内做第二个 Driver，验证接口、交付多样性

这是真正解决你最初问题的阶段，也是对阶段 1 接口的第一次实战检验。写一个 `PersonaDriver`：持有私有状态（画像、未披露信息、耐心余量、可能的中途改意），每轮一次 LLM 调用同时决定"还继续吗"和"说什么"，输出的是**用户原话**而不是 `REQUEST_SCHEMA`。用户原话到 API 请求的翻译下沉到项目 adapter 的一个新扩展点（比如 `Live.request_from_user_message`），这样 `_contains_internal_user_language` 那类补丁就自然消失了。

`MockAgent` 现有的 prompt 这一步**不要**同时重写，先原样复用它的 `_complete_json` 基础设施，只改结构。多样性来自画像采样，采样分布放在评测系统这边（这是"测什么"的职责）。

先在 `policy_search` 一个项目上跑通，对比新旧两个 driver 产出的 trace 在 judge 结果分布上的差异，再推到另外两个项目。

通过条件：同一场景跑 N 次，用户行为（轮数、停止原因、话题漂移）有可观测的方差；judge 能发现旧 driver 没暴露出的问题。如果这一步做完发现 Session 接口有别扭的地方，回去改接口——这时候改还便宜。

### 阶段 4：对外暴露，接回放

Session 接口经过两个进程内 driver 验证后才冻结消息形状，暴露成 HTTP + SSE（不需要 WebSocket，用户发消息是普通 POST，live 事件用 SSE 推就够了）。写一个最小的外部 driver 示例（子进程读 SSE、写 POST），证明"不受限"。然后写 `ReplayDriver`：读生产日志的用户轮次按 Session 协议重放，live 分叉时用 LLM 做少量适配。

A2A 兼容性这一步先不做。如果后面确实有外部 agent 要按 A2A 接入，在 HTTP 接口外面包一层 A2A task 语义是薄的；反过来一开始就上 A2A 是重的。

通过条件：一个纯外部进程能完整驾驭一场多轮会话并产出可判 trace；一份生产日志能回放成 trace。

### 阶段 5：清理

三个项目迁到 `PersonaDriver` 或各自的 driver 后，删 `LegacyMixinDriver`、删 `MultiTurnInteractiveMock` mixin 的多轮回调、删 `_has_visible_goal_evidence`。这一步要等阶段 3 在三个项目上都稳定后再做，不着急。

### 几个不动的东西

单轮路径 `_execute_single_turn` 全程不碰。`ProjectMock.generate_mock_case` 那条离线造 case 池的路径不碰。judge 层不碰，除了阶段 2 的统计口径。`deliver_turn` 的请求/响应语义不碰——流式事件推给用户方这件事，在阶段 4 做 SSE 时如果 live 本身支持流式再接，否则一轮一个事件也完全够用。

### 最需要你现在拍的两个决定

一是阶段 0 要不要做得这么严（golden trace 加 LLM 录制回放）。我倾向于做，因为它是后面四个阶段的共同安全网，但它本身不产出任何用户可见价值，需要接受这一点。二是阶段 3 用户原话到 API 请求的翻译下沉到 adapter，这会给三个多轮项目各加一个必须实现的扩展点，是唯一一处需要项目层配合的改动，要提前和项目 owner 说清楚。

---

## 三、讨论时核对到的仓库事实（便于后续对照）

- 多轮项目（`MultiTurnInteractiveMock` + `MultiTurnInteractiveLive`）：`policy_search`、`marketting-planning`、`deerflow`
- 单轮项目（`SingleTurnMock`）：`llm_probe`、`marketting-planning-intent`、`client_search`、`QA`（`deerflow` 另有 `DeerflowMockBase`）
- 多轮循环相关测试主要集中在 `tests/test_core_live_protocol.py`（约 23 处），`tests/test_protocols.py`、`tests/test_project_config_contract.py` 少量
- `impl/server/` 目前没有 SSE / WebSocket / StreamingResponse 相关实现
- 文件规模：`impl/core/live_protocol.py` 823 行、`impl/core/mock_agent.py` 769 行、`impl/core/trace.py` 474 行；三个多轮项目 mock 分别为 235 / 112 / 136 行

## 四、待拍板事项

1. 阶段 0 是否按"golden trace + LLM 录制回放"的严格程度执行
2. 阶段 3 新增 adapter 扩展点（用户原话 → API 请求）需项目层配合，是否接受
