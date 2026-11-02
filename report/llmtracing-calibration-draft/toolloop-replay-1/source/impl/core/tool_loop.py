"""Tool loop：把「循环调用工具直到条件满足」做成一个可嵌套的原语。

设计见 spec/adapter/tool-loop-plan-20260922.md。一个 ToolLoop = system prompt + tools + hooks + loop：

- 循环由 ToolLoop 自己驱动：每一步恰好一次模型请求（StepClient.complete_step），模型给出的
  一批工具调用由这里逐个过 pre_tool → 执行 → post_tool，批尾过 post_batch，结果回放后再请求；
- 模型不再调工具即一段 segment 结束，这时问 stop hook：没做完就把 reason 作为 user 消息追加、再跑一段；
- 所有约束（依赖、必做清单、预算）都是 hook，基础层不认识这些词；
- ToolLoop.as_tool() 把整个 loop 暴露成一个普通 VerifiableTool，可以放进另一个 loop。

模型请求不在这里发：路由、降级、端点重试、超时、context 记录都在 LlmClient.complete_step，
且只覆盖单次请求——工具在请求之外执行，端点重试不会重复执行工具（与 OpenAI Agents SDK /
LangGraph 的 agent loop 同一分工）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, Sequence, Union

from impl.tools.protocol import VerifiableTool, _serialize_tool_result, build_agno_tools, runtime_tool_name


# ---------------------------------------------------------------------------
# History


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

    def of(self, tool: str) -> list[Call]:
        return [call for call in self.calls if call.tool == tool]


# ---------------------------------------------------------------------------
# Hook 协议


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


# 正在执行其工具调用的那一步的 ctx（stage 已带段号、步号）；嵌套的子 loop 从这里继承 trace_id 和 stage 前缀。
_step_ctx: ContextVar[LoopContext] = ContextVar("tool_loop_step_ctx")


class Hook:
    """六个挂点的默认实现都是空操作；场景 hook 只覆盖需要的挂点。

    合成规则（多个 hook）：
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

    def stop(self, history: History, blocked: int) -> StopVerdict:
        return Done()


# ---------------------------------------------------------------------------
# 模型调用接口（由 LlmClient 实现）


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


# ---------------------------------------------------------------------------
# ToolLoop


@dataclass
class LoopResult:
    status: str  # complete | failed
    value: Any = None  # 仅 complete 时有值（end 的返回）
    reason: str = ""  # failed 的原因
    segments: int = 0
    calls: list[Call] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


def last_assistant_text(history: History) -> str:
    for message in reversed(history.messages):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return ""


