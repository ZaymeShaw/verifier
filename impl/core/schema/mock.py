from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class MockIntentOutput:
    """mock_agent 意图生成输出（build_intent 结构化约束）。

    四层结构（背景 → 系统认知 → 意图 → 表达）：
        user_context: 用户背景/画像/使用目标
        system_understanding: 用户对 project_id 对应业务系统的主观认知
        user_intent:  用户基于背景产生的具体意图
        query:        用户基于意图说出口的原话
        scenario:     场景名称（trace.md 第五节：build_user_intent 输出时填充）
    """
    user_intent: str
    query: str
    user_context: Dict[str, Any] = field(default_factory=dict)
    system_understanding: str = ""
    scenario: str = ""


@dataclass
class MockIntentFidelityOutput:
    """A fact-preserving edit of one generated user utterance."""
    query: str


@dataclass
class MockNextTurnOutput:
    """mock_agent 下一轮生成输出（next_turn 结构化约束）。"""
    query: str
    turn_index: int = 0


@dataclass
class MockInteractionTurn:
    """轻量 Mock 决策可见的一轮交互事实。"""
    turn_index: int
    live_request: Dict[str, Any]
    extract_output: Dict[str, Any]
    status: str
    error: Optional[str] = None


@dataclass
class MockContinueDecision:
    """模拟用户的极简继续/停止决定。"""
    action: Literal["continue", "stop"]
    stop_reason: Literal[
        "",
        "goal_satisfied",
        "user_abandons",
        "perceived_no_progress",
    ] = ""


@dataclass
class SingleTurnCase:
    # Mock 层：单轮测试输入，承载用户输入、参考输出和样本元数据。
    id: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    scenario: str = ""
    user_intent: str = ""
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
    intent_plan: Dict[str, Any] = field(default_factory=dict)
    interaction: MultiTurnInteraction = field(default_factory=MultiTurnInteraction)
    mock_agent: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockDataset:
    # Mock 层：一组可批量运行的 mock case 集合。
    dataset_id: str
    name: str
    dimension_type: str
    description: str = ""
    cases: List[MockCase] = field(default_factory=list)
    case_count: int = 0


@dataclass
class MockSpec:
    # Mock 层配置：声明支持的输入模式、样本来源和生成指导。
    input_modes: List[str] = field(default_factory=list)
    case_sources: List[str] = field(default_factory=list)
    intent_generation_guidance: str = ""
    user_intent_format: str = ""


@dataclass
class MockBuildSpec:
    # Mock 层：mock agent 构建单条 case 的约束（输入）。与 live API 形状无关，只承载项目语义层字段。
    project_id: str
    scenario: str
    requested_intent: str = ""                                      # 调用方给出的具体意图；若存在则是事实来源，不是候选标签
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
    user_intent: str = ""
    query: str = ""                                                   # 意图层用户原话（build_intent 产出后保留，build_live_request 不覆盖）
    user_context: Dict[str, Any] = field(default_factory=dict)
    scenario: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── MockCase 存储 schema（与运行时 SingleTurnCase 解耦） ──
# 三层分离：元数据 → 意图层 → API 请求层。
# 依赖链路：业务live系统+live协议层 → live schema → 项目扩展点+mock形状
# mock依赖链路：build_intent → build_request → live schema.REQUEST_SCHEMA
#
# 对比旧 SingleTurnCase：
#  旧格式：input 混了 REQUEST_SCHEMA 字段 + 冗余 scenario/metadata，
#          user_intent/query 可能覆盖可能丢失，格式因项目而异。
#  新格式：intent（MockIntentOutput）存用户原始语义（独立于 API 形状），
#          live_request 存纯 REQUEST_SCHEMA 形状（零冗余），
#          project_id 提到顶层。


@dataclass
class MockCase:
    """统一 mock case 存储 schema。

    三层分离：元数据 — 意图层 — API 请求层。
    intent 复用 MockIntentOutput（build_intent 的结构化产出）。
    live_request 对齐 live_schema.REQUEST_SCHEMA，零冗余。
    output/reference 由 ready 协议控制存在性。

    MockCase 只用于存储/传输（JSON 序列化），不流入 pipeline 运行时。
    协议层提供 _to_mock_case() / _from_mock_case() 做边界转换。
    """
    # ── 标识 ──
    id: str
    project_id: str
    scenario: str

    # ── API 请求层（build_request 产出，对齐 REQUEST_SCHEMA） ──
    live_request: Dict[str, Any]

    # ── 意图层（可选；可能尚未从 Request 反推） ──
    intent: Optional[MockIntentOutput] = None

    # ── ready 协议层 ──
    output: Optional[Dict[str, Any]] = None
    reference: Optional[Dict[str, Any]] = None
