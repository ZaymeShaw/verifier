多轮交互完整方案（最终整合）

一、整体定位

live 是独立的内层模块，做 REQUEST_SHAPE → EXTRACT_OUTPUT_SHAPE 的契约转换。不感知 trace，不感知下游 judge/attribute。trace
层通过统一入口 execute_live 调用 live，零感知单轮/多轮差异，分支由 live 协议层内部判断。

二、live 层协议方法分层

live 层暴露三个协议方法，构成分层调用栈：

execute_live (对 trace 层)
    → deliver_multi_turn (多轮编排，内部)
    → deliver_turn (单轮投递+累积，最内层)

- execute_live(normalized_request) -> extracted_output：live 层对 trace 层的唯一入口。输入形状符合
live_schema.REQUEST_SCHEMA，输出形状符合 live_schema.EXTRACT_OUTPUT_SCHEMA。内部判断 isinstance(self, MultiTurnInteractiveLive)
决定走单轮还是多轮。trace 层只调这个方法，不直接碰后两者。
- deliver_multi_turn(case, contract) @final：多轮主循环模板方法，由 execute_live 内部调用。输入是 case（含 interaction
声明），输出是 LiveExecutionResult（含 multi_turn_state）。
- deliver_turn(request, accumulated_output) -> extracted_output：单轮投递+累积，由 deliver_multi_turn 主循环每轮调用。输入是
request（REQUEST_SHAPE）+ accumulated_output（EXTRACT_OUTPUT_SHAPE 或 None），输出是
extracted_output（EXTRACT_OUTPUT_SHAPE，累积后的）。

三、单轮 vs 多轮对比

┌─────────────────────┬────────────────────────────────────────┬────────────────────────────────────────────────────────────────┐
│        维度         │                  单轮                  │                              多轮                              │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ case 形态           │ 一次 input → 一次 output               │ 多轮 input/output 交替，累积成 transcript                      │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Mock 接口           │ build_user_intent +                    │ build_user_intent + build_next_request(case,                   │
│                     │ build_request(case)                    │ accumulated_output)                                            │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Live 接口           │ deliver(case)                          │ deliver_multi_turn @final + deliver_turn                       │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ execute_live 内部   │ 走单轮 deliver 路径                    │ 跑主循环                                                       │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ accumulated_output  │ 不存在                                 │ 首轮 None，后续轮带上一轮累积                                  │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ mixin               │ SingleTurnLive + SingleTurnMock        │ MultiTurnInteractiveLive + MultiTurnInteractiveMock            │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 停止条件            │ 不需要                                 │ _should_stop（协议层默认 + 项目可选覆盖）                      │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 过程状态            │ LiveExecutionResult                    │ LiveExecutionResult + LiveMultiTurnState                       │
├─────────────────────┼────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ judge/attribute     │ deliver 后立即调                       │ 循环结束后由 Pipeline 按单轮链路调                             │
│ 时机                │                                        │                                                                │
└─────────────────────┴────────────────────────────────────────┴────────────────────────────────────────────────────────────────┘

四、Mock 的职责分层

Mock 只产输入，不管 output 和 reference。两个方法分层，单轮和多轮都必须同时实现：

- build_user_intent(scenario) -> 
Dict：用户基础想法抽象，Mock"扮演用户"的核心语义点。场景级，不绑定轮次，固定输出。单轮/多轮都必须实现。
- 产 request 的方法（单轮多轮不同名，避免基类继承冲突）：
    - 单轮：build_request(case) -> Dict：把意图翻译成单轮 request（REQUEST_SHAPE）
    - 多轮：build_next_request(case, accumulated_output) -> Dict：把意图 + 历史累积翻译成每轮 request
        - 首轮：accumulated_output=None，基于 case 里的 build_user_intent 产首轮 request
    - 后续轮：accumulated_output=<上一轮累积>，既看 case 意图又看 accumulated 产下一轮 request

