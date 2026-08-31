"""用户资料存储：capability 预设注册表（impl/data/<project>/capability_map.json）。

用户资料（能力口径、探测端点、mock 模板）与系统资产（evaluation.md 等 judge 治理文档）
分离：前者由资料管理页 / /api/capability/* CRUD 维护，存放在数据目录；后者随代码版本管理。
写入走 active artifact registry（capability_map_store family）做 schema 校验与规范化落盘。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from .portable_artifact import write_active_artifact

ROOT = Path(__file__).resolve().parents[1]

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
# 项目 id 允许大写（如 QA）；此校验的目的只是防路径穿越，不是命名政策。
PROJECT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
MAX_CAPABILITY_CHARS = 20000
ALLOWED_METHODS = ("POST", "PUT", "PATCH")
# json：普通 JSON 响应。sse_last_frame：SSE 但最后一帧是全量内容（伪流式），取最后一帧评。
ALLOWED_RESPONSE_MODES = ("json", "sse_last_frame")


def store_path(project_id: str) -> Path:
    # project_id 进路径，必须先过标识符校验，防止 API 传入路径穿越。
    if not PROJECT_PATTERN.fullmatch(str(project_id or "")):
        raise ValueError(f"非法 project id: {project_id!r}")
    return ROOT / "data" / project_id / "capability_map.json"


def load_capability_map(project_id: str) -> Dict[str, Any]:
    path = store_path(project_id)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 预设名 -> 条目 的 JSON 对象")
    return data


def validate_entry(name: str, entry: Any) -> Dict[str, Any]:
    """校验并规范化单条 capability 预设，返回可落盘形状。"""
    if not NAME_PATTERN.fullmatch(str(name or "")):
        raise ValueError("预设名必须是小写字母开头、由小写字母/数字/_/- 组成的标识符")
    if not isinstance(entry, dict):
        raise ValueError("capability 预设必须是 JSON 对象")
    capability = str(entry.get("capability") or "").strip()
    if not capability:
        raise ValueError("capability 描述不能为空")
    if len(capability) > MAX_CAPABILITY_CHARS:
        raise ValueError(f"capability 描述超过 {MAX_CAPABILITY_CHARS} 字符上限")
    _require_material_refs(capability, field="capability")
    clean: Dict[str, Any] = {"capability": capability}
    service = entry.get("service")
    if service not in (None, "", {}):
        if not isinstance(service, dict) or not str(service.get("url") or "").strip():
            raise ValueError("service 必须是包含 url 的对象")
        method = str(service.get("method") or "POST").strip().upper()
        if method not in ALLOWED_METHODS:
            raise ValueError(f"service.method 只支持 {'/'.join(ALLOWED_METHODS)}")
        try:
            timeout = float(service.get("timeout_seconds") or 60)
        except (TypeError, ValueError) as exc:
            raise ValueError("service.timeout_seconds 必须是数字") from exc
        if timeout <= 0:
            raise ValueError("service.timeout_seconds 必须为正数")
        clean["service"] = {
            "url": str(service["url"]).strip(),
            "method": method,
            "timeout_seconds": timeout,
        }
        response_mode = str(service.get("response_mode") or "json").strip().lower()
        if response_mode not in ALLOWED_RESPONSE_MODES:
            raise ValueError(f"service.response_mode 只支持 {'/'.join(ALLOWED_RESPONSE_MODES)}")
        if response_mode != "json":
            clean["service"]["response_mode"] = response_mode
        raw_headers = service.get("headers")
        if raw_headers not in (None, "", {}):
            if not isinstance(raw_headers, dict):
                raise ValueError("service.headers 必须是对象")
            headers = {}
            for key, value in raw_headers.items():
                name = str(key).strip()
                if not name:
                    raise ValueError("service.headers 的键不能为空")
                headers[name] = str(value)
            if headers:
                clean["service"]["headers"] = headers
    mock_body = entry.get("mock_body")
    if mock_body not in (None, "", {}):
        if not isinstance(mock_body, dict):
            raise ValueError("mock_body 必须是 JSON 对象模板")
        clean["mock_body"] = mock_body
    raw_boundary = entry.get("boundary")
    if raw_boundary not in (None, ""):
        if not isinstance(raw_boundary, str):
            raise ValueError("boundary 必须是字符串")
        boundary = raw_boundary.strip()
        if len(boundary) > MAX_CAPABILITY_CHARS:
            raise ValueError(f"boundary 描述超过 {MAX_CAPABILITY_CHARS} 字符上限")
        if boundary:
            _require_material_refs(boundary, field="boundary")
            clean["boundary"] = boundary
    return clean


def _require_material_refs(text: str, *, field: str) -> None:
    """保存时校验正文里的 material://：格式非法或资料不存在则拒写，正文仍原样保存。

    capability 是 prompt-load 消费，超预算即拒；boundary 走检索式消费，
    超预算的资料运行时自动转可检索目录条目，保存时不因大小拒写。
    """
    from .materials_store import expand_material_uris, expand_material_uris_with_catalog

    try:
        if field == "boundary":
            expand_material_uris_with_catalog(text)
        else:
            expand_material_uris(text)
    except ValueError as exc:
        raise ValueError(f"{field} 资料引用无效: {exc}") from exc


def save_capability(project_id: str, name: str, entry: Any) -> Dict[str, Any]:
    data = load_capability_map(project_id)
    data[str(name)] = validate_entry(name, entry)
    _write(project_id, data)
    return {"project_id": project_id, "name": name, "entry": data[str(name)], "count": len(data)}


def delete_capability(project_id: str, name: str) -> Dict[str, Any]:
    data = load_capability_map(project_id)
    existed = str(name) in data
    data.pop(str(name), None)
    _write(project_id, data)
    return {"project_id": project_id, "name": name, "deleted": existed, "count": len(data)}


def _write(project_id: str, data: Dict[str, Any]) -> None:
    path = store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_active_artifact("capability_map_store", path, data, repository_root=ROOT.parent)
