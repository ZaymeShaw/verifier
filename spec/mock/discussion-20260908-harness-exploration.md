# Mock 协议化：harness 自由探索模式（2026-09-08）

> 状态：讨论记录，已形成决定（见文末），已同步进 `protocol.md`（v0.2）。改动前的 v0.1 备份为 `protocol-v0.1-backup.md`。
> 前序：本目录全部 `discussion-20260907-*.md`、`protocol.md` v0.1、`stage0-task.md`（阶段 0 已完成）。
> 本文按对话顺序原文记录，不做改写。本文**改写**了协议 B 的方向（由"评测系统下发任务"改为"harness 主动拉取；回归侧评测系统推"），并调整了阶段 3/4 的内容。

---

## 一、新想法（用户原话）

我有一个新的想法，我觉得mock也许可以是一个单独的模块，而不是跟评测系统一起，可以使用评测系统搭建的live系统，然后批量构建出mock case，结尾可能有选择性的能直接基于这些case直接再串起一次评测系统批量调用（也可以不掉，只是有这个数据集）

目标：尽可能找更多not fulfilled（或者换句话说的话，是找更多业务系统当前做不好的场景）当然这个只是默认的目标，也可以根据任务的性质找不同的测试方案。harness ai在这个过程中有最高的自由度可以做各种类型的探索

模拟环境应该使用评测系统中标准的live工具，并且搭建一套能够自动记录trace的方案，使得模型每次模拟一轮case交互后，系统可以自动通过某种提取日志/数据之类的方式获得对应case的trace的mock数据集（和mock数据集格式一致）（可以用于verifier复现和进一步观察）当然这个事情是自然的而不是强迫模型完成的。是通过让模型通过标准化方式使用live工具后自动产生的数据

case与case之间应该有分割的方法，比方通过trace id、session id、request id之类。模型调用的时候对于新case应该有意识的使用不同的case进行调用

可以不再以评测系统发起操作来主导，而是可以harness ai直接自由探索，不需要一定靠消费这层来转接，不需要绝对依赖评测系统的各种judge之类的东西，只需要使用对应的live系统即可

简单来说，就是发起某个东西后，harness ai开始进行各种类型的对抗性mock，这里的对抗指的是对抗业务系统我理解，对抗的方式花样的去使用live系统，看看什么样的使用会让这个live系统效果/效率或者各方面不如预期（简单来说就是judge not fulfilled；因此harness ai也可以选择通过调用verifier的judge agent之类来实施对抗的验证），然后需要使用标准化的live使用方式来使用，这个过程需要有trace记录工具记下来这些东西（使得后续这些东西会自然的化作可复现的mock数据集），通过这个方式来发现业务系统的一些问题，无法处理好的case之类。

---

## 二、与现有协议的关系、新增物、担忧（助手原话）

这个想法我觉得是对的，而且它和我们已经定下的协议不冲突——它是把协议 B 的方向反过来了，同时让阶段 0 建的东西直接派上用场。下面按"和现有设计的关系、需要新增什么、我担心的点"三块说。

### 一、和现有协议的关系：协议 B 从"推"变成"拉"

我们之前定的是：评测系统主动发任务给 Driver（协议 B），Driver 通过 Session 使用 live（协议 A）。你现在说的是：**没有人给 Driver 发任务，harness AI 自己决定探索什么**，评测系统退化成一个工具库——提供标准化的 live 使用方式、自动记 trace、可选的 judge。

这其实是你最初那句"评测系统不该做 mock"走到底的样子。协议 A 一个字不用改：Session 本来就是被动的"开会话、转消息、推事件、记 trace、关会话"。变的是协议 B：从"评测系统 → Driver：这是你的任务"变成"Driver → 评测系统：给我开一个会话"。原来的 DriverTask（seed、persona、budget）不再由评测系统下发，而是 harness 自己心里有数；评测系统只在会话层面强制预算。

阶段 1 要做的"抽 Session"仍然是正确的下一步，而且更重要了——它就是 harness 要用的那个"标准 live 工具"。阶段 3 的 `PersonaDriver` 则不再是评测系统内部的一个类，而是 harness 的一种玩法。

### 二、需要新增的东西