class ToolLoop:
    def __init__(
        self,
        id: str,
        system_prompt: str,
        tools: Sequence[VerifiableTool],
        client: StepClient,
        hooks: Sequence[Hook] = (),
        end: Callable[[History], Any] = last_assistant_text,
        max_blocked: int = 8,
        budget: Optional["BudgetStop"] = None,
    ) -> None:
        """budget 是内置的第一个 hook：max_blocked 只限段数，段内步数不设上限，
        没有预算时一个反复被拒的 tool 能让单段无限转下去。不传则用 DEFAULT_BUDGET。"""
        self.id = id
        self.system_prompt = system_prompt
        self.tools = list(tools)
        self.client = client
        self.budget = budget or DEFAULT_BUDGET
        self.hooks = [self.budget, *hooks]
        self.end = end
        self.max_blocked = max_blocked
        self._execute = {tool.tool_id: tool.execute_fn for tool in self.tools}
        self._by_runtime = {runtime_tool_name(tool.tool_id): tool.tool_id for tool in self.tools}

    def run(self, input: str, ctx: LoopContext) -> LoopResult:
        functions = build_agno_tools(self.tools)
        history = History(messages=[
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": input},
        ])
        notes = [note for hook in self.hooks for note in hook.start(history, ctx)]
        if notes:
            history.messages.append({"role": "user", "content": "\n".join(notes)})

        prefix = f"{ctx.stage}/{self.id}" if ctx.stage else self.id
        blocked = 0
        segments = 0
        batch = 0
        while True:
            step_index = 0
            while True:  # 一段：请求 → 执行这批调用 → 回放，直到模型不再调工具
                stage = f"{prefix}:s{segments}:r{step_index}"
                step = self.client.complete_step(history.messages, functions, trace_id=ctx.trace_id, stage=stage)
                history.messages.append(step.message)
                step_index += 1
                if not step.tool_calls:
                    break
                token = _step_ctx.set(LoopContext(trace_id=ctx.trace_id, stage=stage))
                try:
                    aborted = self._run_batch(history, step.tool_calls, batch)
                finally:
                    _step_ctx.reset(token)
                batch += 1
                if aborted:
                    return self._failed(history, aborted, segments + 1)
            segments += 1
            verdict = self._stop(history, blocked)
            if isinstance(verdict, Failed):
                return self._failed(history, verdict.reason, segments)
            if isinstance(verdict, Done):
                break
            if blocked >= self.max_blocked:
                return self._failed(history, f"max_blocked={self.max_blocked}: {verdict.reason}", segments)
            blocked += 1
            history.messages.append({"role": "user", "content": verdict.reason})

        return LoopResult(
            status="complete",
            value=self.end(history),
            segments=segments,
            calls=list(history.calls),
            messages=list(history.messages),
        )

    def _run_batch(self, history: History, tool_calls: list[dict], batch: int) -> str:
        """执行模型一次回复里的全部调用，结果按原顺序回放成 tool 消息；返回 Abort 原因（没有则空串）。

        Abort 之后同批剩下的调用不执行，但仍各回一条 aborted 结果（每个 tool_call 都要有配对的 tool 消息）。
        """
        calls: list[Call] = []
        aborted = ""
        for raw in tool_calls:
            call, invalid = self._parse(raw, len(history.calls) + len(calls), batch)
            calls.append(call)
            if aborted:
                call.denied = aborted
                view: Any = {"status": "aborted", "reason": aborted}
            else:
                # 不合法的调用不认识任何 hook 的语义，只过预算（否则一直乱调也停不下来）
                decision = self._pre_tool(history, call, [self.budget] if invalid else self.hooks)
                if isinstance(decision, Abort):
                    call.denied = aborted = decision.reason
                    view = {"status": "aborted", "reason": aborted}
                elif isinstance(decision, Deny):
                    call.denied = decision.reason
                    view = {"status": "denied", "reason": decision.reason}
                elif invalid:
                    call.error = invalid
                    view = call.result = {"status": "error", "error": invalid}
                else:
                    view = self._execute_call(history, call)
            history.messages.append({"role": "tool", "tool_call_id": raw.get("id"),
                                     "content": _serialize_tool_result(view)})
        history.calls.extend(calls)
        if aborted:
            return aborted
        notes = [note for hook in self.hooks for note in hook.post_batch(history, calls)]
        if notes:
            history.messages.append({"role": "user", "content": "\n".join(notes)})
        return ""

    def _parse(self, raw: dict, id: int, batch: int) -> tuple[Call, str]:
        """模型给的原始 tool_call → (Call, 不合法原因)。"""
        function = raw.get("function") or {}
        name = str(function.get("name") or "")
        tool = self._by_runtime.get(name)
        text = function.get("arguments")
        try:
            args = json.loads(text) if isinstance(text, str) and text.strip() else (text or {})
        except json.JSONDecodeError as exc:
            args, problem = {}, f"arguments 不是合法 JSON：{exc}"
        else:
            problem = "" if isinstance(args, dict) else "arguments 必须是 JSON 对象"
            args = args if isinstance(args, dict) else {}
        if tool is None:
            problem = f"没有名为 {name!r} 的工具；可用：{', '.join(sorted(self._by_runtime))}"
        return Call(id=id, tool=tool or name, args=dict(args), batch=batch), problem

    def _execute_call(self, history: History, call: Call) -> Any:
        try:
            call.result = self._execute[call.tool](**call.args)
        except Exception as exc:  # tool 失败交给模型看，不中断 loop
            call.error = f"{type(exc).__name__}: {exc}"
            call.result = {"status": "error", "error": call.error}
        for hook in self.hooks:
            call.result = hook.post_tool(history, call)
        return call.result

    @staticmethod
    def _pre_tool(history: History, call: Call, hooks: Sequence[Hook]) -> PreDecision:
        denies = []
        for hook in hooks:
            decision = hook.pre_tool(history, call)
            if isinstance(decision, Abort):
                return decision
            if isinstance(decision, Deny):
                denies.append(decision.reason)
            elif decision.args is not None:
                call.args = dict(decision.args)
        return Deny("\n".join(denies)) if denies else Allow()

    def as_tool(
        self,
        description: str,
        parameters: dict,
        render: Optional[Callable[[dict], str]] = None,
    ) -> VerifiableTool:
        """把整个 loop 暴露成一个 tool：父层只拿到 end 的返回（或失败事实），不拿 history。

        render 把父层给的参数变成子 loop 的 user 输入（默认 JSON）；子 loop 的材料由程序备好、
        不经父模型转述时，用它注入。只能在父 loop 执行工具调用时被调用：trace_id 与 stage 前缀取自那一步。
        """
        to_input = render or (lambda args: json.dumps(args, ensure_ascii=False, sort_keys=True))

        def execute(**args: Any) -> Any:
            parent = _step_ctx.get(None)
            if parent is None:
                raise RuntimeError(f"{self.id}: as_tool() 只能在父 ToolLoop 的工具调用里执行")
            result = self.run(to_input(args), parent)
            if result.status == "complete":
                return result.value
            return {"status": "failed", "loop": self.id, "reason": result.reason}

        return VerifiableTool(tool_id=self.id, description=description, parameters=parameters, execute_fn=execute)

    def _stop(self, history: History, blocked: int) -> StopVerdict:
        verdicts = [hook.stop(history, blocked) for hook in self.hooks]
        failed = [v.reason for v in verdicts if isinstance(v, Failed)]
        if failed:
            return Failed("\n".join(failed))
        pending = [v.reason for v in verdicts if isinstance(v, Continue)]
        if pending:
            return Continue("\n".join(pending))
        return Done()

    @staticmethod
    def _failed(history: History, reason: str, segments: int) -> LoopResult:
        return LoopResult(
            status="failed",
            reason=reason,
            segments=segments,
            calls=list(history.calls),
            messages=list(history.messages),
        )


