from __future__ import annotations

import dataclasses

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.mock_agent import load_live_schema
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.client_search import live_schema as client_search_live_schema


def test_live_schema_descriptor_optional_and_nullable_semantics():
    check = LiveSchemaCheck(
        {},
        {
            "required_text": "str",
            "optional_text": "str?",
            "nullable_required_text": "str|null",
        },
        ready=[],
    )

    assert not check.output({"nullable_required_text": None})
    assert not check.output({"required_text": "x"})
    assert check.output({"required_text": "x", "nullable_required_text": None})
    assert check.output({"required_text": "x", "nullable_required_text": "y"})
    assert check.output({"required_text": "x", "nullable_required_text": None, "optional_text": None})


def test_client_search_live_schema_required_nullable_fields_are_enforced():
    check = client_search_live_schema.check
    base = {
        "code": 0,
        "msg": "ok",
        "query": "找父母客户",
        "conditions": [],
        "robot_text": None,
        "query_logic": None,
        "rewritten_query": None,
    }

    assert check.output(base)

    for key in ("query", "conditions", "robot_text", "query_logic", "rewritten_query"):
        payload = dict(base)
        payload.pop(key)
        assert not check.output(payload), key
    nullable_payload = dict(base)
    nullable_payload["robot_text"] = None
    nullable_payload["query_logic"] = None
    nullable_payload["rewritten_query"] = None
    assert check.output(nullable_payload)


def test_project_live_schema_exports_dataclass_source_and_generated_json_schema():
    for project_id in ("QA", "client_search", "marketting-planning-intent", "marketting-planning"):
        live_schema = load_live_schema(project_id)
        request_schema = getattr(live_schema, "REQUEST_SCHEMA", None)
        output_schema = getattr(live_schema, "EXTRACT_OUTPUT_SCHEMA", None)

        assert dataclasses.is_dataclass(request_schema), project_id
        assert dataclasses.is_dataclass(output_schema), project_id
        assert not hasattr(live_schema, "REQUEST_SHAPE"), project_id
        assert not hasattr(live_schema, "EXTRACT_OUTPUT_SHAPE"), project_id
        assert not hasattr(live_schema, "RAW_RESPONSE_SHAPE"), project_id
        assert live_schema.REQUEST_JSON_SCHEMA == dataclass_to_json_schema(request_schema)
        assert live_schema.EXTRACT_OUTPUT_JSON_SCHEMA == dataclass_to_json_schema(output_schema)


def test_live_schema_loader_binds_ready_from_project_config_only():
    qa = load_live_schema("QA")
    base_case = {"input": {"question": "配置来源测试"}}

    assert "ready 含 output" in " | ".join(qa.check.case_errors(base_case))
    assert "ready 含 reference" in " | ".join(qa.check.case_errors(base_case))
    assert qa.check.case({
        **base_case,
        "output": {"actual_answer": "答案"},
        "reference": {"actual_answer": "参考答案"},
    })

    client_search = load_live_schema("client_search")
    assert client_search.check.case({"input": {"user_text": "查找客户"}})
    assert not client_search.check.case({
        "input": {"user_text": "查找客户"},
        "output": {
            "code": 0,
            "msg": "ok",
            "query": "查找客户",
            "conditions": [],
            "robot_text": None,
            "query_logic": None,
            "rewritten_query": None,
        },
    })

    banned_config_names = (
        "READY",
        "SCENARIO_ENUM",
        "INTENT_LABELS",
        "API_ENDPOINT",
        "API_INTENT_ENDPOINT",
        "IS_PROVIDED_OUTPUT",
    )
    for project_id in (
        "QA",
        "client_search",
        "deerflow",
        "marketting-planning",
        "marketting-planning-intent",
    ):
        live_schema = load_live_schema(project_id)
        assert not any(hasattr(live_schema, name) for name in banned_config_names), project_id


def test_marketting_planning_extract_output_schema_is_single_turn():
    live_schema = load_live_schema("marketting-planning")
    assert "turns" not in live_schema.EXTRACT_OUTPUT_JSON_SCHEMA.get("properties", {})
    assert live_schema.check.output({"code": 0, "msg": "ok"})
    assert not live_schema.check.output({"turns": [{"code": 0, "msg": "ok"}]})


def test_deerflow_extract_output_schema_is_single_turn():
    live_schema = load_live_schema("deerflow")
    assert "turns" not in live_schema.EXTRACT_OUTPUT_JSON_SCHEMA.get("properties", {})
    assert live_schema.check.output({})
    assert not live_schema.check.output({"turns": [{}]})