output 由 Live 产，reference 由 Judge 产。

关键修正：意图始终在 case 里，每轮 mock 都要参考 case（不只首轮）。accumulated_output 是额外的"上一轮反馈"信号，不是替代 case。

五、Live 的职责

- execute_live(normalized_request) -> extracted_output：trace 层统一入口，输入 REQUEST_SCHEMA 形状，输出 EXTRACT_OUTPUT_SCHEMA
形状，内部判断单轮/多轮
- deliver_multi_turn(case, contract) @final：多轮主循环模板方法，只产 LiveExecutionResult，不调 judge/attribute
- deliver_turn(request, accumulated_output) -> extracted_output：单轮投递+累积（仅多轮走）
    - 内部流程：用 request 调业务 API → 拿 raw_response → extract_output 提取本轮 turn_output → 追加到 accumulated.turns（None
时先初始化为 {turns: []}）→ 返回新的 accumulated

六、多轮主循环（在 Live 协议层 deliver_multi_turn 里）

@typing_final
def deliver_multi_turn(self, case, contract=None) -> LiveExecutionResult:
    # 1. 初始化 transcript=[], turn_traces=[]
    # 2. accumulated = None
    # 3. request = mock.build_next_request(case, accumulated)     # 首轮
    # 4. while not _should_stop(transcript, last_result):
    #      a. output = self.deliver_turn(request, accumulated)       # 投递+累积
    #      b. transcript.append({input, output})
    #      c. turn_traces.append(_build_turn_trace(...))
    #      d. accumulated = output
    #      e. request = mock.build_next_request(case, accumulated)  # 下一轮
    # 5. 聚合 LiveMultiTurnState(transcript, accumulated_fields, stop_reason)
    # 6. return LiveExecutionResult（含 multi_turn_state）
    
简化伪代码：
accumulated = None
request = mock.build_next_request(case, accumulated)   # 首轮
output = self.deliver_turn(request, accumulated)
while not should_stop(output):
    request = mock.build_next_request(case, output)    # 后续轮
    output = self.deliver_turn(request, output)
return output
    
七、中间基类（mixin 组合）

Mock 按交互模式分（方法不同名，避免基类继承冲突）：

- SingleTurnMock：实现 build_user_intent + build_request(case)（@abstractmethod）
- MultiTurnInteractiveMock：实现 build_user_intent + build_next_request(case, accumulated_output)（@abstractmethod）

Live 两层组合：

- 第一层（投递模式）：RealServiceLive / ProvidedOutputLive
- 第二层（交互模式）：SingleTurnLive / MultiTurnInteractiveLive

项目继承组合：
MarketingPlanningLive(RealServiceLive, MultiTurnInteractiveLive)
MarketingPlanningMock(MultiTurnInteractiveMock)

DeerflowLive(RealServiceLive, MultiTurnInteractiveLive)
DeerflowMock(MultiTurnInteractiveMock)
QALive(ProvidedOutputLive, SingleTurnLive)
QAMock(SingleTurnMock)

ClientSearchLive(RealServiceLive, SingleTurnLive)
ClientSearchMock(SingleTurnMock)

MarketingIntentLive(RealServiceLive, SingleTurnLive)   # 退出多轮
MarketingIntentMock(SingleTurnMock)                    # 退出多轮

八、调用链路

Pipeline._batch_case
↓ 发现 normalized.mode == "interactive_intent"
↓ live = adapter.live()
↓ isinstance(live, MultiTurnInteractiveLive)
live.deliver_multi_turn(case)              ← 协议层模板方法
↓ 主循环（mock.build_next_request + live.deliver_turn 交替）
LiveExecutionResult（含 multi_turn_state）
↓
Pipeline 按正常单轮链路继续：
trace = trace_from_live_result(result)
judge_result = judge(project_id, trace)
attribute_result = attribute(project_id, trace, judge_result)
run_payload = _run_payload(trace, judge, attribute, ...)

