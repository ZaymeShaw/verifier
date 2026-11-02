# Mock 协议化：阶段 0 决定与 adapter 翻译层约束（2026-09-07）

> 状态：讨论记录，已形成两项决定（见文末），未改任何代码。
> 前序：`discussion-20260907-mock-protocol.md`（协议 A/B 方案）、`discussion-20260907-rollout-pacing.md`（五阶段节奏）。
> 本文按对话顺序原文记录，不做改写。

---

## 一、决定与顾虑（用户原话）

1 阶段0要做的
2 用户原话到api请求的翻译，我觉得这个你立意方面确实说的有道理，但是我担心翻译把用户原意给改偏了，需要避免这一点，这块的adapter的处理最好是不经过llm的？只是每个项目要实现的一个东西。总之要看看怎么避免和约束吧

---

## 二、现状核对与约束方案（助手原话）

看完三个多轮项目的 `build_next_request`，先说一个好消息：**你担心的"LLM 翻译改偏用户原意"，在后续轮次里现在就已经不存在，三个项目的翻译都是纯 Python。** 真正有 LLM 翻译的地方只在首轮，而且已经出过问题、打过补丁。下面按事实、约束方案、需要一起决定的一个小点来说。

### 现状事实

后续轮次里，LLM 只产出一个字符串 `query`，项目代码把它原样塞进一个固定槽位，其余字段全是确定性地从上一轮 request 继承或写常量：

- `policy_search`：塞进 `extra_input_params.policySearchParseArgs.query`，`contexts` 用上一轮的问答拼出来，`session_id` 继承、`trace_id` 加 `-turnN` 后缀（第 217 到 232 行）。
- `marketting-planning`：塞进 `user_text` 和 `agent_args.message.content` 两处，信封字段全是常量（第 67 到 85 行）。
- `deerflow`：塞进 `input.messages[-1].content`，`thread_id` 从上一轮输出或请求里取（第 59 到 75 行）。

首轮就不一样了。`policy_search` 自己覆盖了 `build_initial_request`，是确定性的；但 `marketting-planning` 和 `deerflow` 走的是 `ProjectMock.build_initial_request` 默认路径，它委托 `MockAgent.build_live_request` 的 "step2 LLM"——把 intent 和 REQUEST_SCHEMA 的 JSON schema 一起喂给模型，让模型直接生成整个请求体。`_preserve_chat_user_query`（`mock_agent.py` 第 222 行）就是这条路的补丁：模型生成完之后再把用户原话强行写回 `messages[-1].content`，而且只对 chat 形状的请求有效。这说明你担心的漂移已经在首轮真实发生过。

所以结论是：阶段 3 新加的 adapter 扩展点不是引入一个新的翻译层，而是**把后续轮次已经存在的确定性做法提升为协议要求，同时把首轮那条 LLM 路径从在线会话流程里拿掉**。

### 怎么约束到"不经过 LLM、不改原意"

我建议把这个扩展点定义成 `request_from_user_message(message, session_state) -> request`，并在协议层加三道硬约束，都是能自动检查的，不靠自觉：

**第一道：往返不变式。** 三个项目都已经有 `extract_mock_message(request)`，它就是这个扩展点的逆函数。协议层在每次调用后断言 `extract_mock_message(request_from_user_message(msg, state)) == msg`，逐字符相等，不等就当 adapter 违约、trace 标 `adapter_error`。这一条直接堵死了改写、摘要、拆句、加前缀。

**第二道：禁 LLM，用故障注入证明。** 在 `scripts/check_adapter_compliance.py` 里加一项：把 LLM 客户端换成一个一调用就抛异常的桩，然后跑 `request_from_user_message`，必须成功。这比静态扫 import 可靠，也不用信任项目 owner 的声明。

**第三道：确定性。** 同样的 `message` 和 `session_state` 调两次，除去允许的易变字段（`trace_id`、`ts`、uuid 类）后结果相等。这一条保证 adapter 里没有采样、没有随时间变化的推断。

adapter 在这个扩展点里**允许**做的事只有三类：把文本原样放进指定槽位；携带会话身份（`session_id` / `thread_id` / `trace_id`），身份由 Session 分配、adapter 只搬运；根据 Session 提供的只读 transcript 拼 `history` / `contexts`（真实客户端也会带历史，这是客户端行为不是翻译）。**不允许**做的是从文本里推断结构化参数——比如把"上个月"解析成日期填进某个字段。

### 一个需要顺带定的小点：结构化用户动作怎么办

上面那条"不允许从文本推结构化参数"会碰到一个真实情况：有些业务 API 的字段在真实产品里来自用户点按钮、选日期，而不是打字。`policy_search` 请求里的 `user_action: "write"`、`action_scenario` 就是这类。如果只允许纯文本消息，driver 就没法表达"用户点了确认"。

