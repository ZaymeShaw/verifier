from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from .interaction_protocol import ready_from_spec
from .llm_client import LlmClient, project_llm_client
from .schema import MockBuildResult, MockBuildSpec, ProjectSpec
from .structured_output import StructuredOutputSpec, FREE_TEXT_OUTPUT, FREE_DICT_OUTPUT
from dataclasses import dataclass, field


# mock_agent 是独立协议模块：扮演真实用户，只产用户侧产物（意图 + live 输入）。
# 两步串行流程（spec/mock.md 第四节）：
#   1. build_intent —— 生成意图侧语义字段（query/expected_intent/user_intent），与 live 形状无关
#   2. build_live_request —— 按 live_schema.REQUEST_SHAPE 直接产出真实 API 请求体形状
#       adapter 退化为纯协议层（endpoint/method/timeout/鉴权），不再做语义翻译。
# 纯 LLM 驱动：调 LlmClient.complete_json 让 LLM 扮演用户。LLM 失败时返回空 result（无规则 fallback）。
#
# ready 协议（spec/reference.md）：角色按域固化，mock_agent 只产用户侧产物。
#   - input 永远由 mock_agent 产出（live 请求体形状）
# spec/struct_output.md：所有 complete_json 调用必须传 output_spec。


# mock_agent 输出 dataclass（spec/struct_output.md）
@dataclass
class MockIntentOutput:
    query: str
    expected_intent: Optional[str] = None
    user_intent: Optional[str] = None
    turns: Optional[List[Dict[str, Any]]] = None


@dataclass
class MockNextTurnOutput:
    query: str
    turn_index: int = 0


_MOCK_INTENT_SPEC = StructuredOutputSpec.from_dataclass(
    MockIntentOutput,
    required_nonempty=["query"],
    description="mock_agent 意图生成",
)
_MOCK_NEXT_TURN_SPEC = StructuredOutputSpec.from_dataclass(
    MockNextTurnOutput,
    required_nonempty=["query"],
    description="mock_agent 下一轮生成",
)
# build_live_request 产出形状依赖运行时项目 REQUEST_SHAPE。
# 优先加载项目 schema 的 Request dataclass 做结构化约束；
# 如果项目没有 dataclass，退回到 FREE_DICT_OUTPUT（仅要求非空 dict）。
_MOCK_LIVE_REQUEST_SPEC = FREE_DICT_OUTPUT  # 旧默认，运行时按项目动态替换
#   - output 在 ready 中 → 由系统侧产出（真调 live 或系统扮演模块），调度层负责，mock_agent 不碰
#   - reference 在 ready 中 → 由 judge 评估侧产出（仅生成 expected 模式），调度层负责，mock_agent 不碰
#   - mock_agent 按 spec.common.ready 通用化，不硬编码项目 ID


