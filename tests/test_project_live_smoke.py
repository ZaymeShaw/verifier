from __future__ import annotations

import importlib.util
from pathlib import Path

from impl.core.pipeline import live_run
from impl.core.schema import LiveExecutionResult, LiveRequest, MultiTurnInteraction, MultiTurnPolicy, ProjectSpec
from impl.core.live import _apply_interaction_state


_MP_LIVE_PATH = Path(__file__).resolve().parents[1] / "impl" / "projects" / "marketting-planning" / "live.py"
_MP_LIVE_SPEC = importlib.util.spec_from_file_location("test_marketting_planning_live", _MP_LIVE_PATH)
assert _MP_LIVE_SPEC is not None and _MP_LIVE_SPEC.loader is not None
mp_live = importlib.util.module_from_spec(_MP_LIVE_SPEC)
_MP_LIVE_SPEC.loader.exec_module(mp_live)


def _stages(trace) -> list[str]:
    return [getattr(event, "stage", "") for event in trace.execution_trace]


def test_qa_live_run_provided_smoke():
    trace = live_run("QA", {
        "input": {"question": "q", "contexts": []},
        "output": {"actual_answer": "a"},
        "reference": {"actual_answer": "a"},
    })

    assert trace.status == "ok"
    assert trace.execution_mode == "provided"
    assert trace.output_source == "provided_output"
    assert trace.extracted_output == {"actual_answer": "a"}
    assert "live_schema.validate_request" in _stages(trace)
    assert "live_schema.validate_output" in _stages(trace)


def _assert_live_smoke_trace(trace) -> None:
    assert trace.execution_mode == "live"
    assert trace.live_result.call_status in {"succeeded", "failed"}
    assert "live_schema.validate_request" in _stages(trace)
    if trace.live_result.call_status == "succeeded":
        assert trace.status == "ok"
        assert trace.output_source == "live_service"
        assert "live_schema.validate_output" in _stages(trace)
    else:
        assert trace.status == "error"
        assert trace.output_source == "live_service_unavailable"
        assert trace.live_result.call_error
        assert trace.fallbacks
        fallback = trace.fallbacks[0]
        assert fallback.source_stage == "live"
        assert fallback.fallback_type == "live_error"
        assert "live_service_unavailable" in fallback.quality_flags
        assert "live_schema.validate_output" not in _stages(trace)


def test_client_search_live_run_smoke():
    trace = live_run("client_search", {"user_text": "有生存金未领取的客户"})

    _assert_live_smoke_trace(trace)
    assert trace.normalized_request.get("user_text") == "有生存金未领取的客户"
    if trace.live_result.call_status == "succeeded":
        assert trace.extracted_output.get("query")
        assert isinstance(trace.extracted_output.get("conditions"), list)


def test_marketting_planning_intent_live_run_smoke():
    trace = live_run("marketting-planning-intent", {"query": "帮我识别营销意图", "reference": {"intent": "nbev_planning"}})

    _assert_live_smoke_trace(trace)
    if trace.live_result.call_status == "succeeded":
        assert "intent" in trace.extracted_output
        assert "confidence" in trace.extracted_output


def test_marketting_planning_intent_trace_uses_project_taxonomy():
    trace = live_run("marketting-planning-intent", {"query": "帮我识别营销意图", "reference": {"intent": "nbev_planning"}})

    stages = _stages(trace)
    assert "adapter_extraction" in stages
    assert "intent_output.extract" not in stages


def test_marketting_planning_shared_session_string_false_is_false():
    trace = live_run("marketting-planning", {
        "case_id": "shared-session-string-false",
        "query": "帮我做NBEV规划",
        "turns": [{"role": "user", "content": "帮我做NBEV规划"}],
        "shared_session": "false",
        "session_id": "declared-session",
    })

    assert trace.normalized_request.get("shared_session") is False
    assert trace.normalized_request.get("session_id") == "eval-shared-session-string-false"


