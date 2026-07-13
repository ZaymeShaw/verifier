"""Mock 协议层和扩展点基类

三层文件关系：
- mock_protocol.py: 协议层（_MockProtocol）+ 扩展点基类（ProjectMock）
- mock.py: 通用函数（build_mock_spec, generate_mock_case 等）
- projects/<project>/mock.py: 项目实现（XxxMock(ProjectMock)）
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from typing import final as typing_final
from impl.core.schema import ProjectSpec, SingleTurnCase, MultiTurnCase
from impl.core.protocol_base import check_forbidden_overrides


class _MockProtocol(ABC):
    """
    协议层：定义 Mock 生成流程骨架，项目不能覆盖。

    模板方法：
    - generate_mock_case: 完整的 Mock 生成流程（@final，不可覆盖）

    内部方法：
    - _build_mock_spec: 构建 Mock 规格（内部方法，不可覆盖）
    - _apply_mock_strategy: 应用 Mock 策略（内部方法，不可覆盖）
    - _build_case_from_spec: 从规格构建 Case（内部方法，不可覆盖）

    扩展点（通过 ProjectMock 实现）：
    - scenarios: 返回场景列表（必须实现）
    - intent_labels: 返回意图标签（可选覆盖）
    - normalize_case: 归一化 Case（可选覆盖）
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'generate_mock_case',
        '_build_mock_spec',
        '_apply_mock_strategy',
        '_build_case_from_spec',
        '_validate_case'
    })

    def __init_subclass__(cls, **kwargs):
        """检查子类是否覆盖了禁止的方法"""
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def generate_mock_case(
        self,
        scenario: Optional[str] = None,
        intent: Optional[str] = None,
        **kwargs
    ) -> SingleTurnCase | MultiTurnCase:
        """
        模板方法：完整的 Mock 生成流程。

        流程：
        1. 调用 scenarios() 获取场景列表（扩展点）
        2. 调用 _build_mock_spec() 构建 Mock 规格（通用逻辑）
        3. 调用 _apply_mock_strategy() 应用策略（通用逻辑）
        4. 调用 _build_case_from_spec() 构建 Case（通用逻辑）
        5. 调用 _validate_case() 校验 Case（通用逻辑，使用 live_schema）
        6. 调用 normalize_case() 后处理（扩展点）
        7. 返回最终 Case
        """
        # 1. 获取场景列表（项目实现）
        all_scenarios = self.scenarios()
        target_scenario = scenario or (all_scenarios[0] if all_scenarios else "default")

        # 2. 构建 Mock 规格（通用逻辑）
        mock_spec = self._build_mock_spec(target_scenario, intent, **kwargs)

        # 3. 应用策略（通用逻辑）
        case_data = self._apply_mock_strategy(mock_spec)

        # 4. 构建 Case（通用逻辑）
        case = self._build_case_from_spec(case_data)

        # 5. 校验 Case（通用逻辑，使用 live_schema）
        case = self._validate_case(case)

        # 6. 后处理（项目实现）
        final_case = self.normalize_case(case)

        return final_case

    def _validate_case(self, case: SingleTurnCase | MultiTurnCase) -> SingleTurnCase | MultiTurnCase:
        """
        内部方法：使用 live_schema 校验生成的 Case。

        校验 input 是否符合 REQUEST_SCHEMA、output/reference 是否符合 EXTRACT_OUTPUT_SCHEMA。
        失败不阻断，记 metadata.schema_ok=False 供下游判断。
        """
        if self.live_schema is None or not hasattr(self.live_schema, "check"):
            return case
        try:
            case_dict = {
                "id": str(getattr(case, "id", "") or ""),
                "input": dict(getattr(case, "input", {}) or {}),
                "output": getattr(case, "output", None),
                "reference": getattr(case, "reference", None),
                "scenario": str(getattr(case, "scenario", "") or ""),
            }
            schema_errors = self.live_schema.check.case_errors(case_dict)
            if not isinstance(case.metadata, dict):
                case.metadata = {}
            case.metadata["schema_ok"] = not schema_errors
            if schema_errors:
                case.metadata["schema_errors"] = schema_errors
        except Exception as exc:
            if not isinstance(case.metadata, dict):
                case.metadata = {}
            case.metadata["schema_ok"] = False
            case.metadata["schema_check_error"] = str(exc)
        return case

    def _build_mock_spec(
        self,
        scenario: str,
        intent: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        内部方法：构建 Mock 规格。

        使用通用逻辑构建标准的 Mock 规格。
        """
        from impl.core import mock as mock_module

        return mock_module.build_mock_spec(
            spec=self.spec,
            scenario=scenario,
            intent=intent,
            intent_labels=self.intent_labels(),
            **kwargs
        )

    def _apply_mock_strategy(self, mock_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        内部方法：应用 Mock 策略。

        使用通用逻辑应用 Mock 生成策略。
        """
        from impl.core import mock as mock_module

        return mock_module.apply_mock_strategy(
            spec=self.spec,
            mock_spec=mock_spec
        )

    def _build_case_from_spec(self, case_data: Dict[str, Any]) -> SingleTurnCase | MultiTurnCase:
        """
        内部方法：从规格构建 Case。

        使用通用逻辑构建标准的 Case 对象。
        """
        from impl.core import mock as mock_module

        return mock_module.build_case_from_spec(
            spec=self.spec,
            case_data=case_data
        )

    def scenarios(self) -> List[str]:
        """扩展点：返回场景列表。项目可选覆盖。

        定位/目标：
            返回该项目支持的所有 mock 场景名称列表。
            场景名需与 live_schema.SCENARIO_ENUM 对齐，用于 mock_agent 按场景生成用例。

        参数：
            无。
        """
        if self.live_schema is not None and hasattr(self.live_schema, 'SCENARIO_ENUM'):
            return list(self.live_schema.SCENARIO_ENUM or [])
        return []

    @abstractmethod
    def build_user_intent(self, scenario: str) -> Dict[str, Any]:
        """扩展点：扮演用户产意图。项目必须实现。

        定位/目标：
            给定场景，产出该场景下用户的意图规格（query、expected_intent、用户画像等）。
            这是 Mock 的核心动作——"扮演用户"就是定义用户想要什么。
            单轮和多轮项目都需要实现。

        参数：
            scenario: 场景名（来自 scenarios() 返回值）。
        """
        pass

    def intent_labels(self) -> List[str]:
        """扩展点：返回意图标签。项目可选覆盖。

        定位/目标：
            返回该项目支持的所有意图标签列表。
            意图标签用于 mock_agent 在 build_intent 阶段生成符合项目业务语义的用户意图。

        参数：
            无。
        """
        if self.live_schema is not None and hasattr(self.live_schema, 'INTENT_LABELS'):
            return list(self.live_schema.INTENT_LABELS or [])
        return []

    def next_turn(
        self,
        case: SingleTurnCase | MultiTurnCase,
        previous_turns: List[Dict[str, Any]],
        live_feedback: Dict[str, Any]
    ) -> Dict[str, Any]:
        """扩展点：扮演用户追问。项目可选覆盖，仅多轮项目需要。

        定位/目标：
            根据当前 case、历史对话和 live 系统的反馈，生成用户的下一轮输入。
            多轮交互项目才需要覆盖；单轮项目用默认返回"结束"信号。

        参数：
            case: 当前 case（含 input/scenario 等）
            previous_turns: 历史对话轮次列表，每轮含 {"role": "user"|"assistant", "content": str}
            live_feedback: live 系统的反馈（含 extracted_output/application_boundary 等）
        """
        return {"action": "end", "reason": "single_turn_project_no_next_turn"}

    def normalize_case(
        self,
        case: SingleTurnCase | MultiTurnCase
    ) -> SingleTurnCase | MultiTurnCase:
        """
        扩展点：归一化 Case。

        项目可选覆盖，用于：
        - 补充项目特有的字段
        - 转换 Case 格式
        - 添加额外的元数据
        """
        return case


class ProjectMock(_MockProtocol):
    """
    扩展点基类：项目继承这个类，实现 Mock 扩展点。

    必须实现：
    - build_user_intent: 扮演用户产意图

    可选覆盖：
    - scenarios: 返回场景列表（默认从 live_schema.SCENARIO_ENUM 取）
    - intent_labels: 返回意图标签（默认从 live_schema.INTENT_LABELS 取）
    - next_turn: 扮演用户追问（仅多轮项目覆盖，默认返回"结束"信号）
    - normalize_case: 归一化 Case
    """

    def __init__(self, spec: ProjectSpec):
        """
        初始化 ProjectMock。

        Args:
            spec: 项目规格（ProjectSpec）
        """
        self.spec = spec
        # 集成 live_schema：协议层统一加载和使用
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)
