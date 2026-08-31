from __future__ import annotations

from typing import Any

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


def default_capability_ref() -> str:
    mapping = load_capability_map()
    # 按 key 排序取默认项，避免依赖 YAML 键的书写顺序。
    for key in sorted(mapping):
        if capability_text(mapping[key]):
            return str(key)
    raise ValueError("capability 预设为空，请先在资料管理页添加")


def _fill_template(value: Any, query: str) -> Any:
    if isinstance(value, str):
        return value.replace("{query}", query)
    if isinstance(value, dict):
        return {key: _fill_template(item, query) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill_template(item, query) for item in value]
    return value


def mock_body(ref: str, query: str) -> dict[str, Any]:
    """按 capability_map 中的 mock_body 模板生成目标项目可接受的请求 body。"""
    entry = load_capability_map().get(ref)
    template = entry.get("mock_body") if isinstance(entry, dict) else None
    if not isinstance(template, dict):
        raise ValueError(f"capability 预设 {ref} 没有 mock_body 模板，请在资料管理页补充")
    return _fill_template(template, query)