我的建议是用户消息不是一个字符串而是一个很小的联合类型：`{type: "text", text}` 或 `{type: "action", name, params}`。文本消息按上面三道约束原样入槽；动作消息由 driver 显式选择，adapter 做的是一对一字段映射（`action.name` 对应哪个 `user_action` 值，`params` 落到哪些字段），同样是确定性、可往返校验的。这样"用户意图"始终由 driver 决定，adapter 永远只是搬运，不做任何语义推断。这个联合类型的形状建议在阶段 1 设计 Session 的消息模型时就定下来，虽然阶段 3 才用到。

### 对既有代码的影响

`MockAgent.build_live_request` 那条 step2 LLM 路径，在线会话流程不再调用，但离线造 case 池（`generate_mock_case`）还在用它生成首轮 input，先保留，不在这个改造范围内。`_preserve_chat_user_query` 和 `_contains_internal_user_language` 两个补丁在阶段 5 一起删。另外 `policy_search` 的 `decide_next_action` / `build_next_request` 其实是一个按 `user_context.next_query` 预写脚本走的用户，它到阶段 3 会自然变成一个 `ScriptedDriver`，是继 `LegacyMixinDriver`、`PersonaDriver` 之外第三种驱动器，也不需要额外设计。

两个决定我都记下了：阶段 0 按严格版做；阶段 3 的 adapter 翻译层必须是确定性纯代码，配上面三道自动检查。这一轮的结论我还没写进 `spec/mock/`，你确认方向没问题的话我再按之前的格式追加一份记录。

---

## 三、关于首轮归属的补充（用户原话）

嗯。另外我补充下那个首轮的本来就不是用户原话更多是意图的抽离，根据用户意图来推断用户可能会发出的指令的，那个其实应该在用户mock的进程里面完成才对计算要做（原话之前）

---

## 四、三层归属的收敛（助手原话）

同意，这个补充把边界说得更准了。首轮那个 step2 LLM 现在其实是把两件事一步做掉了："从意图推出用户会说的话"和"把话装进请求体"。前者是用户建模的最后一步，天然属于 driver；后者才是 adapter 的确定性搬运。拆开之后，整条链就是三段、三个归属：

- **意图层**（评测系统，"测什么"）：场景、画像、目标——现在 `MockIntentOutput` 里的 `user_context` / `user_intent` 已经是这个东西。
- **表达层**（driver，"用户怎么说"）：从意图产出原话（首轮）或下一句原话（后续轮），可以用 LLM、脚本、回放，随便。`MockIntentOutput.query` 和 `MockAgent.next_turn` 都是这一层，只是现在跑在评测进程里。
- **传输层**（adapter，"客户端怎么发"）：原话到请求体，确定性，受三道约束。

有意思的是，这个三层结构在 `mock_protocol.py` 的 docstring 里早就写着"背景 → 意图 → 表达"，概念是对的，只是首轮把表达和传输合并成一次 LLM 调用、后续轮又把表达放进了评测进程的回调里。所以阶段 3 对首轮的处理不是"删掉 step2"，而是把它里面的表达部分挪进 driver，传输部分交给 adapter 的确定性方法，首轮和后续轮走同一条路。

顺带一个影响：离线 case 池现在存的 `case.input` 是 REQUEST_SCHEMA 形状，也就是传输层产物。按这个分层，case 池更合理的存法是意图加原话（用户侧的东西），请求体在运行时由 adapter 确定性推出。这是另一个改动，不放进这次的范围，但值得记一笔，否则以后 case 池和在线会话会长出两套翻译。

---

## 五、本轮形成的决定

1. **阶段 0 按严格版执行**：golden trace + LLM 录制回放 + trace 比对脚本，作为后续阶段的安全网。
2. **adapter 翻译层（`request_from_user_message`）必须是确定性纯代码，不经过 LLM**，由协议层和 `check_adapter_compliance.py` 自动施加三道约束：
   - 往返不变式：`extract_mock_message(request_from_user_message(msg, state)) == msg`
   - 禁 LLM：LLM 客户端换成抛异常的桩后仍必须成功
   - 确定性：同输入两次调用结果一致（排除 `trace_id` / `ts` / uuid 类易变字段）
3. **三层归属**：意图层归评测系统，表达层（意图 → 原话，含首轮）归 driver，传输层（原话 → 请求体）归 adapter。首轮 step2 LLM 中的表达部分迁入 driver，首轮与后续轮走同一条路。
4. **用户消息为联合类型** `{type: "text", text}` | `{type: "action", name, params}`，形状在阶段 1 设计 Session 消息模型时一并定下。

## 六、记录在案、不在本次范围

- 离线 case 池 `case.input` 目前存的是 REQUEST_SCHEMA 形状（传输层产物）；按三层归属应改存意图 + 原话，请求体运行时由 adapter 推出。另立改动，避免 case 池与在线会话长出两套翻译。
- `MockAgent.build_live_request` step2 LLM 路径暂保留供离线 case 池使用。
- `_preserve_chat_user_query`、`_contains_internal_user_language` 两个补丁在阶段 5 删除。
- `policy_search` 现有的 `next_query` 预写脚本式用户，阶段 3 自然收敛为 `ScriptedDriver`。
