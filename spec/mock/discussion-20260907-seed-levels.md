# Mock 协议化：seed 层级、三层双向映射与扩展点收敛（2026-09-07）

> 状态：讨论记录，已形成决定（见文末），未改任何代码。
> 前序：`discussion-20260907-mock-protocol.md`、`discussion-20260907-rollout-pacing.md`、`discussion-20260907-adapter-translation.md`。
> 本文按对话顺序原文记录，不做改写。本文**修正**了前序 `adapter-translation.md` 第六节关于 case 池存法的记录。

---

## 一、为什么 request 形状必须是一等入口（用户原话）

我说一个最直观的例子说明为什么request_shape，比如我们有现成的api生产数据（首轮或者跑到一半），可以直接使用，这个时候其实就应该直接放这个数据，然后意图这个东西如果需要的话（比如缺少后面多轮的数据又想再此基础上继续mock），我们应该先推断用户意图，再基于用户意图继续接下来的mock输入，所以live 远request_shape我觉得是有必要存在的，只是针对到交互协议这层，让agent提供可能确实给一些更接近原来的东西的话比较好一点，但是提供api、提供用户表述、提供用户意图这种，不同场景可能有不同的需求，你也可以根据这一点，再思考下我们的协议

---

## 二、按层级入口重新整理的协议（助手原话）

这个例子很有说服力，而且它纠正了我上一轮的一个判断。我之前说"case 池应该改存意图加原话"，这是错的——生产数据天然就是 request 形状，它是最真实的输入，协议必须把它当一等公民接进来，而不是要求先翻译成"用户原话"。你说的"不同场景需要在不同层进入"才是对的抽象。下面是我按这一点重新整理的协议。

### 核心变化：三层都是合法入口，协议定义的是层间的双向映射

之前我把三层画成一条单向的生成链（意图 → 原话 → 请求）。现在应该是三层各自可以作为起点，协议要同时定义"向下生成"和"向上推断"：

| 方向 | 意图 ↔ 原话 | 原话 ↔ 请求 |
|---|---|---|
| 向下（生成） | driver 做，允许 LLM：`utterance_from_intent` | adapter 做，确定性：`request_from_user_message` |
| 向上（推断/提取） | driver 做，允许 LLM：`intent_from_transcript` | adapter 做，确定性：`user_message_from_request` |

右边一列其实现在就存在：`build_next_request` 的槽位填充是向下，`extract_mock_message` 是向上，三个项目都有，而且都是纯 Python。左边一列也存在：`build_user_intent` / `next_turn` 是向下，`infer_user_intent` 是向上，只是它们跑在评测进程里而不是 driver 里。所以这张表不是新发明，是把已有的四个函数按归属归位。

这样一来 adapter 的契约就是**一对互逆的确定性函数**，driver 的契约是**一对允许用模型的函数**。上一轮说的三道约束（往返不变式、禁 LLM、确定性）正好就是对 adapter 那一对函数的约束，不需要改。

### 你举的例子在这个协议里怎么走

**有完整首轮生产 request，想从这里往下 mock 多轮。** driver 拿到 seed 是 request 层。它先让 Session 以 `request` 级消息原样发出去（adapter 不翻译，只调 `user_message_from_request` 提取用户原话进 transcript，供 judge 用）。拿到 live 响应后，driver 调自己的 `intent_from_transcript`（就是今天的 `infer_user_intent`，只是挪进 driver）推出意图，向 Session 声明，然后从第二轮开始用 `text` 级消息继续。同一个会话里前后两轮用不同层级的消息，协议允许。

**有跑到一半的生产会话（多轮 request，可能带响应），想接着 mock。** seed 是 transcript 层。这里有一个必须区分的选择，我叫它 `seed.mode`：

- `replay`：Session 把前缀里的每个 request 重新打到 live 上，拿到的是**当前** live 的新响应。这是在评测当前系统，前缀的历史响应只给 driver 做参考（比如检测 live 行为是否和生产时分叉了）。代价是前缀每一轮都要真实调一次 live。
- `context`：前缀不执行，由 adapter 把它转成 live 能接受的历史形式直接注入下一轮请求。这需要 live 支持带历史进来——`policy_search` 的 `contexts`、`marketting-planning` 的 `history` 字段可以，`deerflow` 靠服务端 `thread_id` 持有状态就不行，只能 `replay`。所以 `context` 模式是否可用是 adapter 声明的能力，不是协议默认。

