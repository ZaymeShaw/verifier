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
from impl.core.schema import MockContinueDecision, MockIntentOutput, ProjectSpec, SingleTurnCase, MultiTurnCase
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
    - build_user_intent: 扮演用户产出三层结构（必须实现）
    - intent_labels: 返回意图标签（可选覆盖）
    - normalize_case: 归一化 Case（可选覆盖）

    build_user_intent 三层结构（背景 → 意图 → 表达）：
        user_context: Dict[str, Any]  —— 用户背景/画像/使用系统的目标
        user_intent: str              —— 用户基于背景产生的具体意图
        query: str                    —— 用户基于意图说出口的原话

        三者关系：user_context 决定 user_intent，user_intent 表达为 query。
        下游 build_live_request 的 step2 LLM 同时拿到三层，不再需要从原话反推意图。

    case 承载约定（协议层不变，项目层必须遵守）：
        - case.input 必须保持 REQUEST_SCHEMA 形状纯净，不混入 user_context 或 user_intent
          等描述性字段；input 只装真实业务系统 API 会接受的字段。
        - case.user_intent（str）承载用户意图，由 build_case_from_spec 写入。
        - case.metadata["user_context"] 承载用户背景，由 build_case_from_spec 写入；
          多轮项目 build_next_request 从 metadata 读取，不污染 input。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'generate_mock_case',
        '_build_mock_spec',
        '_apply_mock_strategy',
        '_build_case_from_spec',
        '_validate_case',
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
    def build_user_intent(self, scenario: str) -> MockIntentOutput:
        """扩展点：扮演用户产意图。项目必须实现。

        定位/目标：
            给定场景，扮演真实用户产出三层结构（背景 → 意图 → 表达）。
            "扮演用户"= 同时定义"用户是谁、想干什么、怎么说"。
            单轮和多轮项目都需要实现。

        返回 MockIntentOutput（schema 层定义的结构化对象）：
            - user_intent: str —— 用户核心目标一句话（抽象意图，不是原话）。
            - query: str —— 用户基于意图说出口的原话（口语化，不含系统术语）。
            - user_context: Dict[str, Any] —— 用户背景/画像/使用业务系统的目标。
              缺省为空 dict；下游 build_live_request 把它喂给 step2 LLM 帮助理解用户，
              多轮项目 build_next_request 也基于它生成符合用户画像的追问。

        协议层约定（项目层不得违反）：
            - user_intent / query 必须非空（LLM 失败由 mock_agent 降级产空 result，
              项目层不负责处理 LLM 失败）。
            - 项目层不直接构造 case.input 的业务字段；input 形状由 build_live_request
              按 REQUEST_SCHEMA 产出，build_user_intent 只产意图层。
            - 项目实现通常转调 MockAgent.build_intent，直接返回它的产出。

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
    - build_user_intent: 扮演用户产出三层结构 {user_intent, query, user_context?}。
      详见 _MockProtocol.build_user_intent 协议约定。
      项目实现通常转调 MockAgent.build_intent，直接返回它的产出。

    可选覆盖：
    - scenarios: 返回场景列表（默认从 live_schema.SCENARIO_ENUM 取）
    - intent_labels: 返回意图标签（默认从 live_schema.INTENT_LABELS 取）
    - normalize_case: 归一化 Case（可补充项目特有字段）

    多轮交互：通过继承 MultiTurnInteractiveMock mixin 声明并实现 build_next_request。
      build_next_request(case, intent, accumulated_output) 协议层会先算好 intent 传入，
      项目层直接基于 intent 和 accumulated_output 构造 request，不自己调 build_user_intent。
    单轮：通过继承 SingleTurnMock mixin 实现 build_live_request，协议层同样先算好 intent 传入。

    case 承载约定（build_case_from_spec 已遵守，项目层不得覆盖）：
    - case.input 保持 REQUEST_SCHEMA 形状纯净，不混入 user_context。
    - case.user_intent 承载用户意图字符串。
    - case.metadata["user_context"] 承载用户背景 dict。
    """

    def build_initial_request(
        self,
        intent: MockIntentOutput,
    ) -> Dict[str, Any]:
        """默认实现：委托 MockAgent 把意图翻译成 REQUEST_SCHEMA 形状。

        spec 行 40：build_live_request 签名 (intent: MockIntentOutput) → REQUEST_SCHEMA。
        case 参数已删除（trace.md 第十一节 6：case 不进 live 层，协议层也不传 case 给 mock）。
        单轮项目通常不覆盖。多轮项目通过 MultiTurnInteractiveMock 覆盖 build_next_request。

        仅用于 Intent 正向生成首轮 Request；execute_live 不调用此方法。
        """
        from impl.core.mock_agent import MockAgent, build_spec_from_project, build_initial_request_from_intent
        agent = MockAgent(self.spec)
        scenario = str(getattr(intent, "scenario", "") or "")
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return build_initial_request_from_intent(agent, build_spec, intent).input

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


