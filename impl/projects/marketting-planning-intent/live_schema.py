# marketting-planning-intent live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from .schema import MPIIntentApiRequest, MPIIntentExtractOutput

API_ENDPOINT = "/api/v1/marketing-planning/intent-recognition"

SCENARIO_ENUM = [
    "intent_recognition",
    "non_agent_intent",
    "fallback_unknown",
]
INTENT_LABELS = [
    "other",
    "customer_portrait",
    "nbev_planning",
    "nbev_planning_fallback",
    "achievement_measurement_adjustment",
    "team_portrait",
    "target_value_adjustment",
]
REQUIRED_INPUT_FIELDS = ["session_id", "trace_id", "org_id", "user_text", "extra_input_params"]
READY = ["reference"]

REQUEST_SCHEMA = MPIIntentApiRequest
EXTRACT_OUTPUT_SCHEMA = MPIIntentExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