class MockAgent:
    def __init__(self, spec: ProjectSpec, llm: Optional[LlmClient] = None):
        self.spec = spec
        self.llm = llm or project_llm_client(spec, role="mock_agent")

    # --- 顶层入口：两步串行 ---

    def build(self, build_spec: MockBuildSpec) -> MockBuildResult:
        intent_result = self.build_intent(build_spec)
        live_request = self.build_live_request(intent_result, build_spec)
        return live_request

    # --- 第一步：意图构建（用户语义层，与 live 形状无关）---

    def build_intent(self, spec: MockBuildSpec) -> MockBuildResult:
        trace_id = f"mock-agent-intent-{uuid.uuid4()}"
        system = self._intent_system_prompt(spec)
        user = json.dumps({
            "project_id": spec.project_id,
            "scenario": spec.scenario,
            "intent_labels": spec.intent_labels,
            "required_input_fields": spec.required_input_fields,
            "template": spec.template,
        }, ensure_ascii=False)
        data = self.llm.complete_json(system, user, trace_id=trace_id, reasoning_effort="low", output_spec=_MOCK_INTENT_SPEC)
        if data.get("error"):
            return self._empty_result(spec, reason=f"llm_error:{data.get('error')}")
        return self._map_intent_result(spec, data)

    # --- 第二步：按 live_schema.REQUEST_SHAPE 直接产出真实 API 请求体 ---

    def build_live_request(self, intent_result: MockBuildResult, build_spec: MockBuildSpec) -> MockBuildResult:
        """将意图映射为 live_schema.REQUEST_SHAPE 形状的请求体。
        adapter 收到后直接转发给真实 API，不再做语义翻译。"""
        live_schema = load_live_schema(build_spec.project_id)
        if live_schema is None:
            return intent_result

        live_shape = getattr(live_schema, "REQUEST_SHAPE", {})
        if not live_shape:
            return intent_result

        trace_id = f"mock-agent-live-{uuid.uuid4()}"
        system = self._live_request_system_prompt(live_shape, build_spec)
        user = json.dumps({
            "intent": {
                "query": intent_result.input.get("query"),
                "expected_intent": intent_result.expected_intent,
                "user_intent": intent_result.input.get("user_intent"),
            },
            "live_request_shape": live_shape,
            "scenario": build_spec.scenario,
        }, ensure_ascii=False)
        # spec/schema.md：优先用项目 Request dataclass 做结构化约束，让 LLM 产出符合
        # live_schema.REQUEST_SHAPE 的请求体；项目无 dataclass 时退回 FREE_DICT_OUTPUT。
        live_request_spec = self._build_live_request_spec(build_spec.project_id)
        data = self.llm.complete_json(system, user, trace_id=trace_id, reasoning_effort="low", output_spec=live_request_spec)
        if data.get("error"):
            return intent_result  # 失败时保留原意图，不覆盖 input
        return self._map_live_request_result(intent_result, build_spec, data)

    # --- 运行时逐轮：被项目 adapter.run_interactive 委托 ---

    def next_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]], live_feedback: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = f"mock-agent-next-turn-{uuid.uuid4()}"
        system = self._next_turn_system_prompt(case.get("scenario", ""))
        user = json.dumps({
            "case": {k: v for k, v in case.items() if k in ("input", "scenario", "expected_stage", "expected_path_types")},
            "previous_turns": previous_turns,
            "live_feedback": live_feedback,
        }, ensure_ascii=False)
        data = self.llm.complete_json(system, user, trace_id=trace_id, reasoning_effort="low", output_spec=_MOCK_NEXT_TURN_SPEC)
        if data.get("error"):
            return {"query": str(case.get("input", {}).get("query") or ""), "turn_index": len(previous_turns) + 1}
        query = str(data.get("query") or data.get("user_text") or "")
        return {"query": query, "turn_index": len(previous_turns) + 1}

    # --- prompt 构造 ---

    # 各项目的业务上下文（临时硬编码，长期应从 live_schema/application.md 自动提取）
    _BUSINESS_CONTEXT = {
        "client_search": (
            "系统业务：保险客户搜索，按客户画像、保单、险种等条件从保险数据库筛选客户。"
            "可搜索维度：客户姓名/年龄/性别、年缴保费、保单状态、险种大类（重疾险/年金险/两全险等）、"
            "VIP等级/客户价值、家庭关系（配偶/父母/子女）、生存金领取等。"
            "用户的 query 必须围绕保险客户筛选，禁止涉及电商商品、理财、保费计算等无关领域。"
        ),
        "marketting-planning": (
            "系统业务：营销规划智能体，多轮 SSE 流式输出，帮用户规划 NBEV 达成路径。"
            "支持路径：队伍增长、客户增长、产品组合。场景包括意图识别、字段澄清、规划执行、兜底、非agent意图、SSE协议。"
            "用户的 query 必须围绕保险营销/NBEV 规划，不要涉及电商或无关业务。"
        ),
        "marketting-planning-intent": (
            "系统业务：营销规划意图识别单轮接口，识别用户意图标签。"
            "意图包括：客户画像、NBEV规划、达成测算调整、队伍画像、目标值调整、兜底、其他。"
            "用户的 query 必须围绕保险营销意图，不要涉及电商或无关业务。"
        ),
        "QA": (
            "系统业务：QA 问答评估，评估已产出的问答答案质量。"
            "场景：金标准答案匹配、上下文忠实性、弱质量答案。"
            "用户的问题应围绕保险/产品咨询等典型 QA 场景。"
        ),
    }

    def _capability_context(self, project_id: str, scenario: str) -> str:
        """注入项目业务上下文，让 LLM 产出贴合系统目标的 query。"""
        ctx = self._BUSINESS_CONTEXT.get(project_id, "")
        if not ctx:
            return ""
        # client_search 补充 scenario 对应的字段示例
        if project_id == "client_search":
            ls = load_live_schema(project_id)
            cm = getattr(ls, "CAPABILITY_MANIFEST", None)
            if cm:
                fields = ", ".join(list(cm.keys())[:8])
                ctx += f"可参考字段：{fields}。"
        return ctx

    def _extract_output_shape(self, project_id: str) -> Dict[str, Any]:
        """从 live_schema 读 EXTRACT_OUTPUT_SHAPE，供 prompt 注入。"""
        return get_extract_output_shape(project_id)

    def _build_live_request_spec(self, project_id: str) -> StructuredOutputSpec:
        """按项目 Request dataclass 构造 build_live_request 的结构化输出约束。

        优先加载项目 schema 的 Request dataclass（如 ClientSearchRequest），
        没有则退回 FREE_DICT_OUTPUT。
        """
        try:
            req_cls = get_request_dataclass(project_id)
        except Exception:
            req_cls = None
        if req_cls is not None:
            return StructuredOutputSpec.from_dataclass(
                req_cls,
                description=f"mock_agent live 请求体（{project_id}）",
            )
        return FREE_DICT_OUTPUT

    def _intent_system_prompt(self, spec: MockBuildSpec) -> str:
        labels_hint = f"可用意图标签：{', '.join(spec.intent_labels)}。" if spec.intent_labels else "本项目无意图标签。"
        required_hint = f"input 必须包含字段：{', '.join(spec.required_input_fields)}。" if spec.required_input_fields else ""
        capability = self._capability_context(spec.project_id, spec.scenario)
        base = (
            "你扮演真实终端用户，针对给定业务场景，用自然语言表达你想做的事。"
            f"场景：{spec.scenario}。{labels_hint}{required_hint}"
            f"{capability}"
            "要求：query 必须是口语化的用户原话，不要出现系统术语或 JSON 字段名；"
            "query 必须贴合该系统的真实业务场景，不要涉及系统不支持的业务领域；"
            "如果有意图标签，选择一个最贴合的 expected_intent。"
        )
        # mock_agent 只产用户侧产物（意图 + live 输入）。output/reference 由系统侧/judge 侧产出，不在此处生成。
        fields = ['"query": str']
        if spec.intent_labels:
            fields.append('"expected_intent": str|null')
        base += f'输出 JSON，字段：{{{", ".join(fields)}}}。'
        return base

    def _live_request_system_prompt(self, live_shape: Dict[str, Any], build_spec: MockBuildSpec) -> str:
        """按 live_schema.REQUEST_SHAPE 构造真实 API 请求体的 prompt。"""
        capability = self._capability_context(build_spec.project_id, build_spec.scenario)
        return (
            "你将用户意图映射为真实 API 请求体。"
            f"请求体形状：{json.dumps(live_shape, ensure_ascii=False)}。"
            f"场景：{build_spec.scenario}。{capability}"
            "要求：按形状定义填充所有必填字段；user_text/query 用用户原话，贴合系统业务场景；"
            "session_id/trace_id/user_id 用合理默认值；不要编造输出内容。"
            "输出 JSON，包含完整的请求体字段。"
        )

    def _next_turn_system_prompt(self, scenario: str) -> str:
        return (
            "你扮演真实用户，根据上一轮系统的回复，生成下一轮要说的话。"
            f"场景：{scenario}。"
            "要求：query 必须基于上轮 live 反馈里缺失的字段或系统的澄清提示，自然地补充；不要重复已说内容。"
            '输出 JSON，字段：{"query": str}。'
        )

    # --- 结果映射 ---

    def _map_intent_result(self, spec: MockBuildSpec, data: Dict[str, Any]) -> MockBuildResult:
        query = str(data.get("query") or "").strip()
        input_data: Dict[str, Any] = {"query": query}
        if data.get("user_intent"):
            input_data["user_intent"] = data.get("user_intent")
        if isinstance(data.get("turns"), list) and data.get("turns"):
            input_data["turns"] = data.get("turns")
        for field in spec.required_input_fields:
            if field not in input_data:
                input_data[field] = query if field in ("query", "user_intent") else []

        # mock_agent 只产用户侧产物（意图 + live 输入）。output/reference 由调度层在 mock build 后从系统侧/judge 侧获取。
        case_id = f"mock-agent-{spec.project_id}-{uuid.uuid4().hex[:8]}"
        expected_intent = data.get("expected_intent")
        if expected_intent == "":
            expected_intent = None
        return MockBuildResult(
            case_id=case_id,
            input=input_data,
            output=None,
            reference=None,
            expected_intent=str(expected_intent) if expected_intent else None,
            scenario=spec.scenario,
            metadata={"source": "mock_agent_llm", "ready": list(ready_from_spec(self.spec)), "project_id": spec.project_id},
        )

    def _map_live_request_result(self, intent_result: MockBuildResult, build_spec: MockBuildSpec, data: Dict[str, Any]) -> MockBuildResult:
        """将 LLM 产出的 live 请求体写入 input，覆盖意图层 query。output/reference 由调度层填充。"""
        input_data = dict(data)
        for key in ("output", "reference", "expected_intent", "raw_model_response", "metrics"):
            input_data.pop(key, None)
        result = MockBuildResult(
            case_id=intent_result.case_id,
            input=input_data,
            output=None,  # 由调度层从系统侧获取
            reference=None,  # 由调度层从 judge 评估侧获取
            expected_intent=intent_result.expected_intent,
            scenario=intent_result.scenario,
            metadata={**intent_result.metadata, "live_request_mapped": True},
        )
        # 挂载校验：live_schema.check.request/input，失败记 quality_flag 不阻断
        self._attach_schema_check(result, build_spec)
        return result

    def _empty_result(self, spec: MockBuildSpec, reason: str) -> MockBuildResult:
        return MockBuildResult(
            case_id=f"mock-agent-empty-{spec.project_id}-{uuid.uuid4().hex[:8]}",
            input={field: "" for field in spec.required_input_fields},
            expected_intent=None,
            scenario=spec.scenario,
            metadata={"source": "mock_agent_llm", "error": reason},
        )

    def _attach_schema_check(self, result: MockBuildResult, build_spec: MockBuildSpec) -> None:
        """挂载 live_schema 校验：check.case() 完整校验（含 ready 协议下的 output/reference 存在性）。
        失败不阻断，记 metadata.schema_ok=False 供下游判断。"""
        try:
            live_schema = load_live_schema(build_spec.project_id)
            if live_schema is None or not hasattr(live_schema, "check"):
                return
            case = {
                "id": result.case_id,
                "input": result.input,
                "output": result.output,
                "reference": result.reference,
                "scenario": result.scenario,
            }
            result.metadata["schema_ok"] = live_schema.check.case(case)
        except Exception:
            pass


