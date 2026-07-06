# client_search live schema — 权威契约（spec/live_schema.md）
#
# 真实 API：
#   POST http://localhost:8000/api/v1/client_search_query_parse_no_encipher
#   服务来自原项目：/Users/xiaozijian/WorkSpace/projects/claude_code/llm_client_search_0513/
# 请求体由 adapter.build_request (impl/projects/client_search/adapter.py:142-164) 产出，
# 响应体由 adapter.extract_output (:250-269) 解析。

API_ENDPOINT = "/api/v1/client_search_query_parse_no_encipher"

# ---- mock_agent 构建约束 ----
SCENARIO_ENUM = [
    "single_condition",
    "multi_condition_and",
    "product_category_or",
    "product_exclusion",
    "age_boundary",
    "premium_unit_conversion",
    "policy_status_filter",
    "unsupported_family_phrase",
]
INTENT_LABELS: list[str] = []  # client_search 是 query parse 服务，没有意图标签，有 query 就够了
REQUIRED_INPUT_FIELDS = ["query"]

# ---- 真实 API 请求形状（adapter.build_request 产出的 normalized_request）----
REQUEST_SHAPE = {
    "user_text": "string",           # 自然语言查询（必填，对应 case.input.query）
    "user_id": "string",             # 默认 "eval-user"
    "trace_id": "string",            # 默认 f"general-eval-{ms}"
    "session_id": "string",          # 默认 "general-eval-session"
    "source": "string",              # 默认 "askbob"
    "extra_input_params": "dict",    # 额外参数（默认空 dict）
}

# ---- 真实 API 响应形状（raw_response 的 data 字段）----
# 真实 API 返回：{code, msg, data: {robot_text, end_flag, trace_id, extra_output_params: {...}}}
# 仅描述 live 系统真实返回的字段，adapter 派生字段不在 schema 中。
RAW_RESPONSE_SHAPE = {
    "code": "int",
    "msg": "str",
    "data": {
        "robot_text": "str",
        "end_flag": "int",
        "trace_id": "str?",
        "extra_output_params": {
            "query": "str",
            "query_logic": "str|null",
            "conditions": "list",
            "matched_level": "int?",
            "matched_patterns": "str?",
            "rewritten_query": "str|null",
            "intent_summary": "str?",
            "confidence": "number?",
            "cost_times": "number?",
        },
    },
}

# ---- adapter 提取后的输出形状（adapter.extract_output 产出）----
# 仅保留 live 系统真实返回的字段经 adapter 扁平化后的形状。
EXTRACT_OUTPUT_SHAPE = {
    "code": "int",
    "msg": "str",
    "robot_text": "str|null",
    "end_flag": "int?",
    "trace_id": "str?",
    "query": "str",
    "query_logic": "str|null",
    "conditions": "list",
    "matched_level": "int?",
    "matched_patterns": "str?",
    "rewritten_query": "str|null",
    "intent_summary": "str?",
    "confidence": "number?",
    "cost_times": "number?",
}

# ---- 能力清单（来自原项目 field_definitions_args.yaml）----
# mock_agent 生成 query 时可参考这些业务字段；adapter 判定时也用它们做语义对齐。
# 完整清单由 adapter._capability_manifest() 在运行时从 source_field_definitions 加载，
# 这里只列代表性字段供 mock_agent 直觉参考。
CAPABILITY_MANIFEST = {
    "clientAge": {"operators": ["RANGE", "GTE", "LTE", "MATCH"], "value_type": "number"},
    "clientSex": {"operators": ["MATCH"], "value_type": "enum", "enums": ["男", "女"]},
    "annPremSegNum": {"operators": ["GTE", "LTE", "RANGE", "MATCH"], "value_type": "number"},
    "polNoInfo.payamountdue": {"operators": ["MATCH"], "value_type": "enum", "enums": ["是", "否"]},
    "pCategorys": {"operators": ["CONTAINS", "NOT_CONTAINS"], "value_type": "list"},
    "searchClientName": {"operators": ["MATCH"], "value_type": "extract"},
}

# ---- live_schema 校验器 ----
# 调用方：load_live_schema(pid).check.request(data) / .output(data) / .reference(data) / .case(case)
from impl.core.live_schema_check import LiveSchemaCheck
READY = []
check = LiveSchemaCheck(REQUEST_SHAPE, EXTRACT_OUTPUT_SHAPE, READY)