judge 和 attribute 在多轮循环结束后，由 Pipeline 按正常单轮链路调用。

九、过程状态：单轮多轮不统一

- 单轮：LiveExecutionResult（单个 raw_response + extracted_output + execution_trace）
- 多轮：LiveExecutionResult + LiveMultiTurnState（transcript/turn_traces/accumulated_fields/stop_reason）

下游消费方（judge/attribute/frontend_view）用 isinstance(result.multi_turn_state, LiveMultiTurnState)
判断走多轮分支还是单轮分支。单轮/多轮评估逻辑本质不同（单轮看一次交互，多轮看对话演进），分支是合理的。

十、三方职责
┌───────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│   角色    │                                                       职责                                                        │
├───────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ mock      │ build_user_intent(scenario) 产意图；单轮 build_request(case) 产单轮 request；多轮 build_next_request(case,        │
│           │ accumulated_output) 产每轮 request                                                                                │
├───────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ live      │ execute_live 判断单轮/多轮；多轮时 deliver_multi_turn 跑主循环；deliver_turn 做投递+累积                          │
│ 协议层    │                                                                                                                   │
├───────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ trace 层  │ 只调 execute_live，组装 trace，不感知单轮多轮差异；下游用 isinstance 处理多轮状态                                 │
└───────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

十一、协议层硬约束

MultiTurnInteractiveLive._FORBIDDEN_OVERRIDES：
- deliver_multi_turn（模板方法）

_should_stop / _build_turn_trace / _build_next_turn_input 为协议层默认实现，项目可选覆盖以实现特化语义（如 marketting-planning 的
stage+missing_fields 推进、deerflow 的 stage 推进）。

- SingleTurnLive 禁止项目实现 run_interactive
- MultiTurnInteractiveMock 必须实现 build_next_request（@abstractmethod）
- SingleTurnMock 必须实现 build_request（@abstractmethod）
- 两个方法不同名，避免基类继承冲突

十二、live 和 trace 的串联关系

单向依赖：trace 依赖 live，live 不依赖 trace。

pipeline (trace 层)
    ↓ 调
live.execute_live(normalized_request) → extracted_output
    ↓ 返回
trace 层组装：spec + case + extracted_output + 过程事实 → RunTrace
    ↓ 输出
judge / attribute / check 等下游消费 trace

十三、关键特性
1. 形状统一：多轮的输入和输出都用 EXTRACT_OUTPUT_SHAPE 表达"累计状态"
2. 首轮语义清晰：None 表示"无历史"
3. 状态显式传递：每轮的 accumulated 显式传入，不依赖外部维护
4. 意图始终在 case：每轮 mock 都从 case 拿意图，accumulated_output 只作为"上一轮反馈"信号，不替代 case
5. build_user_intent 是用户基础想法抽象：场景级，不绑定轮次，单轮/多轮都必须实现
6. 产 request 方法单轮多轮不同名：build_request(case) / build_next_request(case, accumulated_output)，避免基类继承冲突
7. live 层协议方法分层：execute_live（对 trace 层）→ deliver_multi_turn（多轮编排）→ deliver_turn（单轮投递+累积），trace 层只调
execute_live
8. execute_live 输入输出形状由 live_schema 锁定：REQUEST_SCHEMA → EXTRACT_OUTPUT_SHAPE
9. 单轮多轮统一入口：都走 execute_live，trace 层零感知
10. mock 简单：只产 request，不看 accumulated 自己组装
11. live 纯粹：只做投递+累积，不感知 trace
12. 主循环归属 Live 协议层：trace 层不调度循环
13. 过程信息归属 trace：raw_response、execution_trace、fallbacks、multi_turn_state 等由 trace 层维护
14. 过程状态不强行统一：单轮 LiveExecutionResult，多轮加 LiveMultiTurnState，下游 isinstance 分支处理

十四、对现有项目的影响

