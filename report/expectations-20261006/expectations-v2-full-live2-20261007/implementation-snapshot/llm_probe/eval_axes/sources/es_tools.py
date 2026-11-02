"""受目录范围约束的 ES 工具和引用回读；mapping 决定字段，不预设知识库形状。"""
from __future__ import annotations

import json
import re
from typing import Any

from impl.projects.llm_probe.material_tools import quote_in_text
from impl.tools.protocol import VerifiableTool, build_agno_tools
from .es_client import EsClient


def _fields(properties, prefix='', nested=False):
    result = []
    for name, spec in properties.items():
        path = prefix + name
        kind = spec.get('type', 'object')
        is_nested = nested or kind == 'nested'
        result.append({'name': path, 'type': kind, 'text_or_keyword': kind in ('text', 'keyword'),
                       'full_text': kind == 'text' and spec.get('index', True) and not is_nested,
                       'nested': is_nested})
        result.extend(_fields(spec.get('properties', {}), path + '.', is_nested))
        # multi-fields 不在 _source 中单独存在；明确给出回读用的源字段。
        for child in _fields(spec.get('fields', {}), path + '.', is_nested):
            child['source_field'] = path
            result.append(child)
    return result


def _project(value, field):
    if not field:
        return value
    if isinstance(value, list):
        return [_project(item, field) for item in value]
    if not isinstance(value, dict):
        raise ValueError(f'ES 字段不存在: {field}')
    if field in value:
        return value[field]
    head, _, tail = field.partition('.')
    if head not in value:
        raise ValueError(f'ES 字段不存在: {field}')
    return _project(value[head], tail)


def _has(source, field):
    try:
        _project(source, field)
        return True
    except ValueError:
        return False