**1. Session 以工具形态暴露，而不是 Python 类。** harness AI 是一个独立进程（Claude Code、codex、任何 agent），所以 Session 要以它能调的形式存在：一组 CLI 或 MCP 工具，大概是 `session open <project>` → 返回 `session_id`；`session send <session_id> --text "..."`（或 `--action` / `--request`）→ 返回 live 的可见输出；`session close <session_id> --reason ...`；`session export <session_id>` → 落成 case + trace。这基本就是阶段 4 的"对外暴露"提前到阶段 1 之后做，而且不需要 HTTP+SSE，CLI 够用。

**2. case 之间的分割靠工具结构保证，不靠模型自觉。** 你说"模型对新 case 应该有意识地用不同 id"——我建议反过来：模型根本拿不到 id 的生成权。`open` 才产生 `session_id`，所有消息都必须带 `session_id`，没 `open` 就 `send` 直接报错。这样"忘了开新会话"在结构上不可能发生，模型只需要决定"这是不是一个新 case"。

**3. 自动导出成 mock 数据集。** 这一步阶段 0 已经解决了大半：`TraceContext` 记的就是 `RunTrace`，`record_golden.py` 已经会把一次执行落成 `case.json + trace.*.json`。要补的是导出格式对齐 case pool——按我们定的 seed 层级，一条 harness 会话天然导出为 `level: transcript` 的 seed（完整用户轮次 + live 响应），单轮的就是 `level: request`。这样导出的 case 直接能进 case pool，再被 verifier 批量重跑，就是你说的"结尾可选地串一次评测"。

**4. judge 作为工具而非流程。** `judge <trace>` 暴露成一个可选调用，harness 想验证"这条是不是真的 not_fulfilled"就调，不想调就只留 trace。judge 的产出不阻断 harness。

**5. 发现台账（findings ledger）。** 对抗式探索最容易犯的毛病是找到一个坑之后反复往里跳，产出 50 条本质相同的 not_fulfilled。需要一个 harness 可读写的台账：每条发现记 `失败签名`（judge 的 blocking expectation + 失败维度）、`触发方式摘要`、`真实性标签`（下面说）、`session_id`。harness 每次 judge 完先查台账，同签名的不再算新发现，逼它换方向。这个台账是 harness 探索的"记忆"，也是最终交付物。

### 三、我担心的三个点

**1. 对抗的对象要说清楚，否则 harness 会去打 judge 而不是打 live。** 目标是"judge 判 not_fulfilled"的话，最便宜的路径是找 judge 的误判，而不是找 live 的缺陷——judge 也是 LLM，也有洞。这正好接上我们前面"两个意图"的讨论：harness 作为模拟用户**知道自己的真实意图**，judge 只能推断。所以 harness 每条发现应该带自己的真值判断"live 到底有没有满足我"，和 judge 的结论并列；两者一致的才算"live 的问题"，不一致的单独归一类"judge 校准样本"。这样 harness 打 judge 的产出也没浪费，但不会被当成 live 的缺陷。

**2. 对抗不等于不真实。** 用乱码、超长输入、协议畸形请求当然能让 live 翻车，但那是 fuzz，不是"业务系统做不好的场景"。我建议默认 harness 只能用 `text` / `action` 级消息（走 adapter 的确定性翻译，保证请求体合法），`request` 级透传要显式开一个 `--mode protocol-fuzz` 并打标签。同时每条发现自评一个"真实用户会这么干吗"的等级，人工抽检时优先看高真实性的。

**3. 预算和收敛。** harness 自由度最高，也就最容易跑飞。会话层预算（阶段 2 那套：每轮超时、会话超时、最大轮数）照样强制；探索层再加一个总预算（会话数、token、墙钟），到了就停并交台账。"什么时候算探索完"没有自然终点，只能靠预算加"连续 N 个会话没有新签名"这种收敛判据。

### 四、对阶段计划的影响

阶段 1（抽 Session、`LegacyMixinDriver`、开关、六条 golden 不变）**不变**，它是一切的地基。阶段 2（预算、归责）**不变**。原阶段 3/4 改成：**3 = Session 的 CLI/工具化 + 导出到 case pool + judge 工具化 + 台账**；**4 = 写一个 harness skill（给 Claude Code / codex 用的探索指令与工作流），跑第一轮对抗探索，产出台账和一批可重跑的 case**。原来的 `PersonaDriver`、`ReplayDriver` 变成 harness 的两种探索策略，不再是评测系统的代码。阶段 5 清理不变。

