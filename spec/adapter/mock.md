核心结构
build_intent
{
user_intent: str,                        # 核心目标一句话
user_context: Dict[str, Any] = {},       # 背景信息、约束条件
query: str                               # 用户原话
}



--------------

明白了，我之前理解偏了。修正三者关系：

- user_intent = 用户意图（他心里想干什么，抽象目标）。
- query = 用户基于这个意图说出口的原话。
- user_context = 用户背景信息、用户画像、当前使用业务系统的目标等背景，不是约束条件。

三者关系是：

user_context（用户是谁、为什么用这个系统）
    ↓ 决定了
user_intent（这次他想干什么）
    ↓ 表达为
query（他实际说出口的原话）

user_context 是更上游的"用户画像/场景背景"，user_intent 是基于这个背景产生的具体意图，query 是意图的语言表达。三者是"背景 → 意图 →
表达"的层次关系，不是"意图 + 约束 + 原话"的并列关系。

这个修正对前几轮讨论的影响：

1. user_context 不是约束条件，不能当"预算 5000"这种确定性参数塞。它是用户画像层的东西，本质还是描述性的，LLM
产出的合理性更高（不像约束那样需要确定性）。
2. 之前 Q3 的"项目预填 user_context"这条路就不太对了——项目预填约束是降不确定性，但项目预填"用户画像"语义上不太通，画像更像 LLM
扮演用户时该产的东西。
3. 真正降不确定性的部分不在 user_context，而在 user_intent 这一层——意图被显式产出后，step2 LLM 不用从原话反推意图，不确定性降低在这里。

新的讨论起点应该是：user_context 作为背景信息喂给 step2 LLM 帮助它理解"这个用户是谁"，user_intent 作为目标告诉
step2"这次要填的字段往哪个方向填"，query 作为原话告诉 step2"用户原话要落到 schema 哪个字段"。


--------------


改造目标

把 mock 的 build_intent 推出一层，显式输出：user_intent（用户意图）、query（用户原话）、user_context（用户背景/画像）。让下游 LLM
同时看到"用户是谁"、"想干什么"、"怎么说"，降低从原话到意图的推断不确定性。

需要变化的部分
    
1. 产出结构变更

MockIntentOutput: 
    user_intent: str                    # 核心目标一句话
    user_context: Dict[str, Any]        # 用户背景、画像、使用场景等
    query: str                          # 用户原话



-------------changes

---
Spec: build_intent 产出结构改造

1. 背景

当前 MockAgent.build_intent 产出 {query, expected_intent?, user_intent?, turns?}，意图层只产
query（用户原话），意图抽象层是可选且不稳定的。下游 build_live_request LLM 要从原话反推"用户想干什么"，是 mock 链路里 LLM
不确定性的重要来源。

2. 目标

把 build_intent 推出一层，显式产出三层结构：

- user_intent：用户意图（用户心里想干什么，抽象目标）。
- user_context：用户背景信息、用户画像、当前使用业务系统的目标等。
- query：用户基于意图说出口的原话。

三者关系是"背景 → 意图 → 表达"的层次关系：

user_context（用户是谁、为什么用这个系统）
    ↓ 决定了
user_intent（这次他想干什么）
    ↓ 表达为
query（他实际说出口的原话）

下游 build_live_request LLM 同时拿到背景、意图、原话，不用再从原话反推意图，降低不确定性。

3. 产出结构

3.1 MockIntentOutput（mock_agent.py）

@dataclass
class MockIntentOutput:
    user_intent: str                          # 必填，用户核心目标一句话
    query: str                                 # 必填，用户原话
    user_context: Dict[str, Any] = field(default_factory=dict)  # 用户背景/画像/使用目标

