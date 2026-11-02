"""ToolLoop 的运行记录、模型单步接口与 hook 协议；不依赖循环实现或业务项目。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, Union


@dataclass
class Call:
    """一次 tool 调用的记录。result 是 tool 返回的原始对象（未 JSON 化）。"""

    id: int  # 本次 loop 内的全局序号，从 0 开始；被拒的调用也占号
    tool: str  # 逻辑 tool_id（未知工具时是模型给的原始名字）
    args: dict
    batch: int  # 第几批（模型一次回复里的全部调用为一批）
    result: Any = None
    error: str = ""  # tool 执行抛异常 / 调用本身不合法（未知工具、参数不是 JSON 对象）
    denied: str = ""  # 被 pre_tool 拒绝 / 中止的原因

    @property
    def ok(self) -> bool:
        return not self.error and not self.denied


@dataclass
class History:
    """hook 之间唯一的共享状态。

    messages：OpenAI messages 协议（与 ContextRecord.messages 同形），每步请求后追加。
    calls：已结束批次的调用。pre_tool 看到的是「本调用所在批次之前」的全部调用——
    同一批里的调用互相不可见（与 Claude Code PreToolUse 每个调用独立判定一致）。
    """

    messages: list[dict] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    llm_calls: int = 0  # complete_step 次数；同批工具与客户端内部端点重试不另计轮次

    def of(self, tool: str) -> list[Call]:
        return [call for call in self.calls if call.tool == tool]


@dataclass(frozen=True)
class Allow:
    args: Optional[dict] = None  # 非 None 时替换本次调用的参数


@dataclass(frozen=True)
class Deny:
    reason: str  # 以 tool result 回给模型，写成事实陈述


@dataclass(frozen=True)
class Abort:
    reason: str  # 立刻结束整个 loop，结果为 failed


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class Continue:
    reason: str  # 作为下一条 user 消息，模型据此继续


@dataclass(frozen=True)
class Failed:
    reason: str


PreDecision = Union[Allow, Deny, Abort]
StopVerdict = Union[Done, Continue, Failed]


@dataclass(frozen=True)
class LoopContext:
    """外→内通道：同一次 loop 的每次模型请求共用 trace_id，stage 作为前缀。"""

    trace_id: str
    stage: str = ""


HOOK_EVENTS = ('start', 'pre_tool', 'post_tool', 'post_batch', 'stop')


class Hook:
    """事件处理器对象。只执行显式注册事件的方法，不自动注册整个对象。

    completion_hook 只绑定 stop；基础 Hook() 表示显式接受模型自行结束。
    辅助 hooks 通过 {事件名: [Hook, ...]} 注册。同一有状态对象可注册到多个事件。
    合成规则（同事件多个 hook）：
    - start / post_batch：返回的文本全部追加；
    - pre_tool：Abort > Deny > Allow；Deny 原因拼接；Allow(args) 按 hook 顺序链式替换；
    - post_tool：按 hook 顺序链式改写 call.result；
    - stop：Failed > Continue > Done；reason 拼接。
    """

    def start(self, history: History, ctx: LoopContext) -> Sequence[str]:
        return ()

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        return Allow()

    def post_tool(self, history: History, call: Call) -> Any:
        return call.result

    def post_batch(self, history: History, calls: Sequence[Call]) -> Sequence[str]:
        return ()

    def ready_to_finish(self, history: History) -> bool:
        """Completion policy may request stop after a completed batch, without another model step.

        False preserves model-driven stopping. True still runs all stop checks
        and end; it does not itself certify success or bypass budgeted tools.
        """
        return False

    def stop(self, history: History, blocked: int) -> StopVerdict:
        return Done()


@dataclass
class Step:
    """一次模型请求的产出：本次新增的 assistant 消息（OpenAI 形：content / tool_calls）。"""

    message: dict

    @property
    def text(self) -> str:
        return str(self.message.get("content") or "")

    @property
    def tool_calls(self) -> list[dict]:
        return list(self.message.get("tool_calls") or [])


class StepClient(Protocol):
    def complete_step(self, messages: list[dict], functions: list, *, trace_id: str, stage: str) -> Step:
        """恰好一次模型请求（实现：LlmClient.complete_step）。实现方必须：
        - 把 functions 的 schema 交给模型，但不执行任何工具调用，原样放进 Step.message.tool_calls；
        - 端点重试只重发这一次请求；全部失败时抛异常。
        """
        ...


@dataclass
class LoopResult:
    status: str  # complete | failed
    value: Any = None  # 仅 complete 时有值（end 的返回）
    reason: str = ""  # failed 的原因
    segments: int = 0
    llm_calls: int = 0
    calls: list[Call] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
