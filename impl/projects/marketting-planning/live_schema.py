# marketting-planning live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from .schema import MPTurnOutput, MPNormalizedRequest, MPApiRequest

REQUIRED_INPUT_FIELDS = ["user_text", "session_id", "trace_id", "org_id"]

# live schema 用真实业务系统形状（MPApiRequest 对齐 MarketingPlanningRequest）
REQUEST_SCHEMA = MPApiRequest
EXTRACT_OUTPUT_SCHEMA = MPTurnOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
