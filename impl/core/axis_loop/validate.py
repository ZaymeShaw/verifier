"""加载期校验（fail fast，spec/alg/axis_loop.md §3.4）：一次收齐全部问题再报。

分两层：
- `check_definitions`：轴定义自身与注册表、标准校验对得上（不看场景）；
- `check_scenario`：某个场景启用的轴，依赖、信息源类别在这个场景里满足。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable, Optional, Sequence

from . import checks as standard
from . import paths
from .definitions import (
    EXECUTOR_PROGRAM, FILL_PROGRAM, START_TOOL, SUBMIT_PER_ITEM, AxisDef, Definitions, SharedToolDef, Work)
from .materials import BUILTIN_SPACES, RESULT_SPACE, Registry, parse_entry


def _material_schema(name: str, defs: Definitions, registry: Registry) -> Optional[Mapping[str, Any]]:
    if name.startswith(RESULT_SPACE + "."):
        axis = defs.axes.get(name.split(".", 1)[1])
        return axis.output if axis else None
    material = registry.get(name)
    return material.schema if material else None


def readable_results(work: Work) -> set[str]:
    """这份工作能读哪些轴的结果（spec §4.3）：轴读它依赖的轴（可以跨 loop）；被调用启动的 loop 不读轴结果。"""
    return {d.axis for d in work.depends} if isinstance(work, AxisDef) else set()


def check_entry(text: str, work: Work, defs: Definitions, registry: Registry) -> Optional[str]:
    """一条材料选择合不合法（白名单与分发脚本的输出共用这一条规则）。"""
    try:
        entry = parse_entry(text)
    except ValueError as exc:
        return str(exc)
    if entry.space == RESULT_SPACE and entry.axis not in readable_results(work):
        return f"{text} 超出读取范围（可读的轴结果：{sorted(readable_results(work)) or '无'}）"
    schema = _material_schema(entry.name, defs, registry)
    if schema is None:
        return f"{entry.name} 不在注册表里"
    return paths.check_schema(schema, entry.path)


def _check_work(work: Work, label: str, defs: Definitions, registry: Registry, dispatched: bool = False) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    for text in work.materials:
        if problem := check_entry(text, work, defs, registry):
            errors.append(f"{label}.materials: {problem}")
        else:
            names.add(parse_entry(text).name)
    props = work.output.get("properties") or {}
    if work.submit == SUBMIT_PER_ITEM:
        items = props.get(work.items_field) or {}
        if not work.items_field or items.get("type") != "array" or (items.get("items") or {}).get("type") != "object":
            errors.append(f"{label}: 分条交要写 items_field，且它是 output 里元素为对象的列表")
    elif work.items_field:
        errors.append(f"{label}: 一次交齐的不写 items_field")
    if dispatched:
        if not work.code.synthesize:
            errors.append(f"{label}: 所在 loop 有 dispatch.py，必须有 synth.py（合并各份结果）")
    elif bool(work.program_fields) != bool(work.code.synthesize):
        errors.append(f"{label}: 程序填的字段 {list(work.program_fields)} 与 synth.py 必须同时有或同时没有")
    for name, keys in work.explained_fields.items():
        if work.fill(name) != FILL_PROGRAM:
            errors.append(f"{label}.output.{name}: x-explain 只能标在程序填的字段上")
        elif keys is not True and not (isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys)):
            errors.append(f"{label}.output.{name}: x-explain 写 true 或非空的键名列表")
    for use in work.checks:
        if problem := standard.check_params(use.name, use.params):
            errors.append(f"{label}.checks: {problem}")
            continue
        stage = use.params.get("on", "final")
        if stage == "item" and work.submit != SUBMIT_PER_ITEM:
            errors.append(f"{label}.checks.{use.name}: on=item 只用于分条交")
        scope = work.item_schema() if stage == "item" else work.output
        if problem := paths.check_schema(scope, paths.parse(str(use.params["field"]))):
            errors.append(f"{label}.checks.{use.name}.field: {problem}")
        for key in ("of", "material"):
            ref = use.params.get(key)
            if not isinstance(ref, str):
                continue
            head = ref.split(".", 1)[0]
            if head == "own":
                problem = paths.check_schema(scope, paths.parse(ref.split(".", 1)[1]))
            elif head == "params":
                problem = None if isinstance(work, SharedToolDef) else "只有被调用启动的 loop 有 params"
            elif head in (*BUILTIN_SPACES, RESULT_SPACE):
                entry = parse_entry(ref)
                schema = _material_schema(entry.name, defs, registry)
                problem = (f"{entry.name} 不在本任务的材料白名单里" if entry.name not in names
                           else paths.check_schema(schema or {}, entry.path))
            else:
                problem = f"{ref} 的根只能是 own / params / 标准名"
            if problem:
                errors.append(f"{label}.checks.{use.name}.{key}: {problem}")
    return errors


def _wait_cycle(defs: Definitions) -> Optional[list[str]]:
    """谁要等谁（spec/alg/axis_loop.md §3.4、§6.1）：节点是任务，两种边——
    1. 任务 t 依赖任务 u：u → t；
    2. ready loop 要等它的任务依赖的、别的 loop 里的任务全齐才起，所以 loop 里每个任务都被迫等这些：x → m。
    case loop 一开始就在跑，不带来被迫等。有圈就会卡死，没圈就一定跑得通。返回圈上的任务。"""
    from .definitions import START_READY
    ready = {k for k, l in defs.loops.items() if l.start == START_READY}
    waits: dict[str, set[str]] = {k: {d.axis for d in a.depends if d.axis in defs.axes} for k, a in defs.axes.items()}
    for loop in ready:
        members = {k for k, a in defs.axes.items() if a.loop == loop}
        door = {d for m in members for d in waits[m] if defs.axes[d].loop != loop}
        for m in members:
            waits[m] |= door
    state: dict[str, int] = {}

    def visit(key: str, trail: list[str]) -> Optional[list[str]]:
        if state.get(key) == 1:
            return trail[trail.index(key):] + [key]
        if state.get(key) == 2:
            return None
        state[key] = 1
        for up in sorted(waits[key]):
            if found := visit(up, trail + [key]):
                return found
        state[key] = 2
        return None

    for key in sorted(defs.axes):
        if found := visit(key, []):
            return found
    return None


def check_definitions(defs: Definitions, registry: Registry) -> list[str]:
    errors: list[str] = []
    if cycle := _wait_cycle(defs):
        where = " -> ".join(f"{k}（{defs.axes[k].loop}）" for k in cycle)
        errors.append("依赖会卡死（谁都在等下一个，绕回了自己）：" + where)
    for key, axis in defs.axes.items():
        label = f"axis {key}"
        props = axis.output.get("properties") or {}
        missing = [f for f in ("verdict", "reason") if f not in props]
        if missing:
            errors.append(f"{label}.output 缺 {missing}")
        for dep in axis.depends:
            if dep.axis not in defs.axes:
                errors.append(f"{label}.depends: 未定义的轴 {dep.axis}")
        if axis.trigger:
            dep = next((d for d in axis.depends if d.axis == axis.trigger.axis), None)
            if dep is None or not dep.hard:
                errors.append(f"{label}.trigger 只能引用硬依赖，{axis.trigger.axis} 不是")
            elif axis.trigger.axis in defs.axes:
                bad = sorted(set(axis.trigger.verdict_in) - set(defs.axes[axis.trigger.axis].verdict_values))
                if bad:
                    errors.append(f"{label}.trigger.verdict_in 含 {bad}，不在 {axis.trigger.axis} 的 verdict 枚举里")
        if axis.executor == EXECUTOR_PROGRAM:
            model_fields = [f for f in props if axis.fill(f) != FILL_PROGRAM]
            if model_fields or axis.tools or axis.tool_categories:
                errors.append(f"{label}: 程序任务不能有模型填的字段 {model_fields} 或工具")
        for name in axis.tools:
            if name not in defs.shared_tools:
                errors.append(f"{label}.tools: {name} 不是 start=tool 的 loop")
        for name in axis.optional_tools:
            if name not in axis.tools:
                errors.append(f"{label}.optional_tools: {name} 不在 tools 里")
        loop = defs.loops.get(axis.loop)
        if loop is None:
            errors.append(f"{label}.loop: 未定义的 loop {axis.loop}")
        elif loop.start == START_TOOL:
            errors.append(f"{label}.loop: {axis.loop} 是被调用启动的 loop，不能放轴")
        errors += _check_work(axis, label, defs, registry, dispatched=bool(loop and loop.dispatch))
    for key, tool in defs.shared_tools.items():
        label = f"loop {key}"
        errors += _check_work(tool, label, defs, registry)
        if not tool.description.strip():
            errors.append(f"{label}: description（给调用方看的工具说明）不能为空")
        for name, prop in (tool.params.get("properties") or {}).items():
            if not str((prop or {}).get("description") or "").strip():
                errors.append(f"{label}.params.{name}: 每个参数都要写 description")
    return errors


def scenario_warnings(defs: Definitions, enabled: Sequence[str], selected: Iterable[str]) -> list[str]:
    """场景选用了某类信息源，却没有启用的任务（或它选用的被调用 loop）声明这一类：能跑，但这类证据没人用，
    依赖它的判断会系统性地落到判不了（spec/alg/axis_loop.md §12.2.3）。"""
    used = {c.category for k in enabled if k in defs.axes
            for w in (defs.axes[k], *(defs.shared_tools[t] for t in defs.axes[k].tools if t in defs.shared_tools))
            for c in w.tool_categories}
    return [f"场景选用了 {cat} 类信息源，但没有启用的轴用它" for cat in sorted(set(selected) - used)]


def check_scenario(defs: Definitions, enabled: Sequence[str], categories: Iterable[str]) -> list[str]:
    """场景启用了哪些轴、选用的信息源有哪些类别。"""
    errors: list[str] = []
    on = set(enabled)
    available = set(categories)
    for key in enabled:
        axis = defs.axes.get(key)
        if axis is None:
            errors.append(f"场景启用了未定义的轴 {key}")
            continue
        for dep in axis.depends:
            if dep.hard and dep.axis not in on:
                errors.append(f"{key} 硬依赖 {dep.axis}，场景没开")
        # 可选的被调用 loop 缺信息源时只是不提供（运行时 AxisLoop.withheld），必需的才报错
        works: list[Work] = [axis, *(defs.shared_tools[t] for t in axis.tools
                                     if t in defs.shared_tools and t not in axis.optional_tools)]
        for work in works:
            for cat in work.tool_categories:
                if cat.required and cat.category not in available:
                    errors.append(f"{key}（{work.id}）必需 {cat.category} 类信息源，场景一个都没选")
    return errors
