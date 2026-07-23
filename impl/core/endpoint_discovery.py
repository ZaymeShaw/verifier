"""API endpoint 自动发现引擎（spec/apitool_discover.md）。

通用层一次写好，所有项目复用。根据 project.yaml 的 endpoint_discovery 配置：
- 扫描业务系统源码中的路由装饰器/注册（fastapi / flask / grpc / generic）
- 解析类型注解推导入参/出参形状
- 判断每个 endpoint 可调用性（直接调 / 远程调 / 不能调）
- 自动构建为 VerifiableTool，扫描结果落盘到项目 tools/api_discover/ 目录

新项目接入只需在 project.yaml 填 source_roots 和 framework。
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from impl.core.config_schema import ConfigError
from impl.core.path_contract import LogicalPathRef, PathScope
from impl.core.portable_artifact import write_active_artifact
from impl.tools import ToolResult, VerifiableTool

logger = logging.getLogger(__name__)

__all__ = ["EndpointDiscovery", "discover_endpoints", "write_discovered_tools", "load_discovered_tools"]

# 扫描结果落盘的目录名（相对项目 root）
API_DISCOVER_DIRNAME = "tools/api_discover"

# 落盘的清单文件名
DISCOVER_MANIFEST = "_manifest.json"

# 框架装饰器映射
FRAMEWORK_DECORATORS: Dict[str, List[str]] = {
    "fastapi": ["app.get", "app.post", "app.put", "app.delete", "app.patch", "router.get", "router.post", "router.put", "router.delete", "router.patch"],
    "flask": ["app.route", "bp.route", "blueprint.route"],
    "grpc": [],  # grpc 用 proto 文件，不走 AST
    "generic": ["route", "endpoint", "handler"],
}

# app 级别的装饰器前缀（不在 include_router 里，不加 route_prefix）
APP_DECORATOR_PREFIXES = {"app."}

# HTTP 方法关键词
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
FRAMEWORK_PARAMETER_NAMES = {"request", "response", "background_tasks", "websocket"}
REQUEST_BODY_PARAMETER_NAMES = {"body", "payload", "request", "data"}


def _is_framework_parameter(arg: ast.arg) -> bool:
    if arg.arg in FRAMEWORK_PARAMETER_NAMES:
        return True
    annotation = arg.annotation
    if isinstance(annotation, ast.Name):
        return annotation.id in {"Request", "Response", "BackgroundTasks", "WebSocket"}
    if isinstance(annotation, ast.Attribute):
        return annotation.attr in {"Request", "Response", "BackgroundTasks", "WebSocket"}
    return False


def _tool_description(method: str, route: str, function_name: str, docstring: str) -> str:
    summary = docstring[:200] if docstring else "无函数文档"
    return f"调用已发现的业务 API endpoint。输入该 endpoint 的路径参数和/或 body；输出 {method} {route} ({function_name}) 的 HTTP 响应内容。该工具提供远程 API 行为证据，不解释源码、配置规则或根因。接口说明：{summary}"


def _parameter_description(method: str, route: str, parameter_name: str) -> str:
    return f"业务 API 参数 {parameter_name}，来自 {method} {route} 的处理函数签名；按该接口原始业务协议填写。"


def _body_description(method: str, route: str) -> str:
    return f"请求体 JSON，对应 {method} {route} 的 request body；字段和值应按该业务接口原始协议填写。"

def _match_pattern(path: str, pattern: str) -> bool:
    """简单 glob 匹配：支持 * 通配符。"""
    path_parts = Path(path).parts
    pattern_parts = pattern.split("/")
    if len(path_parts) != len(pattern_parts):
        return False
    for pp, pt in zip(path_parts, pattern_parts):
        if pt == "*" or pt == "**":
            continue
        if pp != pt:
            return False
    return True


def _is_excluded(rel_path: str, exclude_patterns: List[str]) -> bool:
    for pattern in exclude_patterns:
        try:
            if _match_pattern(rel_path, pattern):
                return True
        except Exception:
            if pattern.strip("*") in rel_path:
                return True
    return False


class EndpointInfo:
    """扫描发现的一个 API endpoint。"""
    def __init__(self) -> None:
        self.path: str = ""           # 源码文件路径
        self.method: str = "POST"     # HTTP 方法
        self.route: str = ""          # 路由路径
        self.function_name: str = ""  # 处理函数名
        self.line: int = 0            # 行号
        self.params: List[str] = []   # 参数字段名列表
        self.has_request_body: bool = False
        self.docstring: str = ""      # 函数文档字符串

    def to_manifest_entry(self, project_id: str, source_root: Path | None = None) -> Dict[str, Any]:
        """序列化为 manifest 一条记录（不含 execute_fn）。"""
        tool_id = f"{project_id}.api.{self.function_name}"
        params_properties: Dict[str, Any] = {}
        for p in self.params:
            params_properties[p] = {"type": "string", "description": _parameter_description(self.method, self.route, p)}
        if self.has_request_body:
            params_properties["body"] = {"type": "object", "description": _body_description(self.method, self.route)}
        source_ref = None
        if self.path:
            source_file = Path(self.path).resolve()
            if source_root is None or not source_file.is_relative_to(source_root.resolve()):
                raise ValueError(f"discovered endpoint source is outside business_source: {source_file}")
            source_ref = dict(LogicalPathRef(
                PathScope.BUSINESS_SOURCE,
                source_file.relative_to(source_root.resolve()).as_posix(),
                symbol=self.function_name,
                sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
            ).to_mapping())
        return {
            "tool_id": tool_id,
            "description": _tool_description(self.method, self.route, self.function_name, self.docstring),
            "applicable_scenario": "attr",
            "method": self.method,
            "route": self.route,
            "function_name": self.function_name,
            "source": source_ref,
            "line": self.line,
            "params": self.params,
            "has_request_body": self.has_request_body,
            "docstring": self.docstring,
            "parameters": {
                "type": "object",
                "properties": params_properties,
                "required": list(params_properties.keys())[:1],
            },
        }


class EndpointDiscovery:
    """通用 endpoint 发现引擎。

    根据 project.yaml 的 endpoint_discovery 配置扫描源码，
    找到 API endpoint 并构建为 VerifiableTool。
    """

    def __init__(self, spec: Any) -> None:
        self.spec = spec
        self._config: Dict[str, Any] = {}

    @property
    def config(self) -> Dict[str, Any]:
        if not self._config:
            raw = self.spec.endpoint_discovery_config
            self._config = raw if isinstance(raw, dict) else {}
        return self._config

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled") is True

    def _resolve_source_roots(self) -> List[Path]:
        if self.enabled and hasattr(self.spec, "require"):
            self.spec.require("project.resources.source.repository")
        resolver = getattr(self.spec, "endpoint_source_paths", None)
        if not callable(resolver):
            raise ConfigError("endpoint discovery requires ProjectSpec.endpoint_source_paths")
        return list(resolver())

    def _scan_patterns(self) -> List[str]:
        return list(self.config["scan_patterns"])

    def _exclude_patterns(self) -> List[str]:
        return list(self.config["exclude_patterns"])

    def _framework(self) -> str:
        return str(self.config["framework"])

    def _route_prefix(self) -> str:
        """路由前缀（如 /api/v1）。

        很多项目用 include_router(prefix=...) 给所有 route 加前缀，
        AST 扫描只能看到 @router.post("/foo")，看不到 prefix。
        项目在 endpoint_discovery.route_prefix 声明，加载时拼到 route 前面。
        """
        return str(self.config["route_prefix"])

    def _blacklist_methods(self) -> List[str]:
        """HTTP 方法黑名单（默认 PUT/DELETE/PATCH）。

        项目可在 endpoint_discovery.blacklist.methods 覆盖。
        命中的 endpoint 在发现阶段直接排除，不落盘、不暴露给 LLM。
        """
        return [str(m).upper() for m in self.config["blacklist"]["methods"]]

    def _blacklist_keywords(self) -> List[str]:
        """路由关键词黑名单（默认 reload/reindex/delete/update/create/write）。

        命中 route 或 function_name 任一关键词即排除。
        项目可在 endpoint_discovery.blacklist.route_keywords 覆盖。
        """
        return [str(k).lower() for k in self.config["blacklist"]["route_keywords"]]

    def _is_blacklisted(self, endpoint: EndpointInfo) -> bool:
        """判断 endpoint 是否命中黑名单。命中则发现阶段排除。"""
        # HTTP 方法黑名单
        method = (endpoint.method or "").upper()
        if method in self._blacklist_methods():
            return True
        # 路由关键词黑名单：route 或 function_name 任一命中即排除
        keywords = self._blacklist_keywords()
        route_lower = (endpoint.route or "").lower()
        func_lower = (endpoint.function_name or "").lower()
        for kw in keywords:
            if kw in route_lower or kw in func_lower:
                return True
        return False

    def _walk_source_files(self) -> List[Path]:
        """遍历源码目录，收集所有需要扫描的文件。"""
        files: List[Path] = []
        exclude = self._exclude_patterns()
        for root in self._resolve_source_roots():
            for py_file in root.rglob("*.py"):
                if py_file.is_symlink():
                    continue
                try:
                    rel = str(py_file.relative_to(root))
                except ValueError:
                    continue
                if _is_excluded(rel, exclude):
                    continue
                files.append(py_file)
        return files

    def _extract_endpoints_from_file(self, file_path: Path) -> List[EndpointInfo]:
        """从单个 Python 文件提取 route 装饰器信息。

        注意：AST 扫描只能看到 @router.post("/foo") 里的相对路径，
        看不到 app.include_router(router, prefix="/api/v1") 加的 prefix。
        需要项目在 endpoint_discovery.route_prefix 声明。
        """
        endpoints: List[EndpointInfo] = []
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return endpoints
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return endpoints

        framework = self._framework()
        decorator_names = FRAMEWORK_DECORATORS.get(framework, FRAMEWORK_DECORATORS.get("generic", []))
        prefix = self._route_prefix()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.decorator_list:
                continue

            endpoint = EndpointInfo()
            endpoint.function_name = node.name
            endpoint.line = node.lineno
            endpoint.docstring = ast.get_docstring(node) or ""

            for arg in node.args.args:
                if arg.arg in {"self", "cls"} or _is_framework_parameter(arg):
                    continue
                endpoint.params.append(arg.arg)

            for decorator in node.decorator_list:
                decorator_str = self._decorator_to_string(decorator)
                if not decorator_str:
                    continue

                matched = False
                for dn in decorator_names:
                    if decorator_str.startswith(dn):
                        matched = True
                        break
                if not matched:
                    continue

                method, route = self._parse_decorator(decorator_str, decorator)
                if method:
                    endpoint.method = method
                if route:
                    # app 级别装饰器（@app.get）不加 prefix；
                    # router 级别装饰器（@router.post）才加 route_prefix
                    is_app_decorator = any(decorator_str.startswith(p) for p in APP_DECORATOR_PREFIXES)
                    if prefix and not is_app_decorator:
                        endpoint.route = prefix.rstrip("/") + "/" + route.lstrip("/")
                    else:
                        endpoint.route = route

                endpoint.has_request_body = any(
                    arg.arg in REQUEST_BODY_PARAMETER_NAMES
                    for arg in node.args.args
                )

                if endpoint.route:
                    endpoints.append(endpoint)
                    break

        return endpoints

    def _decorator_to_string(self, node: ast.expr) -> str:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                parts = [node.func.attr]
                obj = node.func.value
                while isinstance(obj, ast.Attribute):
                    parts.append(obj.attr)
                    obj = obj.value
                if isinstance(obj, ast.Name):
                    parts.append(obj.id)
                parts.reverse()
                return ".".join(parts)
            elif isinstance(node.func, ast.Name):
                return node.func.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def _parse_decorator(self, decorator_str: str, node: ast.expr) -> tuple[str, str]:
        """从装饰器调用中提取 HTTP 方法和路由路径。"""
        method = ""
        route = ""
        parts = decorator_str.split(".")
        for part in parts:
            if part.lower() in HTTP_METHODS:
                method = part.upper()
                break

        if not method:
            method = "POST"

        # 提取路由路径
        if isinstance(node, ast.Call) and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                route = first_arg.value
            elif isinstance(first_arg, ast.Str):  # Python 3.7 兼容
                route = first_arg.s

        return method, route

    def _build_tool_from_endpoint(self, endpoint: EndpointInfo, file_path: Path) -> VerifiableTool:
        """将发现的一个 endpoint 构建为 VerifiableTool。"""
        tool_id = f"{self.spec.project_id}.api.{endpoint.function_name}"
        # 自动生成 execute_fn（占位，调远程 API）
        params_properties: Dict[str, Any] = {}
        for p in endpoint.params:
            params_properties[p] = {"type": "string", "description": _parameter_description(endpoint.method, endpoint.route, p)}
        if endpoint.has_request_body:
            params_properties["body"] = {"type": "object", "description": _body_description(endpoint.method, endpoint.route)}

        return VerifiableTool(
            tool_id=tool_id,
            description=_tool_description(endpoint.method, endpoint.route, endpoint.function_name, endpoint.docstring),
            applicable_scenario="attr",
            parameters={
                "type": "object",
                "properties": params_properties,
                "required": list(params_properties.keys())[:1],
            },
            execute_fn=None,  # 远程调用的 execute_fn 由 adapter 按需填充
        )

    def discover_raw(self) -> List[EndpointInfo]:
        """执行扫描，返回 EndpointInfo 列表（不构建 tool，不落盘）。

        黑名单过滤在发现阶段就执行——命中黑名单的 endpoint 不进入列表，
        后续落盘、注册、暴露给 LLM 等所有环节都看不到它。
        """
        if not self.enabled:
            return []
        all_endpoints: List[EndpointInfo] = []
        files = self._walk_source_files()
        if not self._resolve_source_roots():
            raise ConfigError(
                f"enabled endpoint discovery has no readable source roots: {self.spec.project_id}"
            )
        for file_path in files:
            all_endpoints.extend(self._extract_endpoints_from_file(file_path))
        blacklisted = 0
        passed: List[EndpointInfo] = []
        for ep in all_endpoints:
            if self._is_blacklisted(ep):
                blacklisted += 1
                continue
            passed.append(ep)
        logger.info(
            f"[endpoint_discovery] project={self.spec.project_id} "
            f"framework={self._framework()} files={len(files)} "
            f"endpoints={len(passed)} (blacklisted={blacklisted})"
        )
        return passed

    def discover(self) -> List[VerifiableTool]:
        """执行扫描，返回发现的 endpoint 构成的 VerifiableTool 列表。

        不落盘——落盘用 write_discovered_tools()。这里只构建内存中的 tool。
        """
        return [self._build_tool_from_endpoint(ep, Path(ep.path)) for ep in self.discover_raw()]


def write_discovered_tools(spec: Any) -> Path:
    """扫描源码并把结果落盘到项目 tools/api_discover/_manifest.json。

    全量覆盖（清空旧文件后重写），不和手工 tool 混。
    返回 manifest 文件路径。未配置 endpoint_discovery 时返回空 Path。
    """
    discovery = EndpointDiscovery(spec)
    if not discovery.enabled:
        return Path()

    endpoints = discovery.discover_raw()
    package_accessor = getattr(spec, "project_package_path", None)
    source_accessor = getattr(spec, "source_root_path", None)
    verifier_accessor = getattr(spec, "verifier_root_path", None)
    if not all(callable(item) for item in (package_accessor, source_accessor, verifier_accessor)):
        raise ConfigError("endpoint discovery requires resolver-backed ProjectSpec path accessors")
    out_dir = package_accessor(
        API_DISCOVER_DIRNAME,
        field_path="endpoint_discovery.output_directory",
        expected_type="any",
        must_exist=False,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清空目录下旧的自动生成文件（保留 __init__.py）
    for old in out_dir.glob("*"):
        if old.name == "__init__.py":
            continue
        try:
            old.unlink()
        except OSError:
            pass

    business_root = source_accessor()
    manifest_entries = [ep.to_manifest_entry(spec.project_id, business_root) for ep in endpoints]
    manifest_path = out_dir / DISCOVER_MANIFEST
    write_active_artifact(
        "endpoint_discovery_manifest",
        manifest_path,
        {
            "schema_version": 2,
            "project_id": spec.project_id,
            "framework": discovery._framework(),
            "endpoint_count": len(manifest_entries),
            "endpoints": manifest_entries,
        },
        repository_root=verifier_accessor(),
    )
    logger.info(
        f"[endpoint_discovery] wrote {len(manifest_entries)} endpoints to {manifest_path}"
    )
    return manifest_path


def load_discovered_tools(spec: Any) -> List[VerifiableTool]:
    """从项目 tools/api_discover/_manifest.json 加载已落盘的发现 tool。

    若 manifest 不存在，先触发一次 write_discovered_tools 落盘。
    execute_fn 为 None 的 tool 由 call_api 通用 tool 间接调用，不直接暴露给 agno。
    """
    service = spec.require_service("primary")
    api_base = str(service["base_url"])
    request_timeout_seconds = float(service["timeout_seconds"])
    manifest_accessor = getattr(spec, "endpoint_manifest_path", None)
    if not callable(manifest_accessor):
        raise ConfigError("endpoint discovery requires ProjectSpec.endpoint_manifest_path")
    manifest_path = manifest_accessor(must_exist=False)
    if not manifest_path.exists():
        written = write_discovered_tools(spec)
        if not written:
            return []
    if not manifest_path.exists():
        return []

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[endpoint_discovery] failed to read manifest {manifest_path}: {exc}")
        return []

    tools: List[VerifiableTool] = []
    for entry in data.get("endpoints") or []:
        missing = [key for key in ("method", "route", "tool_id", "parameters") if key not in entry]
        if missing:
            raise ConfigError(f"endpoint discovery manifest entry is missing: {', '.join(missing)}")
        method = entry["method"]
        route = entry["route"]
        tool_id = entry["tool_id"]
        params_properties = entry.get("parameters", {}).get("properties", {})
        for param_name, param_schema in params_properties.items():
            if not isinstance(param_schema, dict):
                continue
            description = str(param_schema.get("description") or "")
            if description.startswith("参数 ") or description.startswith("API 路由参数 "):
                param_schema["description"] = _parameter_description(method, route, param_name)
            elif description == "请求体 JSON" or description.startswith("请求体 JSON"):
                param_schema["description"] = _body_description(method, route)
        raw_required = entry.get("parameters", {}).get("required") or []
        normalized_required = [item for item in raw_required if item in params_properties]

        # 为每个 api-discovered tool 生成远程调用 execute_fn
        def _make_execute_fn(m: str, r: str, tid: str, base: str, timeout_seconds: float) -> Any:
            import urllib.request as _urllib_req
            import urllib.error as _urllib_err
            import json as _json
            from urllib.parse import urljoin as _urljoin

            def _execute(**kwargs: Any) -> Any:
                # agno validate_call 按 JSON schema kwargs 传参，用 **kwargs 接收
                params = kwargs
                url = _urljoin(str(base).rstrip("/") + "/", r.lstrip("/"))
                # GET 请求不传 body，params 作为 query string
                if m.upper() == "GET":
                    import urllib.parse as _up
                    qs = _up.urlencode(params) if params else ""
                    full_url = f"{url}?{qs}" if qs else url
                    req = _urllib_req.Request(full_url, method="GET")
                else:
                    payload = params.get("body") if isinstance(params, dict) and "body" in params else params
                    body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    req = _urllib_req.Request(url, data=body, headers={"Content-Type": "application/json"}, method=m.upper())
                try:
                    with _urllib_req.urlopen(req, timeout=timeout_seconds) as resp:
                        text = resp.read().decode("utf-8")
                    try:
                        result = _json.loads(text)
                    except _json.JSONDecodeError:
                        result = {"raw_text": text}
                    return ToolResult(tool_id=tid, status="succeeded", actual=result if isinstance(result, dict) else {"response": result}, evidence=f"called {m} {r}")
                except (_urllib_err.URLError, TimeoutError, OSError) as exc:
                    return ToolResult(tool_id=tid, status="failed", error=str(exc), evidence=f"called {m} {r}; error={exc}")
            _execute.__name__ = tid.replace(".", "_")
            _execute.__doc__ = entry.get("description", f"API endpoint: {m} {r}")
            return _execute

        execute_fn = _make_execute_fn(method, route, tool_id, api_base, request_timeout_seconds)

        tools.append(
            VerifiableTool(
                tool_id=tool_id,
                description=entry.get("description", ""),
                applicable_scenario=entry.get("applicable_scenario", "attr"),
                parameters={**(entry.get("parameters") or {}), "properties": params_properties, "required": normalized_required},
                execute_fn=execute_fn,
            )
        )
    return tools


def discover_endpoints(spec: Any) -> List[VerifiableTool]:
    """便捷函数：从 ProjectSpec 发现 endpoint 并构建为 VerifiableTool 列表（内存，不落盘）。"""
    return EndpointDiscovery(spec).discover()