marketting-planning
- 删除 Live 里的 run_interactive、build_interactive_turn、_mock_agent_next_turn
- 删除 Live 里对 judge/attribute/run_payload 的直接调用
- 继承 MultiTurnInteractiveLive
- Live 瘦回成"单轮业务执行器"
- Mock：build_user_intent 保留，原 next_turn 改名 build_next_request

deerflow
- 继承 MultiTurnInteractiveLive
- 实现 deliver_real 处理多轮 turns
- 自动获得主循环
- Mock：同 marketting-planning

marketting-planning-intent
- 退出多轮签名，继承 SingleTurnLive
- Mock 继承 SingleTurnMock（实现 build_request 而非 build_next_request）

    QA、client_search
- 继承 SingleTurnLive
- Mock 实现 build_request(case)
- 保持不变

十五、实施顺序

1. 在 live_protocol.py 定义 SingleTurnLive 和 MultiTurnInteractiveLive mixin
2. 在 mock_protocol.py 定义 SingleTurnMock 和 MultiTurnInteractiveMock mixin（方法不同名：build_request / build_next_request）
3. MultiTurnInteractiveLive 提供 deliver_multi_turn 模板方法（@final）+ deliver_turn 方法
4. 把 marketting-planning 的主循环逻辑上移到协议层模板方法，剥离 judge/attribute 调用
5. 两个多轮项目的 Mock：next_turn → build_next_request（签名 (case, accumulated_output)）
6. 单轮项目的 Mock：确认 build_request(case) 实现
7. 四个项目切换 Live 和 Mock 的继承组合
8. 删除 ProjectLive.run_interactive（被 deliver_multi_turn 替代）
9. Pipeline 调整：多轮路径调 deliver_multi_turn 拿 LiveExecutionResult，再按单轮链路调 judge/attribute
10. 回归测试 + API 验收

核心修正点（相对之前）

- live 层协议方法分层明确：execute_live 是 live 层对 trace 层的唯一入口（REQUEST_SCHEMA →
EXTRACT_OUTPUT_SHAPE），deliver_multi_turn 和 deliver_turn 是 execute_live 内部调度的协议方法，trace 层不直接碰
- 产 request 方法单轮多轮不同名：单轮 build_request(case)，多轮 build_next_request(case, accumulated_output)，避免基类继承冲突
- build_user_intent 单轮多轮都必须有：它是用户基础想法抽象，不是多轮专属
- 过程状态不强行统一：单轮用 LiveExecutionResult，多轮加 LiveMultiTurnState，下游 isinstance 分支处理



-------------



⏺ 完整分析

单轮 live 现状
    
单轮 live 走 deliver 模板方法：

def deliver(self, case, contract=None):
    request = self._build_request(case)  # ← 调 live.build_request
    # ... 投递

live.build_request（line 476-486）默认透传 case.input。case.input 已经是 REQUEST_SCHEMA 形状——因为 mock 在构造 case
时，mock_agent.build_live_request 跑 step2 LLM，已经按 REQUEST_SCHEMA 产出了 input。

所以单轮实际流程：

mock.build_intent (step1 LLM) → intent + input(query)
mock.build_live_request (step2 LLM) → input(REQUEST_SCHEMA 形状)
case.input = input
---
live.deliver(case)
→ live.build_request(case) → 透传 case.input
→ 业务 API 用 REQUEST_SCHEMA 形状的 request

mock.build_request 在这一层根本没位置——意图翻译在 step2 已经做了，case.input 就是 REQUEST_SCHEMA 形状。

协议层流程 vs 实际流程

┌─────────────────────────────────────────────────────────┬───────────────────────────────────────────┐
│            协议层定义（multiturn.md 第四节）            │                 实际流程                  │
├─────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ build_user_intent → intent                              │ build_intent → intent + input             │
├─────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ build_request(case) → request（单轮）                   │ 跳过，直接透传 case.input                 │
├─────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ build_next_request(case, accumulated) → request（多轮） │ 项目层实现（marketing-planning/deerflow） │
└─────────────────────────────────────────────────────────┴───────────────────────────────────────────┘

