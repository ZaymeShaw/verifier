from __future__ import annotations

from impl.core.project_loader import load_project
from impl.core.schema import JudgeResult, RunTrace
from impl.projects.client_search.judge import ClientSearchJudge
from impl.projects.client_search.judge_strategy import (
    DraftSinglePassJudgeExecution,
)


def test_promoted_judge_selects_single_pass_strategy() -> None:
    spec = load_project("client_search")

    assert isinstance(
        ClientSearchJudge(spec).judge_execution(),
        DraftSinglePassJudgeExecution,
    )


def test_draft_strategy_executes_one_judge_call_without_planning(monkeypatch) -> None:
    """方案 i：Draft 单次 agentic 会话，不再有 planning→assessment 两阶段。"""
    from impl.projects.client_search import judge_execution as je_module
    from impl.projects.client_search.judge import ClientSearchJudge
    from impl.projects.client_search.judge_strategy import (
        DraftSinglePassJudgeExecution,
    )

    judge = ClientSearchJudge(load_project("client_search"))
    calls = []

    def fake_build_context(trace):
        return {
            "user_intent": "查找30岁以上的客户",
            "intent_frame": {"request_candidates": []},
            "tools": [],
        }

    def fake_judge_trace(**kwargs):
        calls.append(kwargs)
        return JudgeResult(
            trace_id=kwargs["trace"].trace_id,
            project_id=kwargs["trace"].project_id,
            overall_fulfillment={"status": "fulfilled"},
            reasoning_summary="Draft single-pass result",
        )

    monkeypatch.setattr(judge, "build_context", fake_build_context)
    monkeypatch.setattr(judge, "build_intent_frame", lambda trace, context: {"request_candidates": []})
    monkeypatch.setattr(je_module, "judge_trace", fake_judge_trace)

    result = DraftSinglePassJudgeExecution().run(
        judge,
        RunTrace(
            trace_id="draft-single-pass",
            project_id="client_search",
            input={"user_text": "查找30岁以上的客户"},
            normalized_request={"user_text": "查找30岁以上的客户"},
            extracted_output={
                "conditions": [{
                    "field": "clientAge",
                    "operator": "GTE",
                    "value": 30,
                }],
            },
        ),
        user_intent=None,
    )

    assert len(calls) == 1
    assert calls[0]["project_judge_context"]["intent_frame"] == {
        "request_candidates": []
    }
    assert "assessment_context_builder" not in calls[0]
    assert result.overall_fulfillment["status"] == "fulfilled"
