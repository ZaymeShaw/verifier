"""意图理解：表达环节 intent_understanding（用户原文 → 系统内部表达）。"""
from .process_common import AxisSpec, Subcapability, axis_type


SUBCAPABILITIES = (
    Subcapability("对象与字段一致", "用户原文点名了对象、字段或知识点",
                  "内部表达（截至本轮的步骤产出、交给 Agent 的任务、工具参数）里的对象与字段和原文一致，没有被改写或替换"),
    Subcapability("子问题均识别", "用户原文含一个或多个子问题",
                  "每个子问题都在内部表达里有对应（任务表述或工具调用意图）；逐个列出"),
    Subcapability("约束保留", "用户给出了时间、条件、比较关系、范围或输出要求",
                  "这些约束在内部表达里被保留，没有弱化或换成默认口径"),
    Subcapability("指代解析", "用户用指代词指向会话历史里的对象",
                  "指代解析到历史中正确的对象"),
    Subcapability("歧义识别", "用户原文确有歧义或缺关键信息",
                  "内部表达把它保留为待确认或并列候选，而不是选定一种解读当确定事实。是否发起澄清、澄清是否多余不在此判"),
)

SPEC = AxisSpec(
    question="表达环节：系统把用户原文转成内部表达时，对象、字段、约束、子问题、指代是否与原文一致完整。",
    excludes="理解之后的一切：路由与拆解、是否发起澄清（编排或模型决策）、调用是否成功、上下文是否传丢、数据源有没有、模型答得好不好。",
    subcapabilities=SUBCAPABILITIES,
    requires="要判断系统有没有听懂用户：需要看到截至本轮系统内部如何表达用户问题——各步骤的产出、交给 Agent 的任务表述、"
             "各次工具调用的请求参数。跨轮追问还要看到历史轮里被指代的对象。",
)

AXIS_TYPE = axis_type("intent_understanding", "意图理解", "用户原文到系统内部表达是否一致完整", SPEC)
