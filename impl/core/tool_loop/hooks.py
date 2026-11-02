"""通用 hook 实现：依赖、读取回执、被接受提交与预算，不引入项目语义。"""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Callable, Optional, Sequence, Union

from .types import Abort, Allow, Call, Continue, Deny, Done, History, Hook, PreDecision, StopVerdict


Rule = Callable[[History, Call], Optional[str]]  # 返回缺什么；None 表示满足


class DependsOn(Hook):
    """tool → 前置条件。不满足就拒绝，拒绝到底；前置永远满足不了时 loop 会以 failed 结束。"""

    def __init__(self, rules: Mapping[str, Rule]) -> None:
        self.rules = dict(rules)

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        rule = self.rules.get(call.tool)
        missing = rule(history, call) if rule else None
        return Deny(missing) if missing else Allow()


def after(*tools: str, accepted: Optional[Callable[[Call], bool]] = None) -> Rule:
    """前置：这些 tool 在之前的批次里各有过一次成功调用；给了 accepted 时还要求该调用被接受
    （tool 以结果报告失败、调用本身没出错时，只看「成功调用」会把失败当成满足）。"""
    done = "被接受的调用" if accepted else "成功调用"

    def rule(history: History, call: Call) -> Optional[str]:
        missing = [tool for tool in tools
                   if not any(c.ok and (accepted is None or accepted(c)) for c in history.of(tool))]
        if not missing:
            return None
        return f"{call.tool} 依赖 {', '.join(missing)}；此前的批次中 {', '.join(missing)} 没有{done}。"

    return rule


def until_accepted(accepted: Optional[Callable[[Call], bool]] = None) -> Rule:
    """前置：本 tool 此前还没有被接受的调用（被接受之后不再重复调用）。"""
    judge = accepted or is_accepted

    def rule(history: History, call: Call) -> Optional[str]:
        if any(c.ok and judge(c) for c in history.of(call.tool)):
            return f"{call.tool} 此前已被接受，结果在之前的返回里，不再重复调用。"
        return None

    return rule


def cites_read(cite_arg: str, read_tool: str, read_arg: str) -> Rule:
    """前置：call.args[cite_arg] 里引用的每个编号，都在此前批次中被 read_tool 以 read_arg 成功读取过。"""

    def rule(history: History, call: Call) -> Optional[str]:
        cited = call.args.get(cite_arg)
        refs = cited if isinstance(cited, list) else [cited]
        read = {c.args.get(read_arg) for c in history.of(read_tool) if c.ok}
        unread = [ref for ref in refs if ref is not None and ref not in read]
        if not unread:
            return None
        return f"{call.tool} 引用了 {', '.join(map(str, unread))}；此前的批次中 {read_tool} 没有读取过这些编号。"

    return rule


def is_accepted(call: Call) -> bool:
    return isinstance(call.result, Mapping) and call.result.get("accepted") is True


class RequireDone(Hook):
    """这些 tool 都有被接受的调用才算做完。

    tools 也可以是 history → 清单的函数：清单要等运行中的某个结果出来才知道时（如先整理、才知道哪些轴要交）。
    """

    def __init__(self, tools: Union[Sequence[str], Callable[[History], Sequence[str]]],
                 accepted: Callable[[Call], bool] = is_accepted) -> None:
        self.tools = tools if callable(tools) else list(tools)
        self.accepted = accepted

    def stop(self, history: History, blocked: int) -> StopVerdict:
        tools = self.tools(history) if callable(self.tools) else self.tools
        missing = [t for t in tools if not any(c.ok and self.accepted(c) for c in history.of(t))]
        if not missing:
            return Done()
        return Continue(f"以下调用尚未被接受：{', '.join(missing)}。")


class BudgetStop(Hook):
    """LLM 轮次 / 工具调用数（含被拒的）/ 墙钟秒数，超出则 failed，无部分结果。

    段数上限由 max_blocked 表达（段数 = 拦回次数 + 1），这里不再重复。
    """

    def __init__(self, tool_calls: Optional[int] = None, seconds: Optional[float] = None,
                 *, llm_calls: Optional[int] = None) -> None:
        self.tool_calls = tool_calls
        self.seconds = seconds
        self.llm_calls = llm_calls

    def before_step(self, history: History) -> PreDecision:
        """只在新模型请求前检查轮次；最后允许轮次返回的整批工具仍正常执行。"""
        if self.llm_calls is not None and history.llm_calls >= self.llm_calls:
            return Abort(f"budget: llm_calls 已达上限 {self.llm_calls}")
        if self.seconds is not None and time.monotonic() - history.started_at > self.seconds:
            return Abort(f"budget: 已超过墙钟上限 {self.seconds:g}s")
        return Allow()

    def step_note(self, history: History) -> str:
        if self.llm_calls is None:
            return ""
        return (f"LLM 调用预算：已使用 {history.llm_calls}/{self.llm_calls} 轮，"
                f"剩余 {self.llm_calls - history.llm_calls} 轮（含本轮）；"
                "同一回复中的多个工具调用合计一轮。")

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        if self.tool_calls is not None and call.id >= self.tool_calls:
            return Abort(f"budget: tool_calls 已达上限 {self.tool_calls}")
        if self.seconds is not None and time.monotonic() - history.started_at > self.seconds:
            return Abort(f"budget: 已超过墙钟上限 {self.seconds:g}s")
        return Allow()


DEFAULT_BUDGET = BudgetStop(tool_calls=32)  # 无状态（只读 history），可在 loop 间共用
