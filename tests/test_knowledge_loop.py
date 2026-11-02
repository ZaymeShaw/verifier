"""知识查证 loop 的程序把关（spec/alg/knowledge-evidence.md §4）：模型回复脚本化，知识源工具是假的。"""
from __future__ import annotations

import json

import pytest

from impl.core.tool_loop import LoopContext, Step
from impl.projects.llm_probe.knowledge_loop import loop as kl
from impl.projects.llm_probe.knowledge_loop.evidence import window
from impl.tools.protocol import VerifiableTool, build_agno_tools, runtime_tool_name

KB = {
    '贷款 比例': {'text': '保单贷款可以将保单中80%的现金价值提取出来。短期险不能贷款。'},
    '贷款 利率': {'text': json.dumps({'qa': '贷款利率一般在4.5%-6%之间。\n按年公布。'}, ensure_ascii=False)},
    '坏查询': {'error': 'MCP 调用失败（Timeout）'},
}
TOOL = 'insurance_tools__general_qa'
CATALOG = [{'source': 'mcp', 'uri': 'mcp://insurance-tools', 'title': 'insurance-tools', 'description': ''}]
ITEMS = [{'item_id': 'a', 'kind': 'claim', 'text': '可贷80%', 'context': ['保单贷款']},
         {'item_id': 'b', 'kind': 'claim', 'text': '手续费500元', 'context': ['保单贷款']}]


@pytest.fixture(autouse=True)
def fake_sources(monkeypatch):
    tool = VerifiableTool(tool_id=TOOL, description='通用问答', execute_fn=lambda query: dict(KB.get(query, {'text': ''})),
                          parameters={'type': 'object', 'properties': {'query': {'type': 'string', 'description': '查询'}}, 'required': ['query']})
    monkeypatch.setattr(kl, 'build_tools', lambda catalog, recorder, request=None: build_agno_tools([tool]))


class Script:
    """按顺序回放模型回复；每条回复是 [(工具名, 参数)]，空列表 = 不再调工具。"""

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def complete_step(self, messages, functions, *, trace_id, stage):
        self.seen.append(list(messages))
        calls = self.steps.pop(0) if self.steps else []
        return Step({'role': 'assistant', 'content': '' if calls else '完成', 'tool_calls': [
            {'id': f'x{len(self.seen)}-{i}', 'type': 'function',
             'function': {'name': runtime_tool_name(name), 'arguments': json.dumps(args, ensure_ascii=False)}}
            for i, (name, args) in enumerate(calls)]})


def search(query):
    return (TOOL, {'query': query})


def submit(item_id, status, citations=(), searches=('c0',), note='查了 general_qa', gap=None):
    if gap is None:
        gap = 'item_absent' if status == 'not_found' else ''
    return (kl.SUBMIT, {'item_id': item_id, 'status': status, 'citations': [dict(c) for c in citations],
                        'search_calls': list(searches), 'note': note, 'gap': gap})


def run(*steps, items=ITEMS):
    script = Script(*steps)
    knowledge = kl.KnowledgeLoop(items, CATALOG, script, seconds=60)
    return knowledge.loop.run('清单', LoopContext('t')), script


def tool_results(result):
    return [json.loads(m['content']) for m in result.messages if m['role'] == 'tool']


def test_happy_path_builds_dossier_and_ends_without_summary_step():
    result, script = run(
        [search('贷款 比例')],
        [submit('a', 'found', [{'call_id': 'c0', 'quote': '可以将保单中80%的现金价值提取出来'}]),
         submit('b', 'not_found', note='查了比例、手续费，均无手续费原文')],
    )
    assert result.status == 'complete'
    assert len(script.seen) == 2  # 最后一条被接受即结束，不再请求收尾文本
    items = {i['item_id']: i for i in result.value['items']}
    assert items['a']['status'] == 'found' and items['b']['status'] == 'not_found'
    assert items['a']['gap'] == '' and items['b']['gap'] == 'item_absent'
    cite = items['a']['citations'][0]
    assert cite['source'] == 'mcp://insurance-tools' and '短期险不能贷款' in cite['window']
    assert result.value['searches'][0]['call_id'] == 'c0'
    assert tool_results(result)[0]['call_id'] == 'c0'  # 模型看得到 call_id


def test_same_batch_result_cannot_be_cited():
    result, _ = run(
        [search('贷款 比例'), submit('a', 'found', [{'call_id': 'c0', 'quote': '80%的现金价值'}])],
        [submit('a', 'found', [{'call_id': 'c0', 'quote': '80%的现金价值'}]), submit('b', 'not_found')],
    )
    assert result.status == 'complete'
    denied = tool_results(result)[1]
    assert denied['status'] == 'denied' and '下一次回复' in denied['reason']


