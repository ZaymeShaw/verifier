from impl.core.schema import LiveExchange, MockIntentOutput, RunTrace
from impl.core.schema.fixture import available_fixtures
from impl.core.show_schema import ShowSchema, build_show_projection, load_show_schema, parse_path, select_path, validate_schema_paths


def test_show_schema_requires_non_empty_unique_string_paths():
    ShowSchema(input_fields=["input.messages[-1].content"], output_fields=["reply_text"])
    for kwargs in (
        {"input_fields": [], "output_fields": ["reply_text"]},
        {"input_fields": ["query", "query"], "output_fields": ["reply_text"]},
        {"input_fields": ["query"], "output_fields": ["bad[*]"]},
    ):
        try:
            ShowSchema(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid ShowSchema must fail")


def test_select_path_supports_nested_and_last_index():
    value = {"input": {"messages": [{"content": "A"}, {"content": "B"}]}}
    assert parse_path("input.messages[-1].content")[-1] == ("content", None)
    assert select_path(value, "input.messages[-1].content") == (True, "B")
    assert select_path(value, "input.messages[4].content") == (False, None)


def test_projection_keeps_mock_and_pairs_each_turn():
    trace = RunTrace(
        trace_id="t1",
        project_id="client_search",
        mock_intent=MockIntentOutput(user_intent="找客户", query="有子女的客户", user_context={"role": "顾问"}),
        turn_records=[{
            "turn_index": 1,
            "mock_message": "有子女的客户",
            "request": {"user_text": "有子女的客户"},
            "extracted_output": {"robot_text": "已找到", "conditions": [], "query_logic": "and", "confidence": 0.9},
            "call_status": "succeeded",
            "live_exchanges": [LiveExchange(
                exchange_id="x1", sequence=0, transport="http", method="POST",
                url="http://live.test/run", carries_live_request=True,
                contributes_raw_response=True, status_code=200,
                request={"user_text": "有子女的客户"}, response={"robot_text": "已找到"},
            )],
        }],
        final_output_turn=1,
    )
    projection = build_show_projection(trace)
    assert projection["mock"]["user_intent"] == "找客户"
    assert projection["turns"][0]["mock_message"] == "有子女的客户"
    assert projection["turns"][0]["output"][0]["value"] == "已找到"
    exchange = projection["turns"][0]["live_exchange_summary"][0]
    assert exchange == {
        "sequence": 0,
        "method": "POST",
        "url": "http://live.test/run",
        "status_code": 200,
        "carries_live_request": True,
        "contributes_raw_response": True,
        "error": None,
    }
    assert "request" not in exchange and "response" not in exchange


def test_all_current_projects_have_schema_valid_show_schema():
    for project_id in ("QA", "client_search", "deerflow", "marketting-planning", "marketting-planning-intent"):
        live = __import__(f"impl.projects.{project_id}.live_schema", fromlist=["live_schema"])
        show = load_show_schema(project_id)
        assert show is not None
        validate_schema_paths(show, live.REQUEST_JSON_SCHEMA, live.EXTRACT_OUTPUT_JSON_SCHEMA)


def test_core_fixture_has_registered_show_schema():
    available_fixtures()
    show = load_show_schema("fixture-project")
    assert show is not None
    assert show.input_fields == ["query"]
