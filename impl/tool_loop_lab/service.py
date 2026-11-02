"""固定可信 Python 示例 → 原生 ToolLoop → 最新运行与实时事件。"""
from __future__ import annotations

import hashlib
import inspect
import json
import runpy
import threading
import uuid
from pathlib import Path

from impl.core.tool_loop import LoopContext
from . import alignment, store
from .connection import load_connection
from .observation import BoundaryGuard, Interrupted, observe

EXAMPLES_PATH = Path(__file__).with_name('examples.py')


def load_examples():
    # 只加载服务自身的固定文件；HTTP 请求不能指定文件名、模块路径或 Python 源码。
    return runpy.run_path(str(EXAMPLES_PATH))


def describe(loop):
    def hook(value):
        return {'type': type(value).__name__, 'description': inspect.getdoc(type(value)) or ''}
    return {'id': loop.id, 'system_prompt': loop.system_prompt,
            'tools': [{'id': tool.tool_id, 'description': tool.description, 'parameters': tool.parameters} for tool in loop.tools],
            'completion_hook': hook(loop.completion_hook),
            'hooks': {event: [hook(value) for value in values] for event, values in loop.hooks.items() if values},
            'budget': {'tool_calls': loop.budget.tool_calls, 'seconds': loop.budget.seconds, 'max_blocked': loop.max_blocked},
            'end': getattr(loop.end, '__name__', type(loop.end).__name__)}


def catalog():
    module = load_examples()
    examples = []
    snapshot = store.STORE.alignment()
    for name, example in module['EXAMPLES'].items():
        loop = example['build'](None)
        aligned_definition = describe(example['build'](None, dataset=snapshot)) if name == 'clustering' and snapshot and snapshot['counts']['reasons'] else None
        examples.append({'id': name, 'title': example['title'], 'description': example['description'],
                         'aligned_definition': aligned_definition, 'alignment_id': snapshot['id'] if aligned_definition else None,
                         'input': example['input'], 'definition': describe(loop),
                         'source': inspect.getsource(example['build']),
                         'path': str(Path(inspect.getsourcefile(example['build'])).relative_to(Path(__file__).resolve().parents[2]))})
    try:
        model = load_connection().public()
    except ValueError as error:
        model = {'ready': False, 'errors': [str(error)], 'source': '.env.tool_loop'}
    return {'examples': examples, 'model': model}


def alignment_state():
    return {'snapshot': alignment.public(store.STORE.alignment())}


def sync_alignment(source_url, project):
    current = store.STORE.state()['run']
    if current and current['status'] == 'running': raise ValueError('试验正在运行，请结束后再对齐')
    snapshot = alignment.collect(source_url, project)
    store.STORE.save_alignment(snapshot)
    return {'snapshot': alignment.public(snapshot)}


def alignment_preview(snapshot_id):
    snapshot = store.STORE.alignment()
    if snapshot is None or snapshot['id'] != snapshot_id: raise ValueError('对齐快照已被替换，请从试验台重新打开')
    return {key: snapshot[key] for key in ('id', 'source_url', 'project', 'synced_at', 'cases', 'types', 'criteria', 'baseline', 'counts')}


def start(example_id, input_text, mode, data_source='demo', alignment_id=None):
    module = load_examples()
    if example_id not in module['EXAMPLES']: raise ValueError('未知示例')
    example = module['EXAMPLES'][example_id]
    dataset = None
    if data_source == 'aligned':
        if example_id != 'clustering': raise ValueError('对齐材料只用于聚类示例')
        if mode != 'model': raise ValueError('真实案例必须使用真实模型；预置脚本只支持合成演示材料')
        dataset = store.STORE.alignment()
        if not dataset or dataset['id'] != alignment_id: raise ValueError('对齐快照已变化或不存在，请重新读取')
    connection = load_connection() if mode == 'model' else None
    client = connection.client() if connection else example['script_client']()
    loop = example['build'](client, dataset=dataset) if dataset is not None else example['build'](client)
    metadata = {'example_id': example_id, 'title': example['title'], 'mode': mode, 'input': input_text,
                'definition': describe(loop), 'source': inspect.getsource(example['build']),
                'source_sha256': hashlib.sha256(EXAMPLES_PATH.read_bytes() + Path(inspect.getsourcefile(example['build'])).read_bytes()).hexdigest(),
                'model': connection.public() if connection else {'model': 'scripted-demo', 'protocol': 'scripted'},
                'data_source': data_source, 'alignment': alignment.public(dataset) if dataset is not None else None,
                'runtime_guard': '最长 1200 秒，在模型请求前后与工具边界检查；停止不会强杀正在执行的请求或工具'}
    run_id = uuid.uuid4().hex
    active_store = store.STORE  # 运行固定使用启动时的实例，刷新页面不重新构造运行。

    def redact(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if connection and connection.api_key:
            # 对 JSON 编码后的 key 替换，避免引号等字符导致泄漏或破坏 JSON。
            encoded = json.dumps(connection.api_key, ensure_ascii=False)[1:-1]
            text = text.replace(encoded, '[REDACTED]')
        return json.loads(text)

    def emit(kind, data): active_store.event(run_id, kind, redact(data))
    guard = BoundaryGuard(lambda: active_store.cancelled(run_id))
    observed = observe(loop, emit, guard)
    active_store.start(run_id, metadata, alignment_id=alignment_id if dataset is not None else None)
    def execute():
        try:
            emit('run_start', {'mode': mode, 'example_id': example_id})
            result = observed.run(input_text, LoopContext(trace_id=f'tool-loop-lab:{run_id}'))
            final_message = next((m.get('content') for m in reversed(result.messages) if m.get('role') == 'assistant' and m.get('content')), '')
            output = {'value': result.value, 'final_message': final_message, 'segments': result.segments,
                      'tool_calls': len(result.calls), 'model_requests': observed.client.steps}
            status = 'cancelled' if active_store.cancelled(run_id) else result.status
            emit('run_end', {'status': status, 'reason': result.reason, **output})
            active_store.finish(run_id, status, redact(output), redact(result.reason))
        except Exception as error:
            status = 'cancelled' if isinstance(error, Interrupted) or active_store.cancelled(run_id) else 'failed'
            safe_error = redact(str(error))
            emit('run_error', {'error': safe_error})
            active_store.finish(run_id, status, error=safe_error)
    try:
        threading.Thread(target=execute, name=f'tool-loop-lab-{run_id[:8]}', daemon=True).start()
    except Exception as error:
        active_store.finish(run_id, 'failed', error=redact(str(error)))
        raise
    return {'run_id': run_id}
