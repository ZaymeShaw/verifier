"""扩展轴资料分发；文件目录条目原样交给既有工具箱。"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from impl.core.capability_store import validate_es_refs
from impl.core.config import get_runtime_config
from impl.core.materials_store import expand_material_uris_with_catalog
from impl.projects.llm_probe.material_tools import build_material_tools
from .es_client import EsClient
from .es_tools import build_es_tools


def validate_source_refs(description):
    """语法层：{es://} 引用是否合法。所有框（含未启用）都查。"""
    return validate_es_refs(description)


def validate_source_capability(description):
    """能力层：引用了 ES 时本部署是否开了 ES 且配置合法。只查会跑的框。加载期不发 HTTP 请求。"""
    indices = validate_es_refs(description)
    if indices and not get_runtime_config().eval_axes.es.enabled:
        raise ValueError('ES 数据源未启用（.env: EVAL_AXES_ES_ENABLED=true）')
    if indices:
        EsClient()
    return indices


def expand_sources(description, *, material_catalog=False):
    indices = validate_source_capability(description)
    text, catalog = expand_material_uris_with_catalog(description, budget=0 if material_catalog and "{material://" in description else None)
    if not indices:
        return text, catalog
    client = EsClient()
    for index in indices:
        uri = 'es://' + index
        snapshot = client.index_uuid(index) + '@' + datetime.now(timezone.utc).isoformat()
        # 引用后面到句号为止的那段话当作该知识源的说明；紧跟着就是句号/逗号时说明为空，别把标点当说明。
        match = re.search(re.escape('{' + uri + '}') + r'[。，；：、,;:\s]*([^\n。{}]*)', description)
        catalog.append({'source': 'es', 'uri': uri, 'title': index,
                        'description': match.group(1).strip() if match else '',
                        'doc_count': client.count(index), 'snapshot_id': snapshot})
        text = text.replace('{' + uri + '}', f'（ES 知识源 {uri}，正文请用 es_* 工具查询）')
    return text, catalog


def build_tools(catalog, recorder):
    material = [item for item in catalog if item.get('source', 'material') == 'material']
    es = [item for item in catalog if item.get('source') == 'es']
    unknown = [item.get('source') for item in catalog if item.get('source', 'material') not in ('material', 'es')]
    if unknown:
        raise ValueError(f'不支持的资料来源: {unknown}')
    return build_material_tools(material, recorder) + build_es_tools(es, recorder)
