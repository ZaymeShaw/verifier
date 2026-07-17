多轮下的循环由协议层的 deliver_multi_turn 模板方法驱动，每轮交替调用 Live 和 Mock：

deliver_multi_turn(case, contract):   ← 协议层 @final 模板方法，项目不能覆盖
    1. 初始化 transcript=[], turn_traces=[]
    2. 第 1 轮输入 = Mock.build_user_intent(case)   ← Mock 产初始输入
    3. while not _should_stop(transcript, last_result):
        a. result = self.deliver_real(本轮输入)      ← 项目 Live 处理单轮业务
        b. transcript.append({input, output=result})
        c. turn_traces.append(_build_turn_trace(...))
        d. 下一轮输入 = Mock.next_turn(case, transcript, result)  ← Mock 产下一轮输入
    4. 聚合：LiveMultiTurnState(transcript, accumulated_fields, stop_reason)
    5. 构造完整 run payload（trace、judge、attribute）
    6. return run payload

关键点：

- 主循环在协议层（MultiTurnInteractiveLive.deliver_multi_turn），不在项目 Live 里，也不在通用层
- 每轮的执行方是 Live：deliver_real 只处理"本轮输入 → 本轮输出"
- 每轮的输入方是 Mock：build_user_intent 产第一轮，next_turn 产后续轮
- 停止条件由协议层默认实现（或项目可选覆盖 _should_stop）
- 项目 Live 完全不知道自己在多轮里，它只是被协议层反复调用 deliver_real

所以循环转起来的本质是：协议层的主循环在 Live 和 Mock 之间做交替调度，Live 产输出、Mock 产输入，直到停止条件触发。




----------------



    多轮方案完整设计

一、多轮形态

只承认一种：verifier 主导的回合制交互

- verifier 控制节奏
- Mock 只产每一轮用户输入
- Live 只处理单轮业务（本轮输入 → 本轮输出）
- 主循环在协议层模板方法
- judge/attribute 不在多轮循环里，是循环结束后的下游环节
- deerflow 和 marketting-planning 同属这一种形态

二、Mock 的职责

Mock 只产输入，不管 output 和 reference：

- build_user_intent(case) -> Dict：产初始用户意图
- next_turn(case, previous_turns, live_feedback) -> Dict：多轮时产下一轮输入

output 由 Live 产，reference 由 Judge 产。如果 case 需要提前生成 output/reference，由 Mock 协议层根据 ready 协议调用 Live/Judge 完成，具体实现是 Live 和
Judge 的事。

Mock 协议层编排：
1. Mock.build_user_intent(case)                ← 产输入
2. if ready.output: Live 提前生成 output       ← 调 Live
3. if ready.reference: Judge 提前生成 reference ← 调 Judge
4. 组装 case（input + 可能的 output + 可能的 reference）

三、中间基类（mixin 组合）

Mock 只按交互模式分，不再按投递模式分（投递模式是 Live 的事）：

- SingleTurnMock：实现 build_user_intent
- MultiTurnInteractiveMock：实现 build_user_intent + next_turn（@abstractmethod）

Live 保持两层组合：

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
MarketingIntentMock(SingleTurnMock)                    # 退出 next_turn

四、MultiTurnInteractiveLive 的职责边界

协议层提供的（@final 模板方法，项目不能覆盖）

@typing_final
def deliver_multi_turn(self, case, contract=None) -> LiveExecutionResult:
    """多轮主循环模板方法，只负责 Live+Mock 交替调度"""
    # 1. 初始化 transcript=[], turn_traces=[]
    # 2. 第 1 轮输入 = Mock.build_user_intent(case)
    # 3. while not self._should_stop(transcript, last_result):
    #      a. result = self.deliver_real(本轮输入)        ← 项目 Live 单轮业务
    #      b. transcript.append({input, output=result})
    #      c. turn_traces.append(self._build_turn_trace(...))
    #      d. 下一轮输入 = Mock.next_turn(case, transcript, result)
    # 4. 聚合 LiveMultiTurnState(transcript, accumulated_fields, stop_reason)
    # 5. return LiveExecutionResult（含 multi_turn_state）
    
模板方法只产出 LiveExecutionResult，不产出 run payload，不调 judge，不调 attribute。

