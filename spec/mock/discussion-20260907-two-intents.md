# Mock 协议化：两个意图——driver 真值标签与 judge 推理意图（2026-09-07）

> 状态：讨论记录，已形成决定（见文末），已同步进 `protocol.md`（4.2 / 4.9 / 5.2 / 第 7 节 / 第 8 节 / 第 10 节）。未改任何代码。
> 前序：`discussion-20260907-mock-protocol.md`、`-rollout-pacing.md`、`-adapter-translation.md`、`-seed-levels.md`，以及 `protocol.md` v0.1 初稿。
> 本文按对话顺序原文记录，不做改写。本文**修正**了 `protocol.md` 初稿中把 `declare_intent` 定位为"judge 需要意图所以 driver 要告知"的因果。

---

## 一、起因（助手在 `protocol.md` 初稿说明中的原话）

一个我在写的过程中新增、讨论中没有明说的小决定：`declare_intent` 在第 7 节 Driver 契约里定为"应发、非强制"，因为 `ScriptedDriver` 和 `ReplayDriver` 有时确实没有意图可声明，强制会让它们不得不编一个。你如果觉得 judge 必须有意图，这一条可以改成强制，那样 seed 为 `utterance` / `request` 级时 Driver 就必须做一次向上推断。

---

## 二、追问（用户原话）

这个是啥意思？

---

## 三、解释（助手原话）

意思是：judge 判一条 trace 时需要知道"用户想要什么"，才能判 live 有没有满足用户。这个"用户想要什么"就是 `user_intent`，今天它一定存在——评测进程在多轮循环里要么从 seed 里读，要么调 `infer_user_intent` 推一个出来，然后 `ctx.set_intent` 写进 trace。

协议化之后，评测进程不再算意图，意图由 Driver 通过 `declare_intent` 消息告诉 Session。这就冒出一个问题：**Driver 可以不发**。协议里要不要规定"必须发"？

我在草案里写的是"应发、非强制"，理由是有些 Driver 天然没有意图可说：

- `ReplayDriver` 只是把生产日志里用户说过的话按顺序重放，它并不知道那个用户当时想干什么。要它发 `declare_intent`，它就得先调一次 LLM 从日志里猜一个意图出来。
- `ScriptedDriver` 按预写脚本发话，脚本里可能只有几句台词，没写意图。

如果协议规定必须发，这两种 Driver 就被迫多做一步"从已有的话向上推断意图"（就是第 3 节表里的 `intent_from_transcript`），推出来的意图是猜的，未必准，但 judge 拿到手会当真的用。

如果不强制，这两种 Driver 可以不发，代价是这条 trace 的 `mock_intent` 为空，judge 拿不到用户意图，只能靠 transcript 自己判断，或者判不了。

所以这是一个取舍：**强制** = judge 永远有意图可用，但可能是 Driver 编的；**不强制** = 意图要么是真的要么没有，judge 得能处理"没有"的情况。我选了后者，因为编出来的意图会让 judge 误判而且不留痕迹，而"没有意图"至少是诚实的、judge 可以显式降级处理。但这个选择影响 judge 侧，所以单独标出来让你拍板。

---

## 四、三个问题（用户原话）

1。现在是怎么做的？现在就是推断了intent吧。首先保持一致？
2。推断意图这个事情，既然是从judge侧的推断，所以其实落点不应该再driver即mock侧，而应该就在judge测，举个最简单的例子，我做评估标注，我判断一个东西是不是就是应该先判断下用户的愿意是什么，这不就是推断吗？特别是其实用户的意图本来就很少会直接说出来，更多是直接说一些东西或者做一些东西，用户意图本来就是用户脑子里的话，这其实大概率只能是推断出来吧，而且用户就算说了他所谓的意图可能也不是真的是他全面脑子里想要的意图。你可以从这种角度思考下，检查我们的流程有没有没对上的
3。现在我们其实有要求意图必须是强制正确的吗？其实我不太确定。但是有意图这个事情本身其实是存在的是吗，而且我们目前也是这样实现的？

你先看看。你觉得我说的有道理吗

---

## 五、核对与修正（助手原话）

核对了三处代码，先回答三个问题，再说我觉得流程哪里没对上。

### 1. 现在是怎么做的

**不是总推断，而且推断的目的不是给 judge。**

- 单轮：`_resolve_intent` 的 docstring 写得很明确——"只读取 Case 明确携带的可选 Intent；不从 Request 或 scenario 补造"。case 没带 `user_intent`，trace 里就没有，judge 拿到的 `user_intent` 是 `None`。
- 多轮：`_execute_multi_turn` 第 294 行只在 `intent is None` 时调 `mock.infer_user_intent(initial_request)`，**原因是 mock 自己需要它**——下一行 `decide_next_action(intent, ...)` 和 `build_next_request(intent, ...)` 都要吃这个参数，没有它 mock 走不下去。推完顺手 `ctx.set_intent`，于是它进了 `trace.mock_intent`，又被 pipeline 第 572 行取出来当 `user_intent` 传给 judge。这是**副作用**，不是设计目的。