- 删除 expected_intent、turns 字段。
- user_intent、query 设为必填。

    3.2 _MOCK_INTENT_SPEC

    _MOCK_INTENT_SPEC = StructuredOutputSpec.from_dataclass(
        MockIntentOutput,
        required_nonempty=["query", "user_intent"],
        description="mock_agent 意图生成",
    )   

    3.3 MockBuildResult（mock_agent.py）

    @dataclass
    class MockBuildResult:
        case_id: str
        input: Dict[str, Any]
        output: Optional[Dict[str, Any]] = None
        reference: Optional[Dict[str, Any]] = None
        user_intent: str = ""                     # 新增，替代 expected_intent
        user_context: Dict[str, Any] = field(default_factory=dict)  # 新增
        scenario: str = ""
        metadata: Dict[str, Any] = field(default_factory=dict)
        
    - 删除 expected_intent 字段。
    - 新增 user_intent: str、user_context: Dict[str, Any]。
        
    4. 链路改造

    4.1 build_intent（mock_agent.py:75）

    - _intent_system_prompt：从"扮演用户产 query"扩展到"扮演用户产出 user_intent（意图）+ user_context（背景/画像）+ query（原话）"。
    - _map_intent_result：把 LLM 产出的 user_intent、user_context、query 写入 MockBuildResult，不再产 expected_intent、turns。

    4.2 build_live_request（mock_agent.py:92）

    - step2 LLM 的 user prompt 输入从 {"query": ..., "expected_intent": ..., "user_intent": ...} 改为 {"user_intent": ..., "user_context": ...,
     "query": ...}。
    - step2 LLM 同时拿到背景、意图、原话，基于意图和背景填 schema 字段，原话写进 schema 中表达用户输入的字段。

    4.3 next_turn（mock_agent.py:137）

    - next_turn 读取 case 时，从 case.input["user_context"] 拿到用户背景，作为扮演用户的依据。
    - _MOCK_NEXT_TURN_SPEC 保持 {"query", "turn_index"} 不变。
    - _next_turn_system_prompt 增加指引：基于 user_context 和 live_feedback 产下一轮 query。

    4.4 _empty_result（mock_agent.py:271）

    - 产出空 result 时，user_intent=""、user_context={}、query=""，不再产 expected_intent。

    5. 跨层改名：expected_intent → user_intent

    expected_intent 被 user_intent 替代。涉及文件：

    ┌────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────┐
    │                  文件                  │                                            改动点                                             │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/mock_agent.py                │ MockIntentOutput / MockBuildResult / _map_intent_result / build_live_request / _empty_result  │
    │                                        │ 等                                                                                            │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/mock.py                      │ apply_mock_strategy、build_case_from_spec 里 result.expected_intent 改                        │
    │                                        │ result.user_intent，case metadata key 同步改名                                                │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/mock_protocol.py             │ build_user_intent 文档字符串更新                                                              │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │                                        │ judge_trace(expected_intent=...) 参数改名 user_intent；prompt                                 │
    │ impl/core/judge.py                     │ 里"理解用户意图（run_trace.input / expected_intent / scenario）"改为"run_trace.input /        │
    │                                        │ user_intent / scenario"                                                                       │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/judge_protocol.py            │ judge_trace / pre_judge / _run_llm_judge 签名                                                 │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/pipeline.py                  │ judge() / run_chain() / batch_run() / _batch_case() 的参数和传递                              │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/interaction_protocol.py      │ 序列化 key expected_intent → user_intent                                                      │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/schema/trace.py              │ TraceExecutionContext.expected_intent → user_intent                                           │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/core/live_stub.py                 │ line 119 的 expected_intent                                                                   │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/cli.py                            │ --expected-intent CLI 参数 → --user-intent（考虑加 alias 兼容旧脚本）                         │
    ├────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
    │ impl/projects/*/mock.py / adapter.py / │ 项目侧如有引用，同步改名                                                                      │
    │  judge.py                              │                                                                                               │
    └────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────┘

    5.1 judge 对 user_context 的可见性       

    - user_context 落在 SingleTurnCase.input["user_context"]。
    - judge 从 run_trace.input["user_context"] 能读到，prompt 不显式提 user_context（judge 仍只理解 run_trace.input / user_intent / scenario
    三个依据），但 input 里自然包含 user_context。

    6. user_context 的承载

    - MockBuildResult.user_context: Dict[str, Any]。
    - mock.py.build_case_from_spec：把 result.user_context 写入 SingleTurnCase.input["user_context"]，next_turn 可读。
    - 来源：LLM 从项目文档、场景描述中提取，由 _capability_context 继续喂 prompt，LLM 负责结构化提取到 user_context。
    - 项目 mock.py 保持转调 mock_agent，不改用法。

    7. 不改的部分

    - MockNextTurnOutput 结构（{"query", "turn_index"}）。
    - build_live_request 的两步串行结构。
    - _capability_context 的文档截取逻辑。
    - _attach_schema_check 的 schema 校验逻辑。
    - live_schema 层的 REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA。

    8. 验证

    1. py_compile 通过。
    2. python -c "from impl.core.mock_agent import MockAgent; ..." 实例化不崩。
    3. 选 client_search 项目（单轮最简单），跑一次 MockAgent.build，确认产出形状：MockBuildResult.input 含
    query、user_intent、user_context，不含 expected_intent、turns。
    4. 跑一次 pipeline.judge，确认 judge prompt 里 user_intent 替代 expected_intent，judge 不崩。
    5. 选 marketing-planning 项目（多轮），跑一次 next_turn，确认能从 case.input["user_context"] 读到背景。

    9. 不在本次范围

    - draft skill 的 mock role（结构层 loader / schema / check_draft / ROLE.md / compare_mock.py）—— 下一轮再讨论。
    - live_schema 层的字段语义优化。
    - 项目 mock.py 承担实质决策（user_context 仍由 LLM 产）。

    ---
    这是 spec 草案。重点确认：

    1. 第 5 节跨层改名范围认不认（这是最大改动面）。
    2. 第 6 节 user_context 落 SingleTurnCase.input["user_context"]，认不认这个承载位置。
    3. 第 7 节"不改的部分"有没有漏掉应该改的。
    4. CLI 参数 --expected-intent → --user-intent 要不要保留 alias（旧脚本兼容）。

    你审完拍板，我就按 spec 改。