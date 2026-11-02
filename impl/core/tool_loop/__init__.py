"""ToolLoop 公共入口。实现按协议、循环、通用 hooks、结果提取分模块。

调用方从本包导入；内部模块互相使用相对导入，不通过公共入口形成循环依赖。
"""
from .types import (
    Abort, Allow, Call, Continue, Deny, Done, Failed, History, Hook, HOOK_EVENTS,
    LoopContext, LoopResult, PreDecision, Step, StepClient, StopVerdict,
)
from .hooks import (
    BudgetStop, DEFAULT_BUDGET, DependsOn, RequireDone, Rule,
    after, cites_read, is_accepted, until_accepted,
)
from .outputs import last_assistant_text, take_accepted
from .runtime import ToolLoop

__all__ = [
    "Abort", "Allow", "Call", "Continue", "Deny", "Done", "Failed", "History",
    "Hook", "HOOK_EVENTS", "LoopContext", "LoopResult", "PreDecision", "Step", "StepClient", "StopVerdict",
    "BudgetStop", "DEFAULT_BUDGET", "DependsOn", "RequireDone", "Rule", "after", "cites_read",
    "is_accepted", "until_accepted", "last_assistant_text", "take_accepted", "ToolLoop",
]
