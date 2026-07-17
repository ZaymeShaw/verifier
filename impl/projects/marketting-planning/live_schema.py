# marketting-planning live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from .schema import MPTurnOutput, MPNormalizedRequest, MPApiRequest

API_ENDPOINT = "/api/v1/marketing-planning/stream"
API_INTENT_ENDPOINT = "/api/v1/marketing-planning/intent-recognition"

SCENARIO_ENUM = [
    "intent_recognition",
    "clarification",
    "multi_turn_field_accumulation",
    "execution_planning",
    "fallback_data_unavailable",
    "non_agent_intent",
    "streaming_protocol",
]
INTENT_LABELS: list[str] = []
REQUIRED_INPUT_FIELDS = ["user_text", "session_id", "trace_id", "org_id"]
READY = []

# live schema 用真实业务系统形状（MPApiRequest 对齐 MarketingPlanningRequest）
REQUEST_SCHEMA = MPApiRequest
EXTRACT_OUTPUT_SCHEMA = MPTurnOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
