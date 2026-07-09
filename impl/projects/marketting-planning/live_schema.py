# marketting-planning live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from .schema import MPExtractOutput, MPNormalizedRequest

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
REQUIRED_INPUT_FIELDS = ["query", "turns", "expected_stage", "expected_path_types"]
READY = []

REQUEST_SCHEMA = MPNormalizedRequest
EXTRACT_OUTPUT_SCHEMA = MPExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
