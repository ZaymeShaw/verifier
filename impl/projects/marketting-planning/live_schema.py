# marketting-planning live schema — 权威契约（spec/live_schema.md）
#
# 真实 API：
#   POST http://127.0.0.1:9006/api/v1/marketing-planning/stream  (SSE)
#   POST http://127.0.0.1:9006/api/v1/marketing-planning/intent-recognition  (non-SSE)
# 原项目：/Users/xiaozijian/WorkSpace/package/marketing-planning/
# 真实 API 请求形状：app/schemas/request.py MarketingPlanningRequest
# 真实 API 响应形状：app/schemas/response.py MarketingPlanningStreamResponse
# adapter 翻译层：impl/projects/marketting-planning/adapter.py build_request (:67-109) + _live_request_body (:145-165)

API_ENDPOINT = "/api/v1/marketing-planning/stream"
API_INTENT_ENDPOINT = "/api/v1/marketing-planning/intent-recognition"

# ---- mock_agent 构建约束 ----
SCENARIO_ENUM = [
    "intent_recognition",
    "clarification",
    "multi_turn_field_accumulation",
    "execution_planning",
    "fallback_data_unavailable",
    "non_agent_intent",
    "streaming_protocol",
]
INTENT_LABELS: list[str] = []  # MP 没有意图标签枚举，但有 stage/path_types
REQUIRED_INPUT_FIELDS = ["query", "turns", "expected_stage", "expected_path_types"]

# ---- mock_agent 产出的 case.input 形状（adapter.build_request 消费）----
# mock_agent 不直接产 API 请求体，它产 case.input，adapter 再翻译成真实 API 请求。
# 这个形状是 "项目语义层" 输入，不是真实 API 形状。
CASE_INPUT_SHAPE = {
    "query": "string",                    # 当前轮自然语言查询
    "user_intent": "string",              # 用户意图文本
    "turns": "list[dict]",                # [{role, content}] 对话历史
    "scenario": "string",
    "expected_stage": "string",           # intent/clarification/planning/non_agent/fallback/unknown
    "expected_path_types": "list[str]",   # premium_growth/customer_growth/product_mix/activity/unknown
    "expected_cards": "list[str]",        # 预期的卡片类型
    "shared_session": "bool",             # 是否与上一轮共享 session
    "session_id": "string",
    "boundary": "dict",                   # {dependency_status, allow_fallback, excluded_evidence, notes}
    "reference": "dict",                  # 归一后契约
    "metadata": "dict",
}

# ---- 真实 API 请求形状（adapter._live_request_body 产出，发给真实 API 的 body）----
# 来自原项目 app/schemas/request.py MarketingPlanningRequest
REQUEST_SHAPE = {
    "session_id": "str",                  # 必填
    "trace_id": "str",                    # 必填
    "org_id": "str",                      # 必填，默认 "eval-org"
    "user_text": "str",                   # 用户输入，默认 query
    "extra_input_params": {               # 必填
        "agent_args": {
            "conversation_id": "str",     # = session_id
            "message": {
                "content": "str",         # = query
                "content_type": "str",    # 固定 "text"
            },
        },
        "args": {
            "extensions": "dict",         # 默认 {}
            "contexts": "list[dict]",     # 从 turns 翻译：[{role, query, answer}]
        },
    },
    # 以下为可选字段，adapter 不发送：
    # history, user_action, action_scenario, user_id, ts, token, app_scenario, docs_num, source, module_name, model_name, scenario
}

# ---- 真实 API 响应形状（原始 SSE JSON 帧）----
# 来自原项目 app/schemas/response.py MarketingPlanningStreamResponse
RAW_RESPONSE_SHAPE = {
    "code": "int",
    "msg": "str",
    "data": {
        "robot_text": "str",
        "end_flag": "int",               # 0=继续, 1=结束
        "extra_output_params": {
            "intent": "str",             # 意图编码
            "intent_name": "str",        # 意图中文名
            "card_result": {
                "event": "str",
                "sse_id": "str",
                "think": "str|null",
                "answer": "str|null",
                "card_list": "list[dict]",  # [{card_sort, card_code, card_name, card_data}]
                "extensions": "dict",
            },
        },
    },
}

# ---- 真实 API 响应形状（SSE 单帧）----
# 真实 API 返回 MarketingPlanningStreamResponse，每帧 JSON: {code, msg, data: {robot_text, end_flag, extra_output_params}}
# 仅描述 live 系统真实返回的字段，adapter 派生字段不在 schema 中。
EXTRACT_OUTPUT_SHAPE = {
    "code": "int",
    "msg": "str",
    "robot_text": "str",
    "end_flag": "int",
    "extra_output_params": "dict",
}

# ---- 多轮 turn_expectations 逐轮结构 ----
TURN_EXPECTATION_SHAPE = {
    "turn": "int",
    "stage": "str",
    "missing_fields": "list[str]",
    "required_path_types": "list[str]",
}
# ---- live_schema 校验器 ----
# 调用方：load_live_schema(pid).check.request(data) / .output(data) / .reference(data) / .case(case)
from impl.core.live_schema_check import LiveSchemaCheck
READY = []
check = LiveSchemaCheck(REQUEST_SHAPE, EXTRACT_OUTPUT_SHAPE, READY)
