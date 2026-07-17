完整方案

一、分层职责

mock 层（扮演用户）
- 产意图（MockIntentOutput：user_intent / query / user_context / scenario）
- 产 request（REQUEST_SCHEMA 形状）
- 定义多轮控制（max_turns / should_stop）

live 层（投递业务 API）
- execute_live：完整调用，输入 MockIntentOutput，内部判断单轮/多轮，和 mock 交互
- deliver_turn：单次投递，输入 REQUEST_SCHEMA，不碰 mock，纯投递（只走 real 路径）
- 只返回 EXTRACT_OUTPUT_SCHEMA，不背 trace 字段

trace 层（组装 RunTrace）
- 位置：impl/core/trace.py（新建）
- 通过 TraceContext 在 execute_live 调用过程中收集过程事实（raw_response / call_status / fallbacks / execution_trace / multi_turn_state）
- 从 live 拿 EXTRACT_OUTPUT_SCHEMA
- 组装完整 RunTrace（含 trace 字段 + output）
- 调 judge / attribute / cluster / check / frontend

公共层（跨层载体）
- case 不属于 mock/live，是跨层数据载体
- mock 填 input/intent/scenario，live 填 output，judge 读 reference/output，trace 读全部

二、协议层（框架核心，不可改）

mock 协议层

┌─────────────────────────────────┬────────────────────────────────────────────────────────────────┐
│               项                │                              职责                              │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ build_user_intent 校验          │ 校验输出是否符合 MockIntentOutput schema                       │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ build_live_request /            │ 校验输出是否符合 REQUEST_SCHEMA                                │
│ build_next_request 校验         │                                                                │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ build_user_intent 签名          │ (scenario: str) → MockIntentOutput                             │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ build_live_request 签名         │ (intent: MockIntentOutput) → REQUEST_SCHEMA                    │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ build_next_request 签名         │ (intent: MockIntentOutput, accumulated:                        │
│                                 │ Optional[EXTRACT_OUTPUT_SCHEMA]) → REQUEST_SCHEMA              │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ max_turns 签名                  │ () → int                                                       │
├─────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ should_stop 签名                │ (transcript: List[Dict], last_result: Any) → bool              │
└─────────────────────────────────┴────────────────────────────────────────────────────────────────┘

live 协议层

┌──────────────┬────────────────────────────────┬──────────────────────────────────────────────────┐
│     方法     │              签名              │                       职责                       │
├──────────────┼────────────────────────────────┼──────────────────────────────────────────────────┤
│ execute_live │ (intent: MockIntentOutput,     │ 完整调用入口，内部判断单轮/多轮，调用 mock +      │
│              │ ctx: TraceContext) →           │ deliver_turn；通过 TraceContext 上报每轮过程事实     │
│              │ EXTRACT_OUTPUT_SCHEMA          │                                                  │
├──────────────┼────────────────────────────────┼──────────────────────────────────────────────────┤
│ deliver_turn │ (request: REQUEST_SCHEMA) →    │ 单次 real 投递，调用 deliver_real → extract_output  │
│              │ EXTRACT_OUTPUT_SCHEMA          │ → 校验 EXTRACT_OUTPUT_SCHEMA                      │
└──────────────┴────────────────────────────────┴──────────────────────────────────────────────────┘

trace 协议层

┌─────────────────┬───────────────────────┬────────────────────────────────────────────────────────┐
│      方法       │         签名          │                          职责                          │
├─────────────────┼───────────────────────┼────────────────────────────────────────────────────────┤
│ trace_from_live │ (live: ProjectLive,   │ 构造 TraceContext，调 live.execute_live，收集过程事实， │
│                 │ case) → RunTrace      │ 组装 RunTrace，调 judge/attribute/cluster/check/        │
│                 │                       │ frontend                                              │
├─────────────────┼───────────────────────┼────────────────────────────────────────────────────────┤
│ TraceContext    │ trace 层提供的黑盒    │ 方法：record_turn(raw_response, extracted, call_status,  │
│                 │                       │ runtime_ms, fallbacks, validation)                     │
│                 │                       │ execute_live 内部每轮 deliver_turn 后上报               │
└─────────────────┴───────────────────────┴────────────────────────────────────────────────────────┘