问题：单轮跳过了 mock.build_request，意图翻译被合并到 mock.build_live_request 内部（step1 + step2 串行 LLM）。

协议正确性

按协议层分层：
- build_intent 产意图层（user_intent / query / user_context）
- build_request 把意图翻译成 REQUEST_SCHEMA 形状

当前 mock_agent.build_intent 是 step1（LLM 产意图），build_live_request 是 step2（LLM 产 REQUEST_SCHEMA）。这两个合成了
mock.build_intent + mock.build_request 的语义，但合在了 mock_agent 内部，没暴露在协议层。

修复方案

协议层要恢复 build_request 的调用位置。

单轮 live 的 deliver 模板方法应该改成：

def deliver(self, case, contract=None):
    # 协议层先调 build_user_intent 得意图
    scenario = str(getattr(case, "scenario", "") or "")
    intent = self.mock.build_user_intent(scenario)  # 或 mock 注入
    # 协议层调 mock.build_request(case, intent) 得 request
    normalized = self.mock.build_request(case, intent)
    request = LiveRequest(..., normalized_request=normalized)
    # ... 投递

项目层 mock.build_request 实现：接收 case 和 intent，按 REQUEST_SCHEMA 组装。

但这里有个问题：当前 case.input 已经是 REQUEST_SCHEMA 形状（由 mock_agent.build_live_request 产出）。如果协议层再调一次
mock.build_request 重新翻译，会不会重复？

看当前 case.input 的内容：

{
    "user_text": "帮我找一下45岁以上的女性客户...",
    "user_id": "default_user",
    "trace_id": "trace_001",
    "session_id": "session_001",
    "source": "insurance_search",
    "extra_input_params": {...},
}

这已经是 REQUEST_SCHEMA 形状（UserTextRequest）。case.input 就是 REQUEST_SCHEMA，mock.build_request 不需要再翻译，只需要：

def build_request(self, case, intent):
    return dict(case.input)  # 透传 case.input

但协议层调 mock.build_request 的意义在于：
1. 分层清晰：build_intent 产意图，build_request 产 request，职责分离
2. 扩展点：项目层可以覆盖 build_request 定制 request 形状（比如注入意图字段、加 session_id 等）
3. 意图可见：build_request 能看到 intent 入参，可以根据 intent 调整 request

所以修法：

1. 协议层 deliver 模板方法改成调 mock.build_request(case, intent)
2. intent 由协议层在调用前从 mock.build_user_intent(scenario) 得，或者从 case.user_intent / case.metadata["user_context"] 读
3. 项目层 mock.build_request(case, intent) 实现：默认透传 case.input，可选定制

多轮也类似：mock.build_next_request(case, intent, accumulated)，协议层传 intent 入参。

完整修法

改动: 1. 协议层 build_request / build_next_request 签名加 intent 参数
说明: build_request(case, intent) / build_next_request(case, intent, accumulated)
────────────────────────────────────────
改动: 2. 协议层单轮 deliver 调 mock.build_request（不是 live.build_request）
说明: deliver 模板方法改成调 mock 的 build_request
────────────────────────────────────────
改动: 3. 协议层多轮 deliver_multi_turn 调 mock.build_next_request 时传 intent
说明: 已经在调，加 intent 参数
────────────────────────────────────────
改动: 4. 协议层在调用前先算 intent
说明: 从 case 取（case.user_intent / case.metadata），或调 build_user_intent
────────────────────────────────────────
改动: 5. 项目层 mock 接 intent 参数
说明: 默认透传 case.input
────────────────────────────────────────
改动: 6. mock_agent.next_turn user prompt 加 user_intent
说明: 让 LLM 看到用户意图
────────────────────────────────────────
改动: 7. 项目层 build_next_request 的 case_dict 加 user_intent key
说明: 把意图传给 next_turn
────────────────────────────────────────
改动: 8. 删 mock_protocol.MultiTurnInteractiveMock.next_turn
说明: 死协议清理
────────────────────────────────────────
改动: 9. 项目层 QA/client_search 删 build_request 覆盖
说明: 已删，上一轮

