"""扩展轴资料分发；文件目录条目原样交给既有工具箱。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from impl.core.capability_store import validate_es_refs, validate_mcp_refs
from impl.core.materials_store import expand_material_uris_with_catalog, get_material
from impl.projects.llm_probe.material_tools import build_material_tools
from .es_client import EsClient
from .es_tools import build_es_tools
from .mcp_tools import build_mcp_tools, tool_prefix
from .registry import load_mcp_source, load_registry
from . import registry


# 业务方登记的责任范围资料（demand/information_sources.md §1.2）：{boundary://项目/资料id}，正文就是资料管理页里那份资料。
_BOUNDARY_REF = re.compile(r"\{boundary://([A-Za-z][A-Za-z0-9_-]*)/([a-z][a-z0-9_-]*)\}")


def expand_boundary(description):
    """拆出责任范围登记：返回（去掉引用后的描述，[{uri, title, content}]）。引用的资料不存在直接抛。"""
    registrations, seen = [], set()
    for project, material_id in _BOUNDARY_REF.findall(description or ""):
        uri = f"boundary://{project}/{material_id}"
        if uri in seen:
            continue
        seen.add(uri)
        material = get_material(project, material_id)
        registrations.append({"uri": uri, "title": str(material.get("title") or material_id), "content": material["content"]})
    text = _BOUNDARY_REF.sub(lambda m: f"（责任范围登记 boundary://{m.group(1)}/{m.group(2)}）", description or "")
    return text, registrations


def validate_source_refs(description):
    """语法层：{es://} / {mcp://} / {boundary://} 引用是否合法。所有框（含未启用）都查。"""
    validate_mcp_refs(description)
    expand_boundary(description)
    return validate_es_refs(description)


def validate_source_capability(description):
    """能力层：引用的知识源是否已登记、配置是否合法。只查会跑的框。加载期不发 HTTP 请求。"""
    refs = validate_es_refs(description)
    for ref in refs:
        EsClient(ref.split('/', 1)[0])
    for name in validate_mcp_refs(description):
        load_mcp_source(name)
    return refs


def expand_sources(description, *, material_catalog=False):
    refs = validate_source_capability(description)
    text, catalog = expand_material_uris_with_catalog(description, budget=0 if material_catalog and "{material://" in description else None)
    clients = {}
    for ref in refs:
        source, index = ref.split('/', 1)
        if source not in clients:
            clients[source] = EsClient(source)
        client = clients[source]
        uri = 'es://' + ref
        snapshot = client.index_uuid(index) + '@' + datetime.now(timezone.utc).isoformat()
        # 引用后面到句号为止的那段话当作该知识源的说明；紧跟着就是句号/逗号时说明为空，别把标点当说明。
        match = re.search(re.escape('{' + uri + '}') + r'[。，；：、,;:\s]*([^\n。{}]*)', description)
        catalog.append({'source': 'es', 'uri': uri, 'title': ref,
                        'description': match.group(1).strip() if match else '',
                        'doc_count': client.count(index), 'snapshot_id': snapshot})
        text = text.replace('{' + uri + '}', f'（ES 知识源 {ref}，正文请用 es_* 工具查询，index 参数填 {ref}）')
    for name in validate_mcp_refs(description):
        uri = 'mcp://' + name
        match = re.search(re.escape('{' + uri + '}') + r'[。，；：、,;:\s]*([^\n。{}]*)', description)
        # MCP 是业务系统的活查询接口：没有内容封口，快照只记查询时刻。
        catalog.append({'source': 'mcp', 'uri': uri, 'title': name,
                        'description': match.group(1).strip() if match else '',
                        # 登记时写的读法说明（数据怎么读）：查证和判定都要看。
                        'notes': str(load_registry().get(name, {}).get('description') or ''),
                        'snapshot_id': datetime.now(timezone.utc).isoformat()})
        text = text.replace('{' + uri + '}', f'（MCP 知识源 {name}，用 {tool_prefix(name)}* 工具查询，返回带 call_id）')
    return text, catalog


def build_tools(catalog, recorder, request=None):
    material = [item for item in catalog if item.get('source', 'material') == 'material']
    es = [item for item in catalog if item.get('source') == 'es']
    unknown = [item.get('source') for item in catalog if item.get('source', 'material') not in ('material', 'es', 'mcp')]
    if unknown:
        raise ValueError(f'不支持的资料来源: {unknown}')
    return build_material_tools(material, recorder) + build_es_tools(es, recorder) + build_mcp_tools(catalog, recorder, request)


def _referencing_presets(name):
    from impl.core.capability_store import load_capability_map
    tokens = ('{es://' + name + '/', '{mcp://' + name + '}')
    return sorted(ref for ref, entry in load_capability_map('llm_probe').items()
                  if any(t in json.dumps(entry, ensure_ascii=False) for t in tokens))


def list_sources():
    """types：本项目登记能用的类型（页面类型下拉按它列）。"""
    return {'sources': load_registry(), 'types': list(registry._PARSERS)}


def save_source(name, entry):
    return {'sources': registry.save_source(name, entry)}


def delete_source(name):
    return {'sources': registry.delete_source(name, _referencing_presets(name))}


def check_source(name):
    """登记页「测试连接」：ES 列可引用的索引，MCP 列工具；连不上如实报错。返回可直接插入的引用写法。"""
    entry = load_registry().get(name)
    if not isinstance(entry, dict):
        raise ValueError(f'知识源 {name} 未登记')
    if entry.get('type') == 'es':
        indices = EsClient(name).indices()
        return {'name': name, 'type': 'es', 'items': indices, 'refs': ['{es://' + name + '/' + i + '}' for i in indices]}
    from .mcp_tools import list_tools
    tools = list_tools(load_mcp_source(name))
    return {'name': name, 'type': 'mcp', 'items': [t['name'] for t in tools], 'refs': ['{mcp://' + name + '}']}