项目必须实现

- deliver_real(request) -> LiveExecutionResult
- extract_output(raw_response, request) -> Dict[str, Any]

项目可选覆盖

- _should_stop(transcript, last_result) -> bool（协议层提供默认实现）
- _build_turn_trace(...)（协议层提供默认实现）

项目不应该实现

- 主循环、transcript 累积、多轮结果聚合
- build_interactive_turn（Mock 的事）
- _mock_agent_next_turn（Mock 的事）
- judge 调用、attribute 调用、run payload 组装

五、调用链路


Pipeline._batch_case
    ↓ 发现 normalized.mode == "interactive_intent"
    ↓ live = adapter.live()
    ↓ isinstance(live, MultiTurnInteractiveLive)
live.deliver_multi_turn(case)          ← 协议层模板方法，只产 LiveExecutionResult
    ↓ 主循环
    self.deliver_real(input)           ← 项目 Live（单轮业务）
    Mock.next_turn(history, output)    ← Mock 产下一轮输入
    ↓ 返回
    LiveExecutionResult（含 multi_turn_state）
    ↓
Pipeline 按正常单轮链路继续：
    trace = trace_from_live_result(result)
    judge_result = judge(project_id, trace)
    attribute_result = attribute(project_id, trace, judge_result)
    run_payload = _run_payload(trace, judge, attribute, ...)

judge 和 attribute 在多轮循环结束后，由 Pipeline 按正常单轮链路调用。

六、协议层硬约束

MultiTurnInteractiveLive 通过 _FORBIDDEN_OVERRIDES 禁止项目覆盖：
- deliver_multi_turn（模板方法）
- _should_stop、_build_turn_trace、_build_next_turn_input（默认实现）

SingleTurnLive 禁止项目实现 run_interactive。

MultiTurnInteractiveMock 必须实现 next_turn（@abstractmethod）。
SingleTurnMock 不提供 next_turn。

七、对现有项目的影响

marketting-planning

- 删除 Live 里的 run_interactive、build_interactive_turn、_mock_agent_next_turn
- 删除 Live 里对 judge/attribute/run_payload 的直接调用
- 继承 MultiTurnInteractiveLive
- Live 瘦回成"单轮业务执行器"

deerflow

- 继承 MultiTurnInteractiveLive
- 实现 deliver_real 处理多轮 turns
- 自动获得主循环


marketting-planning-intent

- 退出多轮签名，继承 SingleTurnLive
- Mock 退出 next_turn

QA、client_search

- 继承 SingleTurnLive
- 保持不变

八、收益

1. 项目继承中间基类 = 声明多轮形态
2. 主循环在协议层，项目不能改
3. Mock 职责清晰：只产输入，output 和 reference 由 Live/Judge 负责
4. Mock 不再按投递模式重复分层（投递模式是 Live 的事）
5. judge/attribute 与多轮循环解耦，走正常单轮下游链路
6. deerflow 接入时直接复用主循环
7. marketting-planning-intent 自然退出多轮
8. 项目 Live 瘦回成单轮执行器

九、实施顺序

1. 在 live_protocol.py 定义 SingleTurnLive 和 MultiTurnInteractiveLive mixin
2. 在 mock_protocol.py 定义 SingleTurnMock 和 MultiTurnInteractiveMock mixin
3. MultiTurnInteractiveLive 提供 deliver_multi_turn 模板方法（@final），只产 LiveExecutionResult
4. 把 marketting-planning 的主循环逻辑上移到协议层模板方法，剥离 judge/attribute 调用
5. 四个项目切换 Live 和 Mock 的继承组合
6. 删除 ProjectLive.run_interactive（被 deliver_multi_turn 替代）
7. Pipeline 调整：多轮路径调 deliver_multi_turn 拿 LiveExecutionResult，再按单轮链路调 judge/attribute
8. 回归测试 + API 验收


--------------------------

4. 把 marketting-planning 的主循环逻辑上移到协议层模板方法，剥离 judge/attribute 调用。这是啥意思？
把多轮主循环逻辑从 MarketingPlanningLive之类 移到协议层 MultiTurnInteractiveLive 的 deliver_multi_turn 模板方法