"""冻结 llmtracing 对话稿的只读工具与引用检查；不枚举 Agno 环节、不调用业务。"""
from __future__ import annotations

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

    def validate(self, results: list[dict], obligations: Mapping[str, Any], readable: set[str]) -> list[str]:
        problems = []
        special = {'case'} | {key for key in obligations if key.startswith('project:')}
        for result in results:
            pair = f"{result['obligation_id']} @ {result['link_id']}"
            ob = obligations[result['obligation_id']]
            before, after = result['evidence']['input'], result['evidence']['output']
            refs = result['source_refs'] + before + after
            unread = [ref for ref in refs if ref not in readable and ref not in special]
            if unread:
                problems.append(f'{pair}: 引用没有此前批次的完整正文回执：{unread}；读取、补齐分页或改用有证据的结论')
            status = result['outcome']
            if status in {'pass', 'not_applicable'} and not (before or after):
                problems.append(f'{pair}: 缺少支撑结论的引用')
            if status == 'fail' and not (before and after):
                problems.append(f'{pair}: fail 需要两端证据；不可见时可以明确缺证')
            if status in {'pass', 'fail'} and ob.source in {'trace', 'case'} and not result['source_refs']:
                problems.append(f'{pair}: 没有规则出处')
            if status not in {'pass', 'fail'}:
                continue
            call = '.'.join(result['link_id'].split('.')[:2])
            if ob.link_type == 'μ':
                row = self.records.get(call, {})
                own = set(row.get('input_refs', []))
                outside = [ref for ref in result['source_refs'] + before if ref not in own]
                if not own or outside:
                    problems.append(f'{pair}: 引用不属于该次已记录输入：{outside}；用 call_inputs 核对，不能只按先后位置猜继承')
                if any(ref != f'{call}.response' for ref in after) or not after:
                    problems.append(f'{pair}: 模型输出端只能引用该次 response；不同调用请分别提交')
            if result['obligation_id'] == 'arrives_intact':
                received = [ref for ref in after if self.records.get(ref, {}).get('origin') == 'model_received_tool_result']
                if received:
                    # 本 provider 没有工具执行侧的原始产出，工具请求不能充当该端。
                    problems.append(f'{pair}: {received} 只证明模型收到的工具消息，快照没有独立工具原始产出；'
                                    '工具调用参数不是传递前的产出，不能据此证明无损。可核对其他有两端的边界或明确缺证')
            if result['obligation_id'] == 'delivered_intact':
                finals = [self.records[ref] for ref in after if ref in self.records and self.records[ref]['kind'] == 'final']
                if not finals or any(row.get('origin') != 'http_response' for row in finals):
                    problems.append(f'{pair}: 交付端没有经来源确认的 HTTP 实收；重建输出不能冒充实收')
        return problems
