"""上下文管理：传递环节 κ（一处产出 → 下一处输入，含系统组装模型输入、历史注入与交付）。"""
from .process_common import AxisSpec, Obligation, axis_type, verbatim_arrival


OBLIGATIONS = (
    Obligation(
        "arrives_intact", "κ", "上游产出被传到下一处（工具结果→模型输入、步骤→步骤，含表外传递）",
        "任务相关的目标、对象、状态、原因与关键事实原义到达；合理压缩不算改义；上游本就无关或错误而被如实转交不算本项偏差",
        label="传递保留原义", program=verbatim_arrival,
    ),
    Obligation(
        "input_assembled", "κ", "系统为一次模型调用组装输入",
        "保留当前目标、约束、输出格式要求和前序结果，没有引入错误对象、旧状态或冲突；格式要求缺失、截断或前后冲突算没做到",
        applies_to=("κ:input",), label="模型输入组装",
    ),
    Obligation(
        "history_and_state", "κ", "输入里含有历史、缓存或会话状态带来的内容",
        "来源正确、没有复用失败或过期结果、没有混淆对象；状态快照是运行末态，不证明运行时使用过；本轮没有此类内容时 not_applicable",
        applies_to=("κ:input",), label="历史与状态使用",
    ),
    Obligation(
        "delivered_intact", "κ", "产出被交付给调用方",
        "事实、理由、限制、澄清没有丢失、被替换或改义（比较语义，不要求逐字）；落库与实收都要核对，没有实收记录时交付端注明缺证",
        applies_to=("κ:deliver",), label="交付保留原义",
    ),
)

SPEC = AxisSpec(
    question="系统组装、传递、缓存和交付信息时，有没有把信息弄丢、改义、弄旧或混淆对象？",
    excludes="模型收到输入后的决策与生成由模型轴判断；数据源本来缺失或工具本身返回错误由对应轴判断，不能仅因输入不相关归咎上下文。",
    obligations=OBLIGATIONS,
    requires="需要信息传递前后两端：工具与函数步骤结果、每次模型调用的输入输出（包括重建输入）、"
             "模型最终输出原文、Agent 之后的函数步骤与收尾步骤输出、运行落库输出以及调用方实际收到的答复；还要相关状态、缓存与多轮历史记录。"
             "模型输出、后续函数步骤、交付三端必须同时选入。",
)
AXIS_TYPE = axis_type("context_memory", "上下文管理", "检查信息传递、缓存历史及最终交付是否失真", SPEC)
