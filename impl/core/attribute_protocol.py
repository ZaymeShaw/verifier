"""Attribute 协议层和扩展点基类

四层文件关系：
- attribute_protocol.py: 协议层（_AttributeProtocol，主流程实现）+ 操作层（ProjectAttribute，扩展点）
- attribute.py: 通用层（工具函数：attribute_failure 等）
- projects/<project>/attribute.py: 项目层（实现扩展点）
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from typing import final as typing_final
from impl.core.schema import RunTrace, JudgeResult, AttributeResult, ProjectSpec
from impl.core.protocol_base import check_forbidden_overrides

logger = logging.getLogger(__name__)


class _AttributeProtocol(ABC):
    """
    协议层：Attribute 归因主流程的具体实现。

    主流程（attribute_failure 模板方法）：
    1. 构建上下文（扩展点 build_context）
    2. 运行探针（内部方法 _run_probes）
    3. 调用 LLM 归因（内部方法 _run_llm_attribute，调用通用层）
    4. 校验输出（内部方法 _validate_attribute_output）
    5. 后处理（扩展点 normalize_result）

    需要工具时从通用层取，需要项目定制时调用扩展点。
    项目不能修改流程的执行顺序。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'attribute_failure',
        '_run_llm_attribute',
        '_validate_attribute_output',
        '_run_probes',
    })

    def __init_subclass__(cls, **kwargs):
        """检查子类是否覆盖了禁止的方法"""
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def attribute_failure(
        self,
        trace: RunTrace,
        judge_result: JudgeResult
    ) -> AttributeResult:
        """
        模板方法：Attribute 归因主流程的具体实现。

        流程：
        1. 构建上下文（扩展点）
        2. 运行探针（内部方法）
        3. 调用 LLM 归因（内部方法，调用通用层）
        4. 校验输出（内部方法）
        5. 后处理（扩展点）
        """
        # 1. 构建上下文（扩展点）
        context = self.build_context(trace, judge_result)

        # 2. 运行探针（内部方法）
        probe_results = self._run_probes(trace, judge_result)
        context["probe_results"] = probe_results

        # 3. 调用 LLM 归因（内部方法，调用通用层）
        raw_result = self._run_llm_attribute(trace, judge_result, context)

        # 4. 校验输出（内部方法）
        validated_result = self._validate_attribute_output(raw_result)

        # 5. 后处理（扩展点）
        final_result = self.normalize_result(trace, judge_result, validated_result)

        return final_result

    def _run_probes(self, trace: RunTrace, judge_result: JudgeResult) -> List[Dict[str, Any]]:
        """内部方法：运行探针。探针失败不中断归因流程。"""
        probe_fn = self.probes()
        if not probe_fn:
            return []
        try:
            results = probe_fn(trace, judge_result)
            return results if isinstance(results, list) else []
        except Exception as e:
            return [{"probe_error": str(e), "probe_status": "failed"}]

    def _run_llm_attribute(
        self,
        trace: RunTrace,
        judge_result: JudgeResult,
        context: Dict[str, Any]
    ) -> AttributeResult:
        """内部方法：调用 LLM 归因。委托给通用层 attribute.failure() 函数。"""
        from impl.core import attribute as attribute_module

        return attribute_module.attribute_failure(
            spec=self.spec,
            trace=trace,
            judge=judge_result,
            project_attribute_context=context
        )

    def _validate_attribute_output(self, result: AttributeResult) -> AttributeResult:
        """内部方法：校验 LLM 输出格式。"""
        if result is None:
            raise ValueError("attribute 输出为 None")

        if not isinstance(result.suspected_locations, list):
            result.suspected_locations = []
        if not isinstance(result.evidence, list):
            result.evidence = []

        allowed_strengths = {"none", "weak", "medium", "strong"}
        if result.evidence_strength and result.evidence_strength not in allowed_strengths:
            result.evidence_strength = "weak"

        return result

    # === 扩展点：项目可选覆盖 ===

    @abstractmethod
    def build_context(
        self,
        trace: RunTrace,
        judge_result: JudgeResult
    ) -> Dict[str, Any]:
        """扩展点：构建 Attribute 上下文。项目必须实现。

        定位/目标：
            构建 attribute LLM 的上下文，含 tool_call_limit、system_prompt_override、
            user_prompt_extras、runtime_checks 等项目特有字段。
            产出的 context 会被 attribute_failure 模板方法的 _run_llm_attribute
            传给通用层 attribute_failure 函数，驱动 LLM 归因。

        参数：
            trace: RunTrace，含 normalized_request/extracted_output/execution_trace 等，
                   提供归因所需的业务执行上下文。
            judge_result: JudgeResult，判定结果，含 overall_fulfillment/fulfillment_assessments/
                          expected/actual 等，归因以此为输入定位失败原因。
        """
        pass

    def probes(self) -> Optional[Callable[[RunTrace, JudgeResult], List[Dict[str, Any]]]]:
        """扩展点：返回探针函数。项目可选覆盖，默认返回 None。"""
        return None

    def normalize_result(
        self,
        trace: RunTrace,
        judge_result: JudgeResult,
        result: AttributeResult
    ) -> AttributeResult:
        """扩展点：后处理结果。项目可选覆盖。"""
        return result


class ProjectAttribute(_AttributeProtocol):
    """
    操作层：告诉项目哪些地方可以定制。

    必须实现：
    - build_context: 构建 Attribute 上下文

    可选覆盖：
    - probes / normalize_result
    """

    def __init__(self, spec: ProjectSpec):
        """初始化 ProjectAttribute。"""
        self.spec = spec
        # 集成 live_schema：协议层统一加载和使用
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)