# ---------------------------------------------------------------------------
# 常用 hook（场景层；基础层不依赖它们）

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
    """工具调用数（含被拒的）/ 墙钟秒数，任一超出就中止 loop（failed，无部分结果）。

    段数上限由 max_blocked 表达（段数 = 拦回次数 + 1），这里不再重复。
    """

    def __init__(self, tool_calls: Optional[int] = None, seconds: Optional[float] = None) -> None:
        self.tool_calls = tool_calls
        self.seconds = seconds

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        if self.tool_calls is not None and call.id >= self.tool_calls:
            return Abort(f"budget: tool_calls 已达上限 {self.tool_calls}")
        if self.seconds is not None and time.monotonic() - history.started_at > self.seconds:
            return Abort(f"budget: 已超过墙钟上限 {self.seconds:g}s")
        return Allow()


DEFAULT_BUDGET = BudgetStop(tool_calls=32)  # 无状态（只读 history），可在 loop 间共用


def take_accepted(*tools: str, accepted: Callable[[Call], bool] = is_accepted) -> Callable[[History], Any]:
    """end：返回每个 tool 最后一次被接受调用的参数；只给一个 tool 时直接返回它的参数。"""

    def end(history: History) -> Any:
        values = {}
        for tool in tools:
            hits = [c for c in history.of(tool) if c.ok and accepted(c)]
            values[tool] = hits[-1].args if hits else None
        return values[tools[0]] if len(tools) == 1 else values

    return end
