"""试验台观察现有接口，不另写执行循环，也不改变原 hook 的返回决定。"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, is_dataclass, replace

from impl.core.tool_loop import Abort, Failed, Hook, ToolLoop


class Interrupted(RuntimeError):
    pass


class BoundaryGuard(Hook):
    """协作式停止：在下一次模型请求或工具边界停下，不声称强杀阻塞中的工具。"""
    def __init__(self, cancelled, seconds=1200):
        self.cancelled = cancelled
        self.deadline = time.monotonic() + seconds

    def check(self):
        if self.cancelled(): raise Interrupted('用户要求停止，已停止后续步骤')
        if time.monotonic() >= self.deadline: raise TimeoutError('试验运行超过 1200 秒，已停止后续步骤')

    def pre_tool(self, history, call):
        try:
            self.check()
        except (Interrupted, TimeoutError) as error:
            return Abort(str(error))
        return super().pre_tool(history, call)

    def stop(self, history, blocked):
        try:
            self.check()
        except (Interrupted, TimeoutError) as error:
            return Failed(str(error))
        return super().stop(history, blocked)


def observe(loop, emit, guard):
    """传入新建的 loop，只包装工具、客户端和 hooks；同一 hook 对象的共享状态保持不变。"""
    inner_client = loop.client
    class ObservedClient:
        steps = 0
        def complete_step(self, messages, functions, *, trace_id, stage):
            guard.check()
            self.steps += 1
            emit('model_request', {'step': self.steps, 'stage': stage, 'messages': copy.deepcopy(messages)})
            started = time.monotonic()
            try:
                result = inner_client.complete_step(messages, functions, trace_id=trace_id, stage=stage)
            except Exception as error:
                emit('model_error', {'step': self.steps, 'error': str(error)})
                raise
            emit('model_response', {'step': self.steps, 'message': copy.deepcopy(result.message),
                                    'elapsed_seconds': time.monotonic() - started})
            guard.check()
            return result
    client = ObservedClient()

    wrapped = {}
    class ObservedHook(Hook):
        def __init__(self, hook): self.inner = hook
        def invoke(self, event, *args):
            data = {'hook': type(self.inner).__name__, 'event': event,
                    'core_completion': event == 'stop' and self.inner is loop.completion_hook}
            if event in ('pre_tool', 'post_tool'):
                data.update(tool=args[1].tool, call_id=args[1].id)
            try:
                result = getattr(self.inner, event)(*args)
            except Exception as error:
                emit('hook_error', {**data, 'error': str(error)})
                raise
            emit('hook', {**data, 'decision': type(result).__name__,
                          'result': asdict(result) if is_dataclass(result) else result})
            return result
        def start(self, history, ctx): return self.invoke('start', history, ctx)
        def pre_tool(self, history, call): return self.invoke('pre_tool', history, call)
        def post_tool(self, history, call): return self.invoke('post_tool', history, call)
        def post_batch(self, history, calls): return self.invoke('post_batch', history, calls)
        def ready_to_finish(self, history): return self.invoke('ready_to_finish', history)
        def stop(self, history, blocked): return self.invoke('stop', history, blocked)
        # budget 也由同一观察器包装；请求前预算与反馈必须原样透传。
        def before_step(self, history): return self.invoke('before_step', history)
        def step_note(self, history): return self.inner.step_note(history)
    def hook(value):
        if id(value) not in wrapped: wrapped[id(value)] = ObservedHook(value)
        return wrapped[id(value)]
    hooks = {event: tuple(hook(value) for value in handlers) for event, handlers in loop.hooks.items()}
    hooks['pre_tool'] = (hook(guard), *hooks['pre_tool'])
    hooks['stop'] = (*hooks['stop'], hook(guard))

    def execution(tool):
        def execute(**args):
            guard.check()
            emit('tool_start', {'tool': tool.tool_id, 'args': copy.deepcopy(args)})
            try:
                result = tool.execute_fn(**args)
            except Exception as error:
                emit('tool_error', {'tool': tool.tool_id, 'error': str(error)})
                raise
            emit('tool_result', {'tool': tool.tool_id, 'result': copy.deepcopy(result)})
            return result
        return execute
    tools = [replace(tool, execute_fn=execution(tool)) for tool in loop.tools]
    return ToolLoop(loop.id, loop.system_prompt, tools, client,
                    completion_hook=hook(loop.completion_hook), hooks=hooks,
                    budget=hook(loop.budget), end=loop.end, max_blocked=loop.max_blocked)
