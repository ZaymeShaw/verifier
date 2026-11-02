# Mock 协议化讨论记录（2026-09-07）

> 状态：讨论记录，未形成决议，未改任何代码。
> 用途：作为 spec/mock/ 下后续"会话协议（协议 A）/ 驱动协议（协议 B）"设计的原始输入。
> 本文按对话顺序原文记录，不做改写。

---

## 一、问题提出（用户原话）

我觉得现在确实有一个很关键的问题在于，mock的效果不好（特别是多轮场景），而且我很怀疑我们当前这种模式的mock的效果其实很可能基本无法做好，因为用户的行为其实是多种多样的，你很难分析它到底会怎么输入，而我们现在的mock模式是比较固化的，哪怕评估真的能做的比较准，mock做不全面可能也白搭，对mock的核心可能就是多样性/全面性。而且我很怀疑mock这个事情是否应该交给评测系统来完成，但是多轮的话你不mock数据这个流程又很难搞，而且复杂场景的评估肯定是要以trace为单位的，但是trace的话肯定无论live还是输入也好不可能都总是有生产数据，这就很难避开mock，我们看看怎么分析下这个问题，应该怎么做呢。

其实我觉得核心是主动和被动的区别
正常来说是用户主动调用，系统产生output和对应trace，通过trace测评系统效果
但是评测系统里面我们是主动想要验证测评系统效果，但是缺乏用户的输入，而且也无法等待用户的输入

我觉得其实是不是可以有一个这样的东西，就是我们建一个mock消费的协议，mock agent的核心职责首先是理解业务场景并且主观能动的去消费这个协议（即使用live系统），评测系统暴露这个消费的东西，而不是评测系统去扮演mock的角色，这样的话至少权责上不会说mock的实现受限于评测系统，因为我确实觉得mock agent这个东西评测系统可能很难做好，而且也非常冗余说实话。是不是类似a2a会比较类似这种模式？如果这样的话我可以类似于起一个子agent（可能子进程、普通llm、甚至一个外部的接口都可能，总之可以不受限），然后专门扮演一个用户，去使用评测系统背后绑定的live（类似于一个用户在等待live系统产出，live有新东西出来了他就继续用，这个其实是不是也比较类似于消费的模式？）。这样的话我们应该提供的就不是mock agent的实现，而是一套mock和live交互的协议，然后我们当前的mock模式可以作为其中一种mock方操作的方式，套到这个协议里面。主要这样的话他的可扩展性会高一点？我不知道这样是不是会更贴近世界运转的真实抽象一点。但是这样的话也要担心运行效率的问题，比如mock子agent如果卡着不动了judge的agent要咋整，也不能浪费效率吧感觉

你先别动任何代码，可以看看我们当前实现方案的缺陷，一起来讨论下先

---

## 二、现状分析与方案讨论（助手原话）

我看完了当前 mock/live/trace 这条链的实现，先说结论：你的诊断我基本同意，而且看了代码之后我觉得问题比"mock 多样性不够"更根本一点——**当前设计把"用户"、"会话驱动器"和"trace 记录者"三个角色揉在了评测系统一个进程里**，多样性差只是这个结构的表症。下面分三块说：现状的具体缺陷、你提的协议方案我怎么看、以及效率/卡死问题怎么处理。

### 一、当前实现的缺陷（对着代码说）

**1. 主循环归评测系统所有，用户只是被回调的四个函数。**

```222:233:impl/core/live_protocol.py
        mock = self._mock_for_multi_turn()
        max_turns = max(1, int(mock.safety_max_turns()))
        ...
        request = dict(initial_request or {})
        for turn_index in range(max_turns):
```

`_execute_multi_turn` 拥有 for 循环，mock 通过 `infer_user_intent` / `decide_next_action` / `build_next_request` / `safety_max_turns` 四个同步 Python 方法被回调。这意味着"用户"没有自己的时间线：它不能在 live 流式输出到一半时插话，不能连发两条，不能"等一等再说"，也不能被替换成子进程、外部接口或真人——只能是实现了 `MultiTurnInteractiveMock` mixin 的 Python 类。这就是你说的"mock 受限于评测系统"在代码上的具体体现。

**2. 用户没有私有状态，每一轮都是从 transcript 重新"变成"这个用户。**

`decide_next_action(intent, accumulated)` 和 `build_next_request(intent, accumulated)` 拿到的只有一个固定的 `intent` 加上 `accumulated["turns"]`（每轮的 request/extract_output）。真实用户有大量**没说出口的隐藏状态**：他知道但还没透露的信息、他的耐心余量、他对系统上一轮回答的私下判断、他中途改主意的新目标。当前结构里这些都不存在，每一轮的 LLM 调用都只能从可见对话反推自己是谁，行为自然趋同、趋于"配合"。

