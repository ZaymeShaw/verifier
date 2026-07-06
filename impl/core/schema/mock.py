from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SingleTurnCase:
    # Mock 层：单轮测试输入，承载用户输入、预期意图、参考输出和样本元数据。
    id: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    scenario: str = ""
    expected_intent: str = ""
    reference: Optional[Dict[str, Any]] = None
    source: str = "user_written"
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiTurnTurnExpectation:
    # Mock 层：多轮交互中某一轮的业务期望。
    turn: int
    stage: str = ""
    missing_fields: List[str] = field(default_factory=list)
    required_path_types: List[str] = field(default_factory=list)


@dataclass
class MultiTurnPolicy:
    # Mock 层：多轮 case 的停止条件和最大轮次。
    max_turns: int = 5
    stop_when: List[str] = field(default_factory=list)


@dataclass
class MultiTurnInteraction:
    # Mock 层：多轮交互模式和每轮期望。
    mode: str = "interactive_intent"
    policy: MultiTurnPolicy = field(default_factory=MultiTurnPolicy)
    turn_expectations: List[MultiTurnTurnExpectation] = field(default_factory=list)


@dataclass
class MultiTurnCase(SingleTurnCase):
    # Mock 层：多轮 case = 原始意图 + 交互策略 + mock agent 配置。
    user_intent: Dict[str, Any] = field(default_factory=dict)
    interaction: MultiTurnInteraction = field(default_factory=MultiTurnInteraction)
    mock_agent: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockDataset:
    # Mock 层：一组可批量运行的 mock case 集合。
    dataset_id: str
    name: str
    dimension_type: str
    description: str = ""
    cases: List[SingleTurnCase | MultiTurnCase] = field(default_factory=list)
    case_count: int = 0


@dataclass
class MockSpec:
    # Mock 层配置：声明支持的输入模式、样本来源和生成指导。
    input_modes: List[str] = field(default_factory=list)
    case_sources: List[str] = field(default_factory=list)
    intent_generation_guidance: str = ""
    expected_intent_format: str = ""


@dataclass
class MockBuildSpec:
    # Mock 层：mock agent 构建单条 case 的约束（输入）。与 live API 形状无关，只承载项目语义层字段。
    project_id: str
    scenario: str
    intent_labels: List[str] = field(default_factory=list)            # 可用意图标签
    required_input_fields: List[str] = field(default_factory=list)    # input 必须包含的字段（query/turns 等）
    ready: List[str] = field(default_factory=list)                    # 已就绪字段（NOT mock agent 的产出），仅用于外部 ready 契约校验
    template: Optional[Dict[str, Any]] = None                         # seed 模板（可选，给 LLM 参考）
    live_context: Optional[Dict[str, Any]] = None                     # 上轮 live 输出（多轮场景）


@dataclass
class MockBuildResult:
    # Mock 层：mock agent 构建好的一条 case（输出）。只含 input 侧字段，ready 声明时才带 output/reference。
    case_id: str
    input: Dict[str, Any]                                             # query/turns/user_intent 等用户侧输入
    output: Optional[Dict[str, Any]] = None                          # 仅当 ready 含 output 时 mock_agent 产出
    reference: Optional[Dict[str, Any]] = None                       # 仅当 ready 含 reference 时 mock_agent 产出
    expected_intent: Optional[str] = None
    scenario: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
