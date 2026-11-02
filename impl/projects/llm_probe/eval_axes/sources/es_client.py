"""只读 ES REST 客户端；连接取自知识源登记（registry），零第三方 HTTP 依赖。"""
from __future__ import annotations

import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .registry import load_es_source

INDEX_NAME = r"[a-z0-9][a-z0-9_.-]*"


class EsClient:
    def __init__(self, source_name):
        self.config = load_es_source(source_name)

    def _send(self, path, label, body=None):
        headers = {'Accept': 'application/json'}
        if self.config.api_key:
            headers['Authorization'] = 'ApiKey ' + self.config.api_key
        elif self.config.basic_auth:
            headers['Authorization'] = 'Basic ' + base64.b64encode(self.config.basic_auth.encode()).decode()
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        request = Request(self.config.base_url.rstrip('/') + path, data=data, headers=headers,
                          method='POST' if body is not None else 'GET')
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(f'ES {label}: HTTP {exc.code}') from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ValueError(f'ES {label}: 请求失败 ({type(exc).__name__})') from None

    def indices(self):
        """登记页「测试连接」用：列出可引用的索引（跳过 . 开头的系统索引）。"""
        rows = self._send('/_cat/indices?format=json&h=index', f'{self.config.name}/_cat/indices')
        if not isinstance(rows, list):
            raise ValueError(f'ES {self.config.name}/_cat/indices: 响应不是列表')
        return sorted(r['index'] for r in rows if isinstance(r, dict) and not str(r.get('index', '.')).startswith('.'))

    def _request(self, index, suffix, body=None):
        if not re.fullmatch(INDEX_NAME, index):
            raise ValueError('ES 索引名须为小写字母、数字、_、.、-')
        result = self._send('/' + quote(index, safe='') + '/' + suffix, f'{self.config.name}/{index}/{suffix}', body)
        if not isinstance(result, dict) or result.get('error') or result.get('timed_out') or result.get('_shards', {}).get('failed', 0):
            raise ValueError(f'ES {self.config.name}/{index}/{suffix}: 响应失败或不完整')
        return result

    def mapping(self, index):
        return self._request(index, '_mapping')

    def count(self, index):
        return self._request(index, '_count')['count']

    def index_uuid(self, index):
        result = self._request(index, '_settings/index.uuid')
        try:
            return result[index]['settings']['index']['uuid']
        except KeyError:
            raise ValueError('ES 索引须为具体索引名，且 settings 必须返回 UUID') from None

    def search(self, index, body):
        return self._request(index, '_search', body)

    def get_doc(self, index, doc_id):
        result = self._request(index, '_doc/' + quote(doc_id, safe=''))
        if result.get('found') is False or not isinstance(result.get('_source'), dict):
            raise ValueError('ES 文档不存在或缺少 _source')
        return result['_source']