有一个地方要重新想：`protocol.md` 里协议 B 的 `DriverTask` / `DriverReport` 需要改写成"拉"模型——harness 不接任务，但探索结束后仍然应该交一份报告，形状大概就是台账加统计。

这些我先没写进 spec。如果你觉得方向对，我按之前的格式把这轮记成讨论文件，并把 `protocol.md` 的协议 B 和第 9 节阶段计划改成"拉"模型的版本。

---

## 三、三个追问（用户原话）

1. 原来是消费的逻辑，现在变成主推探索的逻辑，你觉得原来那种消费的逻辑还有借鉴性吗？还是其实比较冗余
2. 如果这套逻辑，那我觉得我原来设计的那套多轮的逻辑其实会多少有点冗余，因为这样的话其实不用模型手动在评测系统的工作流里面做多轮，而是在mock的探索流程中做多轮并自然生成多轮数据就完事了。这样的话你怎么评价呢。是好了还是会丢一些东西？原来那套东西到底是否有本质上仍然值得借鉴的东西？
3. 如果真的要搞成这样，其实还有想下我们前端里面当前那套多轮逻辑以及其对应的展示，如果单看展示的话我觉得其实至少trace那部分还是看的过去的。特别是多轮数据如果当成单次数据打过来的话其实观察的观感可能不会特别好，我感觉至少多轮trace的这块是否应该想办法留住展示这块的一些东西，不然我担心多轮的数据完全看不清楚发生了什么

---

## 四、三个回答（助手原话）

看完了，前端多轮展示读的是 `RunTrace` 上的 `turn_records` / `conversation_transcript` / `conversation_summary` / `stop_reason` 这几个字段（`live.html` 170 到 185 行，`summary.html` 172 起）。这决定了第三个问题的答案。下面按三个问题说。

### 一、"消费"逻辑还有借鉴性吗

**"消费"没有变冗余，变冗余的是"评测系统下发任务"。**这两件事之前被我们绑在一起叫协议 B，现在要拆开看：

- **消费的机制**（协议 A：开会话、发消息、收 live 事件、关会话、自动记 trace）就是 harness 要用的那个"标准 live 工具"。harness 探索的每一步都是在消费这个协议，只是发起方从评测系统换成了 harness 自己。这部分不但不冗余，而且是整个新方案的地基。
- **评测系统下发任务**（DriverTask：seed、persona、budget 推给 Driver）在探索阶段确实没用了，harness 自己决定探索什么。

但"推"模式还剩一个必要的场景：**回归**。harness 发现了一批失败 case 进了 case pool，下次 live 改版后要批量重跑这些 case 看有没有修好、有没有新坏——这时候是评测系统拿着 case 去驱动 live，没有 harness 参与，是纯粹的推。所以最终格局是：**探索用拉（harness 驱动），回归用推（评测系统驱动），两者共用协议 A**。推侧的 Driver 只剩一个确定性的 `ReplayDriver`，评测系统里不再有任何 LLM 扮演用户的代码。

### 二、原来那套多轮逻辑：冗余了什么，留下了什么

原来 `_execute_multi_turn` 加 `MultiTurnInteractiveMock` 那套东西其实混着两件事，要分开评价。

**变冗余的：多轮用户行为的生成。**`infer_user_intent` / `decide_next_action` / `build_next_request` 四回调、`MockAgent.next_turn` 的 LLM 调用、`_has_visible_goal_evidence` 那个评测层替用户改主意的补丁——这些全是"评测进程里扮演用户"，harness 模式下整体不需要了。这是好事，我们前面列的七条缺陷里有五条就出在这一坨上。

**本质上仍然值得留的：多轮的执行与记录模型。**具体是四样东西：

1. **Session 循环本身**——"发一轮请求、`deliver_turn`、`record_turn`、判断是否继续"。回归回放要用它，harness 的每一步 `send` 底下也是它。这就是阶段 1 要抽出来的 Session。
2. **`TraceContext` / `RunTrace` 的多轮结构**——`turns[]`、`transcript`、`stop_reason`、`completion_status`、`turn_count`。harness 的会话最终要落成的就是这个东西，一个字段不用改。
3. **`stop_reason` 的归责分组**——用户决定 / 预算 / Driver 故障 / adapter 故障 / live 故障。harness 会话结束的原因和原来一模一样，统计口径照用。
4. **`MultiTurnTurnExpectation` 那个"逐轮期望"的概念**——harness 在第 3 轮发现失败，导出的回归 case 应该记下"第 3 轮期望 X 实际 Y"，这样回归重跑时 judge 能对着看。schema 里已经有这个 dataclass，虽然现在用得少。

