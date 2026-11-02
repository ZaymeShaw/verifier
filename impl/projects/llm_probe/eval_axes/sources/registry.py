"""知识源登记：按名字登记各业务系统自己的知识源连接，场景描述只写 {es://<名字>/<索引>} 或 {mcp://<名字>}。

登记文件 knowledge_sources.json 与 capability_map.json 同目录（同一个数据根：仓库 impl/data 或实例数据目录）：
连接地址、超时、检索上限都在这里；凭据写 ``${VAR}``，值取 .env + 进程环境（进程覆盖 .env），
变量须在 project.yaml 的 environment 里登记。读登记不连数据源。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from impl.core import capability_store
from impl.core.config import ROOT
from impl.core.config_bootstrap import effective_environment_snapshot


def registry_path():
    # 跟场景预设同一个数据根：场景里的引用和它指向的登记必须读自同一处，否则删除保护会查空。
    return capability_store.store_path("llm_probe").with_name("knowledge_sources.json")

SOURCE_NAME = r"[a-z0-9][a-z0-9_-]*"
_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_ES_KEYS = {"type", "description", "url", "api_key", "basic_auth", "timeout_seconds", "max_hits", "max_field_chars"}
# 与 .mcp.json 的 mcpServers 条目同形（command/args/env），只支持 stdio：由评测侧按需拉起进程。
_MCP_KEYS = {"type", "description", "command", "args", "env", "tools", "timeout_seconds", "max_chars"}


@dataclass(frozen=True)
class EsSource:
    name: str
    base_url: str
    api_key: str = ""
    basic_auth: str = ""
    timeout_seconds: float = 15
    max_hits: int = 8
    max_field_chars: int = 6000


def _expand(value: str, field: str, expand: bool) -> str:
    if not expand:
        # 保存时只校 ${VAR} 的写法，不要求变量已设置：凭据可以晚于登记配好。
        return value
    snapshot = effective_environment_snapshot(ROOT / ".env")

    def replace(match: re.Match[str]) -> str:
        got = str(snapshot.get(match.group(1)) or "").strip()
        if not got:
            raise ValueError(f"{field} 引用的环境变量 {match.group(1)} 未设置")
        return got

    return _ENV_PLACEHOLDER.sub(replace, value)


def _number(entry: dict, key: str, default, kind, label: str):
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or (kind is int and not isinstance(value, int)):
        raise ValueError(f"{label}.{key} 必须是正{'整数' if kind is int else '数'}")
    return kind(value)


@dataclass(frozen=True)
class McpSource:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    tools: tuple[str, ...] = ()  # 允许评测使用的工具（只读白名单）；MCP 里其余工具不暴露
    timeout_seconds: float = 60
    max_chars: int = 6000


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(SOURCE_NAME, name):
        raise ValueError(f"知识源名 {name!r} 只能用小写字母、数字、_、-，且以字母或数字开头")


def _check_keys(entry: dict, keys: set[str], label: str) -> None:
    unknown = sorted(set(entry) - keys)
    if unknown:
        raise ValueError(f"{label} 有未知字段 {unknown}")


def parse_es(name: str, entry: dict, *, expand: bool = True) -> EsSource:
    label = f"knowledge_sources.{name}"
    _check_keys(entry, _ES_KEYS, label)
    url = urlsplit(str(entry.get("url") or ""))
    if url.scheme not in ("http", "https") or not url.netloc or url.query or url.fragment or url.username:
        raise ValueError(f"{label}.url 必须是无凭据的 HTTP(S) 地址")
    api_key = _expand(str(entry.get("api_key") or ""), f"{label}.api_key", expand)
    basic_auth = _expand(str(entry.get("basic_auth") or ""), f"{label}.basic_auth", expand)
    if api_key and basic_auth:
        raise ValueError(f"{label} 的 api_key 与 basic_auth 不能同时配置")
    if basic_auth and not _ENV_PLACEHOLDER.fullmatch(basic_auth) and ":" not in basic_auth:
        raise ValueError(f"{label}.basic_auth 必须是 user:pass")
    return EsSource(
        name=name, base_url=str(entry["url"]), api_key=api_key, basic_auth=basic_auth,
        timeout_seconds=_number(entry, "timeout_seconds", 15, float, label),
        max_hits=_number(entry, "max_hits", 8, int, label),
        max_field_chars=_number(entry, "max_field_chars", 6000, int, label),
    )


def parse_mcp(name: str, entry: dict, *, expand: bool = True) -> McpSource:
    label = f"knowledge_sources.{name}"
    _check_keys(entry, _MCP_KEYS, label)
    command, args, env = entry.get("command"), entry.get("args", []), entry.get("env", {})
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"{label}.command 必须是可执行文件路径")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError(f"{label}.args 必须是字符串列表")
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError(f"{label}.env 必须是字符串到字符串的映射")
    tools = entry.get("tools")
    # 评测只读：登记时逐个声明放开哪些工具，带身份或有副作用的不放（demand/information_sources.md §4.3）。
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t.strip() for t in tools) or len(set(tools)) != len(tools):
        raise ValueError(f"{label}.tools 必须是非空、不重复的工具名列表：只列允许评测使用的只读工具（「测试连接」可列出全部工具）")
    return McpSource(
        name=name, command=command, args=tuple(args),
        env=tuple((k, _expand(v, f"{label}.env.{k}", expand)) for k, v in env.items()),
        tools=tuple(tools),
        timeout_seconds=_number(entry, "timeout_seconds", 60, float, label),
        max_chars=_number(entry, "max_chars", 6000, int, label),
    )


_PARSERS = {"es": parse_es, "mcp": parse_mcp}


def load_registry() -> dict:
    try:
        registry = json.loads(registry_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(registry, dict):
        raise ValueError(f"{registry_path()} 必须是 {{知识源名: 配置}} 对象")
    return registry


def _load(name: str, kind: str):
    _check_name(name)
    entry = load_registry().get(name)
    if not isinstance(entry, dict):
        raise ValueError(f"知识源 {name} 未登记（{registry_path()}）")
    if entry.get("type") != kind:
        raise ValueError(f"knowledge_sources.{name}.type 是 {entry.get('type')!r}，{{{kind}://}} 引用只能指向 type={kind} 的知识源")
    return _PARSERS[kind](name, entry)


def load_es_source(name: str) -> EsSource:
    return _load(name, "es")


def load_mcp_source(name: str) -> McpSource:
    return _load(name, "mcp")


def validate_source_entry(name: str, entry) -> dict:
    """保存前校验一条登记：名字、类型、字段形状；凭据只校 ${VAR} 写法，不要求已设置。"""
    _check_name(name)
    if not isinstance(entry, dict) or entry.get("type") not in _PARSERS:
        raise ValueError(f"knowledge_sources.{name}.type 必须是 {sorted(_PARSERS)} 之一")
    _PARSERS[entry["type"]](name, entry, expand=False)
    return entry


def save_source(name: str, entry) -> dict:
    entry = validate_source_entry(name, entry)
    registry = load_registry()
    registry[name] = entry
    _write(registry)
    return registry


def _write(registry: dict) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def delete_source(name: str, referenced_by: list[str]) -> dict:
    """被场景引用的知识源不让删：删了这些场景下次加载就会报"未登记"。"""
    if referenced_by:
        raise ValueError(f"知识源 {name} 仍被这些预设引用，先改掉引用再删：{referenced_by}")
    registry = load_registry()
    if name not in registry:
        raise ValueError(f"知识源 {name} 未登记")
    del registry[name]
    _write(registry)
    return registry
