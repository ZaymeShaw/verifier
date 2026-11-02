"""轴定义：一个轴 = 一条配置（spec/alg/axis_loop.md §3）。

存储 `axis_definitions.json`（与场景预设 capability_map.json 同目录、同一种存法，页面读写）：

    {"axes": {<id>: {...}}, "loops": {<id>: {...}}}

轴属于一个 loop（字段 `loop`，缺省是 start=case 的那个）；loop 写怎么启动：case 开始 / 它等的任务齐了（ready）/
被模型当工具调用（tool，原公共 loop 工具，§3.3）。
输出写成 JSON Schema（type=object），顶层每个属性用 `x-fill: model | program` 标谁填，缺省 model。
程序填的字段若是模型没直接给出、由规则推出的结论，再标 `x-explain`：true 回给整个值，
字符串列表只回元素（或对象）里的这些键；收下前先回给模型看（spec/alg/axis_loop.md §5.3 第 6 步）。
代码只有三个固定插口：axis_code/<轴>/ 下 checks.py 的 check(view)、synth.py 的 synthesize(view)；
axis_code/loops/<loop>/ 下 dispatch.py 的 dispatch(view)（tool loop 的 checks.py、synth.py 也在这里）。
本模块只管解析与自洽；名字、路径、校验参数是否对得上注册表与场景，见 validate.py。
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

from impl.core import capability_store

FILL_MODEL, FILL_PROGRAM = "model", "program"
EXECUTOR_MODEL, EXECUTOR_PROGRAM = "model", "program"
START_CASE, START_READY, START_TOOL = "case", "ready", "tool"
ROLE_ANALYSIS, ROLE_EVALUATION = "analysis", "evaluation"
DISPLAY_EXPANDED, DISPLAY_COLLAPSED = "expanded", "collapsed"
SUBMIT_ONCE, SUBMIT_PER_ITEM = "once", "per_item"
STORE_NAME = "axis_definitions.json"
CODE_DIR = "axis_code"
_PLUGS = {"check": "checks.py", "synthesize": "synth.py", "dispatch": "dispatch.py"}
LOOPS_DIR = "loops"


@dataclass(frozen=True)
class Dependency:
    axis: str
    hard: bool


@dataclass(frozen=True)
class Trigger:
    axis: str
    verdict_in: tuple[str, ...]


@dataclass(frozen=True)
class ToolCategory:
    category: str
    required: bool


@dataclass(frozen=True)
class CheckUse:
    name: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class Code:
    """上传的代码；没上传为 None。"""

    check: Optional[Callable[[Any], list]] = None
    synthesize: Optional[Callable[[Any], Mapping]] = None
    dispatch: Optional[Callable[[Any], list]] = None


@dataclass(frozen=True)
class Work:
    """轴与公共 loop 工具共有的部分：说明、材料、信息源、提交、输出、校验、代码。"""

    id: str
    instruction: str
    materials: tuple[str, ...]
    tool_categories: tuple[ToolCategory, ...]
    submit: str
    items_field: str
    item_key: str      # 分条交时分项的编号字段（submit 的 item_id 写进它）
    output: Mapping[str, Any]
    checks: tuple[CheckUse, ...]
    code: Code

    def fill(self, name: str) -> str:
        return str((self.output.get("properties") or {}).get(name, {}).get("x-fill") or FILL_MODEL)

    @property
    def program_fields(self) -> tuple[str, ...]:
        return tuple(n for n in self.output.get("properties") or {} if self.fill(n) == FILL_PROGRAM)

    @property
    def explained_fields(self) -> dict[str, Any]:
        """标了 x-explain 的程序字段 → 它的标注（true 或要回的键）。"""
        return {n: p["x-explain"] for n, p in (self.output.get("properties") or {}).items() if p.get("x-explain")}

    def model_schema(self) -> dict[str, Any]:
        """模型交的那部分：去掉程序填的字段；分条交时再去掉分项列表（分项单独交）。"""
        drop = set(self.program_fields) | ({self.items_field} if self.submit == SUBMIT_PER_ITEM else set())
        props = {k: v for k, v in (self.output.get("properties") or {}).items() if k not in drop}
        required = [k for k in self.output.get("required") or [] if k not in drop]
        return {**self.output, "properties": props, "required": required}

    def item_schema(self) -> dict[str, Any]:
        """分条交时一个分项的 schema。"""
        return dict(((self.output.get("properties") or {}).get(self.items_field) or {}).get("items") or {})


@dataclass(frozen=True)
class SharedToolDef(Work):
    """被调用启动的 loop（start=tool，原公共 loop 工具）：调用方的模型按 params 调用，每次一个新 loop（§6.3）。"""

    description: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)  # JSON Schema（type=object）


@dataclass(frozen=True)
class AxisDef(Work):
    title: str = ""
    executor: str = EXECUTOR_MODEL
    loop: str = ""
    role: str = ROLE_EVALUATION
    display: str = DISPLAY_EXPANDED  # 结果页明细里默认展开还是收起；不写按 role：评测轴展开、分析轴收起
    depends: tuple[Dependency, ...] = ()
    trigger: Optional[Trigger] = None
    tools: tuple[str, ...] = ()  # 选用的被调用启动的 loop
    optional_tools: tuple[str, ...] = ()  # tools 里可选的：它要的信息源场景没选时不提供，不报错（spec/alg/axis_loop.md §6.3）

    @property
    def verdict_values(self) -> tuple[str, ...]:
        verdict = (self.output.get("properties") or {}).get("verdict") or {}
        return tuple(verdict.get("enum") or ())

    @property
    def automatic(self) -> bool:
        """程序任务：不推送给模型，依赖满足就由程序合成。"""
        return self.executor == EXECUTOR_PROGRAM


@dataclass(frozen=True)
class LoopDef:
    """一个 loop（spec/alg/axis_loop.md §3.3）：start=case 恰好一个；ready 由台账在它等的任务齐了时起；
    tool 被模型当工具调用（work 是它的说明、材料、参数、输出）。"""

    id: str
    title: str
    start: str
    dispatch: Optional[Callable[[Any], list]] = None
    work: Optional[SharedToolDef] = None


@dataclass(frozen=True)
class Definitions:
    axes: Mapping[str, AxisDef]
    loops: Mapping[str, LoopDef]

    @property
    def shared_tools(self) -> dict[str, SharedToolDef]:
        """start=tool 的 loop，按名字。"""
        return {k: l.work for k, l in self.loops.items() if l.start == START_TOOL and l.work is not None}

    @property
    def case_loop(self) -> str:
        return next((k for k, l in self.loops.items() if l.start == START_CASE), "")

    def members(self, loop: str, enabled) -> list[str]:
        """这个 loop 里、场景启用了的轴（按启用顺序）。"""
        return [k for k in enabled if k in self.axes and self.axes[k].loop == loop]


# ---- 读取 -------------------------------------------------------------------------------

def store_path(project_id: str) -> Path:
    return capability_store.store_path(project_id).with_name(STORE_NAME)


def code_dir(project_id: str) -> Path:
    return capability_store.store_path(project_id).with_name(CODE_DIR)


def _load_code(directory: Path, label: str) -> Code:
    found: dict[str, Callable] = {}
    for name, filename in _PLUGS.items():
        path = directory / filename
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"axis_code.{label.replace('/', '.')}.{path.stem}", path)
        module: ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, name, None)
        if not callable(fn) or len(inspect.signature(fn).parameters) != 1:
            raise ValueError(f"{label}: {filename} 必须定义 {name}(view)")
        found[name] = fn
    return Code(**found)


def _strings(raw: Any, label: str) -> tuple[str, ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise ValueError(f"{label} 必须是非空字符串列表")
    return tuple(x.strip() for x in raw)


def _choice(raw: Any, default: str, allowed: tuple[str, ...], label: str) -> str:
    value = str(raw or default)
    if value not in allowed:
        raise ValueError(f"{label} 只能是 {' / '.join(allowed)}")
    return value


def _work(raw: Mapping[str, Any], label: str, code: Code) -> dict[str, Any]:
    output = raw.get("output")
    if not isinstance(output, Mapping) or output.get("type") != "object" or not isinstance(output.get("properties"), Mapping):
        raise ValueError(f"{label}.output 必须是 type=object 且带 properties 的 JSON Schema")
    checks = []
    for i, item in enumerate(raw.get("checks") or []):
        if not isinstance(item, Mapping) or len(item) != 1:
            raise ValueError(f"{label}.checks[{i}] 必须写成 {{校验名: 参数}}")
        (name, params), = item.items()
        if not isinstance(params, Mapping):
            raise ValueError(f"{label}.checks[{i}].{name} 的参数必须是对象")
        checks.append(CheckUse(str(name), dict(params)))
    cats = []
    for i, item in enumerate(raw.get("tool_categories") or []):
        if not isinstance(item, Mapping) or not str(item.get("category") or "").strip():
            raise ValueError(f"{label}.tool_categories[{i}] 必须有 category")
        cats.append(ToolCategory(str(item["category"]), bool(item.get("required"))))
    return dict(id=str(raw.get("id") or ""), instruction=str(raw.get("instruction") or ""),
                materials=_strings(raw.get("materials"), f"{label}.materials"), tool_categories=tuple(cats),
                submit=_choice(raw.get("submit"), SUBMIT_ONCE, (SUBMIT_ONCE, SUBMIT_PER_ITEM), f"{label}.submit"),
                items_field=str(raw.get("items_field") or ""), item_key=str(raw.get("item_key") or "item_id"),
                output=dict(output), checks=tuple(checks), code=code)


def parse_shared_tool(raw: Mapping[str, Any], *, code: Code) -> SharedToolDef:
    label = f"shared tool {raw.get('id')}"
    params = raw.get("params") or {}
    if params and (not isinstance(params, Mapping) or params.get("type") != "object"):
        raise ValueError(f"{label}.params 必须是 type=object 的 JSON Schema，或留空")
    return SharedToolDef(**_work(raw, label, code), description=str(raw.get("description") or ""), params=dict(params))


def parse_axis(raw: Mapping[str, Any], *, code: Code) -> AxisDef:
    label = f"axis {raw.get('id')}"
    depends = []
    for i, item in enumerate(raw.get("depends") or []):
        if not isinstance(item, Mapping) or not str(item.get("axis") or "").strip():
            raise ValueError(f"{label}.depends[{i}] 必须有 axis")
        depends.append(Dependency(str(item["axis"]), bool(item.get("hard"))))
    trigger = raw.get("trigger")
    if trigger is not None:
        if not isinstance(trigger, Mapping) or not trigger.get("axis") or not trigger.get("verdict_in"):
            raise ValueError(f"{label}.trigger 必须写成 {{axis, verdict_in}}")
        trigger = Trigger(str(trigger["axis"]), _strings(trigger["verdict_in"], f"{label}.trigger.verdict_in"))
    role = _choice(raw.get("role"), ROLE_EVALUATION, (ROLE_ANALYSIS, ROLE_EVALUATION), f"{label}.role")
    display = _choice(raw.get("display"), DISPLAY_EXPANDED if role == ROLE_EVALUATION else DISPLAY_COLLAPSED,
                      (DISPLAY_EXPANDED, DISPLAY_COLLAPSED), f"{label}.display")
    return AxisDef(**_work(raw, label, code), title=str(raw.get("title") or raw.get("id") or ""),
                   executor=_choice(raw.get("executor"), EXECUTOR_MODEL, (EXECUTOR_MODEL, EXECUTOR_PROGRAM), f"{label}.executor"),
                   loop=str(raw.get("loop") or ""),
                   role=role, display=display,
                   depends=tuple(depends), trigger=trigger, tools=_strings(raw.get("tools"), f"{label}.tools"),
                   optional_tools=_strings(raw.get("optional_tools"), f"{label}.optional_tools"))


def parse_loop(raw: Mapping[str, Any], *, code: Code) -> LoopDef:
    label = f"loop {raw.get('id')}"
    start = _choice(raw.get("start"), START_READY, (START_CASE, START_READY, START_TOOL), f"{label}.start")
    if start == START_TOOL:
        return LoopDef(id=str(raw["id"]), title=str(raw.get("title") or raw["id"]), start=start,
                       work=parse_shared_tool(raw, code=Code(check=code.check, synthesize=code.synthesize)))
    if code.check or code.synthesize:
        raise ValueError(f"{label}: start={start} 的 loop 只能上传 dispatch.py（校验、合成写在各轴下）")
    return LoopDef(id=str(raw["id"]), title=str(raw.get("title") or raw["id"]), start=start, dispatch=code.dispatch)


def parse(raw: Mapping[str, Any], code_root: Optional[Path] = None) -> Definitions:
    """存储内容 → Definitions。code_root 下按 §3.1 的目录找上传的代码；None = 没有代码。"""
    if not isinstance(raw, Mapping):
        raise ValueError("轴定义存储必须是对象")
    unknown = set(raw) - {"axes", "loops"}
    if unknown:
        raise ValueError(f"轴定义存储只认 axes / loops，多了 {sorted(unknown)}")

    def code_at(*parts: str) -> Code:
        return _load_code(code_root.joinpath(*parts), "/".join(parts)) if code_root else Code()

    loops = {key: parse_loop({**item, "id": key}, code=code_at(LOOPS_DIR, key)) for key, item in (raw.get("loops") or {}).items()}
    cases = [k for k, l in loops.items() if l.start == START_CASE]
    if len(cases) != 1:
        raise ValueError(f"start=case 的 loop 必须恰好一个，现在是 {cases}")
    axes = {}
    for key, item in (raw.get("axes") or {}).items():
        code = code_at(key)
        if code.dispatch:
            raise ValueError(f"axis {key}: dispatch.py 挂在 loop 上（axis_code/{LOOPS_DIR}/<loop>/），不在轴下")
        axes[key] = parse_axis({**item, "id": key, "loop": item.get("loop") or cases[0]}, code=code)
    return Definitions(axes=axes, loops=loops)


def load(project_id: str) -> Definitions:
    path = store_path(project_id)
    if not path.is_file():
        raise ValueError(f"{project_id}: 没有轴定义存储 {path}")
    return parse(json.loads(path.read_text(encoding="utf-8")), code_dir(project_id))
