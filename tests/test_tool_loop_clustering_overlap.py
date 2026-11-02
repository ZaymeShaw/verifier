"""成员集合约束，不把重叠率当作语义质量评测。全部使用本地脚本。"""
import copy
import json

import pytest

from impl.core.tool_loop import Call, History, LoopContext, Step
from impl.tool_loop_lab.clustering_example import (
    CASES, TYPES, ClusteringScriptClient, OverlapGuard, build_clustering,
    material_of, validate_submission,
)
from impl.tool_loop_lab.observation import BoundaryGuard, observe


def cluster(name, refs):
    return {'name': name, 'description': name, 'priority_reason': '测试顺序',
            'members': [{'ref': ref, 'evidence': '测试原文'} for ref in refs]}


def payload_for(*clusters):
    return {'axes': [{'axis_id': 'any_axis', 'priority_reason': '测试顺序', 'labels': [
        {'value': 'any_label', 'priority_reason': '测试顺序', 'clusters': list(clusters)}]}]}


def call_for(payload, **kwargs):
    return Call(0, 'submit_clustering', payload, 0, result={'accepted': True}, **kwargs)


@pytest.mark.parametrize('left,right,threshold,rejected', [
    (['R1', 'R2'], ['R3', 'R4'], .5, False),
    (['R1', 'R2'], ['R2', 'R3'], .5, False),  # 等于阈值放行，允许多归属。
    (['R1', 'R2', 'R3'], ['R1', 'R2', 'R4'], .5, True),
    (['R1'], ['R1', 'R2', 'R3'], .5, True),  # 分母是小类大小，不是并集。
    (['R1', 'R2'], ['R1', 'R2'], .5, True),
    (['R1', 'R2', 'R3'], ['R1', 'R2', 'R4'], .8, False),
    (['R1'], ['R1'], 1, False),
    (['R1'], ['R2'], 0, False),
])
def test_overlap_coefficient_and_strict_threshold(left, right, threshold, rejected):
    payload = payload_for(cluster('A', left), cluster('B', right))
    original = copy.deepcopy(payload)
    call = call_for(payload)
    result = OverlapGuard(threshold=threshold).post_tool(History(), call)
    assert result['accepted'] is not rejected
    assert payload == original and call.result == {'accepted': True}
    if rejected:
        detail, = result['overlaps']
        assert detail['cluster_names'] == ['A', 'B']
        assert detail['cluster_indexes'] == [0, 1]
        assert detail['shared_refs'] == sorted(set(left) & set(right))
        assert detail['rate'] == len(set(left) & set(right)) / min(len(left), len(right))
        assert 'any_axis/any_label' in result['error'] and '不证明语义重复' in result['error']
    else:
        assert result is call.result


@pytest.mark.parametrize('threshold', [-.1, 1.1, float('nan'), float('inf'), -float('inf')])
def test_invalid_threshold_fails_on_construction(threshold):
    with pytest.raises(ValueError, match='阈值'):
        OverlapGuard(threshold=threshold)


@pytest.mark.parametrize('boundary', ['axis', 'label'])
def test_never_compares_different_axes_or_labels(boundary):
    payload = payload_for(cluster('A', ['R1']))
    axis = payload['axes'][0]
    if boundary == 'axis':
        other = copy.deepcopy(axis)
        other['axis_id'] = 'another_axis'
        payload['axes'].append(other)
    else:
        other = copy.deepcopy(axis['labels'][0])
        other['value'] = 'another_label'
        axis['labels'].append(other)
    call = call_for(payload)
    assert OverlapGuard(threshold=.5).post_tool(History(), call) is call.result


def test_all_offending_pairs_are_reported_in_one_response():
    call = call_for(payload_for(*(cluster(name, ['R1', 'R2']) for name in ['A', 'B', 'C'])))
    result = OverlapGuard(threshold=.5).post_tool(History(), call)
    assert [d['cluster_indexes'] for d in result['overlaps']] == [[0, 1], [0, 2], [1, 2]]


@pytest.mark.parametrize('kind', ['other_tool', 'rejected', 'error', 'denied', 'truthy_not_true'])
def test_only_successful_accepted_submissions_are_checked(kind):
    call = call_for({'axes': 'invalid; must not be examined here'})
    if kind == 'other_tool': call.tool = 'read_reasons'
    if kind == 'rejected': call.result = {'accepted': False, 'error': 'original validation error'}
    if kind == 'error': call.error = 'execution failed'
    if kind == 'denied': call.denied = 'unread reasons'
    if kind == 'truthy_not_true': call.result = {'accepted': 'true'}
    assert OverlapGuard(threshold=.5).post_tool(History(), call) is call.result