def test_marketting_planning_live_run_smoke():
    trace = live_run("marketting-planning", {"query": "帮我做NBEV规划", "turns": [{"role": "user", "content": "帮我做NBEV规划"}]})

    _assert_live_smoke_trace(trace)
    assert trace.normalized_request.get("turns")
    if trace.live_result.call_status == "succeeded":
        assert isinstance(trace.extracted_output.get("turns"), list)
        assert len(trace.extracted_output["turns"]) == 1
        assert trace.extracted_output["turns"][0].get("input_turn") == trace.normalized_request["turns"][-1]
        assert "extra_output_params" not in trace.extracted_output["turns"][0]
        assert "event_summary" in trace.extracted_output["turns"][0]
        assert "card_summary" in trace.extracted_output["turns"][0]


def test_marketting_planning_raw_sse_replay_extracts_business_evidence():
    spec = ProjectSpec(project_id="marketting-planning", name="mp", root=".")
    request = LiveRequest(
        project_id="marketting-planning",
        case_id="mp-replay",
        session_id="eval-mp-replay",
        raw_input={},
        normalized_request={
            "case_id": "mp-replay",
            "session_id": "eval-mp-replay",
            "shared_session": False,
            "user_intent": "",
            "query": "帮我做NBEV规划",
            "turns": [{"role": "user", "content": "帮我做NBEV规划"}],
            "current_turn": {"role": "user", "content": "帮我做NBEV规划"},
            "scenario": "execution_planning",
            "expected_path_types": [],
            "expected_cards": [],
            "metadata": {},
            "boundary": {},
            "reference": {},
        },
        turns=[{"role": "user", "content": "帮我做NBEV规划"}],
    )
    card_payload = {
        "card_code": "TEAM_PROFILE_ANALYSIS",
        "card_name": "队伍分析",
        "card_data": {
            "target_value": 1200,
            "dimension": {"team": "A", "region": "华东"},
            "recommendations": ["提升活动率", "强化主管追踪"],
            "constraints": {"unit": "万元", "period": "Q3"},
            "basis": {"current_value": 900, "achievement_rate": 0.75},
        },
    }
    raw_response = {
        "_normalized_request": request.normalized_request,
        "events": [
            {"event": "card_start"},
            {"event": "card_delta", "data": {"code": 0, "msg": "ok", "data": {"robot_text": "已生成规划", "end_flag": 1, "extra_output_params": {"card_result": {"card_list": [card_payload]}}}}},
            {"event": "card_end", "data": {"code": 0, "msg": "ok", "data": {"robot_text": "已生成规划", "end_flag": 1, "extra_output_params": {"card_result": {"card_list": [card_payload]}}}}},
            {"event": "heartbeat"},
        ],
    }

    turn = mp_live.extract_output(raw_response, request, spec, 0)

    assert turn["event_summary"]["protocol_completed"] is True
    assert turn["event_summary"]["business_completed"] is True
    assert turn["event_summary"]["completed"] is True
    card = turn["card_summary"][0]
    assert card["path_type"] == "premium_growth"
    assert card["business_evidence"]["target_value"] == 1200
    assert card["business_evidence"]["dimension"]["team"] == "A"
    assert card["business_evidence"]["recommendations"] == ["提升活动率", "强化主管追踪"]
    assert card["business_evidence"]["constraints"]["unit"] == "万元"
    assert card["business_evidence"]["basis"]["current_value"] == 900


def test_marketting_planning_card_business_evidence_is_preserved():
    card = mp_live._card_summary({
        "card_code": "TEAM_PROFILE_ANALYSIS",
        "card_name": "队伍分析",
        "card_data": {
            "target_value": 1200,
            "dimension": {"team": "A", "region": "华东"},
            "recommendation": ["提升活动率"],
            "constraints": {"unit": "万元"},
        },
    })

    assert card["path_type"] == "premium_growth"
    assert card["business_evidence"]["target_value"] == 1200
    assert card["business_evidence"]["dimension"]["team"] == "A"
    assert card["business_evidence"]["recommendation"] == ["提升活动率"]
    assert card["business_evidence"]["constraints"]["unit"] == "万元"


