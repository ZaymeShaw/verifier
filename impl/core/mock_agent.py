from __future__ import annotations

import dataclasses
import json
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .interaction_protocol import ready_from_spec
from .project_loader import load_project_document
from .schema import MockBuildResult, MockBuildSpec, MockContinueDecision, MockIntentOutput, MockNextTurnOutput, ProjectSpec
from .structured_output import StructuredOutputSpec, FREE_TEXT_OUTPUT, FREE_DICT_OUTPUT, dataclass_to_json_schema

if TYPE_CHECKING:
    from .llm_client import LlmClient


# mock_agent 是独立协议模块：扮演真实用户，只产用户侧产物（意图 + live 输入）。
# 两步串行流程（spec/mock.md 第四节）：
#   1. build_intent —— 生成意图侧语义字段（query/user_intent），与 live 形状无关
#   2. build_live_request —— 按 live_schema.REQUEST_SCHEMA dataclass 直接产出 live 请求体形状
#       adapter 退化为纯协议层（endpoint/method/timeout/鉴权），不再做语义翻译。
# 纯 LLM 驱动：调 LlmClient.complete_json 让 LLM 扮演用户。LLM 失败时返回空 result（无规则 fallback）。
#
# ready 协议（spec/reference.md）：角色按域固化，mock_agent 只产用户侧产物。
#   - input 永远由 mock_agent 产出（live 请求体形状）
# spec/struct_output.md：所有 complete_json 调用必须传 output_spec。


# mock_agent 输出 dataclass（spec/struct_output.md）—— 定义已迁至 impl/core/schema/mock.py
_MOCK_INTENT_SPEC = StructuredOutputSpec.from_dataclass(
    MockIntentOutput,
    required_nonempty=["query", "user_intent"],
    description="mock_agent 意图生成",
)
_MOCK_NEXT_TURN_SPEC = StructuredOutputSpec.from_dataclass(
    MockNextTurnOutput,
    required_nonempty=["query"],
    description="mock_agent 下一轮生成",
)
_MOCK_CONTINUE_DECISION_SPEC = StructuredOutputSpec.from_dataclass(
    MockContinueDecision,
    description="mock_agent 轻量继续判断",
)
# build_live_request 产出形状依赖运行时项目 REQUEST_SCHEMA dataclass。
# 优先加载项目 schema 的 Request dataclass 做结构化约束；
# 如果项目没有 dataclass，退回到 FREE_DICT_OUTPUT（仅要求非空 dict）。
_MOCK_LIVE_REQUEST_SPEC = FREE_DICT_OUTPUT  # 旧默认，运行时按项目动态替换
#   - output 在 ready 中 → 由系统侧产出（真调 live 或系统扮演模块），调度层负责，mock_agent 不碰
#   - reference 在 ready 中 → 由 judge 评估侧产出（仅生成 expected 模式），调度层负责，mock_agent 不碰
#   - mock_agent 按 spec.common.ready 通用化，不硬编码项目 ID