**3. intent 在第一轮固定，之后不能漂移。**

```294:299:impl/core/live_protocol.py
            if intent is None or not getattr(intent, "user_intent", "") or not getattr(intent, "query", ""):
                try:
                    intent = mock.infer_user_intent(dict(initial_request))
                    ...
                    ctx.set_intent(intent)
```

多轮系统最容易出问题的恰恰是用户目标变化、补充约束、推翻前提的时候，但现在 intent 是只从 `initial_request` 反推一次的常量。

**4. "是否继续"和"下一句说什么"被拆成两个上下文不同的 LLM 调用，而且评测层还在替用户改主意。**

```331:340:impl/core/live_protocol.py
            if (
                decision.action == "stop"
                and decision.stop_reason == "goal_satisfied"
                and not self._has_visible_goal_evidence(output)
            ):
                ...
                decision = MockContinueDecision(action="stop", stop_reason="perceived_no_progress")
```

`_has_visible_goal_evidence` 里写死了 `robot_text` / `card_summary` / `business_completed` 这类字段名——这是协议层带着对业务输出形状的假设去覆盖用户的判断。它本意是防 LLM 瞎判 goal_satisfied，但结果是评测系统既当裁判又替用户表态，权责混了。

**5. "用户"和"客户端"两个角色也是混的。**

`build_next_request` 要求返回 `REQUEST_SCHEMA` 形状。"用户说了一句话"和"把这句话装进 API 请求体"是两件事，后者是客户端/适配层的职责。现在它们都压在 mock 身上，导致 mock 实现必须懂业务 API，进一步抬高了替换 mock 的门槛。`MockAgent` 里那套 `_contains_internal_user_language` 正则修复（第 335 行）本质上就是在给这个混淆打补丁——用户说出了 `thread_id` 这种词，正是因为用户层被迫看到了 API 层。

**6. 多样性的来源太窄，而且系统性偏"乖"。**

`scenarios()` 直接返回 `spec.mock_scenarios`，`intent_labels()` 返回 `spec.intent_labels`，每个场景一次 `build_user_intent`。没有对用户隐变量（专业程度、耐心、目标清晰度、信息披露策略、是否带噪声/对抗）的采样。加上所有 MockAgent 调用都是 `reasoning_effort="low"`，LLM 扮演用户时默认会配合、连贯、不跑题——这恰好是真实用户最不像的地方。

**7. mock 基础设施故障和被测系统故障在 trace 里的区分是有的，但代价是整条 trace 报废。**

`decision_error` / `request_build_error` / `intent_unavailable` 都会 `break` 并把 `completion_status` 标成 `incomplete`。`record_interaction_controller` 确实把责任记在了 mock 头上，这点做得对，但这条 trace 就浪费掉了，而且如果统计时不小心，会把 mock 的锅算到 live 身上。

### 二、对你提的"协议化"方案的看法

方向我同意，但我想把它拆得更精确一点：**其实需要两个协议，不是一个。**

**协议 A：会话协议（session protocol）——用户方 ↔ 评测系统 ↔ live。**
评测系统在这里是一个**被动的代理兼记录员**：开会话、把用户消息转给 live、把 live 的事件（包括流式片段、卡片、工具调用）以事件流的形式推给用户方、把全过程记成 trace、关会话。它不决定用户什么时候说话、说什么、什么时候停。你说的"消费模式"就是这个——用户方订阅 live 事件流，有新东西就反应，没有就等。这和 `TraceContext.record_turn` 现在做的事其实是一致的，只是把"谁在推动这个循环"从评测系统换成了用户方。

**协议 B：驱动协议（driver protocol）——评测系统 → 用户方。**
评测系统仍然要主动发起测试，所以它要对某个"用户 agent"说：这是场景/画像/目标/预算，这是会话入口，去用吧，用完告诉我你为什么停。这一步才是 A2A 形状的东西：一个 task，带输入 artifact（persona + session endpoint + budget），异步执行，产出 artifact（stop_reason + 用户视角的自述）。A2A 本身是"委托任务给另一个 agent"，拿来做协议 B 很合适；做协议 A 就不太对味，协议 A 更像一个简单的 WebSocket/SSE 会话通道。

这样拆完之后权责就清楚了：

- 评测系统拥有：**测什么**（场景分布、画像采样策略、预算）、**记录**（trace）、**评判**（judge）。
- 用户方拥有：**怎么表现得像个用户**（私有状态、意图漂移、耐心、说话方式）。
- 项目 adapter 拥有：**用户的话怎么变成 API 请求、live 的响应怎么变成用户可见事件**（就是客户端那层，从 mock 里剥出来）。