**会丢的东西，以及要不要在意。**

- **无人值守的多轮批量生成**：今天在前端点一下就能让评测系统自己造多轮 case 并跑完，不需要外部 agent。harness 模式下必须有一个外部 agent 进程在跑。这是真实的损失，但可以缓解：评测系统提供一个"启动探索"的入口，底下 spawn 一个带 skill 的 codex / Claude Code 进程，对使用者来说还是点一下。只是这个集成要做。
- **可控的场景分布**：原来 `scenarios()` 列表保证每个场景至少测到，harness 自由探索可能扎堆。缓解是给 harness 一份"覆盖目标"当参考（不是任务），台账里记覆盖情况，让它自己看到哪块没碰。
- **回放分叉问题**：这是一个原来没有、现在会新出现的问题。harness 录的 transcript 拿去回归重跑，live 改版后第 2 轮回的话可能变了，那 harness 原来第 3 轮说的话就可能对不上语境。两种处理：逐字重放并在 trace 上标 `diverged_at_turn`，judge 看到标记后只判分叉前的轮次；或者回放时接一个 LLM 做少量适配。我倾向前者作为评测系统的默认（确定性、便宜），后者作为 harness 的一种探索策略而不是评测系统的功能。

**总评**：是变好了。原来那套里真正有价值的是"记录模型"和"执行骨架"，这两样一样不丢；丢掉的是"评测进程扮演用户"这个本来就做不好的部分。

### 三、前端多轮展示怎么保住

**关键判断：只要 harness 导出的是 `RunTrace`，现有的多轮展示一行不用改。**前端读的就是 `turn_records` / `conversation_transcript` / `conversation_summary` / `stop_reason`，harness 会话经 Session 记出来的 trace 天然带这些字段，`execution_mode` 仍是 `interactive_intent`。你担心的"多轮数据被当成单次数据打过来"只会在一种情况下发生：导出时把会话扁平化成一个单轮 case。所以这条要写成硬约束——**harness 会话导出必须产出两样东西**：一份完整的多轮 `RunTrace`（给 trace 视图和 judge 用），一份 `level: transcript` 的 seed case（给回归回放用）。不允许只导单轮。

在这个基础上，展示侧真正需要**新增**的是三样，都是加法：

1. **harness 的旁注**：每轮的 `declare_intent`（含 `source` 标签）、这条会话的发现签名、真实性等级、harness 自己的"我认为 live 满足了没有"。这些是原来的 trace 没有的字段，在轮次视图旁边加一个面板就行。
2. **judge 结论对齐到轮**：现在 judge 是整条 trace 一个结论，多轮 case 里"第几轮开始不对"看不出来。这个其实是我们留到 judge 侧的那个开放问题（意图列表、分段评判）的展示面，可以先只显示 `diverged_at_turn` 和 harness 标的失败轮次，judge 分段等后面再说。
3. **探索批次视图**：一次 harness 探索会产出几十个会话，需要一个按探索批次分组的列表，能看到台账（多少个不同的失败签名、各签名下几条会话、真实性分布）。这是新页面，但逻辑简单，本质上是 case pool 列表加一层分组和几个统计。

`live.html` 里那个"状态机执行"折叠块（166 行）和 `turn_records` 逐轮展开是可以直接复用的，不用担心。

### 顺带的一个结论

这三个问题问下来，我觉得对协议文档的影响可以收成一句话：**协议 A 不动；协议 B 从"评测系统下发任务"改成两条——探索侧是 harness 主动拉、评测系统只提供工具和预算，回归侧是评测系统用 `ReplayDriver` 推；trace 模型不动；阶段 1、2 不动，阶段 3、4 改成工具化和 harness skill。**要不要我按这个把这轮讨论记成文件，并同步改 `protocol.md` 的协议 B、第 9 节，以及在第 4.9 节加上"导出必须是多轮 RunTrace + transcript seed"这条硬约束？

---

## 五、拍板与追问（用户原话）