@pytest.fixture
def submission():
    messages = list(ClusteringScriptClient().steps)
    return [json.loads(c['function']['arguments']) for m in messages for c in m.get('tool_calls', [])
            if c['function']['name'] == 'submit_clustering'][-1]


def with_overlapping_class(payload):
    payload = copy.deepcopy(payload)
    groups = payload['axes'][0]['labels'][0]['clusters']
    duplicate = copy.deepcopy(groups[0])
    duplicate['name'] = '同一情况的另一种表述'
    groups.append(duplicate)
    return payload


def test_schema_and_provenance_stay_separate_from_overlap_policy(submission):
    groups = submission['axes'][0]['labels'][0]['clusters']
    groups[0]['members'][0]['evidence'] = '本次模型输入没有前轮消息'
    another = copy.deepcopy(groups[0])
    another.update(name='重复询问商品名称', members=[{'ref': 'R1', 'evidence': '系统重复询问商品名称'}])
    groups.append(another)
    # 两段证据真实且不同，结构仍合法；集合约束仍拒绝包含关系，不冒充语义判断。
    assert validate_submission(submission, material_of(CASES, TYPES))['axes']
    result = OverlapGuard(threshold=.5).post_tool(History(), call_for(submission))
    assert result['accepted'] is False and result['overlaps'][0]['rate'] == 1


class CorrectionClient:
    def __init__(self, submission, correct=True):
        self.submission = submission
        self.correct = correct
        self.step = 0
        self.last_tool_result = None

    def complete_step(self, messages, functions, **kwargs):
        self.step += 1
        if self.step == 1:
            name, args = 'read_reasons', {'refs': list(material_of(CASES, TYPES)['refs'])}
        elif self.step == 2:
            name, args = 'submit_clustering', with_overlapping_class(self.submission)
        elif self.step == 3:
            self.last_tool_result = json.loads(messages[-1]['content'])
            assert self.last_tool_result['accepted'] is False
            assert self.last_tool_result['overlaps'][0]['rate'] == 1
            return Step({'role': 'assistant', 'content': '尝试结束'})
        elif self.step == 4 and self.correct:
            assert '尚未被接受' in messages[-1]['content']
            name, args = 'submit_clustering', self.submission
        else:
            return Step({'role': 'assistant', 'content': '结束'})
        return Step({'role': 'assistant', 'tool_calls': [
            {'id': f'call-{self.step}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]})


@pytest.mark.parametrize('correct', [True, False])
def test_observed_loop_feedback_completion_and_final_artifact(submission, correct):
    client = CorrectionClient(submission, correct)
    base = build_clustering(client)
    events = []
    loop = observe(base, lambda k, d: events.append((k, d)), BoundaryGuard(lambda: False))
    result = loop.run('核对目录', LoopContext('overlap-local-test'))
    assert client.last_tool_result['accepted'] is False
    submissions = [c for c in result.calls if c.tool == 'submit_clustering']
    assert submissions[0].ok and not submissions[0].result['accepted']
    assert any(k == 'hook' and d['hook'] == 'OverlapGuard' and d['event'] == 'post_tool'
               and d['tool'] == 'submit_clustering' and d['result'].get('accepted') is False for k, d in events)
    assert any(k == 'hook' and d['core_completion'] and d['decision'] == 'Continue' for k, d in events)
    if correct:
        assert result.status == 'complete'
        assert submissions[-1].result == {'accepted': True}
        groups = result.value['clustering']['axes'][0]['labels'][0]['clusters']
        assert len(groups) == 2 and all(g['name'] != '同一情况的另一种表述' for g in groups)
        assert result.value['clustering'] == validate_submission(submission, material_of(CASES, TYPES))
    else:
        assert result.status == 'failed' and result.value is None
        assert 'max_blocked=3' in result.reason


def test_policy_is_visible_in_the_actual_model_prompt():
    loop = build_clustering(None)
    assert loop.hooks['post_tool'][0].threshold == .5
    assert '严格超过 50%' in loop.system_prompt and '不证明语义重复' in loop.system_prompt
    assert loop.budget.tool_calls == 30
