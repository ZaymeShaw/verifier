"""出清单：核对说法类待查项 = 回答里的事实说法（主张 + 逐字原文片段）。

一次独立模型调用，只看回答和用户问题：不看知识库，就没有理由漏掉难查的。程序只挡"抽错"（改写、编造、夹带），
挡不住"抽漏"；漏抽率由验收样本量化（demand/claims.md §9）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping

from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.eval_axes.llm import axis_llm, merge_usage


@dataclass
class ExtractedClaims:
    claims: list[dict[str, str]] = field(default_factory=list)


EXTRACT_SYSTEM = ('提取回答中的事实说法（demand/claims.md §2）。输出对象只有 claims 一个键，不要输出 schema 里的其他词（如 required）。'
                  'claims 每项只含 claim_id（唯一非空标识）、claim、span、context、qualifies 五个键。'
                  '什么算一条说法：回答断言的、能单独为真或为假的一个主张——某对象的某一项是什么、有没有某项、满足什么条件。'
                  '不限于带数字的：定性的断言（某产品含不含某项责任、某事项要不要某材料、某规定是否存在）也是说法。'
                  '一句话里有几个这样的主张就是几条，每条 claim 只说自己那一个。'
                  '回答断言某对象没有某项、或对象不存在，也是说法：claim 写成"某对象没有某项"或"某对象不存在"，核的是事实本身，不是回答者那次查到了什么。'
                  '不是说法：没有断言的套话、建议、评价、客套；回答者只描述自己做了什么（查了几次、调了什么）；回答自己给内容编的序号、排列、指代。'
                  'span：这条说法在回答里的出处，逐字摘自 output_text 的连续原文，不改写；几条说法可以共用同一段 span。'
                  'claim：用一句话写清断言了什么；可以自己组织语言，但除了 context 里的对象和条件，不得包含 span 里没有的内容，不推测，不补充。'
                  'claim 加 context 合起来要能单独成立：离开这个回答单独读，意思和在回答里一样；不要把一个主张切成单独读不成立的碎片。'
                  '数和单位：期限、次数、年龄这类量，单位是量本身的一部分，不拆。'
                  '一个数据值带的单位、币种、时点（截至某日）、所属对象，各自另成一条说法，与那个数值分开，共用同一段 span；'
                  '这类说法的 qualifies 填它所修饰的那条数值说法的 claim_id，其余说法 qualifies 填空字符串。'
                  'context 是核验这条 claim 所需的最少上下文片段列表，每段逐字摘自 output_text 或用户问题（question）的连续原文，回答里没有时从用户问题里摘，'
                  '只放两种：事实归属对象的标识（姓名、编号、产品名或代码、事项名称），和成立条件；不放任何被断言的数量和属性（它们是说法本身）。'
                  '对象和条件只出现在用户问题里时，照样抽这条说法，context 从问题里摘。'
                  '回答自己编的序号、指代不放进 context，换成它所指对象的标识在回答里的原文写法；回答和用户问题里都找不到它所指对象的标识，这条才不抽。'
                  '不需要上下文就填 []。question 是用户各轮原话，按先后排列，output_text 回答的是最后一轮；用户问题仅作背景。没有说法返回 claims=[]。'
                  '例如问"甲商品退货期限多长？"、回答"七天，需保留包装"：两条，context 都是["甲商品"]（摘自问题）——'
                  'claim="退货期限是七天" span="七天"；claim="退货需保留包装" span="需保留包装"。'
                  '例如"乙账户截至3月1日余额1200元"：claim="余额的数值是1200"（c1）；claim="余额的单位是元" qualifies=c1；'
                  'claim="余额的时点是截至3月1日" qualifies=c1；三条共用 span，context=["乙账户"]。')


_FORMAT = re.compile(r'[\s*`]+')


def _contains_value(segment: str, value: str) -> bool:
    """segment 里有没有 value 这个值：出现在一串字母数字中间的不算（保单号里的“0”不是金额“0”）。"""
    edge = re.compile(r'[A-Za-z0-9]')
    start = segment.find(value)
    while start >= 0:
        end = start + len(value)
        inside = (start > 0 and edge.match(segment[start - 1]) and edge.match(value[0])) or \
                 (end < len(segment) and edge.match(segment[end]) and edge.match(value[-1]))
        if not inside:
            return True
        start = segment.find(value, start + 1)
    return False


_QUOTES = str.maketrans({c: '"' for c in '“”„‟＂「」『』'} | {c: "'" for c in '‘’‚‛＇'})


def _plain(text):
    """逐字比对前去掉空白和 Markdown 强调符、统一引号：回答常带 **加粗**，格式符不是内容，模型摘句不带它们；
    直引号和弯引号模型常互换（回答写 "交费有效"，摘句成 “交费有效”），引号形状不是内容。改字仍判不是原文。"""
    return _FORMAT.sub('', text).translate(_QUOTES)


def _answer_texts(output_text: str) -> tuple[str, ...]:
    """逐字比对的对象：回答原文；回答是 JSON 时再加上各字符串字段解码后的文字（原文里引号、换行是 \\" \\n 转义，模型摘的是解码后的字）。"""
    try:
        parsed = json.loads(output_text)
    except ValueError:
        return (_plain(output_text),)
    leaves, stack = [], [parsed]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            leaves.append(node)
        elif isinstance(node, Mapping):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return (_plain(output_text), *(_plain(leaf) for leaf in leaves))


def _in(segment: str, texts: tuple[str, ...]) -> bool:
    return any(_plain(segment) in text for text in texts)