def load_live_schema(project_id: str) -> Optional[Any]:
    import importlib
    module_path = f"impl.projects.{project_id}.live_schema"
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError:
        return None


def load_project_schema(project_id: str) -> Optional[Any]:
    """加载项目级 schema 模块（impl/projects/<project>/schema/）。

    项目目录名可能含连字符（marketting-planning），不能用普通 import，
    用 spec_from_file_location 按路径加载。返回模块对象，None 表示无 schema。
    """
    import importlib.util
    import sys
    from pathlib import Path
    schema_path = Path(__file__).resolve().parents[1] / "projects" / project_id / "schema" / "__init__.py"
    if not schema_path.exists():
        return None
    module_name = f"impl_project_{project_id}_schema"
    module_spec = importlib.util.spec_from_file_location(module_name, schema_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    # 注册到 sys.modules，否则 dataclass 解析类型注解时会因 cls.__module__ 未注册而失败
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


def get_extract_output_dataclass(project_id: str) -> Optional[type]:
    """从项目 schema 模块读 EXTRACT_OUTPUT 的 dataclass 类型。

    约定：每个项目的 schema/__init__.py 暴露一个 ExtractOutput 命名的 dataclass，
    或项目特化命名的 dataclass（如 QAExtractOutput / ClientSearchExtractOutput）。
    """
    mod = load_project_schema(project_id)
    if mod is None:
        return None
    for attr in ("ExtractOutput", "QAExtractOutput", "ClientSearchExtractOutput",
                 "MPExtractOutput", "MPIIntentExtractOutput"):
        cls = getattr(mod, attr, None)
        if cls is not None:
            return cls
    return None


def get_request_dataclass(project_id: str) -> Optional[type]:
    """从项目 schema 模块读真实 API 请求体的 dataclass 类型。

    约定：每个项目的 schema/__init__.py 暴露一个 Request 命名的 dataclass
    （如 ClientSearchRequest / MPRequest / MPIIntentRequest / QARequest）。
    用于 mock_agent.build_live_request 的结构化输出约束，让 LLM 产出符合项目
    live_schema.REQUEST_SHAPE 的请求体，而非自由 dict。
    """
    mod = load_project_schema(project_id)
    if mod is None:
        return None
    for attr in ("ClientSearchRequest", "MPRequest", "MPIIntentRequest", "QARequest", "Request"):
        cls = getattr(mod, attr, None)
        if cls is not None:
            return cls
    return None


def get_extract_output_shape(project_id: str) -> Dict[str, Any]:
    """从 live_schema 读 EXTRACT_OUTPUT_SHAPE（旧 dict 形式，向后兼容）。

    spec/struct_output.md 后形状定义迁移到 schema/ 下的 dataclass，
    新代码应直接用 get_extract_output_dataclass + StructuredOutputSpec。
    """
    ls = load_live_schema(project_id)
    if ls is None:
        return {}
    return getattr(ls, "EXTRACT_OUTPUT_SHAPE", {}) or {}


def build_spec_from_project(spec: ProjectSpec, scenario: str = "") -> MockBuildSpec:
    live_schema = load_live_schema(spec.project_id)
    scenarios = getattr(live_schema, "SCENARIO_ENUM", []) if live_schema else []
    intent_labels = list(getattr(live_schema, "INTENT_LABELS", []) or []) if live_schema else []
    required = list(getattr(live_schema, "REQUIRED_INPUT_FIELDS", []) or ["query"]) if live_schema else ["query"]
    chosen_scenario = scenario or (scenarios[0] if scenarios else "")
    return MockBuildSpec(
        project_id=spec.project_id,
        scenario=chosen_scenario,
        intent_labels=intent_labels,
        required_input_fields=required,
        ready=list(ready_from_spec(spec)),
    )