所以"保持一致"的答案是：一致的做法是**意图可选、有就带上、没有就没有**，这正是单轮现在的行为，多轮的推断只是 mock 自用。

### 2. 推断意图应该落在 judge 侧——你说得对，而且 judge 现在就是这么做的

看 judge 的 system prompt 第 384 行：

```384:385:impl/core/judge.py
        "首要职责：理解用户/下游消费者的真实业务意图 → 派生 business_expectations → "
        "基于完整执行链路（每轮 output、最终 output、交互过程和停止事实）判断 expectations 的 fulfillment。\n\n"
```

judge 的第一步就是自己从 trace 里理解意图。传进去的 `user_intent` 是 `Optional[str]`，在 prompt 里的地位是"理解用户意图（run_trace.input / user_intent / scenario）"三个线索之一，是提示不是依据。这和你说的评估标注的类比完全一致：标注员先看用户说了什么、做了什么，自己推断他想要什么，再判系统做得对不对。

### 3. 有没有要求意图必须正确

**没有。**代码里没有任何地方校验 `user_intent` 的正确性，也没有地方要求它非空。"意图"作为概念存在于三处：case 可以带、mock 生成时会产、judge 会自己推。但它从来不是一个被强制、被验证的东西。

### 流程里没对上的地方

对照下来，我在 `protocol.md` 里犯了一个方向性错误：**我把 `declare_intent` 定义成"driver 把意图告诉 Session，因为 judge 需要它"**。这个因果是反的。judge 不需要 driver 告诉它意图，judge 自己推。多轮里那次推断本来就是 mock 为了自己继续演下去做的，我把一个副作用当成了协议目的，然后才衍生出"强制还是不强制""ReplayDriver 要不要编一个"这些伪问题。

把因果摆正之后，`declare_intent` 的真实含义变成：**driver 如果确实持有一个真实的用户目标（它在扮演的这个人心里想的东西），就把它记进 trace 当标签**。这个标签的性质和今天 `case.user_intent` 一样——是模拟世界里的"真值"，因为 driver 就是那个用户，它当然知道自己想什么。它的用途不是喂 judge 推断，而是两件别的事：

- **校准 judge**：judge 自己推出来的意图和 driver 实际的目标不一致时，能看出是 judge 推错了、还是 driver 表达得太隐晦、还是 live 没做澄清。这是评测系统自检的手段。
- **判结果而非判过程**：真实用户满意不满意看的是他心里那个目标有没有被满足，不是他嘴上说的。有真值标签时 judge 可以多判一层"最终结果是否满足真实目标"。

于是之前那个"强制 vs 非强制"的取舍就消失了：**它是标签，天然可选，driver 有真值就记，没有就不记，绝不为了填空去推断一个**。`ReplayDriver` 没有真值，不记；`ScriptedDriver` 脚本里写了目标就记，没写不记；`PersonaDriver` 自己的画像目标就是真值，记。从 request 级 seed 起手的 driver，为了继续演下去自己推了一个意图并按它行动——从那一刻起这确实成了模拟用户的真实目标，可以记，但标上 `source: adopted_from_inference`，和 `source: seeded` 区分开，让后面看的人知道这个真值是怎么来的。

还有一个顺带的观察，属于 judge 侧、这次不碰但先记下：judge 现在收到 `user_intent` 时不知道它是谁给的、可信度如何，prompt 里直接写"理解用户意图（… / user_intent / …）"，有被锚定的风险。将来这个字段应该带着来源标签进 judge，让 judge 知道"这是模拟用户自报的目标"而不是"这是正确答案"。

### 你说的有道理吗

有，而且比我原来的框架更准。我原来的错误在于潜意识里把"评测进程今天会推一次意图"当成了协议必须保住的功能，你的视角把它还原成了本来的样子：意图是用户脑子里的东西，观测者只能推断，推断是 judge 的活；模拟用户碰巧知道自己脑子里的东西，那就当标签留下来，不多不少。

如果你认可这个修正，`protocol.md` 里要改四处：4.2 的 `declare_intent` 加 `source` 字段并改写说明、4.9 的 `intent_history` 落点说明改成"真值标签"、5.2 的 `DriverReport.final_intent` 同步、第 7 节 Driver 契约那条改成"有真值则记，不得为记而推"。第 10 节 judge 侧的开放问题也要加上"来源标签防锚定"这一条。

---

## 六、追问：要不要把 infer_intent 接进 judge（用户原话）

认可是认可，不过infer_intent这个事情现在其实好像是mock的活，我们是不是这样的话得把它接进judge啊？要改流程？相当于其实现在driver mock端有个真意图在支撑，judge端也有个推理意图来支撑评测看起来？是这样一回事吗