两种模式下 driver 都先从前缀推意图再继续，和上一个例子一样。

**只有意图，没有任何数据。** 就是今天的常规路径：seed 是 intent 层，driver 一路向下生成。

**只有一句用户原话。** seed 是 utterance 层，driver 需要意图的话自己向上推一次，然后继续。

### 协议 A（会话）需要相应调整的地方

用户侧发给 Session 的消息从上一轮的两种变成三种：`request {payload}`（原样透传，adapter 只提取不翻译）、`text {text}`、`action {name, params}`（后两种走 adapter 确定性翻译）。另外加一条控制消息 `declare_intent {user_intent, user_context}`，driver 随时可发、可多次发——这一条同时解决了"从数据推出的意图要告诉评测系统"（judge 现在就吃 `user_intent`）和上一轮提的"意图中途漂移"两个问题，Session 只记录不计算，相当于今天 `ctx.set_intent` 的对外版本。

Session 打开时接受 seed 的 transcript 前缀和 mode，`context` 模式下 Session 调 adapter 的 `history_from_transcript`，adapter 不支持就拒绝开会话并给出明确错误，不要静默降级成 `replay`（成本差很多，应该由调用方知情选择）。

### 协议 B（驱动任务）的 seed 定义

任务里的 seed 变成一个带层级标签的结构：`level: intent | utterance | request | transcript`，加对应的 payload，transcript 时多一个 `mode: replay | context`。budget 不变。driver 的产出 `DriverReport` 里加一项：它最终声明的意图（可能是推断出来的，也可能是漂移后的），方便离线核对。

### 对 case 池的修正

推翻上一轮"case 池应改存意图加原话"的记录。正确的说法是：case 池存的是**带层级标签的 seed**，`case.input` 现在的 REQUEST_SCHEMA 形状就是 `level: request` 的 seed，完全合法，而且是生产数据进来的自然形态。需要补的只是层级标签（现有 case 缺省视为 `request`），以及允许 intent / utterance / transcript 三种新的 seed 形态。这比改存法小得多，也不会打断现有 case 池。

### 一个顺带的对称性，先记着不展开

request 可以从数据来而不由 driver 生成，同理 live 的响应也可以从数据来而不真实执行——单轮路径今天就有 `ProvidedOutputLive` / `deliver_provided` 干这件事。把它推到多轮，Session 就变成一个两侧都可以"提供或执行"的记录器：用户侧提供或生成，live 侧提供或执行。全提供就是纯导入生产 trace 去 judge，全执行就是常规 mock 评测，一侧提供一侧执行就是回放。这个对称性说明 Session 的抽象是对的，但多轮 provided 不在前五个阶段范围里，只在 spec 里留一句。

### 需要你确认的两点

一是 `seed.mode` 的 `context` 模式要求 adapter 多实现一个 `history_from_transcript`，这是给三个多轮项目的第二个新扩展点（第一个是 `request_from_user_message`），不过它是可选能力，不实现就只能 `replay`。二是 `declare_intent` 允许多次声明意味着 judge 拿到的 `user_intent` 可能不是首轮那个而是最终那个，或者一个带时间戳的列表——judge 侧怎么消费漂移后的意图，需要另开一个讨论，这次先不碰。

---

## 三、追问（用户原话）

一是 seed.mode 的 context 模式要求 adapter 多实现一个 history_from_transcript，这是给三个多轮项目的第二个新扩展点（第一个是 request_from_user_message），不过它是可选能力，不实现就只能 replay。二是 declare_intent 允许多次声明意味着 judge 拿到的 user_intent 可能不是首轮那个而是最终那个，或者一个带时间戳的列表——judge 侧怎么消费漂移后的意图，需要另开一个讨论，这次先不碰。

这个是啥意思？driver做的还是adapter做的？没看懂这个是想干嘛。输入哪来的，输出给谁用呢

---

## 四、两点的数据流解释（助手原话）

这两点我说得太压缩了，用具体数据流重新讲一遍。

### 第一点：`history_from_transcript` 是 adapter 做的

