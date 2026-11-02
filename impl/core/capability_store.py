"""用户资料存储：capability 预设注册表（impl/data/<project>/capability_map.json）。

用户资料（能力口径、探测端点、mock 模板）与系统资产（evaluation.md 等 judge 治理文档）
分离：前者由资料管理页 / /api/capability/* CRUD 维护，存放在数据目录；后者随代码版本管理。
写入走 active artifact registry（capability_map_store family）做 schema 校验与规范化落盘。
"""
from __future__ import annotations

from .instances import data_root

import json
import re
from pathlib import Path
from typing import Any, Dict

from .portable_artifact import write_active_artifact

ROOT = Path(__file__).resolve().parents[1]

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
AXIS_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
TRACE_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
TRACE_SOURCE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")
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
    return data_root(ROOT.parent) / project_id / "capability_map.json"


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
    # Explicit requirement-side material: validate shape without rewriting source text.
    for key in ("criterion", "description"):
        if key in entry:
            value = entry[key]
            if not isinstance(value, str):
                raise ValueError(f"{key} 必须是字符串")
            if len(value) > MAX_CAPABILITY_CHARS:
                raise ValueError(f"{key} 超过 {MAX_CAPABILITY_CHARS} 字符上限")
            clean[key] = value
    if "downstream" in entry:
        downstream = entry["downstream"]
        if not isinstance(downstream, list) or not all(isinstance(item, str) for item in downstream):
            raise ValueError("downstream 必须是字符串列表")
        clean["downstream"] = list(downstream)
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
        # 端点连不上时附在报错里的启动提示（如被测目标是只在实验时才开的本机进程）。
        start_hint = str(service.get("start_hint") or "").strip()
        if start_hint:
            clean["service"]["start_hint"] = start_hint
    business_trace = entry.get("business_trace")
    if business_trace not in (None, "", {}) and isinstance(business_trace, dict) and "source" in business_trace:
        # llm_probe_loop 的写法（spec/alg/axis_loop.md §8.2）：连接在全局登记，场景只写选哪个 trace 源与字段绑定。
        source, bindings = str(business_trace.get("source") or "").strip(), business_trace.get("bindings")
        if not TRACE_SOURCE_PATTERN.fullmatch(source) or not isinstance(bindings, dict) \
                or set(business_trace) - {"source", "bindings"}:
            raise ValueError("business_trace 写成 {source: 登记名, bindings: {...}}")
        clean["business_trace"] = {"source": source, "bindings": dict(bindings)}
    elif business_trace not in (None, "", {}):
        if not isinstance(business_trace, dict):
            raise ValueError("business_trace 必须是对象")
        provider = str(business_trace.get("provider") or "").strip().lower()
        if not TRACE_PROVIDER_PATTERN.fullmatch(provider):
            raise ValueError("business_trace.provider 必须是小写标识符")
        config = business_trace.get("config")
        if not isinstance(config, dict):
            raise ValueError("business_trace.config 必须是对象")
        # provider 专属字段由 llm_probe 在保存和运行前校验；core 只保留稳定信封。
        clean["business_trace"] = {"provider": provider, "config": dict(config)}
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
    raw_failure = entry.get("business_failure")
    if raw_failure not in (None, "", {}):
        clean["business_failure"] = _validate_business_failure(raw_failure)
    raw_axes = entry.get("axes")
    if raw_axes not in (None, "", []):
        clean["axes"] = _validate_axes(raw_axes)
    raw_obligations = entry.get("process_obligations")
    if raw_obligations not in (None, "", []):
        clean["process_obligations"] = _validate_process_obligations(raw_obligations)
    return clean


def _validate_business_failure(raw: Any) -> Dict[str, Any]:
    """场景预先维护的"被测系统调用失败"错误码（demand/main_axis.md §3.6）：命中即这条 case 记运行失败。

    {"http_status": [500, 503], "body": {"pointer": "/code", "values": ["E1001"]}}，两项都可省。
    """
    if not isinstance(raw, dict) or set(raw) - {"http_status", "body"}:
        raise ValueError("business_failure 只认 http_status / body 两项")
    clean: Dict[str, Any] = {}
    statuses = raw.get("http_status")
    if statuses not in (None, []):
        if not isinstance(statuses, list) or any(isinstance(c, bool) or not isinstance(c, int) or not 100 <= c <= 599 for c in statuses):
            raise ValueError("business_failure.http_status 必须是 100–599 的整数列表")
        clean["http_status"] = sorted(set(statuses))
    body = raw.get("body")
    if body not in (None, {}):
        pointer, values = (body or {}).get("pointer"), (body or {}).get("values")
        if not isinstance(body, dict) or set(body) - {"pointer", "values"} or not isinstance(pointer, str) \
                or not pointer.startswith("/") or not isinstance(values, list) or not values:
            raise ValueError("business_failure.body 必须写成 {pointer: '/字段路径', values: [错误码…]}")
        clean["body"] = {"pointer": pointer, "values": [str(v) for v in values]}
    return clean


