from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from impl.core.capability_store import load_capability_map as _load_store


def load_capability_map() -> dict[str, Any]:
    """capability 预设由资料管理页维护，存于 impl/data/llm_probe/capability_map.json。"""
    return _load_store("llm_probe")


def capability_text(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("capability") or "").strip()
    return ""


def boundary_text(entry: Any) -> str:
    """轴2能力边界描述：可选，空字符串表示未填写。"""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("boundary") or "").strip()


def _expand_material_reference(text: str) -> str:
    """capability / boundary 文本里的 material:// 引用展开为资料正文。"""
    from impl.core.materials_store import expand_material_uris

    return expand_material_uris(text).strip()


def resolve_boundary(request: dict[str, Any]) -> dict[str, Any]:
    """从请求或 capability 预设中取 boundary，展开 {material://} 引用。

    返回 {"text": str, "catalog": list}：装得下预算的资料内联进 text；
    装不下的转 catalog 条目（正文由 TextCarrier 的检索工具按需查）。
    未填 boundary 时 text 为空、catalog 为空。
    """
    from impl.core.materials_store import expand_material_uris_with_catalog

    explicit = str(request.get("boundary") or "").strip()
    raw = explicit
    if not raw:
        ref = str(request.get("capability_ref") or "").strip()
        if ref:
            raw = boundary_text(load_capability_map().get(ref))
    if not raw:
        return {"text": "", "catalog": []}
    expanded, catalog = expand_material_uris_with_catalog(raw)
    return {"text": expanded.strip(), "catalog": catalog}


def resolve_capability(request: dict[str, Any]) -> str:
    explicit = str(request.get("capability") or "").strip()
    if explicit:
        return _expand_material_reference(explicit)
    ref = str(request.get("capability_ref") or "").strip()
    if not ref:
        raise ValueError("llm_probe request 需要 capability 或 capability_ref")
    text = capability_text(load_capability_map().get(ref))
    if not text:
        raise ValueError(f"capability 预设 {ref} 不存在或缺能力描述，请在资料管理页添加")
    return _expand_material_reference(text)


def capability_service(ref: str) -> dict[str, Any]:
    """capability 预设自带的探测端点配置（url/method/timeout_seconds）。"""
    entry = load_capability_map().get(ref)
    service = entry.get("service") if isinstance(entry, dict) else None
    if not isinstance(service, dict) or not str(service.get("url") or "").strip():
        raise ValueError(f"capability 预设 {ref} 没有 service.url 配置，请在资料管理页补充")
    return service


def capability_business_trace(ref: str) -> dict[str, Any] | None:
    """仅在场景启用了需要业务 Trace 的过程轴时返回 provider 信封。"""
    entry = load_capability_map().get(ref)
    value = entry.get("business_trace") if isinstance(entry, dict) else None
    if not isinstance(value, dict):
        return None
    from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES

    axes = entry.get("axes") if isinstance(entry.get("axes"), list) else []
    enabled = any(
        isinstance(axis, dict)
        and axis.get("enabled") is True
        and getattr(AXIS_TYPES.get(str(axis.get("type") or "")), "requires_business_trace", False)
        for axis in axes
    )
    return dict(value) if enabled else None


def default_capability_ref() -> str:
    mapping = load_capability_map()
    # 按 key 排序取默认项，避免依赖 YAML 键的书写顺序。
    for key in sorted(mapping):
        if capability_text(mapping[key]):
            return str(key)
    raise ValueError("capability 预设为空，请先在资料管理页添加")


def _fill_template(value: Any, query: str, session_id: str) -> Any:
    if isinstance(value, str):
        # 单次替换，避免把用户 query 中的占位符当成模板再次展开。
        return re.sub(r"\{(query|session_id)\}", lambda match: query if match[1] == "query" else session_id, value)
    if isinstance(value, dict):
        return {key: _fill_template(item, query, session_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill_template(item, query, session_id) for item in value]
    return value


def _body_template(ref: str) -> dict[str, Any]:
    entry = load_capability_map().get(ref)
    template = entry.get("mock_body") if isinstance(entry, dict) else None
    if not isinstance(template, dict):
        raise ValueError(f"capability 预设 {ref} 没有 mock_body 模板，请在资料管理页补充")
    return template


def new_session_id() -> str:
    return f"llm-probe-{uuid4().hex}"


def mock_body(ref: str, query: str) -> dict[str, Any]:
    """按 capability_map 中的 mock_body 模板生成目标项目可接受的请求 body。"""
    return _fill_template(_body_template(ref), query, "{session_id}")


def fresh_session_placeholders(body: Any) -> Any:
    """把请求体里残留的 "{session_id}" 占位符全部换成同一个新会话 id。"""
    session_id = new_session_id()

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            return session_id if value == "{session_id}" else value
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    return fill(body)


Slot = tuple[Any, ...]


def template_slots(ref: str) -> dict[str, list[Slot]]:
    """mock_body 模板里 `{query}` / `{session_id}` 占位符所在的路径。

    会话翻译（SessionTranslator）用它把原话与会话身份确定性地写进请求体，
    不需要知道每个被测接口的字段名。
    """
    slots: dict[str, list[Slot]] = {"query": [], "session_id": []}

    def walk(value: Any, path: Slot) -> None:
        if isinstance(value, str):
            if value == "{query}":
                slots["query"].append(path)
            elif value == "{session_id}":
                slots["session_id"].append(path)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + (index,))

    walk(_body_template(ref), ())
    if not slots["query"]:
        raise ValueError(f"capability 预设 {ref} 的 mock_body 模板没有 {{query}} 占位符")
    return slots


def slot_get(body: Any, path: Slot) -> Any:
    for key in path:
        if isinstance(body, dict):
            body = body.get(key)
        elif isinstance(body, list) and isinstance(key, int) and key < len(body):
            body = body[key]
        else:
            return None
    return body


def slot_set(body: Any, path: Slot, value: Any) -> None:
    for key in path[:-1]:
        body = body[key]
    body[path[-1]] = value