def parse_claims(payload: Any, output_text: str, question: str = '') -> list[dict[str, Any]]:
    """说法 = 主张 + 原文片段（demand/claims.md §2.1）：span 须逐字出自回答，可几条共用；claim 自由写，程序不查逐字；
    context 可逐字出自回答或用户问题（对象、条件常只在问题里，C8）。"""
    if not isinstance(payload, Mapping) or payload.get('error') or not isinstance(payload.get('claims'), list):
        raise ValueError('说法提取失败：缺少 claims 列表')
    answer, asked = _answer_texts(output_text), (_plain(question),)
    seen = set()
    result = []
    for claim in payload['claims']:
        if not isinstance(claim, Mapping):
            raise ValueError('说法必须是对象')
        key, text, span, context = claim.get('claim_id'), claim.get('claim'), claim.get('span'), claim.get('context', [])
        qualifies = claim.get('qualifies') or ''
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError('claim_id 必须唯一且非空')
        # 报错点名是哪条、哪一段：修复轮只拿到报错，不点名模型无从改起。
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'说法 {key} 的 claim 不能为空')
        if not isinstance(span, str) or not span.strip() or not _in(span, answer):
            raise ValueError(f'说法 {key} 的 span {span!r} 不是 output_text 的逐字连续原文')
        if not isinstance(context, list):
            raise ValueError(f'说法 {key} 的 context 必须是字符串列表')
        bad = [c for c in context if not isinstance(c, str) or not c.strip()
               or not (_in(c, answer) or _in(c, asked))]
        if bad:
            raise ValueError(f'说法 {key} 的 context 段 {bad[0]!r} 既不是 output_text 也不是用户问题的逐字连续原文')
        if not isinstance(qualifies, str):
            raise ValueError(f'说法 {key} 的 qualifies 必须是字符串')
        seen.add(key)
        result.append({'claim_id': key, 'claim': text.strip(), 'span': span, 'context': [c.strip() for c in context],
                       'qualifies': qualifies.strip()})
    # 单位、币种、时点修饰的是同一回答里的一条数值说法（demand/claims.md §2.3）。
    for claim in result:
        if claim['qualifies'] and (claim['qualifies'] == claim['claim_id'] or claim['qualifies'] not in seen):
            raise ValueError(f"说法 {claim['claim_id']} 的 qualifies {claim['qualifies']!r} 不是另一条说法的 claim_id")
    # 防偷懒：context 只许带定位所需的上下文，带了别条说法的片段就等于把整句塞回来，隔离失效。共用片段的说法之间不算。
    for claim in result:
        for other in result:
            if other['span'] == claim['span']:
                continue
            # 段与别条片段完全相同：那条说法断言的就是这个标识（如产品名），这里拿它定位，不算塞整句。
            leaked = [c for c in claim['context'] if _plain(c) != _plain(other['span']) and _contains_value(c, other['span'])]
            if leaked:
                raise ValueError(f"说法 {claim['claim_id']} 的 context {leaked[0]!r} 含了说法 {other['claim_id']} 的片段 {other['span']!r}，只放定位所需的上下文")
    return result


def user_turns(trace: Any) -> list[str]:
    """用户各轮原话，按先后排列。多轮时 normalized_request 只是第一轮，后面的更正、追问在对话记录里（demand/expectations.md §1）；
    没有对话记录时取请求体里的用户消息（DashScope 形状在 input.messages，其余在 messages）。"""
    turns = [str(m.get('query') or m.get('content') or '') for m in getattr(trace, 'conversation_transcript', None) or []
             if isinstance(m, Mapping) and m.get('role') == 'user']
    if turns:
        return turns
    body = (getattr(trace, 'normalized_request', None) or {}).get('body') or {}
    messages = (body.get('input') or {}).get('messages') if isinstance(body.get('input'), Mapping) else body.get('messages')
    return [str(m.get('content') or '') for m in messages or [] if isinstance(m, Mapping) and m.get('role') == 'user']


def extract_claims(trace: Any, runtime: Any, usage: dict[str, Any]) -> list[dict[str, Any]]:
    """真实性的待查项来源。失败抛 ValueError（轴记失败，不当作"没有断言"）。"""
    output_text = (trace.extracted_output or {}).get('output_text')
    if not isinstance(output_text, str):
        raise ValueError('output_text 缺失或不是文本')
    client = axis_llm(runtime.spec, role='truthfulness', tools=[])
    turns = user_turns(trace)
    user = json.dumps({'output_text': output_text, 'question': turns}, ensure_ascii=False)
    question = '\n'.join(turns)
    spec = StructuredOutputSpec.from_dataclass(ExtractedClaims)
    try:
        # 提取是逐字摘抄，不需要深推理。
        try:
            claims = parse_claims(client.complete_json(EXTRACT_SYSTEM, user, trace_id=runtime.trace_id, stage='knowledge_extract',
                                                       reasoning_effort='low', output_spec=spec), output_text, question)
        except ValueError as exc:
            # 结构或逐字/隔离校验被阻断只做一次带具体错误的修复，不是语义重试。
            claims = parse_claims(client.complete_json(
                EXTRACT_SYSTEM, user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出只含 claims 键的 JSON。',
                trace_id=runtime.trace_id, stage='knowledge_extract', reasoning_effort='low', output_spec=spec), output_text, question)
    finally:
        merge_usage(usage, client.usage())
    # 待查项 text 是主张；span 随行到判定，取证不看（loop 的待查清单只列 text/context）。
    return [{'item_id': c['claim_id'], 'kind': 'claim', 'text': c['claim'], 'context': c['context'], 'span': c['span'],
             'qualifies': c['qualifies']} for c in claims]
