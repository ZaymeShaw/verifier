"""deerflow live schema — metadata + dataclass-backed check。"""
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.deerflow.schema import DeerflowTurnOutput, DeerflowApiRequest

SCENARIO_ENUM = [
    "single_turn_planning",
    "multi_turn_dimension_accumulation",
    "clarification",
    "non_agent_intent",
    "service_unavailable",
]
INTENT_LABELS: list[str] = []
REQUIRED_INPUT_FIELDS = ["input", "config"]
READY: list[str] = []

# live schema 用真实业务系统形状（DeerflowApiRequest 对齐 /api/threads/{tid}/runs/wait body）
REQUEST_SCHEMA = DeerflowApiRequest
EXTRACT_OUTPUT_SCHEMA = DeerflowTurnOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
