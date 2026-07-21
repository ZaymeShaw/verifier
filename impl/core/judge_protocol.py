"""Judge 协议层和扩展点基类

四层文件关系：
- judge_protocol.py: 协议层（_JudgeProtocol，主流程实现）+ 操作层（ProjectJudge，扩展点）
- judge.py: 通用层（工具函数：judge_trace, _build_judge_output_spec 等）
- projects/<project>/judge.py: 项目层（实现扩展点）
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from typing import final as typing_final
from impl.core.schema import RunTrace, JudgeResult, ProjectSpec, normalize_judge_result
from impl.core.protocol_base import check_forbidden_overrides
from impl.core.judge import judge_trace as core_judge_trace

logger = logging.getLogger(__name__)

_TERMINAL_JUDGE_FAILURE_EVIDENCE = frozenset({
    "llm_call_failed",
    "llm_output_validation_failed",
})


def _is_terminal_judge_failure(result: JudgeResult) -> bool:
    evidence = {
        str(item)
        for item in (result.evidence or [])
        if isinstance(item, str)
    }
    return bool(evidence & _TERMINAL_JUDGE_FAILURE_EVIDENCE)


class _JudgeProtocol(ABC):
    """
    协议层：Judge 判定主流程的具体实现。

    主流程（judge_trace 模板方法）：
    1. 预判（扩展点 pre_judge，可返回缓存结果）
    2. 构建上下文（扩展点 build_context）
    3. 构建意图框架（扩展点 build_intent_frame）
    4. 调用 LLM 判定（内部方法 _run_llm_judge，调用通用层）
    5. 协调结果（扩展点 reconcile_result）

    需要工具时从通用层取，需要项目定制时调用扩展点。
    项目不能修改流程的执行顺序。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'judge_trace',
        '_run_llm_judge',
        '_validate_judge_output',
    })

    def __init_subclass__(cls, **kwargs):
        """检查子类是否覆盖了禁止的方法"""
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def judge_trace(self, trace: RunTrace, user_intent: Optional[str] = None) -> JudgeResult:
        """
        模板方法：Judge 判定主流程的具体实现。

        流程：
        1. 预判（扩展点，可返回缓存结果）
        2. 构建上下文（扩展点）
        3. 构建意图框架（扩展点）
        4. 调用 LLM 判定（内部方法，调用通用层）
        5. 协调结果（扩展点）
        """
        # 1. 预判（扩展点，可返回缓存）
        pre_judge_result = self.pre_judge(trace, user_intent=user_intent)
        if pre_judge_result is not None:
            normalized_pre = self.normalize_result(trace, pre_judge_result)
            reconciled_pre = self.reconcile_result(trace, normalized_pre)
            from impl.core.judge import finalize_judge_result
            return finalize_judge_result(reconciled_pre)

        # 2. 构建上下文（扩展点）
        context = self.build_context(trace)
        from impl.core.judge import build_judge_evidence_view
        context = {**(context or {}), "judge_evidence": build_judge_evidence_view(trace)}
        context = {**(context or {}), "intent_frame": self.build_intent_frame(trace, context)}

        # 3. 调用 LLM 判定（内部方法，调用通用层）
        try:
            raw_result = self._run_llm_judge(trace, context, user_intent)
        except ValueError as e:
            logger.error(f"[judge_trace] LLM 产出不合规，阻断: {e}")
            raw_result = JudgeResult(
                trace_id=trace.trace_id,
                project_id=trace.project_id,
                overall_fulfillment={"status": "not_evaluable"},
                reasoning_summary=str(e)[:500],
                evidence=["llm_output_validation_failed"],
            )

        # 4. 归一化 + 协调结果（扩展点）。LLM 执行/输出失败是公共终态，
        # 项目 reconcile 不得为失败结果补造 assessments 或升级为 fulfilled。
        normalized = self.normalize_result(trace, raw_result)
        from impl.core.judge import finalize_judge_result
        if _is_terminal_judge_failure(normalized):
            return finalize_judge_result(normalized)
        final_result = self.reconcile_result(trace, normalized)
        return finalize_judge_result(final_result)

    def _run_llm_judge(self, trace: RunTrace, context: Dict[str, Any],
                       user_intent: Optional[str]) -> JudgeResult:
        """内部方法：调用 LLM 判定。委托给通用层 judge.trace() 函数。"""
        from impl.core import judge as judge_module

        return judge_module.judge_trace(
            spec=self.spec,
            trace=trace,
            user_intent=user_intent,
            project_judge_context=context
        )

    def _validate_judge_output(self, result: JudgeResult) -> JudgeResult:
        """内部方法：校验 LLM 输出格式。通用层 judge_trace 已含校验，这里用于额外自定义校验。"""
        return result

    # === 扩展点：项目可选覆盖 ===

    def pre_judge(self, trace: RunTrace, user_intent: Optional[str] = None) -> Optional[JudgeResult]:
        """扩展点：预判。项目可选实现，返回缓存结果绕过 LLM 调用。默认返回 None。"""
        return None

    @abstractmethod
    def build_context(self, trace: RunTrace) -> Dict[str, Any]:
        """扩展点：构建 Judge 上下文。项目必须实现。

        定位/目标：
            构建 judge LLM 的上下文，含 user_intent、intent_frame、
            system_prompt_extras、user_prompt_extras 等项目特有字段。
            产出的 context 会被 judge_trace 模板方法的 _run_llm_judge 传给通用层
            judge_trace 函数，驱动 LLM 判定。

        参数：
            trace: RunTrace，含 normalized_request/extracted_output/reference_contract 等，
                   由 live_run 产出，提供判定所需的业务上下文。
        """
        pass

    def build_intent_frame(self, trace: RunTrace, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """扩展点：构建意图框架。项目可选覆盖。

        Args:
            trace: RunTrace
            context: 已构建的 judge 上下文（避免重复调用 build_context）
        """
        context = context if context is not None else self.build_context(trace)
        request_candidates = []
        for source_name in ("normalized_request", "input"):
            source_value = getattr(trace, source_name, None) or {}
            if isinstance(source_value, dict):
                for key in ("query", "user_intent", "question", "input"):
                    value = source_value.get(key)
                    if value:
                        request_candidates.append({"source": f"{source_name}.{key}", "value": value})
            elif source_value:
                request_candidates.append({"source": source_name, "value": source_value})

        return {
            "project_id": self.spec.project_id,
            "downstream_consumer": context.get("project_type") or self.spec.project_id,
            "request_candidates": request_candidates,
            "boundary_hints": context.get("application_boundary") or {},
            "output_semantics": "current trace output should let the user or downstream system continue the project task",
        }

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        """扩展点：协调结果。项目可选覆盖，默认直接返回。"""
        return result

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        """扩展点：后处理结果。项目可选覆盖。

        默认实现：用 normalize_judge_result 函数兜底，保证 JudgeResult 字段完整。
        与协议模板方法的归一化逻辑一致。
        """
        return normalize_judge_result(result) or result


class ProjectJudge(_JudgeProtocol):
    """
    操作层：告诉项目哪些地方可以定制。

    必须实现：
    - build_context: 构建 Judge 上下文

    可选覆盖：
    - pre_judge / build_intent_frame / reconcile_result / normalize_result
    """

    def __init__(self, spec: ProjectSpec):
        """初始化 ProjectJudge。"""
        self.spec = spec
        # 集成 live_schema：协议层统一加载和使用
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)
