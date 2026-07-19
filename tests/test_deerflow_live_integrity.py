from impl.projects.deerflow.live import (
    _extract_reply_and_tool_calls,
    _infer_scenario,
    _stage_inference,
)


def _ai(content, tool_calls=None, caller=""):
    return {
        "metadata": {"caller": caller},
        "content": {
            "type": "ai",
            "content": content,
            "tool_calls": list(tool_calls or []),
        },
    }


def test_latest_reply_does_not_inherit_tool_calls_from_older_message():
    messages = [
        _ai("请补充预算", [{"name": "ask_clarification", "args": {"field": "budget"}}]),
        _ai("信息已经齐全，下面给出完整执行计划。", []),
    ]

    reply, tool_calls = _extract_reply_and_tool_calls(messages)

    assert reply == "信息已经齐全，下面给出完整执行计划。"
    assert tool_calls == []


def test_middleware_message_is_skipped_without_cross_message_merging():
    messages = [
        _ai("业务回复", []),
        _ai("自动标题", [{"name": "title", "args": {}}], caller="middleware:title"),
    ]

    assert _extract_reply_and_tool_calls(messages) == ("业务回复", [])


def test_structured_plan_with_optional_followup_is_planning_not_clarification():
    reply = """以下是营销执行计划：
1. 目标：提升线索转化率
2. 策略：分层触达
3. 执行阶段：第一周完成素材与人群准备
4. 指标：转化率与获客成本
需要我帮您生成更详细的执行文档或 PPT 吗？"""

    stage, rule = _stage_inference(reply, [], [])

    assert stage == "planning"
    assert rule == "structured_planning_reply"


def test_explicit_missing_information_request_is_clarification():
    stage, rule = _stage_inference("为了制定方案，请补充目标人群和预算信息。", [], [])

    assert stage == "clarification"
    assert rule == "explicit_missing_information_request"


def test_current_message_ask_clarification_has_highest_priority():
    stage, rule = _stage_inference(
        "我可以先给出计划框架。",
        [{"name": "ask_clarification", "args": {"field": "budget"}}],
        [],
    )

    assert stage == "clarification"
    assert rule == "current_message_ask_clarification"


def test_scenario_inference_does_not_treat_generic_need_as_clarification():
    scenario = _infer_scenario({"query": "我需要制定一份营销执行计划"}, [])

    assert scenario == "single_turn_planning"


def test_planning_phrase_inside_missing_information_request_is_clarification():
    stage, rule = _stage_inference("为了制定执行计划，请补充目标人群和预算信息。", [], [])

    assert stage == "clarification"
    assert rule == "explicit_missing_information_request"
