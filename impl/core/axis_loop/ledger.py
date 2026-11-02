"""台账：谁出现、谁作废、谁撤下，程序任务何时合成（spec/alg/axis_loop.md §5.4）。

状态：
- hidden     还没出现（依赖没齐，或触发还判不了）
- open       已出现，等模型提交（含被作废后待重交）
- done       已完成，结果在材料表 result.<id>
- absent     不出现：触发条件判为不满足；对下游算已完成、结果为空

程序任务（axis.automatic）不进 open：依赖满足就由 run_auto 当场合成。

一个 loop 一本台账，只管属于它的轴（own）；状态表 state 整个 case 共用一份，依赖别的 loop 的任务时直接读它。
作废沿依赖传递，跨 loop 一样算（downstream 由调用方给出全 case 的依赖图）；别的 loop 里被波及的轴由 case 运行器处理。
全部由程序算：每批结束后 `settle(changed)` 一次，返回要推送给模型的变化与事件。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .acceptance import Submissions, SynthesisError
from .definitions import AxisDef

HIDDEN, OPEN, DONE, ABSENT = "hidden", "open", "done", "absent"


@dataclass(frozen=True)
class Event:
    batch: int
    kind: str          # appear | invalidate | withdraw | absent | program | accept | reject | loop_start | loop_end | shared_tool
    task_id: str
    item_id: str = ""
    call_id: str = ""
    reasons: tuple[str, ...] = ()
    loop: str = ""


@dataclass
class Change:
    appeared: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)
    withdrawn: list[str] = field(default_factory=list)


class Ledger:
    def __init__(self, axes: Mapping[str, AxisDef], own: Sequence[str], results: dict[str, Optional[Mapping[str, Any]]],
                 run_auto: Callable[[AxisDef, Submissions], None], *, state: Optional[dict[str, str]] = None,
                 case_enabled: Sequence[str] = (), dependents: Optional[Callable[[str], list[str]]] = None,
                 events: Optional[list[Event]] = None, loop: str = "") -> None:
        """axes：本台账用的轴定义（分发出去的一份是只交模型填字段的版本）；own：属于本 loop、场景启用的轴；
        results 是材料表的 result.* 字典、state 是全 case 共用的状态表（都共享同一个对象）；
        case_enabled：全 case 启用的轴（判断依赖开没开）；dependents：全 case 的传递下游（缺省只看本台账）；
        run_auto 合成程序任务并写 state.result。"""
        self.defs = axes
        self.enabled = list(own)
        self.on = set(case_enabled or own)
        self.results = results
        self.run_auto = run_auto
        self.loop = loop
        self.state: dict[str, str] = state if state is not None else {}
        for a in self.enabled:
            self.state[a] = HIDDEN
        self.subs: dict[str, Submissions] = {a: Submissions() for a in self.enabled}
        self.events: list[Event] = events if events is not None else []
        self._dependents = dependents
        for axis in self.enabled:
            results[axis] = None

    # ---- 查询 ----

    def axis(self, key: str) -> AxisDef:
        return self.defs[key]

    def open_tasks(self) -> list[str]:
        return [a for a in self.enabled if self.state[a] == OPEN]

    def visible(self, key: str) -> bool:
        """模型能不能交这个任务：已出现或已完成（交给已完成的就是修改）。"""
        return self.state.get(key) in (OPEN, DONE) and not self.axis(key).automatic

    def finished(self) -> bool:
        return all(self.state[a] in (DONE, ABSENT) for a in self.enabled)

    def downstream(self, key: str) -> list[str]:
        """传递下游；有全 case 依赖图时跨 loop 算，本台账只处理属于自己的那些。"""
        if self._dependents is not None:
            return self._dependents(key)
        out, pending = [], [key]
        while pending:
            current = pending.pop()
            for other in self.enabled:
                if other not in out and any(d.axis == current for d in self.axis(other).depends):
                    out.append(other)
                    pending.append(other)
        return out

    # ---- 变化 ----

    def accept(self, key: str, result: Mapping[str, Any]) -> bool:
        """一个任务的收尾被接受；返回是否是修改（原来已完成）。"""
        revised = self.state[key] == DONE
        self.results[key] = result
        self.state[key] = DONE
        return revised

    def _deps_ready(self, axis: AxisDef) -> bool:
        for dep in axis.depends:
            if dep.axis in self.on:
                if self.state.get(dep.axis, HIDDEN) not in (DONE, ABSENT):
                    return False
            elif dep.hard:
                return False  # 加载期已拦；这里不让它出现
        return True

    def _triggered(self, axis: AxisDef) -> Optional[bool]:
        """None = 还判不了。"""
        if axis.trigger is None:
            return True
        upstream = self.results.get(axis.trigger.axis)
        if self.state.get(axis.trigger.axis) == ABSENT:
            return False
        if upstream is None:
            return None
        return upstream.get("verdict") in axis.trigger.verdict_in

    def _clear(self, key: str) -> None:
        self.results[key] = None
        self.subs[key].reset()

    def settle(self, changed: Sequence[str], batch: int) -> Change:
        """changed：本批被修改（原来已完成、又被接受）的任务。"""
        change = Change()
        for key in changed:
            for down in self.downstream(key):
                if down not in self.subs:
                    continue  # 别的 loop 的轴：由 case 运行器整个作废那个 loop
                before = self.state[down]
                if before == HIDDEN:
                    continue
                # 上游变了：下游一律退回 hidden，按新结果重新出现；已出现或已完成的（模型任务）推送作废。
                self._clear(down)
                self.state[down] = HIDDEN
                if before in (OPEN, DONE) and not self.axis(down).automatic and down not in change.invalidated:
                    change.invalidated.append(down)
                self.events.append(Event(batch, "invalidate", down, reasons=(f"{key} 被修改",), loop=self.loop))
        progressed = True
        while progressed:
            progressed = False
            for key in self.enabled:
                axis, current = self.axis(key), self.state[key]
                if current in (OPEN, DONE) and axis.trigger and self._triggered(axis) is False:
                    self._clear(key)
                    self.state[key] = ABSENT
                    change.withdrawn.append(key)
                    self.events.append(Event(batch, "withdraw", key, reasons=("触发条件不再满足",), loop=self.loop))
                    progressed = True
                    continue
                if current != HIDDEN or not self._deps_ready(axis):
                    continue
                triggered = self._triggered(axis)
                if triggered is None:
                    continue
                if not triggered:
                    self.state[key] = ABSENT
                    self.events.append(Event(batch, "absent", key, reasons=("触发条件未满足",), loop=self.loop))
                elif axis.automatic:
                    self.run_auto(axis, self.subs[key])  # SynthesisError 交给调用方中止
                    self.accept(key, self.subs[key].result)
                    self.events.append(Event(batch, "program", key, loop=self.loop))
                else:
                    self.state[key] = OPEN
                    if key not in change.invalidated:
                        change.appeared.append(key)
                    self.events.append(Event(batch, "appear", key, loop=self.loop))
                progressed = True
        return change


__all__ = ["ABSENT", "DONE", "HIDDEN", "OPEN", "Change", "Event", "Ledger", "SynthesisError"]