def _validate_process_obligations(raw: Any) -> list[Dict[str, Any]]:
    """项目声明（spec/math-abstract/process-axes.md §4 第 4 层）：这里只校形状；环节类型是否存在由
    llm_probe 在加载时查。每条必须写明用户确认日期。"""
    if not isinstance(raw, list):
        raise ValueError("process_obligations 必须是列表")
    out: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        label = f"process_obligations[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} 必须是 JSON 对象")
        ob_id = str(item.get("id") or "").strip()
        if not AXIS_TYPE_PATTERN.fullmatch(ob_id) or ob_id in seen:
            raise ValueError(f"{label}.id 必须是唯一的小写标识符")
        seen.add(ob_id)
        clean: Dict[str, Any] = {"id": ob_id}
        for key in ("link_type", "situation", "duty", "confirmed"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label}.{key} 不能为空")
            clean[key] = value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean["confirmed"]):
            raise ValueError(f"{label}.confirmed 必须是 YYYY-MM-DD")
        applies_to = item.get("applies_to")
        if applies_to not in (None, []):
            if not isinstance(applies_to, list) or not all(isinstance(x, str) and x.strip() for x in applies_to):
                raise ValueError(f"{label}.applies_to 必须是非空字符串列表")
            clean["applies_to"] = [x.strip() for x in applies_to]
        if isinstance(item.get("label"), str) and item["label"].strip():
            clean["label"] = item["label"].strip()
        out.append(clean)
    return out


def _validate_axes(raw: Any) -> list[Dict[str, Any]]:
    """扩展评估轴的框（spec/adapter/axe-v4.md §4.2）：这里只校形状，类型是否注册由
    impl/projects/llm_probe/eval_axes 在加载时查——core 不 import 项目代码。"""
    if not isinstance(raw, list):
        raise ValueError("axes 必须是列表")
    axes: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        label = f"axes[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} 必须是 JSON 对象")
        type_id = str(item.get("type") or "").strip()
        if not AXIS_TYPE_PATTERN.fullmatch(type_id):
            raise ValueError(f"{label}.type 必须是小写字母开头、由小写字母/数字/_ 组成的标识符")
        if type_id in seen:
            raise ValueError(f"axes: 同一类型 {type_id} 只允许一个框")
        seen.add(type_id)
        enabled = item.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(f"{label}.enabled 必须是布尔值")
        # 是否必填由轴类型决定（eval_axes.validate）；这里只校形状。
        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"{label}.description 必须是字符串")
        description = description.strip()
        if len(description) > MAX_CAPABILITY_CHARS:
            raise ValueError(f"{label}.description 超过 {MAX_CAPABILITY_CHARS} 字符上限")
        # 保存时按检索式口径校引用有效性（不因大小拒写）；prompt-load 类型的预算在加载时由该类型自己查。
        validate_es_refs(description)
        validate_mcp_refs(description)
        _require_material_refs(description, field=f"{label}.description", catalog=True)
        axes.append({"type": type_id, "enabled": enabled, "description": description})
    return axes


def validate_es_refs(text: str) -> list[str]:
    """ES 引用保存时只校格式，绝不连接数据源；返回 ``<知识源名>/<索引>`` 列表。

    各业务系统的 ES 各自独立：知识源名指向 knowledge_sources.json 里登记的连接。
    """
    refs = []
    for match in re.finditer(r"\{es://([^}]*)\}|(\{es://[^}]*$)", text):
        ref = match.group(1)
        if ref is None or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_.-]*", ref):
            raise ValueError("ES 引用必须形如 {es://<知识源名>/<索引>}，知识源名为小写字母、数字、_、-，索引名为小写字母、数字、_、.、-")
        if ref not in refs:
            refs.append(ref)
    return refs


def validate_mcp_refs(text: str) -> list[str]:
    """MCP 引用保存时只校格式，不拉起进程；返回知识源名列表。"""
    names = []
    for match in re.finditer(r"\{mcp://([^}]*)\}|(\{mcp://[^}]*$)", text):
        name = match.group(1)
        if name is None or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            raise ValueError("MCP 引用必须形如 {mcp://<知识源名>}，知识源名为小写字母、数字、_、-")
        if name not in names:
            names.append(name)
    return names


def _require_material_refs(text: str, *, field: str, catalog: bool | None = None) -> None:
    """保存时校验正文里的 material://：格式非法或资料不存在则拒写，正文仍原样保存。

    capability 是 prompt-load 消费，超预算即拒；boundary 走检索式消费，
    超预算的资料运行时自动转可检索目录条目，保存时不因大小拒写。
    """
    from .materials_store import expand_material_uris, expand_material_uris_with_catalog

    if catalog is None:
        catalog = field == "boundary"
    try:
        if catalog:
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