风险评估

高风险：
- 单轮 deliver 模板方法改动（line 88）会影响所有单轮项目
- 多轮 build_next_request 签名改动会影响所有多轮项目（marketing-planning / deerflow）

中风险：
- intent 从哪来？协议层是先调 mock.build_user_intent 还是从 case 取？
- 如果从 case 取，那 build_user_intent 什么时候跑？

建议方案

intent 来源：
- 协议层 deliver 时先检查 case.user_intent / case.metadata["user_context"] 是否有值
- 如果有值，直接构造 MockIntentOutput（从 case 字段组装）
- 如果没值（比如 live_run 直接传 input，没走 mock），调 mock.build_user_intent(scenario) 补充

这样既能从已有 case 取意图（避免重复 LLM 调用），也能在缺失时补充。

询问

确认按这个方案改吗？

- 协议层改动：live_protocol deliver / deliver_multi_turn 模板方法
- 协议层签名：SingleTurnMock.build_request / MultiTurnInteractiveMock.build_next_request 加 intent 参数
- 项目层：5 个项目 mock 接 intent 参数

确认后我开干。

---
二、协议层调度（live_protocol.py）

单轮 deliver 模板方法：
def deliver(self, case, contract=None):
    # 协议层先算 intent
    intent = self._resolve_intent(case)  # 从 case.user_intent/metadata 读，不够则调 build_user_intent
    # 协议层调 mock.build_live_request
    request_dict = self.mock.build_live_request(case, intent)
    request = LiveRequest(..., normalized_request=request_dict)
    # ... 投递

多轮 deliver_multi_turn 模板方法：
def deliver_multi_turn(self, case, contract=None):
    # 协议层先算 intent（一次性）
    intent = self._resolve_intent(case)
    # 每轮调 mock.build_next_request 时传 intent
    request = mock.build_next_request(case, intent, accumulated)
    ...

_resolve_intent 逻辑：
- 优先从 case.user_intent + case.metadata["user_context"] 构造 MockIntentOutput
- 不够则调 mock.build_user_intent(scenario) 补充

---
三、项目层 mock 接 intent 入参

单轮项目（QA / client_search / marketing-planning-intent）：
- 删 build_request 覆盖（已删）
- build_live_request(case, intent) 默认实现：委托 MockAgent 跑 step2 LLM（用 intent + live_schema.REQUEST_SCHEMA）

多轮项目（marketing-planning / deerflow）：
- build_next_request(case, intent, accumulated) 接收 intent 入参
- 首轮直接用 intent，不调 build_user_intent
- 后续轮把 intent.user_intent / intent.user_context 传给 mock_agent.next_turn

---
四、MockAgent 适配

- 协议层不再感知 MockBuildSpec / MockBuildResult
- MockAgent 提供通用工具函数供协议层默认实现调用（入参改为 (intent, spec) 级别，内部再转 MockBuildResult 调 step2 LLM）
- 项目层可选覆盖 build_live_request 做定制化 REQUEST_SCHEMA 组装

---
五、mock_protocol.py 死协议清理

┌──────────────────────────────────────────────────────┬────────────────────────────────────────────┐
│                        清理项                        │                    原因                    │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────┤
│ 删 SingleTurnMock.build_request abstractmethod       │ 协议层不调它了，由 build_live_request 替代 │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────┤
│ 删 MultiTurnInteractiveMock.next_turn abstractmethod │ 协议层不调它，由 build_next_request 替代   │
└──────────────────────────────────────────────────────┴────────────────────────────────────────────┘

---
六、prompt 和位置修复

