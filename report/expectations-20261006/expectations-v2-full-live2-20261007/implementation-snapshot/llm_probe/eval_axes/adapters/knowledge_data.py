"""知识数据：数据源环节 knowledge_data（本轮问题与已发出的查询 → 外部数据是否给出）。"""
from .process_common import AxisSpec, Obligation, axis_type


OBLIGATIONS = (
    Obligation(
        "data_per_subquestion", "knowledge_data", "用户的子问题需要外部数据或知识",
        "在已正确执行查询的前提下，所需对象存在、字段有值、知识库有应有条目；按业务期望本应为空时空结果符合期望。"
        "未召回不证明全库不存在；只检查用户所需的数据与字段",
        source="case", label="子问题数据已给出",
    ),
    Obligation(
        "object_version_timepoint", "knowledge_data", "问题涉及特定对象、版本、时点或适用条件",
        "取得的数据在对象、版本、时点、适用条件上与问题一致；问题确需版本或时点而返回无依据时 insufficient_evidence，不推断为最新",
        source="case", label="对象版本时点匹配",
    ),
)

SPEC = AxisSpec(
    question="数据源环节：本轮问题所需的数据是否按业务期望给出；给了的对象、版本、时点是否匹配。未定位偏差保留候选归因。",
    excludes="调用怎么发、系统策略与失败处置（规划路由）；工具自身解析或适配出错（工具执行）；返回后系统怎么传（上下文管理）。",
    obligations=OBLIGATIONS,
    requires="要判断外部数据撑不撑得住：需要读到每一次调用的返回正文——每个子问题要的数据落在哪次返回里、"
             "返回的对象、版本、时点是否对得上用户的问题；取不到时要看到返回的状态、提示与失败原因。",
)

AXIS_TYPE = axis_type("knowledge_data", "知识与数据", "数据源对每个子问题给了数据没有；对象、版本、时点对不对", SPEC)
