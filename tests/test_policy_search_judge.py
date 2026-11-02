"""policy_search judge 的 intent frame：intent 只由 judge 自推断，user_goal 取首轮 query（v2 §3）。

回归锚点：`build_intent_frame` 曾悬空调用已删除的 `_intent_from_trace`，policy_search 全部 judge
直接 not_evaluable；固定为首轮 query 后补此覆盖。
"""
from __future__ import annotations

from impl.core.project_loader import load_project
from impl.core.schema import RunTrace
from impl.projects.policy_search.judge import PolicySearchJudge


def _judge() -> PolicySearchJudge:
    # 绕过 ProjectJudge.__init__ 的资源绑定，只测 frame 组装。
    judge = PolicySearchJudge.__new__(PolicySearchJudge)
    judge.spec = load_project("policy_search")
    return judge


def _request(query: str) -> dict:
    return {"extra_input_params": {"policySearchParseArgs": {"query": query}}}


def test_build_intent_frame_uses_first_turn_query_as_user_goal() -> None:
    trace = RunTrace(
        trace_id="t-single",
        project_id="policy_search",
        input=_request("查保额50万以上的保单"),
        normalized_request=_request("查保额50万以上的保单"),
        extracted_output={"status": "SUCCESS"},
    )

    frame = _judge().build_intent_frame(trace, {})

    assert frame["user_goal"] == "查保额50万以上的保单"
    assert frame["request_candidates"] == [
        {"source": "policySearchParseArgs.query", "value": "查保额50万以上的保单"}
    ]


def test_build_intent_frame_multi_turn_lists_every_turn_query() -> None:
    turns = [
        {"turn_index": 1, "request": _request("保额"), "extracted_output": {"status": "UNSUPPORTED"}},
        {"turn_index": 2, "request": _request("50万以上"), "extracted_output": {"status": "SUCCESS"}},
    ]
    trace = RunTrace(
        trace_id="t-multi",
        project_id="policy_search",
        input=_request("保额"),
        normalized_request=_request("保额"),
        extracted_output={"status": "SUCCESS"},
        turn_records=turns,
    )

    frame = _judge().build_intent_frame(trace, {})

    assert frame["user_goal"] == "保额"
    assert frame["request_candidates"] == [
        {"source": "turn_1.query", "value": "保额"},
        {"source": "turn_2.query", "value": "50万以上"},
    ]
