from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from . import connection, service, store


def same_origin(request: Request):
    origin = request.headers.get('origin')
    if origin and (urlsplit(origin).netloc != request.url.netloc or urlsplit(origin).scheme != request.url.scheme):
        raise HTTPException(403, '试验台仅接受同源页面或本机直接 API 调用')


router = APIRouter(prefix='/api/tool_loop_lab', dependencies=[Depends(same_origin)])


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    example_id: str
    input: str = Field(min_length=1, max_length=100000)
    mode: Literal['scripted', 'model'] = 'scripted'
    data_source: Literal['demo', 'aligned'] = 'demo'
    alignment_id: str | None = None


class ModelSettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str
    model: str
    api_key: SecretStr = SecretStr('')
    reasoning_effort: str = ''
    temperature: float = Field(default=0, ge=0, le=2)
    request_timeout_seconds: float = Field(default=300, ge=1, le=3600)
    expected_revision: str


class AlignRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_url: str
    project: str


class StopRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str


@router.get('/catalog')
def catalog():
    return service.catalog()


@router.get('/model')
def model_settings():
    try:
        return connection.connection_state()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/model')
def save_model_settings(payload: dict):
    # 自己序列化验证错误，避免默认错误回显整个请求（其中含 API Key）。
    try:
        selected = ModelSettingsRequest.model_validate(payload)
    except ValidationError as error:
        fields = ', '.join('.'.join(map(str, item['loc'])) for item in error.errors(include_input=False))
        raise HTTPException(422, '模型配置字段不合法：' + fields) from error
    try:
        return connection.save_connection(base_url=selected.base_url, model=selected.model,
            api_key=selected.api_key.get_secret_value(), reasoning_effort=selected.reasoning_effort,
            timeout=selected.request_timeout_seconds, temperature=selected.temperature,
            expected_revision=selected.expected_revision)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except OSError as error:
        raise HTTPException(500, '模型配置保存失败，请检查后端文件权限') from error


@router.get('/state')
def state(after: int = Query(default=0, ge=0), run_id: str | None = None):
    return store.STORE.state(after, run_id)


@router.get('/alignment')
def alignment():
    return service.alignment_state()


@router.get('/alignment/preview')
def alignment_preview(snapshot_id: str):
    try:
        return service.alignment_preview(snapshot_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/alignment/sync')
def sync_alignment(payload: AlignRequest):
    try:
        return service.sync_alignment(payload.source_url, payload.project)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except Exception as error:
        raise HTTPException(502, '对齐源服务失败：' + str(error)) from error


@router.post('/start')
def start(payload: StartRequest):
    try:
        return service.start(payload.example_id, payload.input, payload.mode, payload.data_source, payload.alignment_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/stop')
def stop(payload: StopRequest):
    try:
        store.STORE.stop(payload.run_id)
        return {'stop_requested': True}
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