class MockAgent:
    def __init__(self, spec: ProjectSpec, llm: Optional[LlmClient] = None):
        self.spec = spec
        if llm is None:
            from .llm_client import project_llm_client
            self.llm = project_llm_client(spec, role="mock_agent")
        else:
            self.llm = llm
        self._mandatory_context_loaded = False
        self._mandatory_context_cache = None

    # --- 顶层入口：两步串行 ---

    def build(self, build_spec: MockBuildSpec) -> MockBuildResult:
        intent_result = self.build_intent(build_spec)
        live_request = self.build_initial_request(intent_result, build_spec)
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

    @staticmethod
    def intent_output(result: "MockBuildResult") -> MockIntentOutput:
        """从 MockBuildResult 提取意图层产出，供项目 build_user_intent 直接返回。"""
        from .schema import MockIntentOutput
        return MockIntentOutput(
            user_intent=result.user_intent,
            query=str(result.query or result.input.get("query") or ""),
            user_context=dict(result.user_context or {}),
            system_understanding=str(result.metadata.get("system_understanding") or ""),
            scenario=result.scenario,
        )


    # --- 第二步：按 live_schema.REQUEST_SCHEMA 直接产出 normalized_request ---

    def build_initial_request(self, intent_result: MockBuildResult, build_spec: MockBuildSpec) -> MockBuildResult:
        """将意图映射为 live_schema.REQUEST_SCHEMA dataclass 形状的请求体。

        LLM 产出后用 live_schema.check.request() 兜底校验。若不符（LLM 偶发字段漂移），
        重试一次；仍失败则返回 error result，schema_ok=False 供下游判断。
        """
        live_schema = load_live_schema(build_spec.project_id)
        request_schema = getattr(live_schema, "REQUEST_SCHEMA", None) if live_schema is not None else None
        if request_schema is None:
            return intent_result

        live_shape = dataclass_to_json_schema(request_schema)
        trace_id = f"mock-agent-live-{uuid.uuid4()}"
        system = self._live_request_system_prompt(live_shape, build_spec)
        user = json.dumps({
            "intent": {
                "user_intent": intent_result.user_intent,
                "user_context": intent_result.user_context,
                "query": intent_result.input.get("query"),
            },
            "live_request_json_schema": live_shape,
            "scenario": build_spec.scenario,
        }, ensure_ascii=False)
        live_request_spec = StructuredOutputSpec.from_dataclass(
            request_schema,
            description=f"{build_spec.project_id} live 请求体",
        )

        # 主调用 + 兜底校验重试
        for attempt in range(2):
            data = self.llm.complete_json(system, user, trace_id=trace_id, reasoning_effort="low", output_spec=live_request_spec)
            if data.get("error"):
                if attempt == 0:
                    continue  # 重试一次
                return self._mock_live_request_error(intent_result, build_spec, data.get("error"))

            # 兜底校验：LLM 产出的 dict 必须严格符合 REQUEST_SCHEMA
            # output/reference 是 mock 层字段（ready 协议），但部分项目的 REQUEST_SCHEMA 也包含
            # reference 字段（如 MPIIntentNormalizedRequest）。此时不应过滤掉 reference。
            # 过滤规则：只过滤确实不在 REQUEST_SCHEMA 字段中的 mock 层字段
            filter_keys = set()
            if request_schema is not None and dataclasses.is_dataclass(request_schema):
                allowed = {f.name for f in dataclasses.fields(request_schema)}
                filter_keys = {"output", "raw_model_response", "metrics"} - allowed
            else:
                filter_keys = {"output", "reference", "raw_model_response", "metrics"}
            input_data = {k: v for k, v in data.items() if k not in filter_keys}
            checker = getattr(live_schema, "check", None) if live_schema is not None else None
            if checker is not None and hasattr(checker, "request"):
                try:
                    if checker.request(input_data):
                        # 校验通过，接受这次产出
                        return self._map_live_request_result(intent_result, build_spec, data)
                    # 校验失败：第一次重试，第二次直接降级
                    if attempt == 0:
                        continue
                    # 第二次仍失败，记录详细错误并降级返回
                    return self._mock_live_request_error(
                        intent_result, build_spec,
                        f"LLM 产出不符合 REQUEST_SCHEMA after retry: {input_data}"
                    )
                except Exception as exc:
                    if attempt == 0:
                        continue
                    return self._mock_live_request_error(intent_result, build_spec, f"schema_check_exception: {exc}")
            else:
                # 无 checker，按原逻辑直接产出
                return self._map_live_request_result(intent_result, build_spec, data)

        # 重试用尽，返回错误
        return self._mock_live_request_error(intent_result, build_spec, "build_live_request: retries exhausted")

    def _mock_live_request_error(self, intent_result: MockBuildResult, build_spec: MockBuildSpec, error: Any) -> MockBuildResult:
        return MockBuildResult(
            case_id=intent_result.case_id,
            input={},
            output=intent_result.output,
            reference=intent_result.reference,
            user_intent=intent_result.user_intent,
            user_context=intent_result.user_context,
            scenario=build_spec.scenario or intent_result.scenario,
            metadata={
                **dict(intent_result.metadata or {}),
                "schema_ok": False,
                "mock_live_request_error": str(error),
            },
        )

    # --- 运行时逐轮：由协议层 execute_live 的多轮分支调用 ---

    def next_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]], live_feedback: Dict[str, Any]) -> Dict[str, Any]:
        """多轮后续轮：扮演用户产下一句 query。

        case 字典应含 input/scenario/metadata 三层信息：
        - case.metadata["user_context"]：用户背景/画像
        - case.input["query"] / case.scenario：当前轮基础信息
        - 意图层（user_intent）由项目层 build_next_request 单独传，next_turn 只看 user_context + live_feedback
        """
        trace_id = f"mock-agent-next-turn-{uuid.uuid4()}"
        system = self._next_turn_system_prompt(case.get("scenario", ""))
        # case 含 input / scenario / metadata / user_intent 字段（由项目层 build_next_request 组装）
        case_metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
        user_context = case_metadata.get("user_context") if isinstance(case_metadata.get("user_context"), dict) else {}
        user_intent = str(case.get("user_intent") or "")
        user = json.dumps({
            "case": {k: v for k, v in case.items() if k in ("input", "scenario", "expected_stage", "expected_path_types")},
            "user_intent": user_intent,
            "user_context": user_context,
            "previous_turns": previous_turns,
            "live_feedback": live_feedback,
        }, ensure_ascii=False)
        data = self.llm.complete_json(system, user, trace_id=trace_id, reasoning_effort="low", output_spec=_MOCK_NEXT_TURN_SPEC)
        if data.get("error"):
            return {"error": str(data.get("error")), "turn_index": len(previous_turns) + 1}
        query = str(data.get("query") or "")
        return {"query": query, "turn_index": len(previous_turns) + 1}

    def infer_user_intent(self, initial_request: Dict[str, Any], *, scenario: str = "") -> MockIntentOutput:
        """从已校验的项目 Request 反推有限用户模型。"""
        trace_id = f"mock-agent-infer-intent-{uuid.uuid4()}"
        system = (
            "你扮演正在使用当前业务系统的真实用户建模器。仅根据首轮请求中用户可见的内容，"
            "反推用户表达、用户意图和其对该业务系统的有限认知。不得使用或猜测 verifier、Judge、"
            "Evaluation、鉴权、session、内部 config 等信息；没有证据的 user_context 保持空对象，"
            "没有证据的 system_understanding 保持空字符串。输出必须简短。"
        )
        data = self.llm.complete_json(
            system,
            json.dumps({"project_id": self.spec.project_id, "scenario": scenario, "initial_request": initial_request}, ensure_ascii=False),
            trace_id=trace_id,
            reasoning_effort="low",
            output_spec=_MOCK_INTENT_SPEC,
        )
        if data.get("error"):
            raise RuntimeError(f"infer_user_intent failed: {data.get('error')}")
        return MockIntentOutput(
            user_intent=str(data.get("user_intent") or "").strip(),
            query=str(data.get("query") or "").strip(),
            user_context=dict(data.get("user_context") or {}),
            system_understanding=str(data.get("system_understanding") or "").strip(),
            scenario=scenario,
        )

    def decide_next_action(
        self,
        intent: MockIntentOutput,
        accumulated_output: Dict[str, Any],
    ) -> MockContinueDecision:
        """基于受限交互状态进行极简用户继续判断。"""
        trace_id = f"mock-agent-continue-{uuid.uuid4()}"
        data = self.llm.complete_json(
            (
                "你扮演真实用户，只根据用户可见的交互判断是否继续使用当前业务系统。\n"
                "- continue：目标尚未满足，但交互仍有实质进展，例如获得了新信息、新结果，"
                "或问题范围正在收敛；证据不足以停止时也选择 continue。\n"
                "- goal_satisfied：用户从可见结果主观认为目标已经满足。\n"
                "- user_abandons：用户明确不愿继续交互。\n"
                "- perceived_no_progress：经过持续交互后长期没有实质进展，例如反复询问相同问题、"
                "连续失败，且没有新增有效信息、结果或目标收敛。\n"
                "不得仅因为系统尚未交付最终结果，或仍在进行合理且有推进作用的澄清，就判断停止。"
                "选择 continue 时输出 action=continue、stop_reason=空字符串；其余状态输出 action=stop，"
                "stop_reason 为对应状态名。只能输出 action 和 stop_reason，不要解释。"
            ),
            json.dumps({
                "intent": dataclasses.asdict(intent),
                "accumulated_output": accumulated_output,
            }, ensure_ascii=False),
            trace_id=trace_id,
            reasoning_effort="low",
            output_spec=_MOCK_CONTINUE_DECISION_SPEC,
        )
        if data.get("error"):
            raise RuntimeError(f"decide_next_action failed: {data.get('error')}")
        raw_action = data.get("action")
        reason = str(data.get("stop_reason") or "")
        # 部分 provider 会把 discriminated action 序列化为一层对象。
        # 只解包协议内的 continue/stop，不接受任意文本或其他动作。
        if isinstance(raw_action, dict):
            action = str(raw_action.get("type") or raw_action.get("action") or "")
            reason = str(
                raw_action.get("stop_reason")
                or raw_action.get("reason")
                or reason
            )
        else:
            action = str(raw_action or "")
        if action not in {"continue", "stop"}:
            raise ValueError(f"invalid continue decision action: {action}")
        if action == "continue":
            reason = ""
        elif reason not in {"goal_satisfied", "user_abandons", "perceived_no_progress"}:
            # 部分 provider 未严格执行 JSON Schema enum；在公共层压回长期协议值。
            lowered = reason.lower()
            if any(marker in lowered for marker in ("目标", "达成", "满足", "完成", "satisfied", "achieved", "complete")):
                reason = "goal_satisfied"
            elif any(marker in lowered for marker in ("无进展", "没进展", "没有进展", "no progress", "stuck")):
                reason = "perceived_no_progress"
            else:
                reason = "user_abandons"
        return MockContinueDecision(action=action, stop_reason=reason)

    # --- prompt 构造 ---

    def _capability_context(self, project_id: str, scenario: str) -> str:
        """从项目侧材料注入业务上下文，core 不硬编码项目事实。"""
        parts: list[str] = []
        if self.spec.description:
            parts.append(f"项目说明：{self.spec.description}")
        mandatory_context = self._mandatory_context()
        if mandatory_context is not None:
            parts.append(f"项目 ContextUnit：{mandatory_context['content']}")
        else:
            for key in ("mock", "application", "evaluation"):
                doc = load_project_document(self.spec, key).strip()
                if doc:
                    parts.append(f"{key} 文档摘录：{doc[:1200]}")
        live_schema = load_live_schema(project_id)
        manifest = getattr(live_schema, "CAPABILITY_MANIFEST", None) if live_schema else None
        if isinstance(manifest, dict) and manifest:
            fields = ", ".join(str(item) for item in list(manifest.keys())[:8])
            parts.append(f"可参考能力/字段：{fields}。")
        return "".join(parts)

    def _mandatory_context(self):
        if self._mandatory_context_loaded:
            return self._mandatory_context_cache
        from .context.project import load_role_mandatory_context

        self._mandatory_context_cache = load_role_mandatory_context(
            self.spec,
            role="mock",
            operation="mock",
            run_id="mock-agent",
        )
        self._mandatory_context_loaded = True
        return self._mandatory_context_cache

    def _extract_output_shape(self, project_id: str) -> Dict[str, Any]:
        """从 live_schema.EXTRACT_OUTPUT_SCHEMA dataclass 生成 JSON Schema，供 prompt 注入。"""
        live_schema = load_live_schema(project_id)
        schema_cls = getattr(live_schema, "EXTRACT_OUTPUT_SCHEMA", None) if live_schema is not None else None
        return dataclass_to_json_schema(schema_cls) if schema_cls is not None else {}

    def _build_live_request_spec(self, project_id: str) -> StructuredOutputSpec:
        """按 live_schema.REQUEST_SCHEMA dataclass 构造 build_live_request 的结构化输出约束。"""
        live_schema = load_live_schema(project_id)
        req_cls = getattr(live_schema, "REQUEST_SCHEMA", None) if live_schema is not None else None
        if req_cls is not None:
            return StructuredOutputSpec.from_dataclass(
                req_cls,
                description=f"mock_agent live 请求体（{project_id}）",
            )
        return FREE_DICT_OUTPUT

    def _intent_system_prompt(self, spec: MockBuildSpec) -> str:
        required_hint = f"input 必须包含字段：{', '.join(spec.required_input_fields)}。" if spec.required_input_fields else ""
        mandatory_context = self._mandatory_context()
        if mandatory_context is not None:
            user_visible_context = (
                f"业务产品标识：{spec.project_id}。{self.spec.description or ''}"
                f"{mandatory_context['content']}"
            )
        else:
            mock_doc = load_project_document(self.spec, "mock").strip()
            user_visible_context = f"业务产品标识：{spec.project_id}。{self.spec.description or ''}{mock_doc[:800]}"
        base = (
            "你扮演真实终端用户，针对给定业务场景，用自然语言表达你想做的事。"
            f"场景：{spec.scenario}。{required_hint}"
            f"{user_visible_context}"
            "要求："
            "1. query：口语化的用户原话，不要出现系统术语或 JSON 字段名；"
            "2. user_intent：一句话说明你想干什么，用业务术语准确概括；"
            "3. user_context：描述用户的背景信息、画像和当前目标（可选）；"
            "4. system_understanding：只描述该用户对 project_id 对应业务产品的有限主观认知，"
            "不能写 verifier、Judge、Evaluation、内部能力答案；没有用户可见证据时保持空字符串。"
        )
        base += f'输出 JSON，只包含必填字段：query，user_intent。'
        return base

    def _live_request_system_prompt(self, live_shape: Dict[str, Any], build_spec: MockBuildSpec) -> str:
        """按 live_schema.REQUEST_SCHEMA 生成的 JSON Schema 构造 prompt。"""
        capability = self._capability_context(build_spec.project_id, build_spec.scenario)
        # 显式列出必填字段，避免 LLM 漏掉不熟悉的字段（如 reference/metadata）
        required_fields = live_shape.get("required", []) if isinstance(live_shape, dict) else []
        required_hint = ""
        if required_fields:
            required_hint = f"必填字段列表：{', '.join(required_fields)}。每个必填字段都必须出现且非空；"
            # 对部分项目需要特殊提示的字段
            if "reference" in required_fields:
                required_hint += "reference 是预期答案/参考，若不知内容可填空对象 {}；"
            if "metadata" in required_fields:
                required_hint += "metadata 是请求上下文，可填 {\"trace_id\": \"trace-001\", \"org_id\": \"eval-org\"}；"
        return (
            "你将用户意图映射为 live 请求体。"
            f"请求体 JSON Schema：{json.dumps(live_shape, ensure_ascii=False)}。"
            f"场景：{build_spec.scenario}。{capability}"
            f"{required_hint}"
            "要求：按 schema 填充所有必填字段；用户原话必须写入 schema 中表达用户输入的字段，贴合系统业务场景；"
            "session_id/trace_id/user_id 用合理默认值；不要编造输出内容。"
            "输出 JSON，包含完整的请求体字段。"
        )

    def _next_turn_system_prompt(self, scenario: str) -> str:
        return (
            "你扮演真实用户，根据上一轮系统的回复，生成下一轮要说的话。"
            f"场景：{scenario}。"
            "要求："
            "1. 基于 user_context 的用户画像/背景，保持用户角色一致（语气、诉求、知识水平）。"
            "2. 基于 user_intent 的核心目标，在每轮 query 里体现目标推进（不要偏题）。"
            "3. 基于上轮 live 反馈里缺失的字段或系统的澄清提示，自然地补充；不要重复已说内容。"
            '输出 JSON，字段：{"query": str}。'
        )

    # --- 结果映射 ---

    def _map_intent_result(self, spec: MockBuildSpec, data: Dict[str, Any]) -> MockBuildResult:
        user_intent = str(data.get("user_intent") or "").strip()
        user_context: Dict[str, Any] = data.get("user_context") or {}
        system_understanding = str(data.get("system_understanding") or "").strip()
        query = str(data.get("query") or "").strip()
        input_data: Dict[str, Any] = {"query": query, "user_intent": user_intent}
        for field in spec.required_input_fields:
            if field not in input_data:
                input_data[field] = query if field in ("query", "user_intent") else []

        # mock_agent 只产用户侧产物（意图 + live 输入）。output/reference 由调度层在 mock build 后从系统侧/judge 侧获取。
        case_id = f"mock-agent-{spec.project_id}-{uuid.uuid4().hex[:8]}"
        return MockBuildResult(
            case_id=case_id,
            input=input_data,
            output=None,
            reference=None,
            user_intent=user_intent,
            query=query,
            user_context=user_context,
            scenario=spec.scenario,
            metadata={"source": "mock_agent_llm", "ready": list(ready_from_spec(self.spec)), "project_id": spec.project_id, "system_understanding": system_understanding},
        )

    def _map_live_request_result(self, intent_result: MockBuildResult, build_spec: MockBuildSpec, data: Dict[str, Any]) -> MockBuildResult:
        """将 LLM 产出的 live 请求体写入 input，覆盖意图层 query。output/reference 由调度层填充。"""
        # 严格对齐 REQUEST_SCHEMA：过滤 LLM 多产的字段
        import dataclasses
        live_schema = load_live_schema(build_spec.project_id)
        request_schema = getattr(live_schema, "REQUEST_SCHEMA", None) if live_schema is not None else None
        if request_schema is not None and dataclasses.is_dataclass(request_schema):
            allowed = {f.name for f in dataclasses.fields(request_schema)}
            input_data = {k: v for k, v in data.items() if k in allowed}
        else:
            input_data = dict(data)
        for key in ("output", "raw_model_response", "metrics"):
            input_data.pop(key, None)
        result = MockBuildResult(
            case_id=intent_result.case_id,
            input=input_data,
            output=None,  # 由调度层从系统侧获取
            reference=None,  # 由调度层从 judge 评估侧获取
            user_intent=intent_result.user_intent,
            user_context=intent_result.user_context,
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
            user_intent="",
            user_context={},
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
            schema_errors = live_schema.check.case_errors(case)
            result.metadata["schema_ok"] = not schema_errors
            if schema_errors:
                result.metadata["schema_errors"] = schema_errors
        except Exception as exc:
            result.metadata["schema_ok"] = False
            result.metadata["schema_check_error"] = str(exc)


def load_live_schema(project_id: str) -> Optional[Any]:
    import importlib
    module_path = f"impl.projects.{project_id}.live_schema"
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError:
        return None


def load_project_schema(project_id: str) -> Optional[Any]:
    """加载项目级 schema 模块（impl/projects/<project>/schema/）。

    项目目录名可能含普通 import 不支持的字符，不能用普通 import，
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
    """从 live_schema.EXTRACT_OUTPUT_SCHEMA 读取项目 output dataclass。"""
    live_schema = load_live_schema(project_id)
    return getattr(live_schema, "EXTRACT_OUTPUT_SCHEMA", None) if live_schema is not None else None


def get_request_dataclass(project_id: str) -> Optional[type]:
    """从 live_schema.REQUEST_SCHEMA 读取项目 request dataclass。"""
    live_schema = load_live_schema(project_id)
    return getattr(live_schema, "REQUEST_SCHEMA", None) if live_schema is not None else None


def get_extract_output_shape(project_id: str) -> Dict[str, Any]:
    """从 EXTRACT_OUTPUT_SCHEMA dataclass 生成 JSON Schema 兼容视图。"""
    schema_cls = get_extract_output_dataclass(project_id)
    return dataclass_to_json_schema(schema_cls) if schema_cls is not None else {}


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

def build_initial_request_from_intent(agent: "MockAgent", build_spec: "MockBuildSpec", intent: "MockIntentOutput") -> "MockBuildResult":
    """协议层工具函数：把 MockIntentOutput 翻译成 REQUEST_SCHEMA 形状。

    供 ProjectMock.build_live_request 默认实现调用。
    内部把 intent 包装成 MockBuildResult，复用 MockAgent.build_live_request 的 step2 LLM 调用。
    """
    intent_result = MockBuildResult(
        case_id=f"mock-{build_spec.project_id}-{build_spec.scenario or 'default'}",
        input={"query": intent.query, "user_intent": intent.user_intent},
        output=None,
        reference=None,
        user_intent=intent.user_intent,
        user_context=dict(intent.user_context or {}),
        scenario=build_spec.scenario,
        metadata={"source": "protocol_build_live_request", "system_understanding": intent.system_understanding},
    )
    return agent.build_initial_request(intent_result, build_spec)
