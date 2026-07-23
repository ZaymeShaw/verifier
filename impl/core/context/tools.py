from __future__ import annotations

from typing import Annotated, Mapping, Optional, Sequence

from pydantic import Field

from .runtime import ContextRun


CONTEXT_QUERY_PLANNING_INSTRUCTIONS = """\
搜索上下文前，先把当前任务拆成会改变执行方式的独立知识需求，再把每个需求写成紧凑的
检索词组合，而不是问题、说明句或相关主题列表。按下面的槽位规划，存在什么才查什么：

- 实体/概念：原词 + 可推断别名 + 待验证的隐含属性 + 对象关系 + 定义/规则；
- 条件/动作：原词 + 约束/前置条件 + 可能的实现表示类型（字段、API、配置、操作符等）；
- 时间/数值/集合范围：原词 + 边界 + 单位 + 日期/数值表示 + 转换规则；
- 枚举或名称归一：原词 + 枚举 + 别名 + 值映射；
- 多实体或多条件：保留各原词 + 关联规则 + 组合约束。

每条查询必须逐字保留至少一个任务原文中的具体关键词或短语，不得拆坏专有词。可以加入
模型根据常识推断、但仍需知识库验证的同义词或隐含属性来扩大召回；这些词只是检索假设。
每条只覆盖一个主要未知点。不要用“对象定义”“数据规则”等宽泛上位词替换具体实体；
不要输出完整任务、任务改写或不同语序。除非原任务明确涉及，否则不要凭空增加知识库
位置、存储、访问权限、状态或其他条件。合并重复需求并遵守查询预算；预算不足时优先保留
实体隐含语义、条件实现表示和范围边界，可合并紧密绑定的实体与属性。

例如任务“查找团队负责人审批金额在本季度超过阈值的记录”，可生成：
“团队负责人 负责人 管理角色 组织关系 身份定义 别名”、
“审批金额 超过阈值 金额字段 比较操作 单位 约束”、
“本季度 日期范围 起止边界 日期字段 转换规则”、
“团队负责人 审批金额 本季度 关联规则 组合约束”。
不要生成“目标记录的定义”“记录存储位置”或四种完整任务改写。

查询文本只是假设和发现手段，不是权威证据。候选描述只用于选择 ID；必须加载选中的
ContextUnit 后，才能依赖其完整内容完成原任务。
"""


CONTEXT_CANDIDATE_SELECTION_INSTRUCTIONS = """\
候选选择时，按每条候选的 matched_queries 检查它直接回答了哪个原子信息需求，而不是只看
它与完整任务是否词面相关。选择结果必须覆盖所有会改变执行方式的信息需求；一个候选可以
覆盖多项，但不能用主题相近、对象归属不同的字段或规则互相替代。尤其要核对主体与关联对象、
输入与输出、当前状态与历史状态、单项条件与组合约束的归属差异，并优先采用定义精确、包含
反例或明确边界的候选。

调用 Load 时逐字复制 Search 返回的 selection_ref，不要复制、缩写或重新生成长 ID。候选摘要
只用于选择，最终结论只能依赖已加载 ContextUnit 的完整内容。候选摘要预算 candidate_limit 与
完整内容预算 load_limit 是不同阶段的预算；先保留足够的摘要候选完成跨需求选择，再在
load_limit 内加载最小充分证据集。
"""


def search_context_units_tool(
    context_run: ContextRun,
    queries: Sequence[str],
    top_k_per_query: Optional[int] = None,
):
    """Search model-safe summaries with transient refs, without physical IDs."""

    return [
        {
            "selection_ref": item["selection_ref"],
            "name": item["name"],
            "description": item["description"],
            "matched_queries": list(item["matched_queries"]),
        }
        for item in context_run.search_context_units(
            queries, top_k_per_query=top_k_per_query
        )
    ]


def load_context_units_tool(context_run: ContextRun, unit_ids: Sequence[str]):
    """Load complete authorized ContextUnits without exposing physical IDs."""

    return [
        {
            "selection_ref": context_run.selection_ref_for_loaded_context_unit(unit.id),
            "name": unit.name,
            "description": unit.description,
            "content": unit.content,
        }
        for unit in context_run.load_context_units(unit_ids)
    ]


class GuardedContextTools:
    """Bound tools expose model-controlled queries and IDs, never governance fields."""

    def __init__(self, context_run: ContextRun):
        self._context_run = context_run

    def search_context_units(
        self,
        queries: Annotated[list[str], Field(min_length=1, max_length=4)],
        top_k_per_query: Optional[int] = None,
    ):
        """Search once for a planned list of atomic, self-contained information needs.

        Submit 1-4 query strings directly as a JSON array. Query text may contain discovery hypotheses but is not evidence. Search returns only
        candidate refs, names, descriptions and matched queries; load by selection_ref before using full content.
        """

        return search_context_units_tool(
            self._context_run, queries, top_k_per_query=top_k_per_query
        )

    def load_context_units(
        self, unit_ids: Annotated[list[str], Field(min_length=1, max_length=8)]
    ):
        """Load 1-8 exact ContextUnit IDs/selection_refs; results expose only short refs."""

        return load_context_units_tool(self._context_run, unit_ids)

    def context_debug(self) -> Mapping[str, object]:
        return self._context_run.debug_snapshot()