**它解决的问题。** 你手里有一段跑到一半的生产会话，比如 `policy_search` 的两轮：用户说"查上个月的保单"，系统回"请补充险种"，用户说"寿险"，系统回了个语法树。现在你想从第三轮开始让 driver 接着 mock。第三轮的请求打到 live 上时，live 得知道前两轮说了什么，否则它是在一个空白会话里理解"寿险"这句话。

前两轮的历史有两种办法喂给 live：

- **replay**：Session 把前两轮的 request 原样重新打到 live 上，live 自己形成会话状态，然后第三轮再打。代价是两次真实 live 调用，而且 live 现在的回答可能和生产时不一样了。
- **context**：不打前两轮，直接在第三轮请求体里把前两轮历史塞进去。`policy_search` 的请求体里本来就有这个位置——看它现在的 `build_next_request`：

```221:226:impl/projects/policy_search/mock.py
        extra["args"] = {
            "contexts": [
                {"role": "user", "content": previous_query, "sub_agent": ""},
                {"role": "assistant", "content": assistant, "sub_agent": "POLICY_SEARCH"},
            ]
        }
```

这段代码就是在把上一轮的问答拼成 live 要求的 `contexts` 格式。`history_from_transcript` 就是把这段逻辑抽出来命名：**输入**是 Session 持有的 transcript（一串 `{用户说了什么, 系统回了什么}`，来自生产数据前缀），**输出**是这个项目 live API 能接受的历史字段格式（`policy_search` 是 `contexts` 数组，`marketting-planning` 是 `history` 字段），**给谁用**：给同一个 adapter 的 `request_from_user_message` 用，它在拼第三轮请求体时把这个历史塞进去。

它是 adapter 的活，因为"live 的历史字段长什么样"是这个项目 API 的知识，和用户怎么想没关系。它是确定性的，不涉及 LLM，只是格式转换。

**为什么可选。** `deerflow` 的请求体里没有历史字段，历史靠服务端按 `thread_id` 存着（看它的 `build_next_request` 只传 `thread_id` 和最新一条 message）。这种 live 没法从请求体注入历史，只能 replay。所以 adapter 要声明"我支持不支持 context 模式"，不支持时 Session 收到 `mode: context` 的开会话请求就直接报错。

### 第二点：`declare_intent` 是 driver 发出、Session 记录、judge 消费

**它解决的问题。** 现在 judge 吃一个 `user_intent` 字符串来判断 live 有没有满足用户：

```70:70:impl/core/judge_protocol.py
    def judge_trace(self, trace: RunTrace, user_intent: Optional[str] = None) -> JudgeResult:
```

这个 `user_intent` 今天是评测进程在多轮循环里算出来、通过 `ctx.set_intent(intent)` 写进 trace 的。协议化之后，算意图的活挪进了 driver（不管是从 seed 里读的、从生产数据推的、还是自己生成的），评测进程不再知道意图是什么。但 judge 还是需要它。所以 driver 得有一条通道把意图告诉 Session。

`declare_intent` 就是这条通道。**输入**：driver 内部的用户模型（`user_intent` 一句话 + `user_context` 画像）。**动作**：driver 通过协议 A 发给 Session。**Session 做的事**：原样记进 trace，就是今天 `ctx.set_intent` 干的事，不加工。**输出给谁**：judge，和今天一样。

**为什么允许发多次。** 因为 driver 是在会话进行中才知道意图的，而且意图会变。以第一点的例子说：driver 拿到生产前缀，先发第三轮请求前从前缀推出"用户想筛上个月的寿险保单"，声明一次；跑到第五轮 driver 决定让用户改主意"算了，看所有险种的"，再声明一次。如果只允许发一次，要么 driver 必须在开会话前就想好全部意图（那就回到了今天"intent 固定在首轮"的问题），要么漂移后的意图 judge 看不到。

**我说"另开讨论"的原因。** 允许多次声明后，trace 里的意图从一个字符串变成了一个带轮次的列表。judge 现在的接口只收一个字符串，那它该拿哪个？拿最终的，会误判前几轮；拿首轮的，会误判后几轮；按轮次分段判，judge 得改接口。这是 judge 侧的设计问题，和 mock 协议本身无关，所以我建议这次不碰，先把"Session 记录一个带轮次的意图列表"定下来，judge 暂时取最后一条保持现状。

### 一句话概括归属