当前 `MockAgent` 那套三段式 LLM 就变成协议 B 的一个**参考实现驱动器**，开箱即用但可替换。更重要的是，它让另外两种驱动器变得自然：

- **回放驱动器**：把生产日志里的用户轮次按会话协议重放（live 分叉时用 LLM 做少量适配）。这是多样性的最强来源，而且用同一套 trace 格式进 judge，不需要为"生产数据"单开一条特殊路径——你说的"trace 不可能总有生产数据"，恰好反过来：有生产数据时它只是众多驱动器之一。
- **外部/真人驱动器**：子进程、别的团队的 agent、甚至一个人坐在网页前，都只是协议 B 的一个实现。

你问这是不是"更贴近世界真实运转的抽象"——我觉得是的，因为真实世界里就是：用户有自己的时间线和隐藏状态，系统被动响应，观测者只记录不干预。当前设计里观测者在替用户做决定，这就是别扭的根源。

### 三、效率和"用户卡死了怎么办"

这块我觉得反而不难，关键是一个原则：**预算是评测系统的事，行为是用户的事。**

- 评测系统在协议 A 上强制执行：每轮等待用户消息的墙钟超时、整会话墙钟超时、最大轮数、token 成本上限。超了就由评测系统单方面关会话，`stop_reason` 写成 `driver_timeout` / `driver_budget_exceeded`，trace 照样落盘、照样可判（部分会话也有评判价值，你现在 `incomplete` 的处理已经是这个思路了）。
- 驱动器故障（超时、崩溃、返回非法消息）统一打上"基础设施故障"标签，在统计口径上**从 live 质量指标里剔除**，只进一个独立的"驱动器健康度"指标。你现在的 `interaction_controller_status` 已经是这个雏形，只是要把它提升为一等公民。
- judge 不应该等会话。执行和评判解耦成两个阶段：会话跑完 → trace 入队 → judge 消费队列。这样一个慢用户只占一个并发槽位，不会拖住 judge。多个会话之间本来就独立，并发跑就行。
- 成本上，参考驱动器保持现在这种轻量三小调用的形态，作为默认；重型驱动器（高 reasoning、外部 agent）按需选用。

### 四、几个我想提醒的点

1. **多样性问题协议本身解决不了，它只是让解决变得可能。**真正提升多样性靠的是对用户隐变量采样（画像、专业度、耐心、目标清晰度、信息披露策略、中途改主意）+ 允许驱动器持有私有状态。这两件事在现在的四回调结构里做不了，在协议化之后是驱动器内部的事。
2. **"评测系统不该做 mock"我只同意一半。**评测系统仍然应该拥有"测什么"的分布设计（这是测试设计，属于评测职责），只是不该拥有"用户怎么说话"。另外仓库里 `ProjectMock.generate_mock_case` 那条**离线生成 case 池**的路径和多轮在线驱动其实是两个不同的用途，前者（造首轮 input 进 case pool）协议化之后也还需要，别一起砍了。
3. **要防止过度设计。**如果做，我建议的顺序是：先把 `_execute_multi_turn` 里的循环抽成一个 `Session` 对象（open / send / events / close），现有 `MultiTurnInteractiveMock` 改成包在它外面的一个驱动器，零行为变化；然后给驱动器加预算；再把 Session 暴露成 HTTP/WebSocket 给外部驱动器；最后做回放驱动器。第一步完成后你就可以用测试验证 trace 逐字节相同，风险最小。
4. 还有一个隐含的收益：一旦"用户的话"和"API 请求"分层，judge 也能拿到更干净的 transcript（用户原话 vs 系统可见输出），而不是现在从 `request.get("query") or request.get("content")` 里猜用户说了什么（第 234 行）。

如果你觉得这个拆法对路，下一步可以先把协议 A/B 的消息形状和 stop_reason 枚举写成一份 spec 文档讨论，代码先不动。

---

## 三、涉及的现有代码位置（便于后续对照）

- `impl/core/live_protocol.py` — `_execute_multi_turn` 多轮主循环、`_has_visible_goal_evidence`
- `impl/core/mock_protocol.py` — `_MockProtocol` / `ProjectMock` / `SingleTurnMock` / `MultiTurnInteractiveMock`
- `impl/core/mock_agent.py` — `MockAgent.infer_user_intent` / `decide_next_action` / `next_turn` / `_contains_internal_user_language`
- `impl/core/trace.py` — `TraceContext.record_turn` / `record_interaction_controller` / `finish_execution`、`trace_from_live`
- `impl/core/pipeline.py` — `live_run`、`generate_mock_case` 离线 case 池路径