---

## 七、两个意图的归属（助手原话）

是这么一回事，而且判断"要不要改流程"之前有一个事实要先看清：**judge 端的推理意图今天已经存在，它就藏在 `BusinessExpectation.user_intent` 里。**

```10:18:impl/core/schema/judge.py
@dataclass
class BusinessExpectation:
    # Judge 层：从用户意图推导出的业务期望。
    expectation_id: str
    # 是否阻断整体业务目标。该属性属于期望本身，必须在评估 actual 前确定。
    blocking: bool
    downstream_consumer: str = ""
    user_intent: str = ""
```

judge 的 prompt 要求它"理解真实业务意图 → 派生 business_expectations"，每条 expectation 上都带一个 judge 自己理解出来的 `user_intent`。所以 judge 端的推断不是要新加的功能，它一直在做，只是**没有作为一个独立的、结构化的产物被明确标出来**，散在各条 expectation 里，也没有和任何"真值"做过对比。

### 两个意图各自的归属和现状

| | driver 端真意图 | judge 端推理意图 |
|---|---|---|
| 本质 | 模拟用户脑子里的目标，模拟世界的真值 | 观测者从可见行为推出来的，和标注员做的事一样 |
| 今天在哪 | `case.user_intent` / 多轮时 `infer_user_intent` 推出的 `ctx.intent` → `trace.mock_intent` | 散在 `BusinessExpectation[*].user_intent`，隐式 |
| 用途 | driver 自己演下去需要它；顺带作为标签留在 trace | 评判的起点 |
| 是否强制 | 否 | 是（judge 必须先理解意图才能派生期望） |

### `infer_user_intent` 要不要挪进 judge

**不用挪，它留在 driver 里，因为它服务的是 driver 自己的需求。** 从 request 级或 utterance 级 seed 起手时，driver 没有目标就演不下去，得先给自己推一个——这个推断的消费者是 driver，不是 judge。judge 有自己的推断，走自己的 prompt，两者是独立的，不共用代码也不该共用。

所以流程上真正要改的只有一处：**多轮那次推断的结果不再以"真值"的身份流进 `trace.mock_intent`**。今天它是被当成真值传给 judge 的（pipeline 第 572 行），但它其实是评测进程替 mock 推的一个工作假设。协议化后它成了 driver 内部的事，driver 如果按它行动了就 `declare_intent` 并标 `source: adopted_from_inference`，judge 看到来源标签就知道这不是 seed 给的真值。

### judge 端要不要改

**这次不改，但记一笔。**现在够用是因为 judge 已经在推断。将来值得做的是把 judge 的推断从各条 expectation 里提出来，变成 `JudgeResult` 上一个独立的 `inferred_intent` 字段。这样才能做上一轮说的两件事：和 driver 真值对比校准 judge、判"真实目标是否满足"。这是 judge 侧的 schema 变化，属于之前说好另开的那个讨论，不阻塞 mock 协议的五个阶段。

### 概括

你的理解是对的：driver 端有一个真意图支撑用户行为，judge 端有一个推理意图支撑评判，两者本来就该是两个东西。今天的代码里两者都存在，问题只是它们在 `trace.mock_intent` 这个字段上被混在了一起——多轮时 mock 推的假设被当真值传给了 judge，judge 又没把自己的推断单独标出来。协议改造要做的是把 driver 那一边标清来源；judge 那一边显式化留给后面。

---

## 八、本轮形成的决定

1. **意图分两个，不合并**：driver 端真值标签（模拟用户心里的目标）与 judge 端推理意图（观测者从可见行为推断）。
2. **driver 端真值标签可选、带来源、不为填空而推**：`declare_intent` 增加 `source: seeded | adopted_from_inference | drifted`；driver 有真实目标则记，没有则不记；从可见行为推断意图是 judge 的职责。
3. **`MockAgent.infer_user_intent` 留在 driver 侧**，服务 driver 自身行动，不迁入 judge；judge 走自己的推断。
4. **唯一的流程修正**：多轮时 `infer_user_intent` 的结果不再以真值身份直接写入 `trace.mock_intent`；如 driver 据此行动则以 `source: adopted_from_inference` 记为标签。
5. **judge 端本次不改**，`mock_intent` 暂取 `intent_history` 最后一条并携带 `source`，保持现状。

## 九、记录在案、不在本次范围（judge 侧，另开讨论）

- 把 judge 推断显式化为 `JudgeResult.inferred_intent`（今天散在 `BusinessExpectation[*].user_intent`）。
- `inferred_intent` 与 `intent_history` 真值标签对比：校准 judge；有真值时多判一层"真实目标是否满足"。
- `mock_intent` 进 judge prompt 时携带来源标签，防锚定。
- `intent_history` 多条时取哪条 / 是否分段评判。
