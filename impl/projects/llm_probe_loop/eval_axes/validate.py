"""场景轴框的校验（fail fast，spec/alg/axis_loop.md §3.4）：轴定义与场景启用的轴、选用的信息源对得上。

场景条目的 axes[] 沿用 {type, enabled, description}；description 里的 {es://…}/{mcp://…}/{material://…} 是这个轴挑的知识源。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from impl.core.axis_loop.validate import check_definitions, check_scenario, scenario_warnings
from impl.core.capability_store import load_capability_map

from .materials import registry as material_registry
from .registry import PROJECT, definitions
from .sources import selected_categories, validate_source_capability, validate_source_refs

MAX_DESCRIPTION_CHARS = 20000


@dataclass(frozen=True)
class ScenarioAxes:
    enabled: list[str]            # 按场景框顺序
    notes: dict[str, str]         # 轴 id → 框描述（原文）
    warnings: tuple[str, ...] = ()


def parse_axes(raw: Any, *, owner: str = "axes") -> list[dict[str, Any]]:
    """只校形状（与 capability_store.validate_entry 一致），不查定义。"""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{owner} 必须是列表")
    seen, out = set(), []
    for index, item in enumerate(raw):
        label = f"{owner}[{index}]"
        if not isinstance(item, Mapping) or not str(item.get("type") or "").strip():
            raise ValueError(f"{label} 必须是带 type 的对象")
        if item["type"] in seen:
            raise ValueError(f"{owner}: 同一类型 {item['type']} 只允许一个框")
        seen.add(item["type"])
        if not isinstance(item.get("enabled", False), bool) or not isinstance(item.get("description", ""), str):
            raise ValueError(f"{label}.enabled 必须是布尔值、description 必须是字符串")
        if len(item.get("description", "")) > MAX_DESCRIPTION_CHARS:
            raise ValueError(f"{label}.description 超过 {MAX_DESCRIPTION_CHARS} 字")
        out.append({"type": str(item["type"]), "enabled": bool(item.get("enabled")), "description": str(item.get("description") or "")})
    return out


def scenario_axes(entry: Mapping[str, Any], *, owner: str) -> ScenarioAxes:
    boxes = parse_axes(entry.get("axes"), owner=f"{owner}.axes")
    return ScenarioAxes([b["type"] for b in boxes if b["enabled"]], {b["type"]: b["description"] for b in boxes})


def validate_scenario_entry(entry: Mapping[str, Any], *, owner: str) -> ScenarioAxes:
    """保存场景时：启用的轴已定义、依赖齐、知识源引用合法且已登记；选了 trace 源的，登记在、绑定合法。"""
    if "process_obligations" in entry:
        raise ValueError(f"{owner}: 过程职责写进对应本应轴的描述框，不另设 process_obligations（spec/alg/axis_loop.md §2.5）")
    if "boundary" in entry:
        raise ValueError(f"{owner}: 责任范围写进承载性的描述框，不另设 boundary（spec/alg/axis_loop.md §12.3）")
    axes = scenario_axes(entry, owner=owner)
    defs = definitions()
    errors = check_definitions(defs, material_registry())
    for key in axes.enabled:
        try:
            validate_source_refs(axes.notes.get(key) or "")
            validate_source_capability(axes.notes.get(key) or "")
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    try:
        categories = selected_categories(axes.notes.get(k) or "" for k in axes.enabled)
    except (ValueError, KeyError) as exc:
        errors.append(f"信息源引用解析失败：{exc}")
        categories = set()
    errors += check_scenario(defs, axes.enabled, categories)
    if entry.get("business_trace"):
        from impl.projects.llm_probe_loop.business_trace import validate_selection
        try:
            validate_selection(entry["business_trace"])
        except ValueError as exc:
            errors.append(f"business_trace: {exc}")
    if errors:
        raise ValueError(f"{owner}: 评测轴配置无效：" + "；".join(errors))
    try:  # 选用看全部框（含没启用的）：选了信息源却没开用它的轴，要提醒
        selected = selected_categories(axes.notes.values())
    except (ValueError, KeyError):
        selected = categories
    return ScenarioAxes(axes.enabled, axes.notes, tuple(scenario_warnings(defs, axes.enabled, selected)))


def load_scenario_axes(scenario_id: str) -> ScenarioAxes:
    entry = load_capability_map(PROJECT).get(scenario_id)
    if not isinstance(entry, Mapping):
        raise ValueError(f"场景预设 {scenario_id!r} 不存在")
    return validate_scenario_entry(entry, owner=scenario_id)