def test_marketting_planning_card_fallback_marker_is_not_request_fallback():
    spec = ProjectSpec(project_id="marketting-planning", name="mp", root=".")
    request = LiveRequest(
        project_id="marketting-planning",
        case_id="mp-card-fallback",
        session_id="eval-mp-card-fallback",
        raw_input={},
        normalized_request={
            "case_id": "mp-card-fallback",
            "session_id": "eval-mp-card-fallback",
            "shared_session": False,
            "user_intent": "",
            "query": "帮我做NBEV规划",
            "turns": [{"role": "user", "content": "帮我做NBEV规划"}],
            "current_turn": {"role": "user", "content": "帮我做NBEV规划"},
            "scenario": "execution_planning",
            "expected_path_types": [],
            "expected_cards": [],
            "metadata": {},
            "boundary": {},
            "reference": {},
        },
        turns=[{"role": "user", "content": "帮我做NBEV规划"}],
    )
    raw_response = {
        "_normalized_request": request.normalized_request,
        "code": 0,
        "msg": "ok",
        "data": {
            "robot_text": "已生成规划",
            "end_flag": 1,
            "cards": [{"path_type": "premium_growth", "card_name": "局部兜底卡", "fallback": True}],
        },
    }

    turn = mp_live.extract_output(raw_response, request, spec, 0)
    boundary = mp_live.application_boundary(raw_response, {"turns": [turn]}, request, spec)

    assert turn["card_summary"][0]["fallback"] is True
    assert turn["fallback"]["used"] is False
    assert boundary["fallback_used"] is False


def test_marketting_planning_completion_requires_terminal_tail():
    spec = ProjectSpec(project_id="marketting-planning", name="mp", root=".")

    summary = mp_live._event_summary([{"event": "card_end"}, {"event": "error", "data": "late failure"}], spec, business_completed=True)

    assert summary["protocol_completed"] is False
    assert summary["business_completed"] is True
    assert summary["completed"] is False


def test_marketting_planning_completion_requires_business_evidence():
    spec = ProjectSpec(project_id="marketting-planning", name="mp", root=".")

    summary = mp_live._event_summary([{"event": "card_end"}, {"event": "heartbeat"}], spec)

    assert summary["protocol_completed"] is True
    assert summary["business_completed"] is False
    assert summary["completed"] is False


def test_marketting_planning_completion_allows_business_evidence_after_terminal():
    spec = ProjectSpec(project_id="marketting-planning", name="mp", root=".")

    summary = mp_live._event_summary([{"event": "card_end"}, {"event": "heartbeat"}], spec, business_completed=True)

    assert summary["protocol_completed"] is True
    assert summary["business_completed"] is True
    assert summary["completed"] is True


def test_multi_turn_state_accumulated_fields_uses_latest_declared_session_summary():
    result = LiveExecutionResult(
        project_id="demo",
        case_id="case-1",
        session_id="session-1",
        call_status="succeeded",
        extracted_output={
            "turns": [
                {
                    "stage": "clarification",
                    "session_summary": {"accumulated_fields": {"target_value": 1200}},
                },
                {
                    "stage": "planning",
                    "card_summary": [{"path_type": "premium_growth"}],
                    "session_summary": {"missing_fields": []},
                },
            ]
        },
    )
    request = LiveRequest(
        project_id="demo",
        case_id="case-1",
        session_id="session-1",
        raw_input={},
        normalized_request={"turns": [{"role": "user", "content": "目标1200"}, {"role": "user", "content": "规划"}]},
        turns=[{"role": "user", "content": "目标1200"}, {"role": "user", "content": "规划"}],
    )

    _apply_interaction_state(result, request, MultiTurnInteraction(policy=MultiTurnPolicy()))

    assert result.multi_turn_state is not None
    assert result.multi_turn_state.accumulated_fields == {"target_value": 1200}


def test_multi_turn_state_does_not_guess_accumulated_fields_from_cards():
    result = LiveExecutionResult(
        project_id="demo",
        case_id="case-1",
        session_id="session-1",
        call_status="succeeded",
        extracted_output={
            "turns": [{
                "stage": "planning",
                "card_summary": [{"path_type": "premium_growth", "business_evidence": {"target_value": 1200}}],
                "session_summary": {"missing_fields": []},
            }]
        },
    )
    request = LiveRequest(
        project_id="demo",
        case_id="case-1",
        session_id="session-1",
        raw_input={},
        normalized_request={"turns": [{"role": "user", "content": "规划"}]},
        turns=[{"role": "user", "content": "规划"}],
    )

    _apply_interaction_state(result, request, MultiTurnInteraction(policy=MultiTurnPolicy()))

    assert result.multi_turn_state is not None
    assert result.multi_turn_state.accumulated_fields == {}