三、项目扩展层

必须实现（项目必须正确实现，确保协议层校验能通过）

方法: build_user_intent
签名: (scenario: str) → MockIntentOutput
schema 说明: 输入：场景名称（str）输出：用户意图（MockIntentOutput）
适用场景: 所有项目
────────────────────────────────────────
方法: build_live_request
签名: (intent: MockIntentOutput) → REQUEST_SCHEMA
schema 说明: 输入：用户意图（MockIntentOutput）输出：单轮请求体（符合项目 REQUEST_SCHEMA 的 dict）
适用场景: 单轮项目
────────────────────────────────────────
方法: build_next_request
签名: (intent: MockIntentOutput, accumulated: Optional[EXTRACT_OUTPUT_SCHEMA]) → REQUEST_SCHEMA
schema 说明: 输入：用户意图 + 历史累积输出输出：下一轮请求体（符合项目 REQUEST_SCHEMA 的 dict）
适用场景: 多轮项目
────────────────────────────────────────
方法: max_turns
签名: () → int
schema 说明: 输出：最大轮数（int）
适用场景: 多轮项目
────────────────────────────────────────
方法: should_stop
签名: (transcript: List[Dict], last_result: Any) → bool
schema 说明: 输入：对话历史 + 最后一次结果输出：是否停止（bool）
适用场景: 多轮项目
────────────────────────────────────────
方法: deliver_real
签名: (request: REQUEST_SCHEMA) → raw_response: Any
schema 说明: 输入：请求体输出：业务 API 原始响应（Any，结构不标准）
适用场景: 所有项目
────────────────────────────────────────
方法: extract_output
签名: (raw_response: Any, request: REQUEST_SCHEMA) → EXTRACT_OUTPUT_SCHEMA
schema 说明: 输入：原始响应 + 请求体输出：提取后的输出（必须符合项目 EXTRACT_OUTPUT_SCHEMA）
适用场景: 所有项目

关键保证：项目必须正确实现 extract_output，确保能从 raw_response 提取出符合 EXTRACT_OUTPUT_SCHEMA
的输出。协议层在 deliver_turn 最后校验，校验失败说明项目实现有问题。

可选覆盖（有默认实现）

┌──────────────────────┬───────────────────────────────────────────┬───────────────────────────────┐
│         方法         │                   签名                    │           默认行为            │
├──────────────────────┼───────────────────────────────────────────┼───────────────────────────────┤
│ deliver_stub         │ (request: REQUEST_SCHEMA) → raw_response: │ 返回 None（业务 API           │
│                      │  Optional[Any]                            │ 不可用时降级）                │
├──────────────────────┼───────────────────────────────────────────┼───────────────────────────────┤
│ deliver_provided     │ (request: REQUEST_SCHEMA) → raw_response: │ 返回 None（case 已有 output   │
│                      │  Optional[Any]                            │ 时直接返回）                  │
├──────────────────────┼───────────────────────────────────────────┼───────────────────────────────┤
│ application_boundary │ (raw_response: Any, extracted_output:     │ 返回空                        │
│                      │ EXTRACT_OUTPUT_SCHEMA, request:           │ dict（记录业务边界信息）      │
│                      │ REQUEST_SCHEMA) → boundary: Dict          │                               │
├──────────────────────┼───────────────────────────────────────────┼───────────────────────────────┤
│ normalize_result     │ (result: EXTRACT_OUTPUT_SCHEMA) →         │ 直接返回（标准化结果结构）    │
│                      │ EXTRACT_OUTPUT_SCHEMA                     │                               │
└──────────────────────┴───────────────────────────────────────────┴───────────────────────────────┘

四、权责清晰

单轮项目必须实现：build_user_intent + build_live_request + deliver_real + extract_output
多轮项目必须实现：build_user_intent + build_next_request + max_turns + should_stop + deliver_real +
extract_output

- build_live_request（单轮专用）和 build_next_request（多轮专用）不重叠
- 两类项目都需要 build_user_intent / deliver_real / extract_output（通用）

五、Schema 说明

MockIntentOutput
user_intent: str（必填）
query: str（必填）
user_context: Dict[str, Any]（默认空 dict）
scenario: str（build_user_intent 输出时填充）

