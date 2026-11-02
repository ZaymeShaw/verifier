"""规划路由：编排环节 ρ（任务与状态 → 路径、调用序列、分支、重试、系统策略、收尾）。"""
from .process_common import AxisSpec, Obligation, axis_type


OBLIGATIONS = (
    Obligation(
        "branch_condition", "ρ", "控制步骤（Condition/Router/Loop）在子分支之间做了选择",
        "按步骤定义与当时输入所声明的条件选择分支；Loop 按上限终止",
        source="trace", applies_to=("ρ:branch",), label="分支按声明条件",
    ),
    Obligation(
        "path_choice", "ρ", "本轮需要选定执行路径（直连后端的函数步骤、交给 Agent 编排、调用哪些工具）",
        "所选路径与问题类型相称，实际走的路径与该选择一致",
        applies_to=("ρ:path",), label="路径选择合理",
    ),
    Obligation(
        "work_coverage", "ρ", "问题需要若干项工作（取数、取知识、计算）",
        "每个子问题都有对应处理；确需外部数据时完成取数；依赖的调用排在先决信息之后",
        applies_to=("ρ:path",), label="工作覆盖完整",
    ),
    Obligation(
        "system_policy", "ρ", "本轮触发了系统自身策略（预算、准入、容量闸、拦截、确定性兜底、缓存或去重）",
        "给模型的规则与实际执行的规则一致；没有在仍能完成的任务上拦截或放弃。按设计触发的拒绝属于编排，不是执行偏差",
        source="trace", applies_to=("ρ:path",), label="系统策略",
    ),
    Obligation(
        "failure_branch", "ρ", "本轮出现调用失败、未命中或被拒绝",
        "之后有产出：改参、换工具、澄清或如实收尾，并利用了已取得的信息；失败后什么都没做就收尾算无产出",
        applies_to=("ρ:path",), label="失败分支有产出",
    ),
    Obligation(
        "post_tool_integration", "ρ", "工具返回了可用事实",
        "系统保留了整合与交付的机会：模型继续整合，或被系统终止后有确定性步骤把可用事实组织成用户所需答复；"
        "只把工具卡片、字段名或错误信封交给用户算没做到",
        applies_to=("ρ:path",), label="工具返回后的整合与交付",
    ),
    Obligation(
        "termination", "ρ", "本轮流程收尾",
        "必要工作完成或被如实标记为缺口后才收尾；终止方（模型或系统）没有剥夺整合已有结果的机会",
        applies_to=("ρ:path",), label="结束时机合理",
    ),
    Obligation(
        "repeat_justified", "ρ", "同名同参的调用在前次结束后再次发出",
        "重复有依据：前次结果表明可重试，或有退避、改参、绕过缓存；否则是无效重复。缓存吞掉重试须有缓存使用证据",
        source="trace", applies_to=("ρ:repeat",), label="重复调用有依据",
    ),
    Obligation(
        "decision_matches_rule", "ρ", "该编排环节做出了一个决策（任何编排环节，含表外环节）",
        "决策与出处中的规则或声明一致",
        source="trace", label="编排决策符合规则",
    ),
)

SPEC = AxisSpec(
    question="编排环节：路径选择、任务拆解、调用顺序、系统策略、失败分支、重试、结束时机是否合理。系统按自己的设计跑但设计不对也算。",
    excludes="工具自身执行好坏（工具执行）、信息在环节间传递与交付是否失真（上下文管理）、数据源有没有（知识数据）、模型在给定输入下的逐次输出（模型能力）。",
    obligations=OBLIGATIONS,
    requires="要判断路径合不合理：需要看到系统实际走过的完整路径——每一次调用的参数与返回正文、先后次序与时间点；"
             "控制步骤的决定与理由；系统拒绝、拦截、预算或容量触发的记录，以及给模型的规则原文；"
             "失败或未命中之后系统又做了什么；工具返回后是否确有模型继续整合，或后续函数步骤是否把可用事实转成用户可读答复。",
)

AXIS_TYPE = axis_type("planning_routing", "规划与路由", "路径、拆解、顺序、系统策略、失败分支与重试是否合理", SPEC)
