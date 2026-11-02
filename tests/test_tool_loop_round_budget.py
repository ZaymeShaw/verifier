import json

import pytest

from impl.core.tool_loop import (
    BudgetStop, Continue, History, Hook, LoopContext, RequireDone, Step, ToolLoop, is_accepted,
)
from impl.tools.protocol import VerifiableTool


class Client:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.requests = []

    def complete_step(self, messages, functions, **kwargs):
        self.requests.append(json.loads(json.dumps(messages)))
        item = next(self.steps)
        if isinstance(item, str):
            return Step({'role': 'assistant', 'content': item})
        return Step({'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': f'{len(self.requests)}-{i}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}}
            for i, (name, args) in enumerate(item)]})


class Completed(RequireDone):
    def __init__(self):
        super().__init__(['submit'])

    def ready_to_finish(self, history):
        return any(c.ok and is_accepted(c) for c in history.of('submit'))


def tools(log):
    def read(value):
        log.append(value)
        return {'text': value}

    return [
        VerifiableTool('read', 'read', parameters={'type': 'object', 'properties': {'value': {'type': 'string', 'description': 'value'}}},
                       execute_fn=read),
        VerifiableTool('submit', 'submit', parameters={'type': 'object', 'properties': {}},
                       execute_fn=lambda: {'accepted': True}),
    ]


def test_last_allowed_round_executes_entire_batch_before_completion_checks():
    log, ends = [], []
    batch = [('read', {'value': str(i)}) for i in range(16)] + [('submit', {})]
    client = Client([batch])
    loop = ToolLoop('test', 'system', tools(log), client, completion_hook=Completed(),
                    budget=BudgetStop(llm_calls=1), end=lambda h: ends.append(h.llm_calls))
    result = loop.run('go', LoopContext('test'))
    assert result.status == 'complete' and result.llm_calls == 1
    assert len(result.calls) == 17 and log == list(map(str, range(16)))
    assert ends == [1] and len(client.requests) == 1
    assert all(not c.denied for c in result.calls)
    # 整批每个调用都有配对回执，最后一个提交也执行并通过验收。
    assert len([m for m in result.messages if m['role'] == 'tool']) == 17


@pytest.mark.parametrize('step', ['premature finish', [('missing_tool', {})], [('read', {})]])
def test_round_limit_counts_empty_stops_invalid_tools_and_execution_errors(step):
    client, ends = Client([step] * 3), []
    loop = ToolLoop('test', 'system', tools([]), client, completion_hook=Completed(),
                    budget=BudgetStop(llm_calls=3), end=lambda h: ends.append(1))
    result = loop.run('go', LoopContext('test'))
    assert result.status == 'failed' and result.reason == 'budget: llm_calls 已达上限 3'
    assert result.llm_calls == len(client.requests) == 3 and ends == []


def test_ready_completion_still_runs_auxiliary_stop_checks():
    class Pending(Hook):
        def stop(self, history, blocked):
            return Continue('仍有独立验收未通过')

    client, ends = Client([[('submit', {})]]), []
    loop = ToolLoop('test', 'system', tools([]), client, completion_hook=Completed(),
                    hooks={'stop': [Pending()]}, budget=BudgetStop(llm_calls=1),
                    end=lambda h: ends.append(1))
    result = loop.run('go', LoopContext('test'))
    assert result.status == 'failed' and ends == []
    assert 'llm_calls' in result.reason and result.calls[0].result == {'accepted': True}
    assert result.messages[-1]['content'] == '仍有独立验收未通过'


def test_round_budget_is_per_run_even_when_loop_and_budget_are_reused():
    client = Client([[('submit', {})], [('submit', {})]])
    loop = ToolLoop('test', 'system', tools([]), client, completion_hook=Completed(),
                    budget=BudgetStop(llm_calls=1))
    for _ in range(2):
        result = loop.run('go', LoopContext('test'))
        assert result.status == 'complete' and result.llm_calls == 1
    assert all('已使用 0/1' in request[-1]['content'] for request in client.requests)


def test_wall_clock_is_checked_before_request_even_without_tool_calls():
    client = Client([])
    loop = ToolLoop('test', 'system', tools([]), client, completion_hook=Completed(),
                    budget=BudgetStop(llm_calls=8, seconds=-1))
    result = loop.run('go', LoopContext('test'))
    assert result.status == 'failed' and '墙钟上限' in result.reason
    assert result.llm_calls == 0 and client.requests == []


def test_parent_and_child_round_counters_are_independent():
    child_client = Client([[('read', {'value': 'body'}), ('submit', {})]])
    child = ToolLoop('child', 'child', tools([]), child_client, completion_hook=Completed(),
                     budget=BudgetStop(llm_calls=1), end=lambda h: {'accepted': True, 'rounds': h.llm_calls})
    parent_client = Client([[('child', {})], 'done'])
    parent = ToolLoop('parent', 'parent', [child.as_tool('child', {'type': 'object', 'properties': {}})],
                      parent_client, completion_hook=RequireDone(['child']), budget=BudgetStop(llm_calls=2))
    result = parent.run('go', LoopContext('parent'))
    assert result.status == 'complete' and result.llm_calls == 2
    assert len(parent_client.requests) == 2 and len(child_client.requests) == 1
    assert result.calls[0].result == {'accepted': True, 'rounds': 1}
