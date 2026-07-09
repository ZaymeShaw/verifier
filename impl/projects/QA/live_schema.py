# QA live schema: metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.QA.schema import QAExtractOutput, QAInput

SCENARIO_ENUM = [
    "qa_gold_answer",
    "qa_context_faithfulness",
    "qa_weak_quality",
]
INTENT_LABELS: list[str] = []
REQUIRED_INPUT_FIELDS = ["question"]
IS_PROVIDED_OUTPUT = True
READY = ["output", "reference"]

REQUEST_SCHEMA = QAInput
EXTRACT_OUTPUT_SCHEMA = QAExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