把这轮讨论记成文件。原来的那套方案可以改不过你先备份一下先吧还是
下发任务这个我理解后续确实就不是评测系统做，不过我理解你说的那个探索页里面可以加这个功能，让用户可以决定一下mock探索的方向之类的这种
回放分叉问题这个我没看懂你是啥意思
其他的暂时没什么意见

---

## 六、回放分叉的解释（助手原话）

harness 探索时录下的多轮对话，每一轮用户说的话都是**针对当时 live 的回答**说的。举个例子，harness 对着 live 的旧版本录了这条：

- 第 1 轮，用户："查上个月的保单" → live 回："请补充险种"
- 第 2 轮，用户："寿险" → live 回了个错误的语法树 → 判 not_fulfilled

这条被导出成回归 case。后来 live 修了一版，评测系统拿这条 case 去重跑：第 1 轮用户还是说"查上个月的保单"，但新版 live 这次回的是"请问您的工号是多少"。这时 case 里写好的第 2 轮台词"寿险"就对不上语境了——它是回答"补充险种"的，不是回答"工号"的。live 的回答一变，后面录好的用户台词就可能全部失效，这就是"分叉"。

单轮 case 不存在这个问题，因为没有"后面的轮次"。原来评测系统内部生成多轮时也不存在，因为每一轮都是现场生成的。它是"录好的多轮脚本拿去重放"这个新做法特有的。

两种处理办法：一是**逐字重放、标出分叉点**——重跑时把新 live 的每轮回答和录制时的回答比一下，第一处明显不同的轮次标成 `diverged_at_turn`，judge 只对分叉前的轮次下结论，分叉后的轮次只作参考。二是**回放时接一个 LLM 现场适配**，看到 live 回答变了就重新生成后续台词。我建议评测系统默认用第一种（确定性、便宜、行为可复现），第二种归 harness 的探索策略，因为一旦让 LLM 现场改台词，那就已经不是"回归"而是"再探索一次"了。

---

## 七、本轮形成的决定

1. **mock 探索独立为 harness 模块**，与评测系统解耦：harness 是独立 agent 进程，通过评测系统提供的标准 live 工具（即 Session）自由探索；评测系统提供工具、预算、trace 记录、可选 judge，不再扮演用户、不再下发任务。
2. **协议 A 不变**。**协议 B 拆为两条**：探索侧 harness 主动拉（`open / send / close / export`）；回归侧评测系统用确定性 `ReplayDriver` 推。评测系统内不再保留任何 LLM 扮演用户的代码。
3. **"探索方向"由用户在探索页给出**，作为 harness 的参考输入（覆盖目标、关注场景、对抗策略偏好等），不是任务下发；harness 保留最高自由度。
4. **case 分割靠工具结构**：`session_id` 只由 `open` 产生，所有消息必带 `session_id`。
5. **导出硬约束**：每条 harness 会话必须同时导出完整多轮 `RunTrace`（供 trace 视图与 judge）和 `level: transcript` 的 seed case（供回归回放）；不允许扁平化为单轮。前端现有多轮展示因此无需改动。
6. **发现台账（findings ledger）**：记录失败签名、触发摘要、真实性等级、harness 自评是否满足、judge 结论、`session_id`；同签名去重；harness 自评与 judge 不一致的归为"judge 校准样本"而非 live 缺陷。
7. **默认只允许 `text` / `action` 级消息**；`request` 级透传须显式 `--mode protocol-fuzz` 并打标签。
8. **回放分叉**：评测系统回归默认逐字重放并标 `diverged_at_turn`，judge 只对分叉前轮次下结论；LLM 适配式回放归 harness 探索策略。
9. **阶段计划**：阶段 1、2、5 不变；阶段 3 改为 Session 工具化（CLI/MCP）+ 导出到 case pool + judge 工具化 + 台账；阶段 4 改为 harness skill + 首轮对抗探索 + 探索页（含方向输入与批次视图）。
10. **原方案保留备份**：`protocol-v0.1-backup.md`。

## 八、记录在案、不在本次范围

- 从评测系统 UI 一键 spawn harness 进程（无人值守探索）的集成方式。
- judge 结论对齐到轮（分段评判）——与"两个意图"讨论中的 judge 侧开放问题合并。
- 探索收敛判据的具体参数（连续 N 个会话无新签名）。
