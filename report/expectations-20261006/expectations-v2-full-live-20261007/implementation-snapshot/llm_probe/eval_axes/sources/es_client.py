"""只读 ES REST 客户端；配置来自公共 resolver，零第三方 HTTP 依赖。"""
from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from impl.core.config import get_runtime_config
from impl.core.capability_store import validate_es_refs


class EsClient:
    def __init__(self):
        self.config = get_runtime_config().eval_axes.es
        if not self.config.enabled:
            raise ValueError("ES 数据源未启用")
        url = urlsplit(self.config.base_url)
        if url.scheme not in ('http', 'https') or not url.netloc or url.query or url.fragment or url.username:
            raise ValueError("eval_axes.es.base_url 必须是无凭据的 HTTP(S) 地址")
        if self.config.api_key and self.config.basic_auth:
            raise ValueError("ES ApiKey 与 Basic Auth 不能同时配置")
        if self.config.basic_auth and ':' not in self.config.basic_auth:
            raise ValueError("ES Basic Auth 必须是 user:pass")

    def _request(self, index, suffix, body=None):
        validate_es_refs('{es://' + index + '}')
        headers = {'Accept': 'application/json'}
        if self.config.api_key:
            headers['Authorization'] = 'ApiKey ' + self.config.api_key
        elif self.config.basic_auth:
            headers['Authorization'] = 'Basic ' + base64.b64encode(self.config.basic_auth.encode()).decode()
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        request = Request(self.config.base_url.rstrip('/') + '/' + quote(index, safe='') + '/' + suffix,
                          data=data, headers=headers, method='POST' if body is not None else 'GET')
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ValueError(f'ES {index}/{suffix}: HTTP {exc.code}') from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ValueError(f'ES {index}/{suffix}: 请求失败 ({type(exc).__name__})') from None
        if not isinstance(result, dict) or result.get('error') or result.get('timed_out') or result.get('_shards', {}).get('failed', 0):
            raise ValueError(f'ES {index}/{suffix}: 响应失败或不完整')
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
