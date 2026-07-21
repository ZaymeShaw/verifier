# client_search live schema — metadata + dataclass-backed check
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.project_loader import load_project
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.client_search.capability_manifest import build_capability_manifest
from impl.projects.client_search.schema import ClientSearchExtractOutput, ClientSearchRequest

API_ENDPOINT = "/api/v1/client_search_query_parse_no_encipher"


def _source_field_definitions_path() -> str:
    return load_project("client_search").source_path("field_definitions")


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
INTENT_LABELS: list[str] = []
REQUIRED_INPUT_FIELDS = ["user_text"]
CAPABILITY_MANIFEST = build_capability_manifest(_source_field_definitions_path())
READY = []

REQUEST_SCHEMA = ClientSearchRequest
EXTRACT_OUTPUT_SCHEMA = ClientSearchExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
