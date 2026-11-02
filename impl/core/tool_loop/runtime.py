"""Tool loop：把「循环调用工具直到条件满足」做成一个可嵌套的原语。

设计见 spec/adapter/tool-loop-plan-20260922.md。
一个 ToolLoop = system prompt + tools + completion_hook + 按事件注册的 hooks + loop：

- 循环由 ToolLoop 自己驱动：每一步恰好一次模型请求（StepClient.complete_step），模型给出的
  一批工具调用由这里逐个过 pre_tool → 执行 → post_tool，批尾过 post_batch，结果回放后再请求；
  标了 concurrent 的工具（只读、不调模型、等外部 I/O）同批里同时执行，pre_tool / post_tool / 回放仍按原顺序；
- 模型不再调工具即申请结束：调用必填的 completion_hook 与辅助 stop hooks；没做完就反馈 reason 再跑一段；
- 所有约束（依赖、必做清单、预算）都是 hook，基础层不认识这些词；
- ToolLoop.as_tool() 把整个 loop 暴露成一个普通 VerifiableTool，可以放进另一个 loop。

模型请求不在这里发：路由、降级、端点重试、超时、context 记录都在 LlmClient.complete_step，
且只覆盖单次请求——工具在请求之外执行，端点重试不会重复执行工具（与 OpenAI Agents SDK /
LangGraph 的 agent loop 同一分工）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from typing import Any, Callable, Optional, Sequence

from impl.tools.protocol import VerifiableTool, _serialize_tool_result, build_agno_tools, runtime_tool_name

from .hooks import BudgetStop, DEFAULT_BUDGET
from .outputs import last_assistant_text
from .types import (
    Abort, Allow, Call, Deny, Done, Failed, History, Hook, HOOK_EVENTS,
    LoopContext, LoopResult, PreDecision, StepClient, StopVerdict, Continue,
)


# 正在执行其工具调用的那一步的 ctx（stage 已带段号、步号）；嵌套的子 loop 从这里继承 trace_id 和 stage 前缀。
_step_ctx: ContextVar[LoopContext] = ContextVar("tool_loop_step_ctx")


class ToolLoop:
    def __init__(
        self,
        id: str,
        system_prompt: str,
        tools: Sequence[VerifiableTool],
        client: StepClient,
        *,
        completion_hook: Hook,
        hooks: Optional[Mapping[str, Sequence[Hook]]] = None,
        end: Callable[[History], Any] = last_assistant_text,
        max_blocked: int = 8,
        budget: Optional["BudgetStop"] = None,
    ) -> None:
        """completion_hook 必填；hooks 只能是事件字典，不接收旧匿名列表。

        budget 内置于模型请求前和 pre_tool 首位：max_blocked 只限段数，段内靠预算防止无限调用。
        不传 budget 则用 DEFAULT_BUDGET。注册字典与列表在构造时复制，hook 对象仍由实例持有。
        """
        if not isinstance(completion_hook, Hook):
            raise TypeError('completion_hook 必须是 Hook 对象，并通过 stop 返回完成决定')
        registry = {} if hooks is None else hooks
        if not isinstance(registry, Mapping):
            raise TypeError('hooks 必须是 {事件名: [Hook, ...]} 字典，不接受匿名 hook 列表')
        unknown = set(registry) - set(HOOK_EVENTS)
        if unknown:
            raise ValueError(f'未知 hook 事件：{list(unknown)}；支持 {HOOK_EVENTS}')
        self.hooks: dict[str, tuple[Hook, ...]] = {}
        for event in HOOK_EVENTS:
            handlers = registry.get(event, ())
            if (not isinstance(handlers, Sequence) or isinstance(handlers, (str, bytes))
                    or any(not isinstance(h, Hook) for h in handlers)):
                raise TypeError(f'hooks[{event!r}] 必须是 Hook 对象序列')
            self.hooks[event] = tuple(handlers)
        if any(h is completion_hook for h in self.hooks['stop']):
            raise ValueError('completion_hook 不能重复注册到辅助 stop hooks')
        self.id = id
        self.system_prompt = system_prompt
        self.tools = list(tools)
        self.client = client
        self.completion_hook = completion_hook
        self.budget = budget or DEFAULT_BUDGET
        self.end = end
        self.max_blocked = max_blocked
        self._execute = {tool.tool_id: tool.execute_fn for tool in self.tools}
        self._concurrent = {tool.tool_id for tool in self.tools if tool.concurrent}
        self._by_runtime = {runtime_tool_name(tool.tool_id): tool.tool_id for tool in self.tools}

    def run(self, input: str, ctx: LoopContext) -> LoopResult:
        functions = build_agno_tools(self.tools)
        history = History(messages=[
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": input},
        ])
        notes = [note for hook in self.hooks['start'] for note in hook.start(history, ctx)]
        if notes:
            history.messages.append({"role": "user", "content": "\n".join(notes)})

        prefix = f"{ctx.stage}/{self.id}" if ctx.stage else self.id
        blocked = 0
        segments = 0
        batch = 0
        while True:
            step_index = 0
            while True:  # 一段：请求 → 执行这批调用 → 回放，直到模型不再调工具
                decision = self.budget.before_step(history)
                if isinstance(decision, Abort):
                    return self._failed(history, decision.reason, segments + 1)
                note = self.budget.step_note(history)
                if note:
                    history.messages.append({"role": "user", "content": note})
                stage = f"{prefix}:s{segments}:r{step_index}"
                history.llm_calls += 1
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
                if self.completion_hook.ready_to_finish(history):
                    break
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
            llm_calls=history.llm_calls,
            calls=list(history.calls),
            messages=list(history.messages),
        )

    def _run_batch(self, history: History, tool_calls: list[dict], batch: int) -> str:
        """执行模型一次回复里的全部调用，结果按原顺序回放成 tool 消息；返回 Abort 原因（没有则空串）。

        pre_tool 按原顺序逐个过；放行的调用里 concurrent 的同时执行，其余按顺序执行；post_tool 与回放按原顺序。
        Abort 之后同批剩下的调用不执行，但仍各回一条 aborted 结果（每个 tool_call 都要有配对的 tool 消息）。
        """
        calls: list[Call] = []
        views: list[Any] = []
        run: set[int] = set()   # 放行执行了的调用（按 call.id）
        aborted = ""
        with ThreadPoolExecutor(max_workers=max(1, len(tool_calls))) as pool:
            for raw in tool_calls:
                call, invalid = self._parse(raw, len(history.calls) + len(calls), batch)
                calls.append(call)
                view: Any = None
                if aborted:
                    call.denied = aborted
                    view = {"status": "aborted", "reason": aborted}
                else:
                    # 不合法的调用不认识任何 hook 的语义，只过预算（否则一直乱调也停不下来）
                    before = [self.budget] if invalid else [self.budget, *self.hooks['pre_tool']]
                    decision = self._pre_tool(history, call, before)
                    if isinstance(decision, Abort):
                        call.denied = aborted = decision.reason
                        view = {"status": "aborted", "reason": aborted}
                    elif isinstance(decision, Deny):
                        call.denied = decision.reason
                        view = {"status": "denied", "reason": decision.reason}
                    elif invalid:
                        call.error = invalid
                        view = call.result = {"status": "error", "error": invalid}
                    elif call.tool in self._concurrent:
                        run.add(call.id)
                        pool.submit(copy_context().run, self._invoke, call)  # 出 with 时等齐
                    else:
                        run.add(call.id)
                        self._invoke(call)
                views.append(view)
        for i, call in enumerate(calls):
            if call.id in run:
                views[i] = self._post_tool(history, call)
            history.messages.append({"role": "tool", "tool_call_id": tool_calls[i].get("id"),
                                     "content": _serialize_tool_result(views[i])})
        history.calls.extend(calls)
        if aborted:
            return aborted
        notes = [note for hook in self.hooks['post_batch'] for note in hook.post_batch(history, calls)]
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

    def _invoke(self, call: Call) -> None:
        try:
            call.result = self._execute[call.tool](**call.args)
        except Exception as exc:  # tool 失败交给模型看，不中断 loop
            call.error = f"{type(exc).__name__}: {exc}"
            call.result = {"status": "error", "error": call.error}

    def _post_tool(self, history: History, call: Call) -> Any:
        for hook in self.hooks['post_tool']:
            call.result = hook.post_tool(history, call)
        return call.result

    @staticmethod
    def _pre_tool(history: History, call: Call, hooks: Sequence[Hook]) -> PreDecision:
        denies = []
        for hook in hooks:
            decision = hook.pre_tool(history, call)
            if not isinstance(decision, (Allow, Deny, Abort)):
                raise TypeError('pre_tool 必须返回 Allow / Deny / Abort')
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
        # 核心完成条件始终参与；辅助 Done 不能覆盖其 Continue / Failed。
        verdicts = [hook.stop(history, blocked) for hook in [self.completion_hook, *self.hooks['stop']]]
        if any(not isinstance(v, (Done, Continue, Failed)) for v in verdicts):
            raise TypeError('completion_hook / stop 必须返回 Done / Continue / Failed')
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
            llm_calls=history.llm_calls,
            calls=list(history.calls),
            messages=list(history.messages),
        )
