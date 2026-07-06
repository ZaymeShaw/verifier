from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.projects.client_search import live_schema as client_search_live_schema


def test_live_schema_descriptor_optional_and_nullable_semantics():
    check = LiveSchemaCheck(
        request_shape={},
        output_shape={
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
