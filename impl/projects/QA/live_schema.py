# QA live schema: normalized_request/extract_output 形状约束 + mock_agent 构建参数
# adapter: impl/projects/QA/adapter.py build_request (lines 15-40) / extract_output (lines 60-63)
# 注意：QA 是 provided-output 模式，不调外部 live 服务。call_or_prepare 直接把 normalized_request.output 当 raw_response。

# mock_agent 构建约束
SCENARIO_ENUM = [
    "qa_gold_answer",
    "qa_context_faithfulness",
    "qa_weak_quality",
]
INTENT_LABELS: list[str] = []  # QA 没有意图标签
REQUIRED_INPUT_FIELDS = ["question"]

# normalized_request 形状（6 字段，嵌套结构）
REQUEST_SHAPE = {
    "input": "dict",                    # {question: str, contexts: list[str]}
    "reference": "dict?",                # {actual_answer: str} or {} — 可选，case 层有
    "metadata": "dict",
    "scenario": "string",               # qa_gold_answer/qa_context_faithfulness/qa_weak_quality/invalid_sample
    "data_quality_flags": "list[str]?",  # 可选
    "output": "dict?",                   # {actual_answer: str} — 可选，case 层有
}

# QA 标记：provided-output 模式，不调外部 live 服务
IS_PROVIDED_OUTPUT = True

# extract_output 形状（极简）
EXTRACT_OUTPUT_SHAPE = {
    "actual_answer": "string",
}
# ---- live_schema 校验器 ----
# 调用方：load_live_schema(pid).check.request(data) / .output(data) / .reference(data) / .case(case)
from impl.core.live_schema_check import LiveSchemaCheck
READY = ['output','reference']
check = LiveSchemaCheck(REQUEST_SHAPE, EXTRACT_OUTPUT_SHAPE, READY)
