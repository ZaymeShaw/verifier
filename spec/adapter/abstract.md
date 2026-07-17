  Live 和 Mock 的必须实现扩展点修正

  Live：deliver_real 作为必须实现

  live_schema 已经定义了输入形状（case.input = REQUEST_SCHEMA），build_request 只是透传，可以给默认实现。真正项目特有的是"如何调用业务系统"——这是 Live
  的核心业务知识，无法通用化。

  修正：
  - build_request：改为可选扩展点，默认透传 case.input 作为 normalized_request
  - deliver_real(request) -> Any：提升为必须实现扩展点（@abstractmethod），项目实现真实 API 调用
  - deliver_provided：保持可选（provided-output 模式才需要）

  Mock：扮演用户 → 必须项是什么

  Mock 的定位是"扮演使用业务系统的用户"。结合当前流程"用户意图 → 多轮"，拆解用户必须提供什么：

  当前流程（mock_agent 两步）：
  1. build_intent：构建用户意图（query、user_intent、expected_intent）
  2. build_live_request：按 REQUEST_SCHEMA 产出 live 请求体

  扮演用户必须给的：

  1. 用户意图层（build_intent 的项目特有部分）：
    - 该项目的用户会提什么类型的意图（业务语义层）
    - 项目特有的意图标签（intent_labels）
    - 不同场景下用户的典型表达方式
  2. 多轮交互层（next_turn 的项目特有部分）：
    - 用户看到 live 回复后，会怎么追问（项目特有的追问模式）
    - 多轮的终止条件（用户什么时候满意/放弃）
    - 每轮输入如何承接上一轮的 live_feedback

  scenarios() 只是一个枚举，不足以覆盖这些。真正必须实现的应该是：

  - build_user_intent(scenario) -> IntentSpec：给定场景，产出该场景下用户的意图规格（query、expected_intent、用户画像等）
  - next_user_turn(case, previous_turns, live_feedback) -> TurnSpec：根据 live 回复，产出用户的下一轮输入

  这两个扩展点才是"扮演用户"的核心——前者定义"用户想要什么"，后者定义"用户如何根据回复继续追问"。

  修正后的 Live/Mock 必须实现扩展点

  ┌──────┬─────────────────────────────────────────────────┬─────────────────────────────┐
  │ 角色 │                 必须实现扩展点                  │            定位             │
  ├──────┼─────────────────────────────────────────────────┼─────────────────────────────┤
  │ Live │ deliver_real(request)                           │ 调用业务系统拿 raw_response │
  ├──────┼─────────────────────────────────────────────────┼─────────────────────────────┤
  │ Mock │ build_user_intent(scenario)                     │ 扮演用户产意图              │
  ├──────┼─────────────────────────────────────────────────┼─────────────────────────────┤
  │ Mock │ next_user_turn(case, prev_turns, live_feedback) │ 扮演用户追问                │
  └──────┴─────────────────────────────────────────────────┴─────────────────────────────┘

  build_request、scenarios、deliver_provided 等降为可选扩展点（有默认实现）。

  这样上限更高：Mock 能表达多轮追问的项目特有逻辑，而不是靠 LLM 按 scenario 名字猜；Live 能表达项目特有的调用方式，而不是被一个多余的 build_request 框住。




-----------

要有一个函数，他的输入是live schema的REQUEST_SCHEMA，输出是live schema的EXTRACT_OUTPUT_SCHEMA，所以场景都通过它拿live的结果。我理解应该是要有的

def execute_live(
  normalized_request: REQUEST_SCHEMA
) -> EXTRACT_OUTPUT_SCHEMA:
  """执行 live 调用。
  
  输入：normalized_request，类型 = live_schema.REQUEST_SCHEMA
  输出：extracted_output，类型 = live_schema.EXTRACT_OUTPUT_SCHEMA
  
  屏蔽业务系统调用细节和响应提取细节，单轮和多轮统一入口。
  """
  ...
  return extracted_output