from __future__ import annotations

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace
from impl.projects.client_search.attribute import build_attribute_context
from impl.projects.client_search.judge import condition_comparison
from impl.projects.client_search.live import (
    boundary_from_trace,
    capability_manifest,
    source_config_paths,
)


def _build_project_attribute_context(
    spec: ProjectSpec,
    trace: RunTrace,
    judge_result: JudgeResult,
) -> dict:
    from impl.core.project_loader import load_project_role_tools

    context = build_attribute_context(spec, trace, judge_result)
    context.update({
        "tools": list(load_project_role_tools(spec, "attribute") or []),
        "tool_call_limit": 8,
        "system_prompt_override": """你是 client_search 项目的 draft attribute agent。
第一步只 Load `project.client_search.attribute.investigation.parse_flow`；它已经包含运行时所需的节点、data、边界和操作索引。`parse_graph` 与 `overview` 是设计期辅助材料，除非 parse_flow 缺失必要关系，否则不要同时加载。先把 Judge 的 not_fulfilled gap 对齐到当前公共输出中的具体 data，再按 Operational index 沿真实数据流逆向选择候选节点；只深入能够区分主要竞争解释的最短路径，不罗列整条架构，也不预设 route、字段或缺陷节点。
Tool 由当前节点的 input/output data、进入条件、可观测事实和 observation gap 决定。公共 API、replay/probe、配置和源码各自只能证明其声明的边界：静态材料只能解释已经观察到的机制，不能证明当前 case 经过该机制；专用 replay 也不能越过自身边界证明路由选择或其他阶段。
配置、文档或历史 probe JSON 证据优先使用 `source_search_text` 的精确 query、较小 max_results 和 context_lines 获取命中附近的最小充分原文；已有命中片段足以解释观察到的转换时立即停止，不得再读取整文件。只有小文件且无法用有界搜索表达所需材料时才允许 full_file；若材料会挤占 Finalization 预算，保留 unresolved，不以超量材料换取结论。
只有当前 query 的公共边界偏差与同一 case 的机制级观察能被因果连接，并且足以排除会导向不同修复的主要解释时，才输出完整 finding。若只能证明偏差发生在两个接口之间，可保留有限 finding，但只要该区间仍包含 mock、session、adapter、请求构造等不同修复位置，必须同时写 unresolved_reason，列明尚未区分的机制；不得把边界定位标成完整归因。所需阶段数据不可取得、不同观察不一致或只能证明故障层级时，收缩为 unresolved。
最终只输出 findings、unresolved_reason，证据必须引用 Finalization 重载的 ContextUnit。
若 findings 已覆盖全部 not_fulfilled expectation 且没有真实遗留问题，unresolved_reason 必须为 ""；禁止用该字段写“无未解决问题”或结论强化语。
禁止输出 attributed_to、root_cause_summary、evidence_refs、causal_category、earliest_divergence、verification_steps 等旧字段或项目私有字段。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "investigation_context": "client_search parser business flow",
                "root_cause_policy": (
                    "Start from the current expected-vs-actual output diff, follow the investigation data flow "
                    "to the earliest observable mechanism-level divergence, and do not reuse historical fields."
                ),
                "tool_selection_policy": (
                    "Select only capabilities attached to the current candidate node and needed to distinguish "
                    "competing explanations; never treat static config presence as case execution proof."
                ),
                "evidence_contract": [
                    "current query",
                    "judge expected-vs-actual gap",
                    "current public parser output",
                    "case-specific observation at the claimed mechanism",
                    "relevant project config/source only as explanatory support",
                ],
            },
            "condition_comparison": condition_comparison(spec, trace),
            "application_boundary": boundary_from_trace(trace),
            "source_config_paths": source_config_paths(spec),
            "capability_manifest": capability_manifest(spec),
        },
    })
    return context


class ClientSearchAttribute(ProjectAttribute):
    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        return _build_project_attribute_context(self.spec, trace, judge_result)