REQUEST_SCHEMA：项目特定 dataclass（如 MPApiRequest / ClientSearchRequest / DeerflowApiRequest）
EXTRACT_OUTPUT_SCHEMA：项目特定 dataclass（如 MPExtractOutput / ClientSearchOutput /
DeerflowExtractOutput）

TraceContext（trace 层提供，execute_live 接收）
- record_turn(request, raw_response, extracted_output, call_status, runtime_ms, error, fallbacks, validation) → None
  每轮 deliver_turn 后由 execute_live 上报本轮过程事实
- 过程事实由 trace 层持有，不成为 live 层返回值的一部分

六、协议层保证

- mock 产出 request 后校验符合 REQUEST_SCHEMA（校验失败说明项目 build_live_request/build_next_request
    实现有问题）
- live 投递 output 后校验符合 EXTRACT_OUTPUT_SCHEMA（校验失败说明项目 extract_output 实现有问题）
- request 产出后不被覆盖
- turn_index 等控制信息不进 request
- case 不进 live 层
- 校验位置：函数最前面校验输入，函数最后面校验输出

七、case 的定位

- case 是公共层跨层载体，不属于 mock/live
- mock 填 input/intent/scenario
- live 填 output（EXTRACT_OUTPUT_SCHEMA）
- judge 读 reference/output
- trace 读全部，组装 RunTrace
- case 不进 live 层（只在 pipeline 入口用，转成 intent 后传 live）

八、完整调用链

pipeline.live_run(case)
    ↓ 从 case 提取 intent（调 mock.build_user_intent 或从 case.user_intent 取）
    ↓ trace 层构造 TraceContext
    ↓ live.execute_live(intent, ctx)
        ↓ isinstance(MultiTurnInteractiveLive)?
        ↓ 单轮：
            ├─ provided 路径：mock.build_live_request(intent) → request
            │   → deliver_provided(request) → extract_output → 校验
            │   → ctx.record_turn(...) → 返回 EXTRACT_OUTPUT_SCHEMA
            └─ real 路径：mock.build_live_request(intent) → request
                → deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA
                → ctx.record_turn(...) → 返回
        ↓ 多轮：循环
            → mock.build_next_request(intent, accumulated) → request
            → deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA
            → ctx.record_turn(...)
            → mock.should_stop 判断停止
            → 返回聚合的 EXTRACT_OUTPUT_SCHEMA（含 turns）
    ↓ trace 层从 ctx 取过程事实，组装 RunTrace（含 trace 字段 + output）

pipeline 层不再判断单轮/多轮，统一调 execute_live(intent)，由 live 层内部判断。

九、trace 层职责

- 位置：impl/core/trace.py（新建）
- 构造 TraceContext，传给 live.execute_live(intent, ctx)
- execute_live 内部通过 ctx.record_turn() 上报每轮过程事实
- 从 live 拿 EXTRACT_OUTPUT_SCHEMA
- 从 ctx 拿过程事实（raw_response / call_status / fallbacks / execution_trace / multi_turn_state）
- 组装完整 RunTrace
- 调 judge / attribute / cluster / check / frontend
- 返回 RunTrace

十、live 层职责边界

┌──────────────┬──────────────────┬──────────────────────────┬───────────┐
│     函数     │       输入       │           职责           │ 单轮/多轮 │
├──────────────┼──────────────────┼──────────────────────────┼───────────┤
│ deliver_turn │ REQUEST_SCHEMA   │ 单次 real 投递业务 API    │ 不区分    │
├──────────────┼──────────────────┼──────────────────────────┼───────────┤
│ execute_live │ MockIntentOutput │ 完整调用（含 mock 交互），│ 内部判断  │
│              │ + TraceContext   │ 通过 ctx 上报过程事实     │           │
└──────────────┴──────────────────┴──────────────────────────┴───────────┘

deliver_turn 内部流程（只走 real 路径）：
deliver_turn(request)
    ↓ 校验 request 符合 REQUEST_SCHEMA
    ↓ deliver_real(request) → raw_response
    ↓ extract_output(raw_response, request) → EXTRACT_OUTPUT_SCHEMA
    ↓ 校验 output 符合 EXTRACT_OUTPUT_SCHEMA
    ↓ 返回 EXTRACT_OUTPUT_SCHEMA

