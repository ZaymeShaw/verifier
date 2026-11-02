"""ToolLoop 的框架注册契约：核心完成条件必填，辅助 hooks 按事件显式注册。"""
import json

import pytest

from impl.core.tool_loop import (
    Abort, Allow, Continue, Done, Failed, Hook, LoopContext, Step, ToolLoop,
)
from impl.tools.protocol import VerifiableTool


class Client:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = 0

    def complete_step(self, *args, **kwargs):
        self.calls += 1
        return next(self.steps)


def text():
    return Step({'role': 'assistant', 'content': 'done'})


def invoke():
    return Step({'role': 'assistant', 'tool_calls': [{
        'id': 'one', 'type': 'function', 'function': {'name': 'echo', 'arguments': json.dumps({'value': 'x'})}}]})


def tool():
    return VerifiableTool('echo', 'echo a value', parameters={
        'type': 'object', 'properties': {'value': {'type': 'string', 'description': 'value to echo'}},
        'required': ['value']}, execute_fn=lambda value: value)


def loop(client=None, **kwargs):
    return ToolLoop('test', 'test', [tool()], client or Client([text()]), **kwargs)


def test_completion_hook_is_required():
    with pytest.raises(TypeError, match='completion_hook'):
        loop()
    with pytest.raises(TypeError, match='completion_hook'):
        loop(completion_hook=None)


def test_flat_hook_list_is_rejected_not_adapted():
    with pytest.raises(TypeError, match='hooks'):
        loop(completion_hook=Hook(), hooks=[Hook()])


@pytest.mark.parametrize('hooks,error', [
    ({'pretool': []}, ValueError),
    ({'pre_tool': Hook()}, TypeError),
    ({'pre_tool': [object()]}, TypeError),
    ({'post_tool': 'callback'}, TypeError),
    ({'post_tool': ''}, TypeError),
])
def test_bad_registration_fails_before_model_call(hooks, error):
    client = Client([text()])
    with pytest.raises(error):
        loop(client, completion_hook=Hook(), hooks=hooks)
    assert client.calls == 0


def test_completion_hook_cannot_be_registered_twice_for_stop():
    completion = Hook()
    with pytest.raises(ValueError, match='completion_hook'):
        loop(completion_hook=completion, hooks={'stop': [completion]})


def test_registered_event_only_runs_that_method():
    seen = []

    class Observer(Hook):
        def start(self, history, ctx):
            pytest.fail('start not registered')

        def pre_tool(self, history, call):
            seen.append('pre')
            return Allow()

        def post_tool(self, history, call):
            pytest.fail('post_tool not registered')

        def stop(self, history, blocked):
            pytest.fail('observer is not a completion/stop hook')

    instance = loop(Client([invoke(), text()]), completion_hook=Hook(), hooks={'pre_tool': [Observer()]})
    assert instance.run('input', LoopContext('t')).status == 'complete'
    assert seen == ['pre']


def test_completion_object_does_not_implicitly_register_other_events():
    class Completion(Hook):
        calls = 0

        def pre_tool(self, history, call):
            pytest.fail('completion hook only binds stop')

        def stop(self, history, blocked):
            self.calls += 1
            return Done()

    completion = Completion()
    result = loop(Client([invoke(), text()]), completion_hook=completion).run('x', LoopContext('t'))
    assert result.status == 'complete' and completion.calls == 1


def test_auxiliary_done_cannot_override_core_continue():
    class Completion(Hook):
        def stop(self, history, blocked):
            return Continue('not finished') if blocked == 0 else Done()

    client = Client([text(), text()])
    result = loop(client, completion_hook=Completion(), hooks={'stop': [Hook()]}).run('x', LoopContext('t'))
    assert result.status == 'complete' and result.segments == 2 and client.calls == 2
    assert any(m.get('content') == 'not finished' for m in result.messages)


def test_auxiliary_failure_overrides_core_done_and_never_runs_end():
    class Failure(Hook):
        def stop(self, history, blocked):
            return Failed('guard failed')

    instance = loop(completion_hook=Hook(), hooks={'stop': [Failure()]},
                    end=lambda _: pytest.fail('failed loop must not run end'))
    result = instance.run('x', LoopContext('t'))
    assert result.status == 'failed' and result.reason == 'guard failed'


def test_missing_completion_verdict_is_not_silently_done():
    class Broken(Hook):
        def stop(self, history, blocked):
            return None

    with pytest.raises(TypeError, match='stop'):
        loop(completion_hook=Broken()).run('x', LoopContext('t'))


def test_pre_tool_handlers_apply_in_order():
    class Append(Hook):
        def __init__(self, suffix):
            self.suffix = suffix

        def pre_tool(self, history, call):
            return Allow({'value': call.args['value'] + self.suffix})

    instance = loop(Client([invoke(), text()]), completion_hook=Hook(),
                    hooks={'pre_tool': [Append('1'), Append('2')]})
    result = instance.run('x', LoopContext('t'))
    assert result.calls[0].args == {'value': 'x12'}
    assert result.calls[0].result == 'x12'


def test_registration_lists_are_copied():
    class FailIfUsed(Hook):
        def pre_tool(self, history, call):
            return Abort('registration changed')

    handlers = []
    config = {'pre_tool': handlers}
    instance = loop(Client([invoke(), text()]), completion_hook=Hook(), hooks=config)
    handlers.append(FailIfUsed())
    config['stop'] = [FailIfUsed()]
    assert instance.run('x', LoopContext('t')).status == 'complete'


@pytest.mark.parametrize('event', ['start', 'pre_tool', 'post_tool', 'post_batch', 'stop'])
def test_event_handler_exception_is_not_treated_as_success(event):
    handler = Hook()

    def broken(*args):
        raise RuntimeError('hook failed')

    setattr(handler, event, broken)
    instance = loop(Client([invoke(), text()]), completion_hook=Hook(), hooks={event: [handler]},
                    end=lambda _: pytest.fail('must not extract result after hook failure'))
    with pytest.raises(RuntimeError, match='hook failed'):
        instance.run('x', LoopContext('t'))


def test_invalid_pre_tool_verdict_fails_loudly():
    handler = Hook()
    handler.pre_tool = lambda *args: None
    with pytest.raises(TypeError, match='pre_tool'):
        loop(Client([invoke()]), completion_hook=Hook(), hooks={'pre_tool': [handler]}).run('x', LoopContext('t'))


def test_core_failure_cannot_be_overridden_by_auxiliary_done():
    class Failure(Hook):
        def stop(self, history, blocked):
            return Failed('core failed')

    result = loop(completion_hook=Failure(), hooks={'stop': [Hook()]}).run('x', LoopContext('t'))
    assert result.status == 'failed' and result.reason == 'core failed'
