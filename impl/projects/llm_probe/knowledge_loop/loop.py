"""查证 ToolLoop：模型自由检索，逐条 submit_item；程序管范围、完成与证据（spec/alg/knowledge-evidence.md §4）。

- 范围：只有场景目录里的知识源工具（sources.build_tools 同一组）。
- 完成：清单每条都有被接受的提交才结束；模型停调工具只是申请结束。
- 证据：引用 = {call_id, quote}，quote 必须逐字出现在此前批次那次调用的返回里。
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from impl.core.tool_loop import (
    Allow, BudgetStop, Call, Continue, Deny, Done, History, Hook, PreDecision, StepClient, StopVerdict, ToolLoop, is_accepted)
from impl.projects.llm_probe.eval_axes.sources import build_tools
from impl.projects.llm_probe.eval_axes.sources.mcp_tools import recorded_response, tool_prefix
from impl.tools.protocol import VerifiableTool

from .evidence import StampCallId, call_id, failed, find, quote_ok, window

SUBMIT = 'submit_item'
FOUND, NOT_FOUND = 'found', 'not_found'
# not_found 缺的是哪一格（demand/claims.md §3.3）：对象整个不在，还是对象在、这一项不在。只有查证人知道，提交时就要。
GAPS = ('object_absent', 'item_absent')

SYSTEM = '''你在为一份被测回答做知识查证：针对待查清单里的每一条，到给定知识源里取证。你只取证，不判对错。

每条交两种结果之一：
- found：知识源里有讲同一对象、同一事项的原文。引用这些原文。
- not_found：查过了，知识源里没有相关原文。note 写清检索了哪些知识源、用了什么词、为什么认为没有；
  gap 写缺的是哪一格：object_absent = 这个对象在知识源里就找不到；item_absent = 对象找到了，只是没有这一项。

取证规则：
1. 对象要对：原文说的必须就是说法说的那个对象（谁、哪张单、哪款产品哪个版本）的那个事项、那个条件。
   对象的组成部分（客户名下的某张保单、保单里的某一行险种）不是对象本身；手里只有部分时，接着去查对象本身的记录。
   别的产品、别的版本的同类条款也不算相关原文。
2. 正反都查：每条都要同时找支持它的、与它矛盾的、给它加条件或例外的原文（适用条件、其他版本、免责、限制）。不能找到一段相符的就停。
   你可以有自己的判断来决定往哪查，但不要在提交里写"支持""矛盾"之类的结论——判定由别人做。
3. 相关原文全部引用，不挑：找到的相关原文都要交，包括互相矛盾的（同一事项知识库里有两种说法时两段都引）。
   说法里用到的术语、字段，知识源若给了定义或字段说明，也一并引用（判定要据此确认含义）。
   对象本身确实没有这一项、说法是由几条数据算出来的时：参与计算的每条数据都引上，算法的出处（字段说明、知识库文档）
   找到了也引上；找不到出处在 note 里写明"没找到 X 的算法"。
4. 只用工具，不凭记忆。引用 = {call_id, quote}：call_id 是工具返回里的 call_id，quote 是那次返回里逐字摘的连续原文，
   不改写、不拼接；一段话太长就摘含关键值及其条件的那一截。工具返回被截断时，用翻页工具看后面，翻出来的页同样带 call_id 可引用。
5. 同一次回复里拿到的返回，要到下一次回复才能引用（先看到、再引用）。
6. 工具报错（不是零命中）不能当作"没找到"：换参数重试；查不了就如实写在 note 里，但这条不能交 not_found。
7. 数字写法在原文里可能不同：阿拉伯数字与中文数字、%与百分之、天与日、万与万元互为等价。搜数字零命中时换另一种写法再搜一次。
8. 查得全：返回显示结果不全（总数大于已读条数、列表只给了第一页）时，翻页或换别的工具、别的查法补全（如按对象逐个查详情）；
   实在补不全，在 note 里写明"结果不全：总数多少、看到多少"。全不全以数据本身为准（总数与已读条数）。
   单次返回很长被截断时，没看到的部分不能当作"没有"：用 mcp_find 在全文里搜（字段名、中文名、数值），或翻页看完。
9. 知识源目录里的 notes 是登记方写的读法说明（字段含义、数据怎么读），取证时照着读。
10. 按说法的对象查过，返回明确表明这个对象本身不存在（结果为空、提示未查询到该对象）：这个返回就是关于该对象的原文，交 found 并引用它
   （返回本身就是依据，demand/claims.md §3.3）；查回别的对象、没读全、工具报错都不算。

提交：每查完一条就调用 submit_item 交这一条（可以一次回复里交多条）。search_calls 列出为这一条做过的检索调用的 call_id
（同一次调用可以被多条共用）；found 时每个引用的 call_id 也要列在 search_calls 里。被拒就按原因改了再交。
全部条目都被接受后就结束，不需要再写总结。'''

_SUBMIT_PARAMETERS = {'type': 'object', 'properties': {
    'item_id': {'type': 'string', 'description': '待查清单里的 item_id'},
    'status': {'type': 'string', 'enum': [FOUND, NOT_FOUND], 'description': 'found=找到相关原文；not_found=查过，没找到'},
    'citations': {'type': 'array', 'description': 'found 时必填：全部相关原文；not_found 时为 []',
                  'items': {'type': 'object', 'properties': {
                      'call_id': {'type': 'string', 'description': '工具返回里的 call_id'},
                      'quote': {'type': 'string', 'description': '该次返回里逐字摘的连续原文'}},
                      'required': ['call_id', 'quote'], 'additionalProperties': False}},
    'search_calls': {'type': 'array', 'items': {'type': 'string'}, 'description': '为这一条做过的检索调用的 call_id，至少一个'},
    'note': {'type': 'string', 'description': '检索思路与取舍；not_found 时写清查了什么、为什么认为没有。不写支持/矛盾的结论'},
    'gap': {'type': 'string', 'enum': ['', *GAPS],
            'description': 'not_found 时必填：object_absent=对象本身找不到；item_absent=对象在、没有这一项。found 时为空字符串'},
}, 'required': ['item_id', 'status', 'citations', 'search_calls', 'note', 'gap'], 'additionalProperties': False}


def knowledge_tools(catalog: Sequence[Mapping[str, Any]], recorder: list, request: Any = None) -> list[VerifiableTool]:
    """sources.build_tools 的同一组工具（名字、说明、参数不变），还原成 ToolLoop 要的 VerifiableTool。"""
    return [VerifiableTool(tool_id=fn.entrypoint.logical_tool_id, description=fn.description,
                           parameters=fn.parameters, execute_fn=fn.entrypoint)
            for fn in build_tools(list(catalog), recorder, request)]


def source_of(call: Call, catalog: Sequence[Mapping[str, Any]]) -> str:
    """这次调用查的是哪个知识源（目录里的 uri）。"""
    args = call.args
    if isinstance(args.get('index'), str):
        return 'es://' + args['index']
    if 'material_id' in args:
        return next((item['uri'] for item in catalog if str(item.get('id')) == str(args['material_id'])), '')
    if call.tool in ('mcp_read', 'mcp_find') and isinstance(args.get('page_id'), str):
        return args['page_id'].split('#', 1)[0]
    for item in catalog:
        if item.get('source') == 'mcp' and call.tool.startswith(tool_prefix(item['uri'][len('mcp://'):])):
            return item['uri']
    return ''


class Checklist(Hook):
    """state：待查清单。pre_tool 验收 submit_item；stop 要求每条都有被接受的提交。"""

    def __init__(self, items: Sequence[Mapping[str, Any]], tools: set[str]) -> None:
        self.items = {item['item_id']: dict(item) for item in items}
        self.tools = tools
        self._batch = -1
        self._pending: set[str] = set()  # 本批已放行的 item：同批两次提交同一条，第二次拒

    def accepted(self, history: History) -> dict[str, Call]:
        return self.accepted_in(history.calls)

    @staticmethod
    def accepted_in(calls: Sequence[Call]) -> dict[str, Call]:
        done: dict[str, Call] = {}
        for call in calls:
            if call.tool == SUBMIT and call.ok and is_accepted(call):
                done.setdefault(call.args.get('item_id'), call)
        return done

    def missing(self, history: History) -> list[str]:
        return self.missing_from(history.calls)

    def missing_from(self, calls: Sequence[Call]) -> list[str]:
        done = self.accepted_in(calls)
        return [key for key in self.items if key not in done]

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        if call.tool != SUBMIT:
            return Allow()
        if call.batch != self._batch:
            self._batch, self._pending = call.batch, set()
        problems = self._check(history, call.args)
        if problems:
            return Deny(f"{SUBMIT}（{call.args.get('item_id')}）被拒：" + '；'.join(problems))
        self._pending.add(call.args['item_id'])
        return Allow()

    def _check(self, history: History, args: Mapping[str, Any]) -> list[str]:
        key, status = args.get('item_id'), args.get('status')
        citations, searches, note = args.get('citations'), args.get('search_calls'), args.get('note')
        if key not in self.items:
            return [f'item_id 不在待查清单里；清单：{list(self.items)}']
        if key in self.accepted(history) or key in self._pending:
            return ['这一条已经被接受，不能再交']
        problems = []
        if status not in (FOUND, NOT_FOUND):
            problems.append(f'status 只能是 {FOUND} 或 {NOT_FOUND}')
        if not isinstance(note, str) or not note.strip():
            problems.append('note 不能为空')
        gap = args.get('gap') or ''
        if status == NOT_FOUND and gap not in GAPS:
            problems.append(f'not_found 时 gap 必须是 {GAPS[0]}（对象本身找不到）或 {GAPS[1]}（对象在、没有这一项）')
        if status == FOUND and gap:
            problems.append('found 时 gap 为空字符串')
        if not isinstance(searches, list) or not searches:
            problems.append('search_calls 至少列一个为这一条做过的检索调用的 call_id；一次都没查就不能交')
            searches = []
        for ref in searches:
            target = find(history, ref, self.tools) if isinstance(ref, str) else None
            if target is None:
                problems.append(f'search_calls 里的 {ref!r} 不是此前回复里的知识源调用（同一次回复里拿到的要到下一次回复才能用）')
            elif failed(target):
                problems.append(f'search_calls 里的 {ref} 是报错的调用，不算检索过；换参数重查')
        if not isinstance(citations, list):
            return problems + ['citations 必须是列表']
        if status == NOT_FOUND and citations:
            problems.append('not_found 时 citations 必须为 []；有相关原文就交 found')
        if status == FOUND and not citations:
            problems.append('found 必须引用相关原文')
        for cite in citations if status == FOUND else []:
            ref = cite.get('call_id') if isinstance(cite, Mapping) else None
            quote = cite.get('quote') if isinstance(cite, Mapping) else None
            if not isinstance(ref, str) or not isinstance(quote, str) or not quote.strip():
                problems.append('每个引用要有 call_id 和非空 quote')
                continue
            if ref not in searches:
                problems.append(f'引用的 {ref} 没列在 search_calls 里')
            target = find(history, ref, self.tools)
            if target is None or failed(target):
                problems.append(f'引用的 {ref} 不是此前回复里成功的知识源调用')
            elif not quote_ok(target, quote):
                problems.append(f'引句 {quote[:40]!r} 没有逐字出现在 {ref} 的返回里；照返回原文摘，不改写、不拼接')
        return problems

    def stop(self, history: History, blocked: int) -> StopVerdict:
        missing = self.missing(history)
        if not missing:
            return Done()
        return Continue(f'还有 {len(missing)} 条没有被接受的提交：{missing}。继续查证并用 {SUBMIT} 提交。')

    def ready_to_finish(self, history: History) -> bool:
        return not self.missing(history)


def render_input(description: str, catalog: Sequence[Mapping[str, Any]], outline: Sequence[Any],
                 items: Sequence[Mapping[str, Any]], question: Any) -> str:
    listing = [{k: item[k] for k in ('item_id', 'kind', 'text', 'context') if k in item} for item in items]
    parts = [
        '## 场景说明（含知识源）\n' + description,
        '## 知识源目录\n' + json.dumps([{k: c.get(k) for k in ('uri', 'title', 'description', 'notes', 'doc_count') if c.get(k)}
                                     for c in catalog], ensure_ascii=False),
    ]
    if outline:
        parts.append('## ES 字段骨架（已给出，不必再调 es_outline）\n' + json.dumps(list(outline), ensure_ascii=False))
    parts += [
        '## 用户问题（背景）\n' + json.dumps(question, ensure_ascii=False),
        '## 待查清单\nkind=claim 是回答里说出的事实：text 是事实本身，context 是它归属的对象与成立条件，查的是「context 之下的 text」。\n'
        + json.dumps(listing, ensure_ascii=False),
    ]
    return '\n\n'.join(parts)


class KnowledgeLoop:
    """一次查证。run() 成功时 dossier 是案卷：items（逐条结果）与 searches（全部知识源调用）。"""

    def __init__(self, items: Sequence[Mapping[str, Any]], catalog: Sequence[Mapping[str, Any]],
                 client: StepClient, *, seconds: float, request: Any = None) -> None:
        self.catalog = list(catalog)
        self.receipts: list = []
        tools = knowledge_tools(self.catalog, self.receipts, request)
        names = {tool.tool_id for tool in tools}
        self.checklist = Checklist(items, names)
        n = len(self.checklist.items)
        self.limits = {'llm_calls': 8 + 3 * n, 'tool_calls': 16 + 6 * n, 'seconds': seconds}
        submit = VerifiableTool(tool_id=SUBMIT, parameters=_SUBMIT_PARAMETERS, execute_fn=lambda **_: {'accepted': True},
                                description='交一条待查项的查证结果。合规返回 accepted=true；不合规会被拒并给出原因，改了再交。')
        stamp = StampCallId(names)
        self.names = names
        self.loop = ToolLoop('knowledge_evidence', SYSTEM, [*tools, submit], client,
                             completion_hook=self.checklist,
                             hooks={'pre_tool': [self.checklist], 'post_tool': [stamp]},
                             end=self._end, budget=BudgetStop(**self.limits))

    def _citation(self, call: Call, cite: Mapping[str, Any]) -> dict[str, Any]:
        """引用 + 判定需要的上下文：哪个工具、按什么参数查的（归属常靠它，如按姓名查而数据里姓名是密文），引句所在的整条记录。"""
        tool, args = call.tool, call.args
        page_id = call.result.get('page_id') if isinstance(call.result, Mapping) else None
        if tool in ('mcp_read', 'mcp_find') and isinstance(page_id, str):
            # 翻页、搜索看到的：工具与参数记原始那次调用的。
            origin = next((c for c in self.receipts if c.get('page_id') == page_id and c.get('tool') == 'mcp_call'), None)
            if origin:
                tool, args = tool_prefix(origin['source']) + origin['mcp_tool'], origin['arguments']
        full = recorded_response(self.receipts, page_id) if isinstance(page_id, str) else None
        return {'call_id': cite['call_id'], 'source': source_of(call, self.catalog), 'tool': tool, 'args': args,
                'quote': cite['quote'], 'window': window(call, cite['quote'], full_text=full)}

    def _end(self, history: History) -> dict[str, Any]:
        calls = {call_id(c): c for c in history.calls if c.tool in self.names}
        accepted = self.checklist.accepted(history)
        items = []
        for key, item in self.checklist.items.items():
            args = accepted[key].args
            citations = [self._citation(calls[c['call_id']], c) for c in args['citations']]
            items.append({**item, 'status': args['status'], 'citations': citations,
                          'search_calls': list(args['search_calls']), 'note': args['note'], 'gap': args.get('gap') or ''})
        searches = [{'call_id': ref, 'tool': c.tool, 'args': c.args, 'source': source_of(c, self.catalog),
                     'batch': c.batch, 'error': failed(c), 'result': c.result} for ref, c in calls.items()]
        return {'items': items, 'searches': searches}
