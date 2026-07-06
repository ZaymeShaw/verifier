from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sys
from pathlib import Path

import pytest


def _load_registry_module():
    path = Path(__file__).with_name("api_check_registry.py")
    spec = importlib.util.spec_from_file_location("api_check_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


registry = _load_registry_module()


NONDETERMINISTIC_RESPONSE_KEYS = {"trace_id", "created_at"}
NONDETERMINISTIC_REPLAY_CASES = {"live_run", "run_chain", "judge", "attribute", "batch_run"}


PUBLIC_API_FORBIDDEN_KEYS = {
    "raw_model_output",
    "raw_response",
    "raw_sections",
    "raw_sse",
    "raw_cards",
    "downstream_payload",
    "project_fields",
    "runtime_logs",
    "conversation_transcript",
    "multi_turn_input",
}


def assert_public_api_is_slim(value):
    if isinstance(value, dict):
        leaked = PUBLIC_API_FORBIDDEN_KEYS.intersection(value)
        assert not leaked, f"public API leaked raw/debug/legacy fields: {sorted(leaked)}"
        for item in value.values():
            assert_public_api_is_slim(item)
    elif isinstance(value, list):
        for item in value:
            assert_public_api_is_slim(item)


def scrub_nondeterministic_values(value):
    if isinstance(value, dict):
        return {
            key: "<nondeterministic>" if key in NONDETERMINISTIC_RESPONSE_KEYS else scrub_nondeterministic_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_nondeterministic_values(item) for item in value]
    return value


def test_minimal_fixture_to_api_to_expected_schema():
    case = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "judge")
    request = case.request_for_project(registry.PROJECT_ID)
    response = case.call_api(request)

    assert_public_api_is_slim(response)
    result = registry.normalize_judge_result(response)
    assert result.trace_id == request["trace"]["trace_id"]


@pytest.mark.parametrize("case", registry.API_FIXTURE_CHECKS, ids=lambda item: item.name)
def test_fixture_goes_into_api_and_response_matches_schema(case):
    request = case.request_for_project(registry.PROJECT_ID)
    response = case.call_api(request)
    assert_public_api_is_slim(response)
    case.assert_response_schema(response)
    if os.environ.get("API_CHECK_VERBOSE"):
        print(json.dumps({
            "api": f"POST {case.path}",
            "project": registry.PROJECT_ID,
            "curl": registry.curl_command(case.path, request),
            "request_body": registry.to_dict(request),
            "response_body": registry.to_dict(response),
            "expected_schema": case.expected_schema,
            "schema_check": "pass",
        }, ensure_ascii=False, indent=2))


def test_report_curl_matches_recorded_request_body():
    report = registry.visible_api_report()
    for row in report:
        tokens = shlex.split(row["curl"])
        assert tokens[:3] == ["curl", "-sS", "-X"]
        assert tokens[3] == "POST"
        assert tokens[tokens.index("-H") + 1] == "Content-Type: application/json"
        assert tokens[tokens.index("--data-raw") + 1]
        curl_url = tokens[4]
        expected_url = f"{registry.API_BASE_URL}{row['api'].replace('POST ', '')}"
        assert curl_url == expected_url
        curl_body = json.loads(tokens[tokens.index("--data-raw") + 1])
        assert curl_body == row["request_body"]


def test_report_curl_replays_to_recorded_response():
    report = registry.visible_api_report()
    for row in report:
        status_code, response = registry.call_api_raw(row["api"].replace("POST ", ""), row["request_body"])
        assert status_code == row["http_status"]
        if row["case"] in NONDETERMINISTIC_REPLAY_CASES:
            assert row["schema_check"] == "pass"
            next(item for item in registry.API_FIXTURE_CHECKS if item.name == row["case"]).assert_response_schema(response)
        else:
            assert scrub_nondeterministic_values(response) == scrub_nondeterministic_values(row["response_body"])


def test_project_specific_requests_use_project_flow_outputs():
    project_id = registry.PROJECT_ID
    flow = registry.project_flow(project_id)
    assert next(item for item in registry.API_FIXTURE_CHECKS if item.name == "judge").request_for_project(project_id)["trace"] == flow["trace"]
    attribute_request = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "attribute").request_for_project(project_id)
    assert attribute_request["trace"] == flow["trace"]
    assert attribute_request["judge"] == flow["judge"]
    cluster_request = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "cluster").request_for_project(project_id)
    assert cluster_request["attributes"] == [flow["attribute"]]
    table_row_request = next(item for item in registry.API_FIXTURE_CHECKS if item.name == "table_row").request_for_project(project_id)
    assert table_row_request["trace"] == flow["trace"]
    assert table_row_request["judge"] == flow["judge"]
    assert table_row_request["attribute"] == flow["attribute"]
    assert table_row_request["check"] == flow["check"]
    assert table_row_request["frontend_view"] == flow["frontend_view"]
    assert "run" not in table_row_request


def test_api_project_cross_matrix():
    report = registry.visible_api_report()
    assert len(report) == sum(len(case.projects) for case in registry.API_FIXTURE_CHECKS)
    for row in report:
        assert row["curl"].startswith("curl -sS -X POST")
        assert row["project"]
        assert row["api"].startswith("POST /")
        assert isinstance(row["request_body"], dict)
        assert row["response_body"] is not None
        if row["http_status"] == 200:
            assert row["schema_check"] == "pass", row["schema_error"]
            assert_public_api_is_slim(row["response_body"])
        else:
            assert row["schema_check"] == "http_error"
            assert row["schema_error"]


def test_visible_api_report_contains_api_inputs_and_outputs():
    report = registry.visible_api_report()
    assert len(report) == sum(len(case.projects) for case in registry.API_FIXTURE_CHECKS)
    for item in report:
        assert item["api"].startswith("POST /")
        assert item["curl"].startswith("curl -sS -X POST")
        assert isinstance(item["request_body"], dict)
        assert item["response_body"] is not None
        assert item["expected_schema"]
        if item["http_status"] == 200:
            assert item["schema_check"] == "pass"
            assert_public_api_is_slim(item["response_body"])
        else:
            assert item["schema_check"] == "http_error"
            assert item["schema_error"]
