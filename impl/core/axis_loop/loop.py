"""AxisLoop：一个 case 跑几个 loop（spec/alg/axis_loop.md §1、§5、§6、§9、§10）。

loop 定义三种启动方式：start=case（case 开始就起，恰好一个）、ready（它等的、别的 loop 里的任务都齐了，由台账起；
可按分发起几份）、tool（被模型当工具调用，原公共 loop 工具；只嵌一层）。每个 loop 都搭在 ToolLoop 上，只用它现有的 hook：
- start / post_batch：本 loop 台账结算 → 推送新任务、作废、撤下；程序任务当场合成；case loop 结算时一个一个起已齐的 ready loop
- pre_tool：submit 走验收流水线；信息源工具与被调用启动的 loop 按门禁放行
- post_tool：给每个返回盖 call_id
- stop / ready_to_finish：本 loop 出现过的任务都完成
状态表、材料表、事件、预算、致命错误整个 case 共用一份。
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Protocol, Sequence

from impl.core.tool_loop import (
    Abort, Allow, BudgetStop, Call, Continue, Deny, Done, Failed, History, Hook, LoopContext, PreDecision,
    StepClient, StopVerdict, ToolLoop)
from impl.tools.protocol import VerifiableTool, _serialize_tool_result

from . import acceptance
from .acceptance import Submissions, SynthesisError
from .checks import SUBLOOP_CATEGORY
from .definitions import START_READY, SUBMIT_PER_ITEM, AxisDef, Definitions, Dependency, Work
from .ledger import ABSENT, DONE, HIDDEN, Change, Event, Ledger
from .materials import BUILTIN_SPACES, MaterialTable, MaterialUnavailable, parse_entry, render
from .reader import Reader, summarize
from .text import dump
from .validate import check_entry
from .view import CallView, TaskView

SUBMIT, RECALL = "submit", "recall"
AXIS_NOTE = "axis.note"

SYSTEM = """你是评测员，在一个 case 上完成一组评测任务。任务由程序陆续推送：一开始只给没有前置的任务，
某个任务被接受后，依赖它的任务才会出现。每个任务写明了说明、材料、可用工具和提交格式。

规则：
1. 按任务说明判；只依据给你的材料和工具返回，不凭自己的知识。
2. 用 submit 交：task_id 写任务名，payload 照提交格式写。分条交的任务每个分项单独交（带 item_id），全部交完再不带 item_id 交一次收尾。
3. 被拒就按原因改了再交。几个任务可以交错做。
4. 引用写成 {"ref": 出处, "quote": 原文}：出处是工具返回里的 call_id，或材料的标题；quote 从原文逐字摘，不改写、不拼接。
5. 同一次回复里拿到的工具返回，要到下一次回复才能引用。
6. 已经交过的任务发现交错了，可以重交来修改；依赖它的任务会被作废，需要重做。
7. 工具返回太长时会被归档，用 recall(call_id) 重看。
8. 材料太大时只给目录：用 read_material 按编号取正文，或 search_material 按关键词找；该看的都要看，依据要充分。
   按目录里的大小挑要看的编号，ids 可以写多个。
   读回来的「〔同 X 里已给过的那段〕」表示这段正文和 X 里的一字不差，要引用就引 X；「〔预览…〕」是太长只给了开头，需要全文按里面写的 path 加 full=true 再读。
9. 互不依赖的工具调用，放在同一次回复里一起发：要读的几份材料、要查的几项数据、已经判完的几个任务，一次发出。后一个调用要用到前一个的返回时（先看结构再下钻、按搜索结果去取、交结果要引用刚取回的证据），才留到下一次回复，因为同一次回复里拿到的返回要到下一次回复才能引用。工具执行得很快，慢的是回复的来回次数。
10. 唯一性原则：一件事只给一份，一份只装一件事。
   - 一件事只给一份："同一件"看实质——同一个对象、同一件事、同样的内容，换了叫法、编号或措辞也是同一件；出现在几处也只给一份，用到它的地方引用这一份；只去掉重复的部分，判断要用的内容不少给。
   - 一份只装一件事：列之后要逐条判定的条目（说法、期望、本应清单等）时，一条里的几件事有可能一件成立、一件不成立，就拆成几条；拆到每条单独读仍然意思完整为止，几条合起来正好是原来的意思。