┌───────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│                          修复项                           │                          说明                          │
├───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ mock_agent.next_turn user prompt 加 user_intent           │ 当前只传 user_context，LLM 看不到用户意图              │
├───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 项目层 build_next_request 的 case_dict 加 user_intent key │ 从 intent.user_intent 取，传给 next_turn               │
├───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ mock_agent.next_turn docstring 说明入参结构               │ 标注 case 字典含 metadata（user_context）+ user_intent │
└───────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────┘

---
七、实施顺序

1. mock_protocol.py：签名改名 + 加 intent 入参 + 删死协议
2. live_protocol.py：deliver / deliver_multi_turn 模板方法改调度逻辑
3. MockAgent：提取 step2 LLM 工具函数，入参改为 (intent, spec)
4. 5 个项目 mock.py：接 intent 入参，删旧覆盖
5. mock_agent.py：修 next_turn prompt 传 user_intent
6. py_compile + smoke 测试

---
八、风险评估

- 高风险：协议层签名改动（所有项目 mock 都要同步改）
- 中风险：intent 来源逻辑（从 case 读 vs 调 build_user_intent）
- 低风险：prompt 修复、死协议清理


------------------


mock / live 扩展方案 + execute_live 定位

一、mock 扩展方案

单轮（SingleTurnMock）：
- build_user_intent(scenario) -> MockIntentOutput
- build_live_request(case, intent) -> Dict（产 REQUEST_SCHEMA 形状）

多轮（MultiTurnInteractiveMock）：
- 继承单轮的全部
- 加 build_next_request(intent, accumulated) -> Dict（每轮产 request，入参只有 intent + accumulated，不接 case）
- 加 max_turns() -> int（项目扩展层定最大轮数）
- 加 should_stop(transcript, last_result) -> bool（项目扩展层定停止信号）

设计原则：多轮控制（max_turns / stop_when）是 mock 扮演用户的能力，由项目 mock 扩展层实现，不放在 case 里。

二、live 扩展方案

单轮（SingleTurnLive）：
- deliver(case) -> LiveExecutionResult

多轮（MultiTurnInteractiveLive）：
- 继承单轮
- 加 deliver_multi_turn @final（多轮主循环模板方法）
- 加 deliver_turn(request, accumulated) -> extracted_output（单轮投递+累积）

设计原则：live 通过 mixin 知道自己单轮还是多轮，不依赖 case 或 normalized_request 携带多轮声明。

三、execute_live 定位

def execute_live(
    self,
    normalized_request: Dict,                       # 本轮 request（首轮），REQUEST_SCHEMA 纯净形状
    intent: Optional[MockIntentOutput] = None,      # 多轮时传，单轮 None
) -> Any:

职责：
- 对 trace 层唯一入口
- 内部通过 isinstance(self, MultiTurnInteractiveLive) 判断单轮/多轮
- 单轮 → deliver
- 多轮 → deliver_multi_turn（内部跑主循环：mock.build_next_request + deliver_turn 交替）


关键约束：
- 输入只有 normalized_request + 可选 intent，不接收 case / mock / metadata
- 多轮控制：deliver_multi_turn 内部通过 _mock_for_multi_turn() 拿 mock，调 mock.max_turns() / mock.should_stop()
- 多轮驱动信息：用 intent（build_intent 产出），不用 case
- 输出：extracted_output（符合 EXTRACT_OUTPUT_SHAPE）

四、三方职责

┌──────────────┬───────────────────────────────────────────────────────────────────────────────────────────────┐
│     角色     │                                             职责                                              │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ mock         │ 扮演用户：产意图、产 request、定义多轮控制（max_turns/should_stop）                           │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ live         │ 投递业务 API：单轮投递、多轮主循环编排、提取 output                                           │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ execute_live │ 对 trace 层入口，内部判断单轮/多轮，不接收 case/mock，只接收 normalized_request + 可选 intent │
└──────────────┴───────────────────────────────────────────────────────────────────────────────────────────────┘
