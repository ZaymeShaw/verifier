"""冻结 llmtracing 对话稿的只读工具与引用检查；不枚举 Agno 环节、不调用业务。"""
from __future__ import annotations

import re
from typing import Any, Mapping

from impl.tools.protocol import VerifiableTool

READ_CHARS = 12_000


class TranscriptEvidence:
    def __init__(self, transcript: Mapping[str, Any]):
        self.records = {r['id']: r for r in transcript['records']}
        self.receipts: list[dict[str, Any]] = []
        self._ranges: dict[str, list[tuple[int, int]]] = {}

    def catalog(self) -> list[dict[str, Any]]:
        return [{k: r[k] for k in ('id', 'kind', 'role', 'origin', 'canonical_ref') if k in r}
                | {'chars': len(r['text'])} for r in self.records.values()]

    @property
    def read_ids(self) -> set[str]:
        """只有已交付全部正文的条目可作为完整条目引用；分段可累积，不把目录当正文。"""
        complete = set()
        for ref, ranges in self._ranges.items():
            end = 0
            for start, stop in sorted(ranges):
                if start > end:
                    break
                end = max(end, stop)
            if end >= len(self.records[ref]['text']):
                complete.add(ref)
        # “同某条”的短引用不是规则原文；原条目也完整可读时才承认别名已读。
        return {ref for ref in complete if not self.records[ref].get('canonical_ref')
                or self.records[ref]['canonical_ref'] in complete}

    def read(self, ids: list[str], offset: int = 0) -> dict[str, Any]:
        if not isinstance(ids, list) or not ids or len(ids) > 32 or any(not isinstance(x, str) for x in ids):
            raise ValueError('ids 必须是1–32个编号')
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError('offset 必须是非负整数')
        items, unknown, deferred = [], [], []
        remaining = READ_CHARS
        for ref in dict.fromkeys(ids):
            if ref not in self.records:
                unknown.append(ref)
                continue
            row = self.records[ref]
            text = row['text']
            if offset > len(text):
                unknown.append(f'{ref}: offset 超出正文长度')
                continue
            if remaining <= 0:
                deferred.append(ref)
                continue
            end = min(len(text), offset + remaining)
            item = {k: v for k, v in row.items() if k != 'text'}
            item.update(text=text[offset:end], offset=offset, next_offset=end if end < len(text) else None,
                        chars=len(text))
            items.append(item)
            remaining -= end - offset
            self._ranges.setdefault(ref, []).append((offset, end))
            self.receipts.append({'id': ref, 'offset': offset, 'end': end, 'chars': len(text)})
        return {'items': items, 'unknown': unknown, 'deferred': deferred}

    def call_inputs(self, call_id: str) -> dict[str, Any]:
        row = self.records.get(call_id)
        if not row or row['kind'] != 'call':
            raise ValueError('call_id 必须是对话稿的调用编号，如 t1.c2')
        return {'call_id': call_id, 'input_refs': row.get('input_refs', []),
                'recorded': 'input_refs' in row,
                'note': '成员来自本次实际请求的精确消息比对；这里只给成员索引，正文用 evidence_read 读取。'}

    def tools(self) -> list[VerifiableTool]:
        return [VerifiableTool(
            tool_id='evidence_read', description='批量读取冻结原文及来源。next_offset 非空则继续分页；没有完整正文不能当作读全。',
            parameters={'type': 'object', 'properties': {
                'ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 32,
                        'description': '目录中的原文编号，可一次读取多个'},
                'offset': {'type': 'integer', 'minimum': 0, 'description': '正文字符偏移；长条目按 next_offset 继续读取'}}, 'required': ['ids']}, execute_fn=self.read),
            VerifiableTool(
                tool_id='call_inputs', description='核对某次模型调用实际输入成员，避免用未进入本次请求的旧规则或后续材料判模型。',
                parameters={'type': 'object', 'properties': {'call_id': {'type': 'string', 'description': '对话稿调用编号，如 t1.c2'}},
                            'required': ['call_id']}, execute_fn=self.call_inputs)]

    def runtime_links(self, axis: str, obligations: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Enumerate observable exercises, never infer unrecorded tool outputs.

        Call input membership is the transcript's exact request comparison, not
        chronological inheritance. Suffixes identify program-owned boundaries,
        not new evidence records; every endpoint remains a real transcript ID.
        """
        links = []

        def add(ident, before, after, obs=None, basis=''):
            links.append(dict(link_id=ident, link_type=axis, turn=ident.split('.')[0],
                input=[{'ref': r, 'field': ''} for r in dict.fromkeys(before)],
                output=[{'ref': r, 'field': ''} for r in dict.fromkeys(after)],
                obligation_ids=list(obligations) if obs is None else list(obs), facts={}, basis=basis))

        calls = [r for r in self.records.values() if r['kind'] == 'call']
        responses = [r for r in self.records.values() if r['kind'] in {'response', 'error'}]
        position = {ref: n for n, ref in enumerate(self.records)}
        if axis in {'model_capability', 'intent_understanding', 'planning_routing'}:
            for response in responses:
                call = self.records.get(response['id'].rsplit('.', 1)[0], {})
                # Replayed responses also have actual assistant-message members.
                # The provider's extra original-response aliases are transfer
                # provenance, not a second request body (nor its earlier rules).
                inputs = [ref for ref in call.get('input_refs', [])
                          if self.records.get(ref, {}).get('origin') != 'model_response']
                add(response['id'], inputs, [response['id']],
                    basis='本次实际请求 → 完整模型响应/可见调用决定')
        elif axis in {'tool_execution', 'knowledge_data'}:
            # The renderer preserves emitted tool IDs and request arguments.
            # A received tool message is observable data, NOT an original return.
            claimed = set()
            for response in responses:
                for n, match in enumerate(re.finditer(r'^→ 调用 [^\n#]+#([^\n(]+)\(', response['text'], re.MULTILINE), 1):
                    tool_id = match.group(1)
                    received = [r['id'] for r in self.records.values()
                                if r.get('origin') == 'model_received_tool_result'
                                and r.get('role', '').endswith('#' + tool_id)
                                and r['id'].split('.')[0] == response['id'].split('.')[0]
                                and position[r['id']] > position[response['id']]
                                and response['id'] in self.records.get(r['id'].rsplit('.', 1)[0], {}).get('input_refs', [])
                                and r['id'] not in claimed]
                    claimed.update(received)
                    add(f"{response['id']}:tool:{n}", [response['id']],
                        received if axis == 'knowledge_data' else [],
                        basis='模型发起的工具请求；独立工具原始返回未采集，实收 tool 消息只证明收到的数据')
            for row in self.records.values():
                if row.get('origin') == 'model_received_tool_result' and row['id'] not in claimed:
                    add(row['id'], [], [row['id']] if axis == 'knowledge_data' else [],
                        basis='可见实收工具消息，但工具请求/原始返回关联缺失')
        elif axis == 'context_memory':
            assembly = [ob for ob in obligations if ob in {'input_assembled', 'history_and_state'} or ob.startswith('project:')]
            arrivals = set()
            for call in calls:
                own = call.get('input_refs', [])
                replayed = [r for r in own if self.records.get(r, {}).get('origin') == 'model_response']
                actual = [r for r in own if r != call['id'] and r not in replayed]
                request = call['id'].split('.')[0] + '.request'
                add(call['id'] + ':input', [request] if request in self.records else [], actual, assembly,
                    '业务请求 → 本次实际输入；未采集的应交付设计不补造')
                for ref in actual:
                    row = self.records.get(ref, {})
                    if ref in arrivals:
                        continue
                    if row.get('origin') == 'model_request' and row.get('role') == 'assistant':
                        arrivals.add(ref)
                        originals = [r for r in replayed if self.records[r]['text'] == row['text']]
                        add(call['id'] + ':arrival:' + ref, originals, [ref], ['arrives_intact'],
                            '实际请求成员中的重放响应 → assistant 消息；仅精确匹配能确认前端')
                    elif row.get('origin') == 'model_received_tool_result':
                        arrivals.add(ref)
                        add(call['id'] + ':arrival:' + ref, [], [ref], ['arrives_intact'],
                            '独立工具原始产出缺失，不能以工具参数冒充传递前端')
            for row in self.records.values():
                if row['kind'] != 'final':
                    continue
                prior = [r['id'] for r in responses if r['id'].split('.')[0] == row['id'].split('.')[0]]
                add(row['id'], prior[-1:], [row['id']], ['delivered_intact'], '末次模型响应 → 应用实收（来源另核验）')
        if not links:
            for row in self.records.values():
                if row['kind'] == 'request':
                    add(row['id'], [row['id']], [], basis='本轮可见请求；未记录事件不能推断本轮不需要')
        return links

    def validate(self, results: list[dict], obligations: Mapping[str, Any], readable: set[str], *,
                 expectations: Mapping[str, Any], design_refs: frozenset[str] = frozenset()) -> list[str]:
        """Provider boundary after shared validation; design_refs are validated quote identities only."""
        problems = []
        entries = {e['expectation_id']: e for e in expectations['expectations']}
        sources = {s['id']: s for s in expectations['sources']}
        expectation_refs = {'expectation:' + key for key in entries}
        comparisons = set()
        special = expectation_refs | {'case'} | {key for key in obligations if key.startswith('project:')} | design_refs
        for result in results:
            pair = f"{result['obligation_id']} @ {result['link_id']}"
            ob = obligations[result['obligation_id']]
            before, after = result['evidence']['input'], result['evidence']['output']
            refs = result['source_refs'] + before + after
            for issue in result.get('problems', []):
                refs += issue['source_refs'] + issue['input_refs'] + issue['output_refs']
            special.add('obligation:' + result['obligation_id'])
            unread = [ref for ref in refs if ref not in readable and ref not in special]
            if unread:
                problems.append(f'{pair}: 引用没有此前批次的完整正文回执：{unread}；读取、补齐分页或改用有证据的结论')
            for issue in result.get('problems', []):
                if issue['impact'] in {'yes', 'no'}:
                    turn = result.get('matched_link_id') or result['link_id']
                    turn = turn.split('.')[0]
                    finals = [row for row in self.records.values() if row['kind'] == 'final'
                              and (not turn.startswith('t') or row['id'].startswith(turn + '.'))]
                    if not any(row.get('origin') == 'http_response' and row['text'].strip() not in {'', 'null', '{}'} for row in finals):
                        problems.append(f'{pair}: 最终实收不可见，impact 必须 unknown')
            status = result['outcome']
            if status in {'pass', 'not_applicable'} and not (before or after):
                problems.append(f'{pair}: 缺少支撑结论的引用')
            if status == 'fail' and not (before and after):
                problems.append(f'{pair}: fail 需要两端证据；不可见时可以明确缺证')
            if status in {'pass', 'fail'} and ob.source in {'trace', 'case'} and not result['source_refs']:
                problems.append(f'{pair}: 没有规则出处')
            if status not in {'pass', 'fail'}:
                continue
            comparison = (result['obligation_id'], tuple(sorted(before)), tuple(sorted(after)))
            if result['obligation_id'] == 'arrives_intact' and comparison in comparisons:
                problems.append(f'{pair}: 同一输入输出对照不能用多个位置重复计为行使；请选择一个位置')
            comparisons.add(comparison)
            call = '.'.join((result.get('matched_link_id') or result['link_id']).split('.')[:2])
            if ob.link_type == 'model_capability':
                response = self.records.get(f'{call}.response', {})
                if result['obligation_id'] == 'output_contract' and status == 'pass' and response.get('whole_content_json') is False:
                    params = self.records.get(f'{call}.params', {})
                    params = self.records.get(params.get('canonical_ref'), params)
                    import json
                    try:
                        declared = json.loads(params.get('text', '{}')).get('response_format', {})
                    except (ValueError, AttributeError):
                        declared = {}
                    if isinstance(declared, dict) and declared.get('type') in {'json_schema', 'json_object'}:
                        problems.append(f'{pair}: 声明 JSON 格式，但完整 content 不能解析为 JSON；片段字段齐全不能支持 pass')
                row = self.records.get(call, {})
                own = set(row.get('input_refs', []))
                outside = [ref for ref in result['source_refs'] + before if ref not in own
                           and ref not in expectation_refs and ref not in design_refs
                           and ref not in {key for key in obligations if key.startswith('project:')}
                           and not ref.startswith('obligation:')]
                # A validated quote identity is not itself an input member. Recheck
                # its original source at the provider boundary as well.
                outside.extend(q['ref'] for check in result.get('criterion_checks', []) for q in check.get('quotes', [])
                               if q['ref'] not in own)
                # Compare actual request payloads, never IDs, rendered labels or
                # call metadata. Even a matching trace_ref can be stale/misbound.
                actual_inputs = []
                for ref in own:
                    item = self.records.get(ref, {})
                    if item.get('kind') == 'message':
                        actual_inputs.append(item.get('message', {}).get('content'))
                    elif item.get('kind') == 'system':
                        actual_inputs.extend(m.get('content') for m in item.get('messages', []))
                    elif item.get('kind') in {'tools', 'params'} and not item.get('canonical_ref'):
                        actual_inputs.append(item['text'])
                for ident in result.get('expectation_ids', []):
                    entry = entries[ident]
                    for ref in entry['source_refs']:
                        source = sources[ref]
                        if source['side'] == 'history':
                            continue
                        from ...process_contract import source_in_inputs
                        if not source_in_inputs(source, actual_inputs):
                            outside.append('expectation:' + ident + '（出处未证实进入本次输入）')
                if not own or outside:
                    problems.append(f'{pair}: 引用不属于该次已记录输入：{outside}；用 call_inputs 核对，不能只按先后位置猜继承')
                if any(ref != f'{call}.response' for ref in after) or not after:
                    problems.append(f'{pair}: 模型输出端只能引用该次 response；不同调用请分别提交')
            if result['obligation_id'] == 'arrives_intact':
                received = [ref for ref in before + after if self.records.get(ref, {}).get('origin') == 'model_received_tool_result']
                if received:
                    # 本 provider 没有工具执行侧的原始产出，工具请求不能充当该端。
                    problems.append(f'{pair}: {received} 只证明模型收到的工具消息，快照没有独立工具原始产出；'
                                    '工具调用参数不是传递前的产出，不能据此证明无损。可核对其他有两端的边界或明确缺证')
                elif (not before or not after
                      or any(self.records.get(ref, {}).get('origin') != 'model_response' for ref in before)
                      or any(self.records.get(ref, {}).get('kind') != 'message'
                             or self.records[ref].get('origin') != 'model_request'
                             or self.records[ref].get('role') != 'assistant' for ref in after)):
                    problems.append(f'{pair}: 传递两端必须是模型原始 response 与后续请求中的 assistant 消息；'
                                    '调用元数据、同一实收消息或规则不是独立两端。不可见时明确缺证')
            if result['obligation_id'] == 'delivered_intact':
                finals = [self.records[ref] for ref in after if ref in self.records and self.records[ref]['kind'] == 'final']
                if not finals or any(row.get('origin') != 'http_response' for row in finals):
                    problems.append(f'{pair}: 交付端没有经来源确认的 HTTP 实收；重建输出不能冒充实收')
        return problems
