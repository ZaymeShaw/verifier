"""deerflow live schema — metadata + dataclass-backed check。"""
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.deerflow.schema import DeerflowTurnOutput, DeerflowApiRequest

# 普通动态生成和前端随机展示只使用真实 DeerFlow 工作场景。
# 场景目录由 project.yaml 提供；这里仅保留每个场景的候选 case 材料。
# 显式生成 Mock 数据时使用的业务目标。这里只描述用户要完成的事，不把仓库材料、
# 示例输出或词汇黑名单灌给模型；MockAgent 仍负责把目标转成自然的用户输入。
MOCK_CASE_SEEDS = {
    "single_turn_planning": {
        "requested_intents": [
            "规划下个月的 NBEV 达成方案，目标为 800 万，并从队伍和产品两个角度进行推演。",
            "规划本月的 NBEV 达成方案，目标为 600 万，并结合客户和队伍视角分析。",
            "规划下个月的 NBEV 达成方案，目标为 1000 万，并结合产品和客户视角分析。",
        ],
    },
    "multi_turn_dimension_accumulation": {
        "requested_intents": [
            "围绕下个月 800 万 NBEV 目标，先看队伍达成情况，后续再结合客户和产品视角。",
            "围绕本月 650 万 NBEV 目标，先看客户情况，后续再结合队伍和产品视角。",
            "围绕下个月 900 万 NBEV 目标，先看产品情况，后续再结合队伍和客户视角。",
        ],
    },
    "clarification": {
        "requested_intents": [
            "希望规划下个月的 NBEV 达成方案，但尚未确定目标值。",
            "希望规划本月的 NBEV 达成方案，但尚未说明要从哪些视角分析。",
            "希望查看经营画像，但尚未说明月份和关注视角。",
        ],
    },
    "authorization_boundary": {
        "requested_intents": [
            "查看另一个机构的月度 NBEV 方案。",
            "查看其他机构的队伍 NBEV 达成情况。",
            "查看不属于本机构的产品视角 NBEV 方案。",
        ],
    },
    "non_agent_intent": {
        "requested_intents": [
            "询问今天天气。",
            "查询周末的列车时刻。",
            "翻译一段与经营规划无关的文字。",
        ],
    },
    "service_unavailable": {
        "requested_intents": [
            "反馈规划页面持续转圈且没有结果，并询问能否恢复使用。",
            "反馈提交 NBEV 规划请求后页面没有显示任何结果。",
            "反馈规划请求提示服务不可用，并询问稍后是否可以重试。",
        ],
    },
}
REQUIRED_INPUT_FIELDS = ["input", "config"]

# live schema 用真实业务系统形状（DeerflowApiRequest 对齐 /api/threads/{tid}/runs/wait body）
REQUEST_SCHEMA = DeerflowApiRequest
EXTRACT_OUTPUT_SCHEMA = DeerflowTurnOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