全部任务完成后不需要再写总结。"""

SUBLOOP_SYSTEM = """你在一个独立的上下文里完成一件任务：只看下面给你的材料和工具返回，按说明做，用 submit 交（task_id 写任务名）。
被拒就按原因改了再交。引用写成 {"ref": call_id, "quote": 原文}，quote 逐字摘自那次返回；同一次回复里拿到的返回要到下一次回复才能引用。
工具返回太长时会被归档，用 recall(call_id) 重看。材料太大时只给目录，用 read_material / search_material 读。互不依赖的工具调用放在同一次回复里一起发（要读的几份材料、要查的几项数据、已查完的几条一起交）；后一个调用要用前一个的返回时才留到下一次回复，因为同一次回复里拿到的返回要到下一次回复才能引用。工具执行得很快，慢的是回复的来回次数。交完不需要再写总结。"""


class Sources(Protocol):
    """信息源：工具（固定在工具列表里）+ 每次调用属于哪个类别、哪条登记。"""

    tools: Sequence[VerifiableTool]

    def route(self, call: Call) -> tuple[str, str]:
        """(类别, 登记)；不是信息源调用为 ("", "")。"""

    def instances(self, category: str) -> list[str]:
        """场景选用的这个类别的登记。"""

    def describe(self, category: str, instances: Sequence[str]) -> str:
        """推送给模型的说明：这些信息源有哪些工具、怎么读。"""

    # 可选：check(instance) -> str。登记了检查工具的实例，返回不可用的说明；可用或不查返回 ""（§8.1）。


@dataclass
class Settings:
    llm_calls: int
    tool_calls: int
    seconds: float
    context_limit_tokens: int = 200_000
    archive_ratio: float = 0.8
    chars_per_token: float = 2.0
    max_blocked: int = 8
    material_inline_chars: int = 20_000


@dataclass
class RunState:
    """主 loop 与各子 loop 共用：全局用量与致命错误。"""

    settings: Settings
    started: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    tool_calls: int = 0
    fatal: str = ""
    archived: int = 0


class LoopFailed(RuntimeError):
    """一个 ready loop 没跑成：整个 case 记运行失败。"""


class Governor(BudgetStop):
    """全局预算 + 致命错误 + 上下文归档。每个 loop 一个实例，共用 RunState。"""

    def __init__(self, run: RunState) -> None:
        super().__init__()
        self.run = run

    def _limits(self) -> Optional[str]:
        s = self.run.settings
        if self.run.fatal:
            return self.run.fatal
        if self.run.llm_calls >= s.llm_calls:
            return f"budget: llm_calls 已达全局上限 {s.llm_calls}"
        if time.monotonic() - self.run.started > s.seconds:
            return f"budget: 已超过全局墙钟上限 {s.seconds:g}s"
        return None

    def before_step(self, history: History) -> PreDecision:
        if why := self._limits():
            return Abort(why)
        if why := self._fit_context(history):
            self.run.fatal = why
            return Abort(why)
        self.run.llm_calls += 1
        return Allow()

    def step_note(self, history: History) -> str:
        return ""

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        if self.run.fatal:
            return Abort(self.run.fatal)
        if self.run.tool_calls >= self.run.settings.tool_calls:
            return Abort(f"budget: tool_calls 已达全局上限 {self.run.settings.tool_calls}")
        self.run.tool_calls += 1
        return Allow()

    def _tokens(self, history: History) -> float:
        return sum(len(str(m.get("content") or "")) for m in history.messages) / self.run.settings.chars_per_token

    def _fit_context(self, history: History) -> str:
        """接近上限就把较早的工具返回换成归档提示（原文仍在调用记录里，recall 可重看）；仍超限 → 失败原因。"""
        s = self.run.settings
        if self._tokens(history) <= s.context_limit_tokens * s.archive_ratio:
            return ""
        last_batch = max((c.batch for c in history.calls), default=-1)
        recent = {c.id for c in history.calls if c.batch == last_batch}
        returns = []
        for message in history.messages:
            content = message.get("content")
            if message.get("role") != "tool" or not isinstance(content, str) or content.startswith("[已归档]"):
                continue
            try:
                ref = str(json.loads(content).get("call_id", ""))
            except (ValueError, AttributeError):
                ref = ""
            if ref:
                number = re.search(r"c(\d+)$", ref)  # call_id = 前缀 + c<调用序号>
                returns.append((bool(number) and int(number.group(1)) in recent, ref, message))
        # 先归档旧批次的；仍超阈值，同一批的也按先后归档，只留最后一份（spec/alg/axis_loop.md §9 第 2b 条）。
        same_batch = [r for r in returns if r[0]][:-1]
        for _, ref, message in [r for r in returns if not r[0]] + same_batch:
            if self._tokens(history) <= s.context_limit_tokens * s.archive_ratio:
                break
            message["content"] = f"[已归档] call_id={ref}，需要时用 recall(call_id) 重看"
            self.run.archived += 1
        if self._tokens(history) > s.context_limit_tokens:
            return f"上下文超限：归档后仍约 {int(self._tokens(history))} tokens，上限 {s.context_limit_tokens}"
        return ""


def _is_error(result: Any) -> bool:
    return isinstance(result, Mapping) and bool(result.get("isError") or result.get("error") or result.get("status") == "failed")


def submit_tool(names: Sequence[str]) -> VerifiableTool:
    return VerifiableTool(
        tool_id=SUBMIT, execute_fn=lambda **_: {"accepted": True},
        description="交一个任务的结果。合规返回 accepted=true；不合规会被拒并给出原因，改了再交。",
        parameters={"type": "object", "properties": {
            "task_id": {"type": "string", "enum": list(names), "description": "任务名"},
            "item_id": {"type": "string", "description": "分条交的任务：分项编号；交收尾时不填"},
            "payload": {"type": "object", "description": "按该任务的提交格式写的内容"}},
            "required": ["task_id", "payload"]})


def _format(work: Work) -> str:
    if work.submit == SUBMIT_PER_ITEM:
        return (f"分条交：每个分项 submit(task_id={work.id!r}, item_id=<分项编号，写进 {work.item_key}>, payload=分项)，"
                f"分项格式：{dump(acceptance.item_payload_schema(work))}\n"
                f"全部分项交完后 submit(task_id={work.id!r}, payload=收尾)，收尾格式：{dump(work.model_schema())}")
    return f"一次交齐：submit(task_id={work.id!r}, payload=...)，格式：{dump(work.model_schema())}"


class _Base(Hook):
    """三种 loop 共用：盖 call_id、组视图、recall、信息源与公共 loop 工具的门禁。"""

    def __init__(self, loop: "AxisLoop", prefix: str, shared: Sequence[str]) -> None:
        self.loop = loop
        self.sources = loop.sources
        self.prefix = prefix
        self.shared = set(shared)
        self.history: Optional[History] = None

    def call_id(self, call: Call) -> str:
        return f"{self.prefix}c{call.id}"

    def post_tool(self, history: History, call: Call) -> Any:
        if call.tool == SUBMIT or not isinstance(call.result, Mapping):
            return call.result
        return {**call.result, "call_id": self.call_id(call)}

    def post_batch(self, history: History, calls: Sequence[Call]) -> Sequence[str]:
        for call in calls:
            if call.tool in self.shared and isinstance(call.result, Mapping) and call.result.get("status") == "failed":
                self.loop.run_state.fatal = self.loop.run_state.fatal or f"被调用启动的 loop {call.tool} 失败：{call.result.get('reason')}"
        return ()

    def category(self, call: Call) -> str:
        return SUBLOOP_CATEGORY if call.tool in self.shared else self.sources.route(call)[0]

    def call_views(self, history: History) -> list[CallView]:
        out = []
        for call in history.calls:
            if call.tool in (SUBMIT, RECALL) or call.denied:
                continue
            result = call.result
            structured = result.get("structuredContent") if isinstance(result, Mapping) else None
            if call.tool in self.shared and isinstance(result, Mapping):
                structured = result.get("result")
            out.append(CallView(self.call_id(call), call.tool, self.category(call), dict(call.args), call.batch,
                                str(_serialize_tool_result(result) or ""), structured, not call.ok or _is_error(result)))
        return out

    def view(self, history: History, entries: Sequence[str], own: Mapping[str, Any], stage: str, axis_id: str,
             params: Mapping[str, Any] | None = None, parts: Sequence[Mapping[str, Any]] = ()) -> TaskView:
        chosen = [parse_entry(t) for t in entries]
        # 本轴描述同任务文本一样放进来：代码读的范围与所属的轴相同（spec/alg/axis_loop.md §2.5）
        if axis_id and self.loop.table.registry.get(AXIS_NOTE) and AXIS_NOTE not in entries:
            chosen.append(parse_entry(AXIS_NOTE))
        materials = self.loop.table.for_code(chosen, axis_id)
        return TaskView(axis_id, own, materials, dict(params or {}), self.call_views(history), stage, tuple(parts))

    def recall_tool(self) -> VerifiableTool:
        def recall(call_id: str) -> Any:
            history = self.history or History()
            call = next((c for c in history.calls if self.call_id(c) == call_id), None)
            if call is None:
                return {"isError": True, "error": f"没有 call_id={call_id} 的调用"}
            return {"recalled": call_id, "result": call.result}
        return VerifiableTool(tool_id=RECALL, execute_fn=recall, description="重看一次已归档的工具返回原文。",
                              parameters={"type": "object", "properties": {
                                  "call_id": {"type": "string", "description": "要重看的 call_id"}}, "required": ["call_id"]})

    def gate_tool(self, call: Call, instances: Mapping[str, set[str]], shared: set[str]) -> PreDecision:
        if call.tool in self.shared:
            return Allow() if call.tool in shared else Deny(f"{call.tool} 现在不能用：还没有出现选用它的任务")
        category, instance = self.sources.route(call)
        if category and instance not in instances.get(category, set()):
            return Deny(f"{instance or category} 现在不能用：这个任务没有选用它")
        return Allow()


class _Submitter(_Base):
    """只做一份工作的子 loop（独立运行的轴的一份、公共 loop 工具的一次调用）：收尾被接受即完成。"""

    def __init__(self, loop: "AxisLoop", work: Work, axis_id: str, entries: Sequence[str], prefix: str,
                 shared: Sequence[str], users: Sequence[str], params: Mapping[str, Any] | None = None) -> None:
        super().__init__(loop, prefix, shared)
        self.work, self.axis_id, self.entries, self.params = work, axis_id, list(entries), dict(params or {})
        self.state = Submissions()
        self.instances = {c.category: {i for k in users for i in loop.allowed_instances(k, c.category)}
                          for c in work.tool_categories}

    def start(self, history: History, ctx: LoopContext) -> Sequence[str]:
        self.history = history
        return ()

    def readable(self) -> dict[str, Any]:
        return self.loop.table.view([parse_entry(t) for t in self.entries], self.axis_id)

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        self.history = history
        if call.tool != SUBMIT:
            return self.gate_tool(call, self.instances, self.shared)
        if call.args.get("task_id") != self.work.id:
            return Deny(f"task_id 只能是 {self.work.id}")
        make_view = lambda stage, own: self.view(history, self.entries, own, stage, self.axis_id, self.params)
        try:
            outcome = acceptance.submit(self.work, self.state, call.args.get("payload"), call.args.get("item_id") or None, make_view)
        except SynthesisError as exc:
            self.loop.run_state.fatal = str(exc)
            return Abort(str(exc))
        if outcome.explain is not None:
            return Deny(acceptance.explain_text(self.work.id, outcome.explain))
        if not outcome.accepted:
            return Deny("submit 被拒：" + "；".join(outcome.reasons))
        return Allow()

    def ready_to_finish(self, history: History) -> bool:
        return self.state.result is not None or bool(self.loop.run_state.fatal)

    def stop(self, history: History, blocked: int) -> StopVerdict:
        if self.loop.run_state.fatal:
            return Failed(self.loop.run_state.fatal)
        return Done() if self.state.result is not None else Continue(f"还没有被接受的提交；用 submit(task_id={self.work.id!r}) 交。")


def _task_text(loop: "AxisLoop", work: Work, axis_id: str, entries: Sequence[str], title: str, shared: Sequence[str],
               users: Sequence[str], params: Mapping[str, Any] | None = None) -> str:
    parts = [title, "说明：" + work.instruction]
    chosen = [parse_entry(t) for t in entries]
    if axis_id and loop.table.registry.get(AXIS_NOTE) and AXIS_NOTE not in entries:
        chosen.insert(0, parse_entry(AXIS_NOTE))
    limit = loop.run_state.settings.material_inline_chars
    values = {title: summarize(title, value, limit) for title, value in loop.table.view(chosen, axis_id).items()}
    if values:
        parts.append("材料：\n" + render(values))
    if params:
        parts.append("调用参数：\n" + dump(params))
    tools = []
    for cat in work.tool_categories:
        instances = sorted({i for k in users for i in loop.allowed_instances(k, cat.category)})
        if instances:
            tools.append(loop.sources.describe(cat.category, instances))
    for name in shared:
        if name in loop.withheld:
            tools.append(f"工具 {name}：本场景不可用（场景没选 {'、'.join(loop.withheld[name])} 类信息源）")
        else:
            tools.append(f"工具 {name}：{loop.defs.shared_tools[name].description}")
    if tools:
        parts.append("可用工具：\n" + "\n".join(tools))
    parts.append("提交：" + _format(work))
    return "\n".join(parts)


class _SharedTool:
    """公共 loop 工具 = 一个工具：每次调用新开一个 ToolLoop（各自的提交状态），材料按它的白名单、加上参数。"""

    def __init__(self, loop: "AxisLoop", name: str) -> None:
        self.loop, self.name, self.tool_def = loop, name, loop.defs.shared_tools[name]

    def tool(self) -> VerifiableTool:
        params = dict(self.tool_def.params) or {"type": "object", "properties": {}, "required": []}
        return VerifiableTool(tool_id=self.name, description=self.tool_def.description, parameters=params, execute_fn=self.execute)

    def execute(self, **params: Any) -> Any:
        problems = acceptance.schema_errors(self.tool_def.params, params) if self.tool_def.params else []
        if problems:
            return {"status": "error", "isError": True, "error": "参数不对：" + "；".join(problems)}
        work, users = self.tool_def, self.loop.users_of(self.name)
        gate = _Submitter(self.loop, work, "", work.materials, f"{self.name}#{self.loop.run_state.tool_calls}.", (), users, params)
        text = _task_text(self.loop, work, "", work.materials, f"【任务 {work.id}】", (), users, params)
        tools = [submit_tool([work.id]), gate.recall_tool(), *Reader(gate.readable, self.loop.run_state.settings.material_inline_chars).tools(),
                 *(self.loop.sources.tools if work.tool_categories else [])]
        child = ToolLoop(self.name, SUBLOOP_SYSTEM, tools, self.loop.client, completion_hook=gate,
                         hooks={"start": [gate], "pre_tool": [gate], "post_tool": [gate]},
                         end=lambda history: {"result": gate.state.result}, budget=Governor(self.loop.run_state),
                         max_blocked=self.loop.run_state.settings.max_blocked)
        # 嵌在调用方那一步里跑：as_tool 让它继承调用方的 trace_id 与 stage。
        value = child.as_tool(work.description, self.tool().parameters, render=lambda args: text).execute_fn(**params)
        failed = isinstance(value, Mapping) and value.get("status") == "failed"
        self.loop.ledger.events.append(Event(self.loop.batch, "shared_tool", self.name,
                                             reasons=(f"failed: {value.get('reason')}",) if failed else ("complete",)))
        return {**value, "isError": True} if failed else value


@dataclass
class LoopReport:
    status: str
    reason: str
    results: Mapping[str, Optional[Mapping[str, Any]]]
    states: Mapping[str, str]
    events: list[Event]
    llm_calls: int
    tool_calls: int
    seconds: float
    archived: int
    messages: list[dict]
    loops: list[dict] = field(default_factory=list)   # 每个 loop 一条：{id, status, reason, llm_calls, tool_calls, seconds}


class AxisLoop:
    """一个 case 的运行器：起 case loop，按依赖一个一个起 ready loop（§6.1）。"""

    def __init__(self, defs: Definitions, enabled: Sequence[str], table: MaterialTable, sources: Sources,
                 client: StepClient, settings: Settings, *, axis_sources: Mapping[str, Sequence[str]] | None = None) -> None:
        """axis_sources：场景里各轴挑的信息源登记（不挑 = 该类别下场景选用的全部）。"""
        self.defs = defs
        self.table = table
        self.sources = sources
        self.client = client
        self.run_state = RunState(settings)
        self.axis_sources = {k: list(v) for k, v in (axis_sources or {}).items()}
        self.enabled = list(enabled)
        self.state: dict[str, str] = {k: HIDDEN for k in self.enabled}
        for k in self.enabled:
            table.results[k] = None
        self.events: list[Event] = []
        self.loop_of = {k: defs.axes[k].loop for k in self.enabled}
        self.ready_loops = [l for l, d in defs.loops.items() if d.start == START_READY and defs.members(l, self.enabled)]
        self.done_loops: set[str] = set()
        self.loop_stats: list[dict] = []
        # 被调用启动的 loop 要的必需信息源，选用它的轴一个都没挑到 → 这个 case 不提供它，任务文本里写明（§6.3）
        self.withheld: dict[str, list[str]] = {}
        for name in sorted({t for k in self.enabled for t in defs.axes[k].tools}):
            lack = [c.category for c in defs.shared_tools[name].tool_categories
                    if c.required and not any(self.allowed_instances(k, c.category) for k in self.users_of(name))]
            if lack:
                self.withheld[name] = lack
        self.shared_impl = {name: _SharedTool(self, name) for name in sorted({t for k in self.enabled for t in defs.axes[k].tools})
                            if name not in self.withheld}
        self.ctx = LoopContext(trace_id="")
        self.batch = 0
        self.checked: dict[str, str] = {}
        case = defs.case_loop
        self.gate = _LoopGate(self, case, {k: defs.axes[k] for k in defs.members(case, self.enabled)}, None, "", is_case=True)
        self.ledger = self.gate.ledger

    # ---- 选用关系 ----

    def allowed_instances(self, axis_id: str, category: str) -> list[str]:
        chosen = self.axis_sources.get(axis_id)
        return [i for i in self.sources.instances(category) if not chosen or i in chosen]

    def users_of(self, tool: str) -> list[str]:
        """选用这个被调用启动的 loop 的轴（信息源取它们挑的并集）。"""
        return [k for k in self.enabled if tool in self.defs.axes[k].tools]

    # ---- 依赖（全 case） ----

    def dependents(self, key: str) -> list[str]:
        out, pending = [], [key]
        while pending:
            current = pending.pop()
            for other in self.enabled:
                if other not in out and any(d.axis == current for d in self.defs.axes[other].depends):
                    out.append(other)
                    pending.append(other)
        return out

    def waits_for(self, loop: str) -> set[str]:
        """一个 loop 等的任务：它的轴依赖的、属于别的 loop、场景启用了的任务（§6.1）。"""
        return {d.axis for k in self.defs.members(loop, self.enabled) for d in self.defs.axes[k].depends
                if d.axis in self.loop_of and self.loop_of[d.axis] != loop}

    def cross_invalidate(self, changed: Sequence[str], loop: str) -> None:
        """本 loop 里被修改的任务，波及别的已跑完的 ready loop：那个 loop 整个作废，齐了再在新上下文里重起。"""
        for key in changed:
            for down in self.dependents(key):
                other = self.loop_of[down]
                if other != loop and other in self.done_loops:
                    self.done_loops.discard(other)
                    for member in self.defs.members(other, self.enabled):
                        self.table.results[member] = None
                        self.state[member] = HIDDEN
                    self.events.append(Event(self.batch, "invalidate", other, reasons=(f"{key} 被修改",), loop=other))

    # ---- ready loop ----

    def schedule(self) -> bool:
        """一个一个起已齐的 ready loop，直到没有可起的；返回起没起过。"""
        progressed = False
        while True:
            ready = [l for l in self.ready_loops if l not in self.done_loops
                     and all(self.state.get(d) in (DONE, ABSENT) for d in self.waits_for(l))]
            if not ready:
                return progressed
            self.run_loop(ready[0])
            self.done_loops.add(ready[0])
            progressed = True

    def run_loop(self, loop: str) -> None:
        members = self.defs.members(loop, self.enabled)
        before = (self.run_state.llm_calls, self.run_state.tool_calls, time.monotonic())
        self.events.append(Event(self.batch, "loop_start", loop, loop=loop))
        status, reason = "complete", ""
        try:
            if self.defs.loops[loop].dispatch:
                self._run_dispatched(loop, members)
            else:
                self._run_instance(loop, {k: self.defs.axes[k] for k in members}, None, loop)
        except (LoopFailed, SynthesisError) as exc:
            status, reason = "failed", str(exc)
            raise
        finally:
            self.events.append(Event(self.batch, "loop_end", loop, reasons=(status if not reason else f"{status}: {reason}",), loop=loop))
            self.loop_stats.append({"id": loop, "status": status, "reason": reason,
                                    "llm_calls": self.run_state.llm_calls - before[0],
                                    "tool_calls": self.run_state.tool_calls - before[1],
                                    "seconds": round(time.monotonic() - before[2], 1)})

    def check_sources(self, keys: Sequence[str]) -> str:
        """loop 起前：这些轴（及它们选用的被调用 loop）声明为必需的信息源，各调一次检查工具（每个 case 每个实例一次）。"""
        check = getattr(self.sources, "check", None)
        if check is None:
            return ""
        needed = [(k, cat.category) for k in keys
                  for work in (self.defs.axes[k], *(self.defs.shared_tools[t] for t in self.defs.axes[k].tools))
                  for cat in work.tool_categories if cat.required]
        for key, category in needed:
            for instance in self.allowed_instances(key, category):
                if instance not in self.checked:
                    self.checked[instance] = check(instance) or ""
                if self.checked[instance]:
                    return self.checked[instance]
        return ""

    def preflight(self) -> str:
        """内置材料先取一遍：取不到就整个 case 运行失败，不起任何 loop（§4.1）。"""
        names = [(k, parse_entry(t).name) for k in self.enabled for t in self.defs.axes[k].materials]
        names += [(k, parse_entry(t).name) for k in self.enabled for tool in self.defs.axes[k].tools
                  for t in self.defs.shared_tools[tool].materials]
        for key, name in dict.fromkeys(names):
            if name.split(".", 1)[0] in BUILTIN_SPACES:
                try:
                    self.table.full(name, key)
                except MaterialUnavailable as exc:
                    return f"内置材料 {name} 取不到：{exc}"
        return ""

    def _run_instance(self, loop: str, axes: Mapping[str, AxisDef], override: Optional[Sequence[str]], label: str,
                      after: Sequence[tuple[str, str]] = ()) -> None:
        if problem := self.check_sources(list(axes)):
            raise LoopFailed(f"loop {label} 的必需信息源不可用：{problem}")
        gate = _LoopGate(self, loop, axes, override, f"{label}.", after=after)
        notes = gate.prepare()
        if self.run_state.fatal:
            raise LoopFailed(f"loop {label} 没跑成：{self.run_state.fatal}")
        if gate.ledger.finished():
            return
        stage = f"{self.ctx.stage}/{label}" if self.ctx.stage else label
        result = gate.tool_loop(label.replace("[", "_").replace("]", ""), notes).run(
            self.header, LoopContext(trace_id=self.ctx.trace_id, stage=stage))
        if result.status != "complete" or not gate.ledger.finished():
            raise LoopFailed(f"loop {label} 没跑成：{result.reason or self.run_state.fatal}")

    def _plan(self, loop: str, members: list[str], entries: list[str], plan: Any
              ) -> list[tuple[str, Optional[list[str]], list[str], list[tuple[str, str]]]]:
        """校验分发结果，返回每份 (id, 材料选择或 None, 任务, 先后对)；先后对 [前, 后]：前一个交了后一个才出现（§6.2）。"""
        if not isinstance(plan, list) or not plan:
            raise SynthesisError(f"{loop}: dispatch.py 必须返回非空列表 [{{id, materials?, tasks?, after?}}]")
        allowed = {parse_entry(t).name for t in entries}
        out, covered = [], set()
        for spec in plan:
            spec = spec if isinstance(spec, Mapping) else {}
            pid, chosen, tasks, after = spec.get("id"), spec.get("materials"), spec.get("tasks"), spec.get("after")
            if not isinstance(pid, str) or not pid:
                raise SynthesisError(f"{loop}: dispatch.py 每份要有非空 id，得到 {spec!r}")
            if chosen is None and tasks is None:
                raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的既没有 materials 也没有 tasks")
            if chosen is not None and (not isinstance(chosen, list) or not chosen):
                raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的 materials 要是非空列表")
            if tasks is not None and (not isinstance(tasks, list) or not tasks or len(set(tasks)) != len(tasks)
                                      or not set(tasks) <= set(members)):
                raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的 tasks 要是这个 loop 里不重复的任务，得到 {tasks!r}")
            order = list(tasks) if tasks is not None else list(members)
            pairs = self._pairs(loop, pid, order, after) if after is not None else []
            for text in chosen or []:
                problems = [check_entry(text, self.defs.axes[k], self.defs, self.table.registry) for k in order]
                problem = None if None in problems else problems[0]
                if not problem and parse_entry(text).name not in allowed:
                    problem = f"{text} 不在这个 loop 的材料白名单里"
                if problem:
                    raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的选择不合法：{problem}")
            covered.update(order)
            out.append((pid, chosen, order if tasks is not None else [], pairs))
        if missing := [k for k in members if k not in covered]:
            raise SynthesisError(f"{loop}: dispatch.py 没把 {missing} 分进任何一份")
        return out

    @staticmethod
    def _pairs(loop: str, pid: str, tasks: list[str], after: Any) -> list[tuple[str, str]]:
        """先后对要是本份的任务、不成环（成环谁都出不来）。"""
        if not isinstance(after, list) or not all(isinstance(p, (list, tuple)) and len(p) == 2 and p[0] != p[1]
                                                    and set(p) <= set(tasks) for p in after):
            raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的 after 要是本份任务的 [前, 后] 对，得到 {after!r}")
        pairs, rest = [(a, b) for a, b in after], set(tasks)
        while rest:
            free = {k for k in rest if not any(a in rest and b == k for a, b in pairs)}
            if not free:
                raise SynthesisError(f"{loop}: dispatch.py 给 {pid} 的 after 成环：{sorted(rest)}")
            rest -= free
        return pairs

    def _run_dispatched(self, loop: str, members: list[str]) -> None:
        """一份一份跑：每份跑它列的任务（不列就是全部；列了就按先后出现），只交模型填的字段；各轴的 synth 合并各份（§6.2）。"""
        entries = list(dict.fromkeys(t for k in members for t in self.defs.axes[k].materials))
        base = self.gate.view(History(), entries, {}, acceptance.STAGE_FINAL, members[0], params={"tasks": list(members)})
        try:
            plan = self.defs.loops[loop].dispatch(base)
        except Exception as exc:
            raise SynthesisError(f"{loop}: dispatch.py 出错：{type(exc).__name__}: {exc}") from exc
        parts: dict[str, list[dict]] = {k: [] for k in members}
        for pid, chosen, listed, pairs in self._plan(loop, members, entries, plan):
            tasks = listed or members
            axes = {k: acceptance.part_work(self.defs.axes[k]) for k in tasks}
            for before, later in pairs:  # 先后对当作依赖（§5.4）：前一个交了后一个才出现
                axes[later] = replace(axes[later], depends=(*axes[later].depends, Dependency(before, True)))
            self._run_instance(loop, axes, chosen, f"{loop}[{pid}]", after=pairs)
            for k in tasks:
                parts[k].append({"id": pid, "result": self.table.results[k]})
        for k in members:
            axis = self.defs.axes[k]
            view = self.gate.view(History(), axis.materials, {}, acceptance.STAGE_FINAL, k, parts=parts[k])
            self.table.results[k] = self._synthesize(axis, view)
            self.state[k] = DONE

    def _synthesize(self, axis: AxisDef, view: TaskView) -> dict[str, Any]:
        try:
            filled = axis.code.synthesize(view)
        except Exception as exc:
            raise SynthesisError(f"{axis.id}: synth.py 出错：{type(exc).__name__}: {exc}") from exc
        problems = acceptance.schema_errors(axis.output, filled)
        if problems:
            raise SynthesisError(f"{axis.id}: 合成结果不合输出 schema：" + "；".join(problems[:5]))
        return dict(filled)

    # ---- 运行 ----

    def run(self, case_header: str, ctx: LoopContext) -> LoopReport:
        self.ctx = ctx
        self.header = case_header
        problem = self.preflight() or self.check_sources(list(self.gate.axes))
        if problem:
            self.run_state.fatal = problem
            return LoopReport(status="failed", reason=problem, results={k: None for k in self.enabled}, states=dict(self.state),
                              events=list(self.events), llm_calls=0, tool_calls=0, seconds=0.0, archived=0, messages=[])
        notes = self.gate.prepare()
        result = self.gate.tool_loop("axis_loop", notes).run(case_header, ctx)
        status = "complete" if result.status == "complete" and not self.run_state.fatal else "failed"
        return LoopReport(status=status, reason=self.run_state.fatal or result.reason,
                          results={k: self.table.results.get(k) for k in self.enabled},
                          states=dict(self.state), events=list(self.events),
                          llm_calls=self.run_state.llm_calls, tool_calls=self.run_state.tool_calls,
                          seconds=round(time.monotonic() - self.run_state.started, 1),
                          archived=self.run_state.archived, messages=result.messages, loops=list(self.loop_stats))


class _LoopGate(_Base):
    """一个 loop 实例：自己的台账、推送、提交与门禁；材料、状态、事件、预算与 case 共用。"""

    def __init__(self, case: AxisLoop, loop: str, axes: Mapping[str, AxisDef], override: Optional[Sequence[str]],
                 prefix: str, *, is_case: bool = False, after: Sequence[tuple[str, str]] = ()) -> None:
        own_tools = sorted({t for a in axes.values() if not a.automatic for t in a.tools if t not in case.withheld})
        super().__init__(case, prefix, own_tools)
        self.case, self.loop_id, self.axes, self.override, self.is_case = case, loop, dict(axes), override, is_case
        self.after = list(after)  # 分发给的先后对 (前, 后)：后一个出现后，前一个锁住（§6.2）
        self.ledger = Ledger(self.axes, list(axes), case.table.results, self._run_program, state=case.state,
                             case_enabled=case.enabled, dependents=case.dependents, events=case.events, loop=loop)
        self.accepted: list[tuple[str, Mapping[str, Any]]] = []  # 本批被接受的收尾 (任务, 结果)
        self._notes: list[str] = []

    def entries(self, key: str) -> list[str]:
        return list(self.override) if self.override is not None else list(self.axes[key].materials)

    def readable(self) -> dict[str, Any]:
        """read_material / search_material 能读的：本 loop 已出现任务白名单条目的合集（§4.4）。"""
        out: dict[str, Any] = {}
        for key, axis in self.axes.items():
            if axis.automatic or self.ledger.state.get(key) not in ("open", "done"):
                continue
            out.update(self.case.table.view([parse_entry(t) for t in self.entries(key)], key))
        return out

    def _run_program(self, axis: AxisDef, state: Submissions) -> None:
        view = self.view(self.history or History(), axis.materials, {}, acceptance.STAGE_FINAL, axis.id)
        state.result = self.case._synthesize(axis, view)

    # ---- 推送 ----

    def push(self, change: Change) -> list[str]:
        def text(key: str, title: str) -> str:
            axis = self.axes[key]
            return _task_text(self.case, axis, key, self.entries(key), title, axis.tools, [key])
        notes = [text(k, f"【任务 {k}：{self.axes[k].title}】") for k in change.appeared]
        notes += [text(k, f"【重做 {k}：{self.axes[k].title}】") + "\n（上游被修改，之前交的作废，按新材料重交）"
                  for k in change.invalidated]
        notes += [f"【撤下 {k}】触发条件不再满足，这个任务不用做了，之前交的作废。" for k in change.withdrawn
                  if not self.axes[k].automatic]
        return notes

    def permissions(self) -> tuple[dict[str, set[str]], set[str]]:
        """本 loop 当前放行的信息源登记与被调用启动的 loop（已出现的任务带进来的，放行后不收回）。"""
        instances: dict[str, set[str]] = {}
        shared: set[str] = set()
        for key, axis in self.axes.items():
            if axis.automatic or self.ledger.state[key] not in ("open", "done"):
                continue
            for cat in axis.tool_categories:
                instances.setdefault(cat.category, set()).update(self.case.allowed_instances(key, cat.category))
            shared.update(t for t in axis.tools if t not in self.case.withheld)
        return instances, shared

    # ---- 结算 ----

    def prepare(self) -> list[str]:
        """进 ToolLoop 之前先结算一次（没有模型任务的 loop 就不用起 ToolLoop）。"""
        self._notes = self._settle([])
        return self._notes

    def _settle(self, changed: Sequence[str]) -> list[str]:
        try:
            change = self.ledger.settle(changed, self.case.batch)
            if changed:
                self.case.cross_invalidate(changed, self.loop_id)
            if self.is_case and self.case.schedule():
                more = self.ledger.settle([], self.case.batch)
                change.appeared += [k for k in more.appeared if k not in change.appeared]
                change.withdrawn += more.withdrawn
        except (SynthesisError, LoopFailed) as exc:
            self.case.run_state.fatal = self.case.run_state.fatal or str(exc)
            return []
        if stuck := self.stuck():
            self.case.run_state.fatal = self.case.run_state.fatal or stuck
            return []
        return self.push(change)

    def stuck(self) -> str:
        """运行时兜底：本 loop 没有可交的任务、也起不了别的 loop，却还有任务没完成 → 卡住了，写明谁在等谁。"""
        if self.ledger.finished() or self.ledger.open_tasks():
            return ""
        waiting = []
        for key in self.ledger.enabled:
            if self.case.state[key] not in (DONE, ABSENT):
                unmet = [d.axis for d in self.axes[key].depends
                         if d.axis in self.case.state and self.case.state[d.axis] not in (DONE, ABSENT)]
                waiting.append(f"{key} 在等 {unmet or '触发条件'}")
        return "依赖卡住，没有任务能往下做：" + "；".join(waiting)

    def tool_loop(self, name: str, notes: Sequence[str]) -> ToolLoop:
        visible = [k for k, a in self.axes.items() if not a.automatic]
        uses_sources = self.is_case or any(a.tool_categories for a in self.axes.values())
        tools = [submit_tool(visible or ["-"]), self.recall_tool(), *Reader(self.readable, self.case.run_state.settings.material_inline_chars).tools(),
                 *(self.case.sources.tools if uses_sources else []),
                 *(self.case.shared_impl[t].tool() for t in sorted(self.shared))]
        self._notes = list(notes)
        return ToolLoop(name, SYSTEM, tools, self.case.client, completion_hook=self,
                        hooks={"start": [self], "pre_tool": [self], "post_tool": [self], "post_batch": [self]},
                        end=lambda history: None, budget=Governor(self.case.run_state),
                        max_blocked=self.case.run_state.settings.max_blocked)

    # ---- hooks ----

    def start(self, history: History, ctx: LoopContext) -> Sequence[str]:
        self.history = history
        return self._notes

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        self.history = history
        if call.tool == SUBMIT:
            return self._submit(history, call)
        instances, shared = self.permissions()
        return self.gate_tool(call, instances, shared)

    def _submit(self, history: History, call: Call) -> PreDecision:
        key, item_id, payload = call.args.get("task_id"), call.args.get("item_id"), call.args.get("payload")
        ledger = self.ledger
        if key not in ledger.subs or not ledger.visible(key):
            self._event("reject", str(key), call, ("任务未出现或不可提交",))
            return Deny(f"任务 {key} 现在不能交：它还没出现，或不是需要你交的任务。当前待交：{ledger.open_tasks()}")
        later = [b for a, b in self.after if a == key]
        if any(ledger.state.get(k) != HIDDEN for k in later):
            self._event("reject", key, call, ("已锁：后面的任务已出现",), item_id or "")
            return Deny(f"任务 {key} 已锁：后面的任务已出现，上下文里有了它的材料，不能再改。当前待交：{ledger.open_tasks()}")
        axis = self.axes[key]
        make_view = lambda stage, own: self.view(history, self.entries(key), own, stage, key)
        try:
            outcome = acceptance.submit(axis, ledger.subs[key], payload, item_id or None, make_view)
        except SynthesisError as exc:
            self.case.run_state.fatal = str(exc)
            return Abort(str(exc))
        if outcome.explain is not None:
            self._event("explain", key, call, (), item_id)
            return Deny(acceptance.explain_text(key, outcome.explain))
        if not outcome.accepted:
            self._event("reject", key, call, outcome.reasons, item_id)
            return Deny(f"submit（{key}{'/' + item_id if item_id else ''}）被拒：" + "；".join(outcome.reasons))
        self._event("accept", key, call, (), item_id)
        if outcome.result is not None:
            self.accepted.append((key, outcome.result))
        return Allow()

    def _event(self, kind: str, key: str, call: Call, reasons: Sequence[str], item_id: str = "") -> None:
        self.case.events.append(Event(self.case.batch, kind, key, item_id or "", self.call_id(call), tuple(reasons), self.loop_id))

    def post_batch(self, history: History, calls: Sequence[Call]) -> Sequence[str]:
        super().post_batch(history, calls)
        changed = [key for key, result in self.accepted if self.ledger.accept(key, result)]
        self.accepted = []
        self.case.batch += 1
        return self._settle(changed)

    def ready_to_finish(self, history: History) -> bool:
        return self.ledger.finished() or bool(self.case.run_state.fatal)

    def stop(self, history: History, blocked: int) -> StopVerdict:
        if self.case.run_state.fatal:
            return Failed(self.case.run_state.fatal)
        if self.ledger.finished():
            return Done()
        return Continue(f"还有任务没完成：{self.ledger.open_tasks()}。继续做并用 submit 提交。")
