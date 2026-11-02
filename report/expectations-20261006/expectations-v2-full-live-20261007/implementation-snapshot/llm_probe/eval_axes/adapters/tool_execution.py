"""工具执行：执行环节 tool_execution（调用参数 → 工具/后端/子 agent 的返回，含内部解析与适配层）。"""
from .process_common import AxisSpec, Obligation, axis_type


OBLIGATIONS = (
    Obligation(
        "executed_without_error", "tool_execution", "工具被调用",
        "调用完成自身职责，没有报错、超时或异常中断；没有错误码不证明执行正确",
        label="调用无执行错误",
    ),
    Obligation(
        "result_matches_request", "tool_execution", "调用正常返回（返回的是执行错误时由「调用无执行错误」判，本项不适用）",
        "按请求条件执行，未丢条件；返回的就是请求的对象，没有残缺截断，没有把别的对象标成目标对象；返回可读且符合工具说明声明的结构",
        label="返回对象与请求一致",
    ),
    Obligation(
        "within_time_limit", "tool_execution", "调用有耗时记录",
        "耗时在该调用适用的时限内（工具配置、诊断记录中的 timeout 等）；没有适用时限 → contract_missing，不自定阈值、不用整轮上限代替",
        source="trace", label="耗时在时限内",
    ),

)

SPEC = AxisSpec(
    question="执行环节：工具/后端/子 agent（含内部解析与适配层）拿到参数后，自身执行有没有问题：报错、超时、返回残缺、返回对象与请求不符、应有结果却没给。",
    excludes="该不该调、调用顺序、系统策略拒绝与重试策略（规划路由）；参数从哪来（意图理解）；返回后怎么传怎么用（上下文管理、模型能力）；"
             "已查明是数据源本来没有（知识数据）。",
    obligations=OBLIGATIONS,
    requires="要逐条检查每一次调用：参数、返回正文、耗时与报错信息都要，一次都不能少；包括函数步骤中的直连调用、"
             "工具说明及内部解析、准入的可见记录、调用适用的超时设置。特别核验空结果、歧义、拒绝及未执行查询时，按业务期望本该如何。",
)

AXIS_TYPE = axis_type("tool_execution", "工具执行", "每次调用自身是否正确执行、返回是否就是请求的对象", SPEC)
