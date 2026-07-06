# marketting-planning-intent live schema — 权威契约（spec/live_schema.md）
#
# 真实 API：
#   POST http://127.0.0.1:9006/api/v1/marketing-planning/intent-recognition  (non-SSE)
# 与 marketting-planning 共享业务服务，但测评边界只覆盖意图识别。
# 原项目：/Users/xiaozijian/WorkSpace/package/marketing-planning/
# 真实 API 请求形状：app/schemas/request.py MarketingPlanningRequest（与 marketting-planning 共用）
# 真实 API 意图识别响应：IntentResult（app/schemas/intent.py）+ MarketingPlanningStreamResponse（外层信封）
# adapter 翻译层：impl/projects/marketting-planning-intent/adapter.py build_request (:40-65) + _live_request_body (:100-113)

API_ENDPOINT = "/api/v1/marketing-planning/intent-recognition"

# ---- mock_agent 构建约束 ----
SCENARIO_ENUM = [
    "intent_recognition",
    "non_agent_intent",
    "fallback_unknown",
]
# 意图标签来自原项目 app/schemas/intent.py IntentType 枚举（7 个，已验证一致）
INTENT_LABELS = [
    "other",
    "customer_portrait",
    "nbev_planning",
    "nbev_planning_fallback",
    "achievement_measurement_adjustment",
    "team_portrait",
    "target_value_adjustment",
]
REQUIRED_INPUT_FIELDS = ["query"]

# ---- mock_agent 产出的 case.input 形状（adapter.build_request 消费）----
CASE_INPUT_SHAPE = {
    "query": "str",                   # 自然语言查询
    "scenario": "str",                # 默认 "intent_recognition"
    "expected_intent": "str",         # 期望意图标签（取值见 INTENT_LABELS）
    "reference": "dict",              # {intent, min_confidence?, required_slots?, allow_fallback?}
    "session_id": "str",
    "metadata": "dict",
}

# ---- 真实 API 请求形状（adapter._live_request_body 产出，发给真实 API 的 body）----
# 来自原项目 app/schemas/request.py MarketingPlanningRequest（与 marketting-planning 共用）
REQUEST_SHAPE = {
    "session_id": "str",              # 必填
    "trace_id": "str",                # 必填
    "org_id": "str",                  # 必填，默认 "eval-org"
    "user_text": "str",               # 用户输入 = query
    "extra_input_params": {           # 必填
        "agent_args": {
            "conversation_id": "str", # = session_id
            "message": {
                "content": "str",     # = query
                "content_type": "str",# 固定 "text"
            },
        },
        "args": {
            "extensions": "dict",     # 默认 {}
            "contexts": "list",       # 默认 []
        },
    },
}

# ---- 真实 API 响应形状（原始 JSON）----
# 外层信封 MarketingPlanningStreamResponse（end_flag=1 的单帧）
RAW_RESPONSE_SHAPE = {
    "code": "int",
    "msg": "str",
    "data": {
        "robot_text": "str",
        "end_flag": "int",             # 固定 1
        "extra_output_params": {
            "intent": "str",
            "intent_name": "str",
            "card_result": {
                "event": "str",
                "sse_id": "str",
                "think": "str|null",
                "answer": "str|null",
                "card_list": "list",
                "extensions": "dict",  # 含 nlu_info：{intent, confidence, target_value?, path_types?}
            },
        },
    },
}

# ---- 真实 API 响应形状（raw_response 的 data 字段）----
# 真实 API 返回 MarketingPlanningStreamResponse（end_flag=1 的单帧）
# extra_output_params.card_result.extensions.nlu_info 承载 IntentResult
RAW_RESPONSE_SHAPE = {
    "code": "int",
    "msg": "str",
    "data": {
        "robot_text": "str",
        "end_flag": "int",
        "extra_output_params": {
            "intent": "str",
            "intent_name": "str",
            "card_result": {
                "event": "str",
                "sse_id": "str",
                "think": "str?",
                "answer": "str?",
                "card_list": "list",
                "extensions": {
                    "trace_id": "str?",
                    "session_id": "str?",
                    "nlu_info": {
                        "intent": "str",
                        "confidence": "number",
                        "subIntent": "str?",
                        "target_value": "str?",
                        "path_types": "list?",
                    },
                },
            },
        },
    },
}

# ---- adapter 提取后的输出形状 ----
# 仅保留 live 系统真实返回的 IntentResult 字段，不含 adapter 派生字段。
EXTRACT_OUTPUT_SHAPE = {
    "intent": "str",                # IntentResult.intent
    "confidence": "number",         # IntentResult.confidence
    "target_value": "str?",         # IntentResult.target_value
    "path_types": "list?",          # IntentResult.path_types
    "subIntent": "str?",            # nlu_info.subIntent（IntentResult 未声明但 live 实际返回）
}
# ---- live_schema 校验器 ----
# 调用方：load_live_schema(pid).check.request(data) / .output(data) / .reference(data) / .case(case)
from impl.core.live_schema_check import LiveSchemaCheck
READY = ['reference']
check = LiveSchemaCheck(REQUEST_SHAPE, EXTRACT_OUTPUT_SHAPE, READY)