def _text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class EsTools:
    def __init__(self, catalog, recorder, client=None):
        self.allowed = {item['uri'][len('es://'):] for item in catalog if item.get('source') == 'es'}
        self.recorder = recorder
        self.client = client or EsClient()

    def _guard(self, index):
        if index not in self.allowed:
            raise ValueError(f'index 必须是目录里的索引之一: {sorted(self.allowed)}')

    def _run(self, tool, index, args, action):
        receipt: dict[str, Any] = {'tool': tool, 'index': index, **args, 'returned_locators': []}
        try:
            self._guard(index)
            result = action()
            receipt['returned_locators'] = ([result['locator']] if 'locator' in result else
                                            [hit['locator'] for hit in result.get('hits', [])])
            return result
        except ValueError as exc:
            receipt['error'] = str(exc)
            return {'error': str(exc)}
        finally:
            self.recorder.append(receipt)

    def _outline(self, index):
        mapping = self.client.mapping(index)
        if index not in mapping:
            raise ValueError('ES 引用须为具体索引名')
        return {'index': index, 'fields': _fields(mapping[index]['mappings'].get('properties', {})),
                'doc_count': self.client.count(index)}

    def es_outline(self, index: str):
        return self._run('es_outline', index, {}, lambda: self._outline(index))

    def es_search(self, index: str, query: str, fields: list[str] | None = None):
        """与 material_tools.search 同一语义：空白拆词，每词子串匹配，词间 OR，命中词多者排前。

        不能把整串交给 ES 默认 multi_match——它按索引分析器切词再 OR；中文在默认 standard 下切成单字，
        任一字命中即命中，13 篇的库搜什么都返回全库，模型拿不到"零命中 = 库里没有"的信号。
        这里每个词对 text 字段做 phrase（单字切分下即子串；装了中文分词也正确），对 keyword 字段做
        大小写不敏感的 *词* 通配，两边一起 OR。"""
        def action():
            terms = [t for t in str(query or '').split() if t]
            if not terms:
                raise ValueError('query 不能为空（空白分隔的关键词）')
            available = {f['name']: f for f in self._outline(index)['fields']}
            text_fields = fields if fields is not None else [name for name, f in available.items() if f['full_text']]
            if not text_fields or any(f not in available or not available[f]['text_or_keyword'] or available[f]['nested'] for f in text_fields):
                raise ValueError('fields 必须是 mapping 中可检索的 text/keyword 字段；nested 字段需要 nested 查询，暂不支持')
            keyword_fields = [] if fields is not None else [
                name for name, f in available.items() if f['type'] == 'keyword' and not f['nested'] and not f.get('source_field')]
            should = []
            for term in terms:
                should.append({'multi_match': {'query': term, 'fields': text_fields, 'type': 'phrase'}})
                escaped = re.sub(r'([*?\\])', r'\\\1', term)
                should.extend({'wildcard': {k: {'value': f'*{escaped}*', 'case_insensitive': True}}} for k in keyword_fields)
            response = self.client.search(index, {
                'size': self.client.config.max_hits,
                'query': {'bool': {'should': should, 'minimum_should_match': 1}},
                'highlight': {'pre_tags': [''], 'post_tags': [''], 'fields': {f: {} for f in text_fields}},
            })
            limit = self.client.config.max_field_chars
            hits = []
            for hit in response.get('hits', {}).get('hits', [])[:self.client.config.max_hits]:
                source = hit.get('_source') or {}
                haystack = ' '.join(_text(_project(source, f)) for f in [*text_fields, *keyword_fields] if _has(source, f))
                matched = [t for t in terms if t.lower() in haystack.lower()]
                highlight = {name: snippets for name, snippets in hit.get('highlight', {}).items() if name in text_fields}
                # 只在 keyword 字段（如产品名）命中的文档没有 highlight，用第一个文本字段原文顶上，别把它丢了。
                shown = highlight or {f: [_text(_project(source, f))] for f in text_fields[:1] if _has(source, f)}
                for name, snippets in shown.items():
                    text = '\n'.join(snippets)
                    hits.append({'locator': hit['_id'] + '#' + available[name].get('source_field', name),
                                 'score': hit.get('_score'), 'matched': matched,
                                 'text': text[:limit], 'truncated': len(text) > limit})
            result = {'index': index, 'hits': hits}
            if not hits:
                result['note'] = '零命中：查询词（子串匹配）未出现在任何可检索字段中；换更短的词再试，仍为零即知识库里没有'
            return result
        return self._run('es_search', index, {'query': query, 'fields': fields}, action)

    def es_read(self, index: str, locator: str):
        def action():
            doc_id, separator, field = locator.partition('#')
            if not doc_id or (separator and not field):
                raise ValueError('locator 必须为 <_id> 或 <_id>#<field>')
            source = self.client.get_doc(index, doc_id)
            text = _text(_project(source, field))
            limit = self.client.config.max_field_chars
            return {'index': index, 'locator': locator, 'text': text[:limit], 'truncated': len(text) > limit}
        return self._run('es_read', index, {'locator': locator}, action)

    def verify_quote(self, index, locator, quote):
        if '#' not in locator:
            return False
        result = self.es_read(index, locator)
        return 'error' not in result and quote_in_text(quote, result['text'])

    def tools(self):
        specs = [
            ('es_outline', self.es_outline, '查看目录中 ES 索引的 mapping 字段与文档数。', {}),
            ('es_search', self.es_search,
             '关键词检索：空白分隔多个词，每个词按子串匹配（text 字段找连续原文，keyword 字段如产品名做包含匹配），'
             '任一词命中即返回、命中词多者排前，每条带 matched（命中了哪些词）与可回读 locator。零命中就是知识库里没有这个词。',
             {'query': {'type': 'string', 'description': '空白分隔的关键词，如「产品名 条款事项」'},
              'fields': {'type': 'array', 'items': {'type': 'string'}, 'description': '可选：只在这些 text 字段里找（缺省全部文本字段 + keyword 字段）'}}),
            ('es_read', self.es_read, '回读 ES 原文；字段 locator 为文档ID#字段路径，只有 ID 时返回整篇摘要。',
             {'locator': {'type': 'string', 'description': '工具返回的文档ID#字段路径'}}),
        ]
        return build_agno_tools([VerifiableTool(tool_id=name, description=description, execute_fn=fn,
            parameters={'type': 'object', 'properties': {'index': {'type': 'string', 'description': '目录里的具体索引名'}, **params},
                        'required': ['index'] + [key for key in params if key != 'fields']})
            for name, fn, description, params in specs])


def build_es_tools(catalog, recorder):
    return EsTools(catalog, recorder).tools() if catalog else []