| 东西 | 谁做 | 输入从哪来 | 输出给谁 |
|---|---|---|---|
| `history_from_transcript` | adapter | Session 持有的生产前缀 transcript | 同一 adapter 拼请求体时用 |
| `declare_intent` | driver 发，Session 记 | driver 自己的用户模型 | trace，最终给 judge |

两者其实分别对应今天已有的代码：前者是 `policy_search.build_next_request` 里拼 `contexts` 那几行，后者是 `_execute_multi_turn` 里 `ctx.set_intent(intent)` 那一行。都不是新概念，只是把它们从"评测进程里的内部步骤"变成"协议里有名字的消息"。

---

## 五、收敛（用户原话）

1. history_from_transcript。这个是不是应该包在我们之前说的adapter里面啊？里面的一个功能函数？不然不是很奇怪吗。->live的东西到底是原来那个还是history_from_transcript？如果你说这个只是原来那个可能会使用的一个adapter性质的功能函数哪我倒是能理解的
2. 第二个点的话我同意

---

## 六、修正（助手原话）

对，就是你理解的那样，而且你这么一问我发现上一轮把它抬得太高了。

发给 live 的东西**只有一个**：`request_from_user_message` 产出的那个请求体。`history_from_transcript` 不是另一条通往 live 的路，它只是 adapter 内部拼请求体时可能调用的一个功能函数——`request_from_user_message` 拿到 Session 传进来的 `session_state`（里面包含 transcript 前缀），如果这个项目的 API 有历史字段，就调一下这个函数把 transcript 转成那个字段的格式塞进请求体；没有历史字段就不调。它是不是单独一个方法、叫什么名字，都是 adapter 内部的事，协议不关心。

所以修正一下上一轮的说法：**给三个多轮项目的新扩展点只有一个**，就是 `request_from_user_message`。协议层对外可见的只多一个布尔能力声明，比如 `supports_history_injection`，Session 收到 `mode: context` 的开会话请求时看这个标志决定接受还是拒绝。`deerflow` 声明 `False`，`policy_search` 和 `marketting-planning` 声明 `True`，各自在 `request_from_user_message` 内部怎么拼历史是自己的实现细节。

第二点你同意，那就按"Session 记带轮次的意图列表、judge 暂取最后一条"定下来。

---

## 七、本轮形成的决定

1. **三层皆为合法入口**，协议定义层间双向映射：
   - 意图 ↔ 原话：driver 负责，允许 LLM（向下 `utterance_from_intent`，向上 `intent_from_transcript`）
   - 原话 ↔ 请求：adapter 负责，确定性（向下 `request_from_user_message`，向上 `user_message_from_request`）
2. **协议 A 用户侧消息三种**：`request {payload}`（透传，adapter 仅提取）、`text {text}`、`action {name, params}`（adapter 确定性翻译）；同一会话内可混用层级。
3. **协议 A 新增控制消息 `declare_intent {user_intent, user_context}`**：driver 发、可多次；Session 记为带轮次的意图列表，不加工；judge 暂取最后一条，漂移意图的 judge 侧消费另开讨论。
4. **协议 B 的 seed 带层级标签** `level: intent | utterance | request | transcript`；transcript 时附 `mode: replay | context`。`DriverReport` 增加最终声明的意图。
5. **`context` 模式**：Session 不执行前缀，由 adapter 在 `request_from_user_message` 内部把 transcript 前缀转成 live 历史字段注入。adapter 不支持时 Session 拒绝开会话并明确报错，**不静默降级为 replay**。
6. **多轮项目新扩展点只有一个：`request_from_user_message`**（含配对的 `user_message_from_request`，即现有 `extract_mock_message`）。`history_from_transcript` 仅为 adapter 内部功能函数，不是协议扩展点。协议层对外只多一个布尔能力声明 `supports_history_injection`（`policy_search`、`marketting-planning` 为 True，`deerflow` 为 False）。
7. **case 池修正**（推翻 `adapter-translation.md` 第六节第一条）：case 池存带层级标签的 seed；现有 `case.input` 的 REQUEST_SCHEMA 形状即 `level: request`，缺省视为此级，合法保留。只需补层级标签并允许其余三种 seed 形态。

## 八、记录在案、不在本次范围

- 多轮 provided（live 侧响应由数据提供而非执行）：Session 两侧均可"提供或执行"的对称性成立，但不在前五阶段范围。
- judge 如何消费带轮次的意图列表（漂移意图）：另开讨论。