execute_live 内部流程（统一入口，判断单轮/多轮）：
execute_live(intent, ctx)
    ↓ isinstance(MultiTurnInteractiveLive) ?
    ↓ 单轮：build_live_request(intent) → request
        ├─ provided 路径：deliver_provided(request) → extract_output → 校验 → ctx.record_turn(...)
        └─ real 路径：deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA → ctx.record_turn(...)
    ↓ 多轮：循环
        → build_next_request(intent, accumulated) → request
        → deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA
        → ctx.record_turn(...)
        → mock.should_stop 判断停止
        → 返回聚合 {"turns": [...], ...}
    ↓ 返回 EXTRACT_OUTPUT_SCHEMA

注意：deliver_turn 只走 real 路径（deliver_real）。single-turn 的 provided / stub fallback
在 execute_live 单轮分支中直接处理，不走 deliver_turn。多轮场景下每轮只走 real。

十一、核心原则

1. mock 层权责清晰：build_live_request（单轮专用）+ build_next_request（多轮专用），不重叠
2. live 层两个函数：deliver_turn（单次 real 投递）+ execute_live（完整调用，支持单轮/多轮）
3. execute_live 是统一入口：输入 intent + TraceContext，内部判断单轮/多轮，pipeline 层不再判断
4. deliver_turn 不碰 mock：纯投递，输入 REQUEST_SCHEMA → deliver_real → extract_output → 校验 → 返回 EXTRACT_OUTPUT_SCHEMA
5. execute_live 才和 mock 交互：单轮调 mock.build_live_request，多轮循环调 mock.build_next_request
6. case 不进 live 层：case 只在 pipeline 入口用，转成 intent 后传给 live
7. request 不被覆盖：build_next_request 产出 → 直接投递，不重复调 build_live_request
8. 校验在协议层：request 产出后校验 REQUEST_SCHEMA，output 投递后校验 EXTRACT_OUTPUT_SCHEMA
9. 停止判断统一：只用 mock.should_stop，删协议层自己的停止判断
10. case 是跨层载体：mock/live/judge/trace 各填各的字段
11. live 只返回 EXTRACT_OUTPUT_SCHEMA：不返回 LiveExecutionResult，不背任何 trace 字段
12. trace 字段由 trace 层收集：trace 层构造 TraceContext 传给 execute_live，execute_live 内部通过 ctx.record_turn() 上报过程事实
13. 项目扩展层必须正确实现 extract_output，确保能从 raw_response 提取出符合 EXTRACT_OUTPUT_SCHEMA
的输出
14. 协议层校验失败说明项目实现有问题，项目层需要修复

十二、影响范围

mock 层（5 个项目）
- 单轮项目：实现 build_user_intent + build_live_request + deliver_real + extract_output
- 多轮项目：实现 build_user_intent + build_next_request + max_turns + should_stop + deliver_real +
extract_output
- MockIntentOutput 加 scenario 字段

live 层（协议层 + 5 个项目）
- 返回值从 LiveExecutionResult 改为 EXTRACT_OUTPUT_SCHEMA
- deliver_turn 只走 real 路径，不背 trace 字段
- execute_live 接受 TraceContext 参数，内部通过 ctx.record_turn() 上报过程事实
- 删 deliver(case) 模板方法
- 删 deliver_multi_turn 模板方法（多轮主循环合并到 execute_live 内部）
- 删 _should_stop 协议层默认实现（停止判断只用 mock.should_stop）
- 删 LiveExecutionResult dataclass
- 删 get_last_execution_facts 访问器

trace 层（新建）
- impl/core/trace.py：trace_from_live + TraceContext
- 构造 TraceContext，传给 live.execute_live
- 从 ctx 收集过程事实，组装 RunTrace
- 调 judge/attribute/cluster/check/frontend

pipeline 层
- live_run 入口：case → intent → live.execute_live(intent, ctx) → EXTRACT_OUTPUT_SCHEMA
- 调 trace 层组装 RunTrace
- 不再判断单轮/多轮