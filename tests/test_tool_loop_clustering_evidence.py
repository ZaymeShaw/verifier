import copy
import json

import pytest

from impl.core.axes_clustering import OUTPUT_SPEC
from impl.tool_loop_lab.clustering_example import (
    CASES, TYPES, SUBMISSION_SPEC, ClusteringScriptClient, build_clustering,
    material_of, validate_submission,
)


@pytest.fixture
def submission():
    script = ClusteringScriptClient()
    payload = None
    while True:
        try: step = script.complete_step()
        except StopIteration: break
        for call in step.message.get('tool_calls', []):
            if call['function']['name'] == 'submit_clustering':
                payload = json.loads(call['function']['arguments'])
    return payload


def first(payload):
    return payload['axes'][0]['labels'][0]['clusters'][0]


def test_submission_requires_paired_evidence_without_changing_source_contract(submission):
    source_fields = OUTPUT_SPEC.json_schema()['$defs']['SituationCluster']['properties']
    assert 'member_refs' in source_fields and 'members' not in source_fields
    lab_fields = SUBMISSION_SPEC.json_schema()['$defs']['SubmittedCluster']['properties']
    assert 'members' in lab_fields and 'member_refs' not in lab_fields
    original = copy.deepcopy(submission)
    result = validate_submission(submission, material_of(CASES, TYPES))
    assert submission == original
    for axis in result['axes']:
        for label in axis['labels']:
            for cluster in label['clusters']:
                assert set(cluster['member_refs']) == set(cluster['member_evidence'])
                assert 'members' not in cluster  # 适配为共享渲染器的引用目录。


@pytest.mark.parametrize('damage', ['missing_evidence', 'foreign_quote', 'fabricated_quote', 'whitespace',
                                   'unknown_ref', 'cross_axis', 'duplicate_ref', 'missing_member', 'bare_refs'])
def test_rejects_bad_evidence_and_still_enforces_original_membership_rules(submission, damage):
    cluster = first(submission);member = cluster['members'][0]
    if damage == 'missing_evidence': del member['evidence']
    if damage == 'foreign_quote': member['evidence'] = CASES[2]['axes'][0]['text']
    if damage == 'fabricated_quote': member['evidence'] = '模型改写的摘要，不是原文'
    if damage == 'whitespace': member['evidence'] = ' '
    if damage == 'unknown_ref': member['ref'] = 'R404'
    if damage == 'cross_axis': member.update(ref='R6', evidence=CASES[5]['axes'][0]['text'])
    if damage == 'duplicate_ref': cluster['members'].append(copy.deepcopy(member))
    if damage == 'missing_member': cluster['members'].pop()
    if damage == 'bare_refs': cluster['member_refs'] = [m['ref'] for m in cluster.pop('members')]
    tool = next(t for t in build_clustering(None).tools if t.tool_id == 'submit_clustering')
    assert tool.execute_fn(**submission)['accepted'] is False


def test_rejection_can_be_corrected_in_existing_submission_tool(submission):
    tool = next(t for t in build_clustering(None).tools if t.tool_id == 'submit_clustering')
    correct = first(submission)['members'][0]['evidence']
    first(submission)['members'][0]['evidence'] = '不存在的引用'
    rejected = tool.execute_fn(**submission)
    assert not rejected['accepted'] and 'R1' in rejected['error'] and '原文' in rejected['error']
    first(submission)['members'][0]['evidence'] = correct
    assert tool.execute_fn(**submission) == {'accepted': True}


def test_same_reason_can_support_different_clusters_with_separate_quotes(submission):
    cluster = first(submission)
    cluster['members'][0]['evidence'] = '本次模型输入没有前轮消息'
    another = copy.deepcopy(cluster)
    another.update(name='另一情况', members=[{'ref': 'R1', 'evidence': '系统重复询问商品名称'}])
    submission['axes'][0]['labels'][0]['clusters'].append(another)
    result = validate_submission(submission, material_of(CASES, TYPES))
    groups = result['axes'][0]['labels'][0]['clusters']
    assert groups[0]['member_evidence']['R1'] != groups[-1]['member_evidence']['R1']


def test_quote_check_does_not_pretend_to_judge_semantic_relevance(submission):
    # 出处真实不等于语义正确：程序没有引入关键词打分或冒充独立语义审查。
    first(submission)['name'] = '语义上不受这些成员支持的标题'
    assert validate_submission(submission, material_of(CASES, TYPES))['axes']
