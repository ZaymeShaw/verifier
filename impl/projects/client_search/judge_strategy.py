"""client_search Draft-only single-pass Judge execution（方案 i）。

对齐 spec/alg/authority.md §8：Production/Draft Judge 保持单次 agentic LLM
调用，`authority.resolve` 作为 Judge Tool 参与同一会话；不再有两阶段
planning→assessment 冻结计划。
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from impl.core.schema import JudgeResult, RunTrace
from impl.projects.client_search import judge_execution

if TYPE_CHECKING:
    from impl.projects.client_search.judge import ClientSearchJudge


class DraftSinglePassJudgeExecution:
    """Run one agentic Judge session with authority.resolve available as a Tool."""

    def run(
        self,
        judge: "ClientSearchJudge",
        trace: RunTrace,
        user_intent: Optional[str],
    ) -> JudgeResult:
        context = judge.build_context(trace)
        context = {
            **(context or {}),
            "intent_frame": judge.build_intent_frame(trace, context),
        }
        # 供 Draft Loop 落盘 judge runtime 快照（authority_tool audit /
        # snapshot sha），与 attribute 的 last_context 观察语义对齐。
        judge._last_draft_context = context
        judge._last_judge_context = context
        return judge_execution.judge_trace(
            spec=judge.spec,
            trace=trace,
            user_intent=user_intent,
            project_judge_context=context,
        )