class SingleTurnMock(ABC):
    """单轮交互模式 mixin。项目 Mock 通过组合继承声明单轮形态。

    使用方式：
        class XxxMock(SingleTurnMock, ProjectMock): ...

    单轮 Mock 必须实现 build_live_request(case, intent)（@abstractmethod），
    把协议层算好的意图翻译成单轮 request（REQUEST_SCHEMA 形状）。
    项目层实现直接调用 MockAgent 工具函数即可。
    Pipeline 通过 isinstance(mock, MultiTurnInteractiveMock) 判断是否支持多轮；
    不继承 MultiTurnInteractiveMock 即视为单轮。
    """

    @abstractmethod
    def build_initial_request(
        self,
        intent: MockIntentOutput,
    ) -> Dict[str, Any]:
        """扩展点：产单轮 request。单轮项目必须实现。

        定位/目标：
            把协议层算好的意图（intent: MockIntentOutput）翻译成单轮 request。
            返回形状符合 live_schema.REQUEST_SCHEMA。
            spec 行 40：build_live_request 签名 (intent: MockIntentOutput) → REQUEST_SCHEMA。
            case 参数已删除（trace.md 第十一节 6：case 不进 live 层）。
            协议层会先调 build_user_intent 得到 intent，再调 build_live_request，
            项目层无需再调 build_user_intent。

        参数：
            intent: 协议层算好的意图层产出（user_intent / query / user_context / scenario）。
        """
        pass


class MultiTurnInteractiveMock(ABC):
    """多轮交互模式 mixin。声明 Mock 支持 build_next_request + 多轮控制。

    使用方式：
        class XxxMock(MultiTurnInteractiveMock, ProjectMock): ...

    多轮 Mock 必须实现：
    - infer_user_intent(initial_request) -> MockIntentOutput
    - decide_next_action(intent, accumulated_output) -> MockContinueDecision
    - build_next_request(intent, accumulated_output) -> Dict
    - safety_max_turns() -> int

    多轮控制（max_turns/should_stop）是 mock 扮演用户的能力，由项目扩展层实现，
    不放在 case 里。live 协议层 execute_live 的多轮分支通过 mock 拿控制信息。

    build_user_intent 仍由 ProjectMock 提供（场景级意图，单轮/多轮通用）。
    协议层会在调用 build_next_request 前先调 build_user_intent 算好 intent，
    作为入参传给 build_next_request，项目层无需再调 build_user_intent。
    """

    @abstractmethod
    def infer_user_intent(self, initial_request: Dict[str, Any]) -> MockIntentOutput:
        """从符合项目 REQUEST_SCHEMA 的首轮 Request 反推有限用户模型。"""
        pass

    @abstractmethod
    def decide_next_action(
        self,
        intent: MockIntentOutput,
        accumulated_output: Dict[str, Any],
    ) -> MockContinueDecision:
        """轻量判断模拟用户是否继续。"""
        pass

    @abstractmethod
    def build_next_request(
        self,
        intent: MockIntentOutput,
        accumulated_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """扩展点：产多轮每轮 request。多轮项目必须实现。

        定位/目标（spec/adapter/multiturn.md 第四节）：
            把 intent + 标准化 accumulated_output 翻译成下一轮 request。
            返回形状符合 live_schema.REQUEST_SCHEMA。
            项目层直接基于 intent 和 accumulated_output 构造 request，不自己调 build_user_intent。

        参数：
            intent: 当前用户模型。
            accumulated_output: 仅含各轮 live_request/extract_output/status/error 和控制字段。
        """
        pass

    @abstractmethod
    def safety_max_turns(self) -> int:
        """扩展点：多轮主循环最大轮数。多轮项目必须实现。

        定位/目标：
            项目扩展层定义多轮交互的最大轮数。
            live 协议层 execute_live 多轮分支通过此方法拿最大轮数，不读 case.interaction.policy。
        """
        pass
