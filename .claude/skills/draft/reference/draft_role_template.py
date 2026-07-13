"""Draft 实现模板（按 spec/draft/draft.md 阶段 3 写）。

复制到 impl/projects/<project>/draft/<role>.py 后填项目实现。

**关键：本模板和正式版 impl/projects/<project>/<role>.py 同结构**
（顶层 helper + 顶层 <role>_failure / judge_trace 函数入口 + class ProjectXxx(ProjectXxx) 继承式扩展点）。
draft 文件中的公开入口、类名和签名必须与当前 production 文件一致；promotion 时直接文件覆盖 draft/<role>.py → <role>.py，不再改名或改结构。

draft 机制的三条硬约束（spec/draft/draft.md）：
1. 继承 ProjectXxx，不另写函数式入口（顶层函数入口只是 run_project_<role>_protocol 的转发）。
2. 不覆盖模板方法（@final）和内部方法（_ 前缀）——
   协议层 _FORBIDDEN_OVERRIDES + __init_subclass__ 已经硬约束，draft 自然受约束。
3. 实现当前协议要求的所有 @abstractmethod——清单由当前 *_protocol.py 决定，draft 不预判。

哪些是 @abstractmethod / @final / _ 前缀，由 introspect_protocol.py 动态发现，
draft 实现者按自省结果按图施工。下面示例以 judge 角色为模板，attribute 角色调整入参签名即可。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# === 复制到项目时，按角色改这两行 import ===
# judge 角色：
from impl.core.judge_protocol import ProjectJudge, run_project_judge_protocol
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace
# attribute 角色：
# from impl.core.attribute_protocol import ProjectAttribute, run_project_attribute_protocol
# from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


# === 顶层 helper（项目特异逻辑写这里）===
# 正式版 <role>.py 也是这种结构：helper 在类外，build_context 委托给 helper。
# 这样 draft 和正式版结构一致，promotion 时直接覆盖。

def _build_core_context(adapter, trace: RunTrace) -> dict:
    """Draft 版的项目特异 context 构建。

    复制到项目后改成实际逻辑——这里只是占位。
    正式版 impl/projects/<project>/<role>.py 也有同名 _build_core_context，
    draft 改进点就写在这里（业务期望提取更贴合 / 链路定位更下沉 / 等）。
    """
    context = adapter.build_judge_context(trace) or {}
    # TODO: draft 改进点写在这里
    return {
        "expected_intent": context.get("expected_intent"),
        "intent_frame": adapter.build_intent_frame(trace),
        "system_prompt_extras": [],  # draft 可在此加项目特异 prompt
        "user_prompt_extras": {},    # draft 可在此加项目特异上下文
    }


# === 顶层入口函数（仅转发到 run_project_<role>_protocol）===
# 正式版 <role>.py 也是这种结构——draft 和正式版一致，promotion 直接覆盖。
# judge 角色：
def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(adapter, trace),
    )

# attribute 角色（取消注释，删掉上面 judge 的 judge_trace）：
# def attribute_failure(
#     spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult
# ) -> AttributeResult:
#     return run_project_attribute_protocol(
#         spec,
#         adapter,
#         trace,
#         judge_result,
#         project_attribute_context=_build_project_attribute_context(spec, adapter, trace, judge_result),
#     )


# === 类继承式实现（按自省结果填所有 @abstractmethod + 按需覆盖 optional）===
# 正式版 <role>.py 也是这种结构。生成具体 draft 文件时，类名必须直接使用
# 当前 production 的公开类名（例如 QAJudge / QAAttribute），不能保留 DraftXxx 名称。
# 下方 DraftJudge 仅是未实例化模板占位名。

class DraftJudge(ProjectJudge):
    """Draft 版的项目层 Judge 实现。

    spec/draft/draft.md 阶段 3 的实现要点：
    - 继承 ProjectXxx，不另写函数式入口。
    - 实现当前 *_protocol.py 要求的所有 @abstractmethod（清单由 introspect_protocol.py 给）。
    - 可选覆盖的扩展点按需覆盖，没需求的不写。
    - 不要覆盖模板方法（@final）和内部方法（_ 前缀）。

    入口签名（模板方法）和正式版一致——loader 切换无感。
    spec 和 live_schema 由父类 __init__ 加载，子类不要重写 __init__。
    """

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    # === 必须实现的 @abstractmethod（按自省结果填）===
    # judge 协议当前只一个 @abstractmethod：build_context
    def build_context(self, trace: RunTrace) -> Dict[str, Any]:
        return _build_core_context(self._adapter, trace)

    # === 可选覆盖的扩展点（按需写，没需求的不写）===
    # 自省结果中的 optional_methods：pre_judge / build_intent_frame /
    # reconcile_result / normalize_result。下面是占位示例，按需取消注释。

    # def pre_judge(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
    #     return self._adapter.pre_judge_result(trace, expected_intent=expected_intent)
    #
    # def build_intent_frame(self, trace: RunTrace, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    #     return self._adapter.build_intent_frame(trace)
    #
    # def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
    #     return self._adapter.reconcile_judge_result(trace, result)
    #
    # def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
    #     from impl.core.schema import normalize_judge_result
    #     return normalize_judge_result(self._adapter.normalize_judge_result(trace, result)) or result

    # === 不要覆盖这些（forbidden_overrides + _ 前缀）===
    # 父类的 @final 模板方法（judge_trace）+ _ 前缀内部方法（_run_llm_judge / _validate_judge_output）。
    # __init_subclass__ 会在子类覆盖时硬报错，不需要 draft 自己拦。


# === attribute 角色的类实现（取消注释，删掉上面 DraftJudge）===
# class DraftAttribute(ProjectAttribute):
#     def __init__(self, spec: ProjectSpec, adapter):
#         super().__init__(spec)
#         self._adapter = adapter
#
#     def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
#         base_context = self._adapter.build_attribute_context(trace, judge_result)
#         extra_context = _build_project_attribute_context(self.spec, self._adapter, trace, judge_result)
#         context = dict(base_context or {})
#         context.update(extra_context)
#         # TODO: draft 改进点写在这里（链路定位下沉、probe 改进等）
#         return context
#
#     # optional: probes / normalize_result 按需覆盖


# === tool 接入（按效果定，spec/draft/draft.md 阶段 3）===
# draft 在 build_context 返回的 tools 里挂项目特异 tool（来自 draft/tools/）。
# tool 经统一 ToolRegistry + ToolOrchestrator + agno 桥接，不经项目 adapter 中转。
# tool 类型用现有的 impl/tools/protocol.py 的 VerifiableTool / ToolResult，不另造。
# 角色特异的 tool 边界（如 judge 默认屏蔽内部代码）由角色层 ROLE.md 定。
# 示例（如需要，在 build_context 的返回里加 "tools": [project_specific_tool_instance]）：


# === 不要写 case id / 样本序号 / 当前样本专属数值文案 ===
# draft 实现要能泛化到没见过的 case。
