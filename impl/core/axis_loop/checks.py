"""标准校验库 V3–V6（spec/alg/axis_loop.md §7.2；V1/V2 由 output schema 承担）。

每个校验：`fn(view, scope, **params) -> [被拒原因]`。scope 是这次要校验的提交（分项或收尾）。
路径参数的根：
- `field`：相对本次提交（scope）；
- `of`：`own.<路径>`（本次提交）、`params.<路径>`（子 loop 参数）、或 `<标准名>.<路径>`（白名单里的材料）。
`on`：`item`（分条交时对每个分项）或 `final`（收尾时，缺省）。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import paths
from .materials import parse_entry
from .text import leaves, quote_in_text
from .view import CallView, TaskView

SUBLOOP_CATEGORY = "subloop"


def resolve(view: TaskView, scope: Mapping[str, Any], ref: str) -> list[Any]:
    """`of` 指向的全部末端值。"""
    head, _, rest = ref.partition(".")
    if head == "own":
        return paths.values(scope, paths.parse(rest))
    if head == "params":
        return paths.values(view.params, paths.parse(rest))
    entry = parse_entry(ref)
    if entry.name not in view.materials:
        raise KeyError(f"{ref} 不在本任务的材料白名单里")
    value = view.materials[entry.name]
    return [] if value is None else paths.values(value, entry.path)


def _field(scope: Mapping[str, Any], field: str) -> list[Any]:
    return paths.values(scope, paths.parse(field))


def _hashable(value: Any) -> Any:
    return value if isinstance(value, (str, int, float, bool)) or value is None else repr(value)


def covers(view: TaskView, scope: Mapping[str, Any], *, field: str, of: str) -> list[str]:
    got = [_hashable(v) for v in _field(scope, field)]
    want = {_hashable(v) for v in resolve(view, scope, of)}
    problems = []
    repeated = sorted(str(v) for v, n in Counter(got).items() if n > 1)
    if repeated:
        problems.append(f"{field} 有重复：{repeated}")
    missing, extra = sorted(map(str, want - set(got))), sorted(map(str, set(got) - want))
    if missing:
        problems.append(f"{field} 漏了：{missing}")
    if extra:
        problems.append(f"{field} 多了不在 {of} 里的：{extra}")
    return problems


def refs_in(view: TaskView, scope: Mapping[str, Any], *, field: str, of: str) -> list[str]:
    allowed = {_hashable(v) for v in resolve(view, scope, of)}
    bad = sorted({str(v) for v in _field(scope, field) if _hashable(v) not in allowed})
    return [f"{field} 里的 {bad} 不在 {of} 里"] if bad else []


def quote_in_material(view: TaskView, scope: Mapping[str, Any], *, field: str, material: str) -> list[str]:
    entry = parse_entry(material)
    if entry.name not in view.materials:
        raise KeyError(f"{material} 不在本任务的材料白名单里")
    text = leaves(paths.extract(view.materials[entry.name], entry.path))
    bad = [q for q in _field(scope, field) if not isinstance(q, str) or not any(quote_in_text(q, t) for t in text)]
    return [f"{field} 的引文没有逐字出现在 {material} 里：{[str(q)[:40] for q in bad]}"] if bad else []


def usable(view: TaskView, ref: str, category: str = "", tool: str = "") -> str:
    """ref 指的调用能不能当依据；能为空串，否则为原因，并列出能过同一判断的 call_id。"""
    why = _unusable(view.call(ref), category, tool)
    if not why:
        return ""
    ok = [c.call_id for c in view.calls if not _unusable(c, category, tool)]
    return f"{why}；现在可引的 call_id 是 {ok}"


def _unusable(call: Optional[CallView], category: str, tool: str) -> str:
    if call is None:
        return "不是此前回复里拿到的调用的 call_id（同一次回复里刚发起的要到下一次回复才能引）"
    if call.is_error:
        return "是报错的调用，不算查过"
    if category and call.category != category:
        return f"不是 {category} 类的调用"
    if tool and call.tool != tool:
        return f"不是 {tool} 的调用"
    return ""


def quote_in_call(view: TaskView, scope: Mapping[str, Any], *, field: str, category: str = "") -> list[str]:
    problems = []
    for cite in _field(scope, field):
        ref = cite.get("ref") if isinstance(cite, Mapping) else None
        quote = cite.get("quote") if isinstance(cite, Mapping) else None
        if not isinstance(ref, str) or not isinstance(quote, str) or not quote.strip():
            problems.append(f"{field} 每条引用要有 ref 和非空 quote")
            continue
        why = usable(view, ref, category)
        call = view.call(ref)
        if why:
            problems.append(f"引用的 {ref} {why}")
        elif not any(quote_in_text(quote, t) for t in [call.text, *leaves(call.structured)]):
            problems.append(f"引句 {quote[:40]!r} 没有逐字出现在 {ref} 的返回里；照返回原文摘，不改写、不拼接")
    return problems


def searched(view: TaskView, scope: Mapping[str, Any], *, field: str, category: str) -> list[str]:
    refs = _field(scope, field)
    if not refs:
        return [f"{field} 至少列一个检索调用；一次都没查不能交"]
    return [f"{field} 里的 {r} {why}" for r in refs if (why := usable(view, str(r), category))]


def from_call(view: TaskView, scope: Mapping[str, Any], *, field: str, tool: str) -> list[str]:
    refs = _field(scope, field)
    if not refs:
        return [f"{field} 必须指向一次 {tool} 调用"]
    return [f"{field} 里的 {r} {why}" for r in refs if (why := usable(view, str(r), SUBLOOP_CATEGORY, tool))]


@dataclass(frozen=True)
class Spec:
    fn: Callable[..., list[str]]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


STANDARD: Mapping[str, Spec] = {
    "covers": Spec(covers, ("field", "of")),
    "refs_in": Spec(refs_in, ("field", "of")),
    "quote_in_material": Spec(quote_in_material, ("field", "material")),
    "quote_in_call": Spec(quote_in_call, ("field",), ("category",)),
    "searched": Spec(searched, ("field", "category")),
    "from_call": Spec(from_call, ("field", "tool")),
}
STAGES = ("item", "final")


def check_params(name: str, params: Mapping[str, Any]) -> Optional[str]:
    """加载期：校验名与参数对不对。"""
    spec = STANDARD.get(name)
    if spec is None:
        return f"未知的标准校验 {name!r}；可用：{', '.join(STANDARD)}"
    keys = set(params) - {"on"}
    missing = [k for k in spec.required if k not in keys]
    extra = sorted(keys - set(spec.required) - set(spec.optional))
    if missing or extra:
        return f"{name} 的参数不对：缺 {missing}，多 {extra}"
    if params.get("on", "final") not in STAGES:
        return f"{name}.on 只能是 {STAGES}"
    return None


def run(name: str, params: Mapping[str, Any], view: TaskView, scope: Mapping[str, Any]) -> list[str]:
    kwargs = {k: v for k, v in params.items() if k != "on"}
    return STANDARD[name].fn(view, scope, **kwargs)
