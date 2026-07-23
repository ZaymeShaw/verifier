# marketting-planning-intent live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from .schema import MPIIntentApiRequest, MPIIntentExtractOutput

REQUIRED_INPUT_FIELDS = ["session_id", "trace_id", "org_id", "user_text", "extra_input_params"]

REQUEST_SCHEMA = MPIIntentApiRequest
EXTRACT_OUTPUT_SCHEMA = MPIIntentExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