@pytest.mark.parametrize('bad, reason', [
    (submit('a', 'not_found', searches=()), '一次都没查'),
    (submit('a', 'found', [{'call_id': 'c0', 'quote': '可贷九成'}]), '没有逐字出现'),
    (submit('a', 'found', []), 'found 必须引用'),
    (submit('a', 'not_found', [{'call_id': 'c0', 'quote': '80%'}]), 'not_found 时 citations 必须为 []'),
    (submit('zz', 'not_found'), '不在待查清单'),
    (submit('a', 'not_found', searches=('c9',)), '不是此前回复里的知识源调用'),
    (submit('a', 'found', [{'call_id': 'c0', 'quote': '80%'}], searches=('c1',)), '没列在 search_calls'),
    # 查不到要说出缺哪一格（demand/claims.md §3.3）。
    (submit('a', 'not_found', gap=''), 'gap 必须是'),
    (submit('a', 'found', [{'call_id': 'c0', 'quote': '80%'}], gap='item_absent'), 'found 时 gap 为空'),
])
def test_submit_rules_are_enforced(bad, reason):
    result, _ = run(
        [search('贷款 比例'), search('贷款 利率')],
        [bad],
        [submit('a', 'not_found'), submit('b', 'not_found')],
    )
    assert result.status == 'complete'
    denied = tool_results(result)[2]
    assert denied['status'] == 'denied' and reason in denied['reason'], denied


def test_errored_call_is_not_a_search():
    result, _ = run(
        [search('坏查询')],
        [submit('a', 'not_found'), submit('b', 'not_found')],
        [search('贷款 比例')],
        [submit('a', 'not_found', searches=('c3',)), submit('b', 'not_found', searches=('c3',))],
    )
    assert result.status == 'complete'
    reasons = [r.get('reason', '') for r in tool_results(result)[1:3]]
    assert all('报错的调用' in r for r in reasons)


def test_missing_items_keep_loop_going_and_accepted_cannot_be_resubmitted():
    result, script = run(
        [search('贷款 比例')],
        [submit('a', 'not_found')],
        [],  # 模型想结束，但 b 还没交
        [submit('a', 'not_found'), submit('b', 'not_found')],
    )
    assert result.status == 'complete'
    assert any('还有 1 条' in str(m.get('content')) for m in script.seen[3] if m['role'] == 'user')
    assert '已经被接受' in tool_results(result)[2]['reason']


def test_same_item_twice_in_one_batch_only_first_accepted():
    result, _ = run(
        [search('贷款 比例')],
        [submit('a', 'not_found'), submit('a', 'not_found'), submit('b', 'not_found')],
    )
    assert result.status == 'complete'
    assert '已经被接受' in tool_results(result)[2]['reason']


def test_budget_exhaustion_fails_not_not_found():
    steps = [[search('贷款 比例')]] * 40
    result, _ = run(*steps)
    assert result.status == 'failed' and 'budget' in result.reason


def test_quote_matches_json_string_leaves_and_window():
    result, _ = run(
        [search('贷款 利率')],
        [submit('a', 'found', [{'call_id': 'c0', 'quote': '贷款利率一般在4.5%-6%之间。'}]), submit('b', 'not_found')],
    )
    assert result.status == 'complete'
    assert '按年公布' in result.value['items'][0]['citations'][0]['window']


def test_window_ignores_whitespace_differences():
    from impl.core.tool_loop import Call
    call = Call(id=0, tool=TOOL, args={}, batch=0, result={'text': '前文。可贷 80 %\n的现金价值。后文'})
    # chars 是总预算（引句前后合计）
    assert window(call, '可贷80%的现金价值', chars=19) == '前文。可贷 80 %\n的现金价值。后文'


def test_tool_own_call_id_never_overrides_evidence_id(monkeypatch):
    """知识源工具自己的返回也带 call_id 类键（如 MCP 翻页句柄）时，模型看到的证据编号仍是 loop 的。"""
    tool = VerifiableTool(tool_id=TOOL, description='通用问答', execute_fn=lambda query: {'call_id': 'mcp://x#9', 'text': '可贷80%'},
                          parameters={'type': 'object', 'properties': {'query': {'type': 'string', 'description': '查询'}}, 'required': ['query']})
    monkeypatch.setattr(kl, 'build_tools', lambda catalog, recorder, request=None: build_agno_tools([tool]))
    result, _ = run([search('贷款')], [submit('a', 'found', [{'call_id': 'c0', 'quote': '可贷80%'}]), submit('b', 'not_found')])
    assert tool_results(result)[0]['call_id'] == 'c0' and result.status == 'complete'


def test_context_leak_check_ignores_values_inside_identifiers():
    from impl.projects.llm_probe.knowledge_loop.extract import _contains_value
    assert not _contains_value('P260922000007857', '0')          # 保单号里的数字不是别条断言的值
    assert _contains_value('安锦宁名下共有 6 张保单', '6 张')         # 前提里塞了张数：算泄露
    assert _contains_value('**投保人**：任言琳', '**投保人**：任言琳')
    assert _contains_value('保费0元', '0')
