"""真实性：隔离提取与逐断言核验，程序汇总，不向核验阶段泄露整份回答。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.material_tools import verify_quote as verify_material_quote
from impl.projects.llm_probe.text_carrier import _TOOL_CALL_LIMIT
from ..llm import axis_llm, merge_usage
from ..sources import expand_sources, build_tools
from ..sources.es_tools import EsTools
from ..types import AxisTimeout, AxisType, AxisSummary, ExecutionLimits, Field, Input, RunOutcome, Verdict


@dataclass
class ExtractedClaims:
    claims: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ClaimVerdict:
    verdict: str = ''
    reason: str = ''
    citations: list[dict[str, str]] = field(default_factory=list)


_VERDICTS = ('verified', 'refuted', 'unverifiable')
_EXTRACT_SYSTEM = ('提取回答中可核验的事实断言。输出对象只有 claims 一个键，不要输出 schema 里的其他词（如 required）。'
                   'claims 每项只含 claim_id（唯一非空标识）、text、context 三个键；text 和 context 里的每一段都必须逐字摘自 output_text 的连续原文。'
                   '不改写，不推测；没有事实断言返回 claims=[]。用户问题仅作背景。'
                   '什么算一条断言：一个能拿去和条款原文比对的具体值——数字、期限、比例、金额、年龄，或明确的有/无某项责任。'
                   '一句话里有几个这样的值就拆几条，每条 text 只含自己那个值及其事项；'
                   '没有具体值的套话、建议、评价（如“视情况而定”“建议另行确认”“适合大多数人”）不是断言，不要抽。'
                   'context 是核验这条 text 所需的最少上下文片段列表：事实归属的对象（通常是产品名）、以及成立条件；'
                   '只放定位所需，不放整句，不放别的断言里的值；不需要上下文就填 []。'
                   '例如“甲产品投保年龄十八周岁，年交保费五千元”抽两条：text=“投保年龄十八周岁” context=[“甲产品”]；'
                   'text=“年交保费五千元” context=[“甲产品”]。'
                   '例如“乙产品在条件C下给付百分之八十”抽一条：text=“给付百分之八十” context=[“乙产品”,“条件C”]。')
_VERIFY_SYSTEM = f'''核验这一条断言：资料中能否找到支持或反驳它的原文？
断言分 text（事实本身）和 context（它归属的对象与成立条件，如产品名、适用条件），核验的是「context 之下的 text」：
命中的原文必须属于同一个对象、同一条件，其他产品的同类条款不能拿来支持或反驳；context 为空时按 text 核验。
只使用给定知识源与工具，不依赖记忆。verified=原文支持；refuted=原文矛盾；unverifiable=找不到支持或反驳原文。
输出 verdict/reason/citations，reason 必须非空。verified 和 refuted 必须引用；unverifiable 时 citations 必须是 []，
不要为了佐证"没找到"去 read 无关条款——检索过哪些词、为何不相关写进 reason 即可。
引用每项只含三个键 source/ref/note（键名固定，不要写成 locator）：source 是给定的 material:// 或 es:// URI；
ref 填工具返回的 locator 值（形如 文档ID#字段）；note 是该位置逐字原文。
知识源的字段骨架（outline）已随本消息给出，不必再调 outline。
search 的语义：空白分隔多个词，每个词按子串匹配（文本字段找连续原文，keyword 字段如产品名做包含匹配），
任一词命中即返回，命中词多者排前，每条 hit 带 matched 说明命中了哪些词。零命中就是知识库里没有这个词，可以相信。
流程：用「产品名 条款事项」search → 看 matched：两者都命中就 read 精读；只命中产品名说明该产品没有此条款事项；
再用条款事项单独 search 一次确认，仍无相关命中即返回 unverifiable，reason 写明检索了哪些词。
数字写法在原文里可能不同：阿拉伯数字与中文数字、%与百分之、天与日、万与万元互为等价。
搜数字零命中时，换另一种写法再搜一次；两种写法都零命中才算知识库没有。核验时等价写法视为一致，不算矛盾。
工具预算共 {_TOOL_CALL_LIMIT} 次，超出即本次作废；一般 2–4 次就该出结论。
检索片段不代替原文，引用前必须 read 到原文；工具报错（不是零命中）不能冒充 unverifiable。'''


def _claims(payload, output_text):
    if not isinstance(payload, Mapping) or payload.get('error') or not isinstance(payload.get('claims'), list):
        raise ValueError('断言提取失败：缺少 claims 列表')
    seen = set()
    result = []
    for claim in payload['claims']:
        if not isinstance(claim, Mapping):
            raise ValueError('断言必须是对象')
        key, text, context = claim.get('claim_id'), claim.get('text'), claim.get('context', [])
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError('claim_id 必须唯一且非空')
        if not isinstance(text, str) or not text.strip() or text not in output_text:
            raise ValueError('断言 text 必须逐字来自 output_text')
        if not isinstance(context, list) or any(not isinstance(c, str) or not c.strip() or c not in output_text for c in context):
            raise ValueError('断言 context 每段必须逐字来自 output_text')
        seen.add(key)
        result.append({'claim_id': key, 'text': text, 'context': [c.strip() for c in context]})
    # 防偷懒：context 只许带定位所需的上下文，带了别条断言的值就等于把整句塞回来，隔离失效。
    for claim in result:
        for other in result:
            if other is claim:
                continue
            leaked = [c for c in claim['context'] if other['text'] in c]
            if leaked:
                raise ValueError(f"断言 {claim['claim_id']} 的 context {leaked[0]!r} 含了断言 {other['claim_id']} 的值 {other['text']!r}，只放定位所需的上下文")
    return result


def _claim_label(claim):
    """展示用：context 段已含在 text 里就不重复。"""
    text = claim['text']
    extra = [c for c in claim.get('context') or [] if c not in text]
    return text if not extra else '·'.join(extra) + '：' + text


def _verify_result(payload, catalog, description, receipts):
    if not isinstance(payload, Mapping):
        raise ValueError('断言核验模型调用失败（无返回）')
    if payload.get('error'):
        # 带上错误码和原因：重试反馈给模型看（预算超了要早停），汇总给人看（不是一句黑盒失败）。
        detail = str(payload.get('raw_text') or '').strip()[:200]
        raise ValueError(f"断言核验模型调用失败（{payload['error']}）" + (f'：{detail}' if detail else ''))
    verdict, reason = payload.get('verdict'), payload.get('reason')
    citations = payload.get('citations')
    if verdict not in _VERDICTS or not isinstance(reason, str) or not reason.strip() or not isinstance(citations, list):
        raise ValueError('核验结果缺少合法 verdict/reason/citations')
    if verdict != 'unverifiable' and not citations:
        raise ValueError('verified/refuted 必须带引用')
    if any(receipt.get('error') for receipt in receipts):
        raise ValueError('知识源工具调用失败')
    if verdict == 'unverifiable':
        # "没找到"的证据在 reason 里；顺手附上的无关条款不是证据，不回读、不落盘。
        return {'verdict': verdict, 'reason': reason, 'citations': []}
    es_catalog = [c for c in catalog if c.get('source') == 'es']
    cleaned = []
    for citation in citations:
        if not isinstance(citation, Mapping) or any(not isinstance(citation.get(k), str) or not citation[k].strip() for k in ('source', 'ref', 'note')):
            raise ValueError('引用必须带 source/ref/note')
        source, ref, note = (citation[k] for k in ('source', 'ref', 'note'))
        if source.startswith('es://'):
            ok = bool(es_catalog) and EsTools(es_catalog, receipts).verify_quote(source[5:], ref, note)
        elif source.startswith('material://') and '{' + source + '}' in description:
            parts = source[len('material://'):].split('/')
            ok = len(parts) == 2 and verify_material_quote(parts[0], parts[1], ref, note)
        else:
            ok = False
        if not ok:
            raise ValueError(f'引用回读核验失败: {source}#{ref}')
        cleaned.append({'source': source, 'ref': ref, 'note': note})
    return {'verdict': verdict, 'reason': reason, 'citations': cleaned}


def _outline_sources(catalog):
    """ES 知识源的字段骨架，随首轮消息给模型。outline 出错直接抛：知识源不可用不该伪装成 unverifiable。"""
    es_catalog = [c for c in catalog if c.get('source') == 'es']
    if not es_catalog:
        return []
    receipts: list[dict[str, Any]] = []
    tools = EsTools(es_catalog, receipts)
    outline = [tools.es_outline(c['uri'][len('es://'):]) for c in es_catalog]
    failed = [r['error'] for r in receipts if r.get('error')]
    if failed:
        raise ValueError('知识源 outline 失败：' + '；'.join(failed))
    return outline


def _outcome(claims, extracted, catalog, errors, usage):
    coverage = {'extracted': extracted, **{v: sum(c['verdict'] == v for c in claims) for v in _VERDICTS}}
    # key 放断言原文而不是 claim_id：表格和导出里读者要看的是"哪句话"，id 只对机器有意义。
    items = [{'key': _claim_label(c), 'value': c['verdict'], 'reason': c['reason'], 'claim_id': c['claim_id'], 'citations': c['citations']} for c in claims]
    groups = []
    for verdict in ('refuted', 'unverifiable', 'verified'):
        lines = [f"{c['claim_id']}（{c['reason']}）" for c in claims if c['verdict'] == verdict]
        if lines:
            groups.append('$' + verdict + '\n' + '\n'.join(lines))
    text = '\n\n'.join(groups) or ('真实性核验失败' if errors else '回答不含可核验的事实断言')
    sources = [{'uri': c['uri'], 'snapshot_id': c.get('snapshot_id') or c.get('sha256', '')} for c in catalog]
    output = {'claims': claims, 'sources': sources, 'coverage': coverage, 'errors': errors}
    return RunOutcome(output=output, summary=AxisSummary(text, items), failed=bool(errors),
                      failure_reason='；'.join(e['last_error'] for e in errors), usage=usage)


def run_truthfulness(inputs, axis, runtime):
    trace = inputs['trace']
    output_text = (trace.extracted_output or {}).get('output_text')
    usage: dict[str, Any] = {'llm_calls': 0, 'tool_calls': 0}
    errors, completed, catalog = [], [], []
    extracted = []
    try:
        if not isinstance(output_text, str):
            raise ValueError('output_text 缺失或不是文本')
        # 第一阶段只带回答和问题背景；无工具、无框描述、无知识源。
        client = axis_llm(runtime.spec, role='truthfulness', tools=[])
        request = trace.normalized_request or {}
        extract_user = json.dumps({'output_text': output_text, 'question': request.get('body') or {}}, ensure_ascii=False)
        extract_spec = StructuredOutputSpec.from_dataclass(ExtractedClaims)
        try:
            # 提取是逐字摘抄，不需要深推理；核验同理（与生产轴2一致用 low）。
            try:
                payload = client.complete_json(_EXTRACT_SYSTEM, extract_user, trace_id=runtime.trace_id,
                                               stage='truthfulness_extract', reasoning_effort='low', output_spec=extract_spec)
                extracted = _claims(payload, output_text)
            except ValueError as exc:
                # 与生产 judge 同一做法：结构或逐字/隔离校验被阻断只做一次带具体错误的修复，不是语义重试。
                payload = client.complete_json(
                    _EXTRACT_SYSTEM, extract_user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出只含 claims 键的 JSON。',
                    trace_id=runtime.trace_id, stage='truthfulness_extract', reasoning_effort='low', output_spec=extract_spec)
                extracted = _claims(payload, output_text)
        finally:
            merge_usage(usage, client.usage())
        if not extracted:
            return _outcome([], 0, [], [], usage)
        description, catalog = expand_sources(axis.description, material_catalog=True)
        # 首轮上下文就把知识源骨架给全：模型不用花一次工具调用去 outline，也一开始就知道产品名在哪个字段。
        outline = _outline_sources(catalog)
        # 每个断言/每次重试用独立客户端；反馈只含本断言的核验错误。
        for claim in extracted:
            feedback = ''
            last_error = ''
            for attempt in range(2):
                receipts = []
                client = None
                try:
                    # 到点就不再开新的核验调用；已核验完的断言保留在结果里作诊断。
                    runtime.ensure_time_left(f"断言 {claim['claim_id']}")
                    tools = build_tools(catalog, receipts)
                    client = axis_llm(runtime.spec, role='truthfulness', tools=tools, tool_call_limit=_TOOL_CALL_LIMIT if tools else None)
                    payload = client.complete_json(
                        _VERIFY_SYSTEM,
                        json.dumps({'claim': claim, 'description': description, 'catalog': catalog, 'outline': outline, 'feedback': feedback}, ensure_ascii=False),
                        trace_id=runtime.trace_id, stage='truthfulness_verify', reasoning_effort='low',
                        output_spec=StructuredOutputSpec.from_dataclass(ClaimVerdict, required_nonempty=['verdict', 'reason']),
                    )
                    verdict = _verify_result(payload, catalog, axis.description, receipts)
                    completed.append({**claim, **verdict})
                    break
                except AxisTimeout as exc:
                    usage['timed_out'] = True
                    errors.append({'claim_id': claim['claim_id'], 'last_error': str(exc), 'attempts': attempt})
                    break
                except Exception as exc:
                    last_error = str(exc)
                    feedback = '上次核验失败，请修正：' + last_error
                finally:
                    usage['tool_calls'] += len(receipts)
                    if client is not None:
                        merge_usage(usage, client.usage())
            else:
                errors.append({'claim_id': claim['claim_id'], 'last_error': last_error, 'attempts': 2})
            if usage.get('timed_out'):
                break
    except Exception as exc:
        errors.append({'claim_id': '', 'last_error': str(exc)})
    return _outcome(completed, len(extracted), catalog, errors, usage)


AXIS_TYPE = AxisType(
    type_id='truthfulness', title='真实性', summary='从回答里提取事实断言，逐条对照知识库核验',
    verdict_scope='item', verdict_enum=(Verdict('verified', '知识库中有原文支持该断言'), Verdict('refuted', '知识库原文与该断言矛盾'), Verdict('unverifiable', '知识库中找不到能支持或反驳的原文')),
    item_path='claims[].verdict', depend_on=(), trigger_when=None, inputs=(Input('trace', 'sample.trace'),),
    output_fields=('claims', 'sources', 'coverage', 'errors'), scenario_fields=(Field('description', expand='catalog'),),
    # seconds 先放宽：逐断言核验本来就慢，上限只为兜住失控，不为常态。
    limits=ExecutionLimits(tool_calls=_TOOL_CALL_LIMIT, seconds=900), run=run_truthfulness,
    implementation_files=('impl/projects/llm_probe/eval_axes/adapters/truthfulness.py', 'impl/projects/llm_probe/eval_axes/sources/__init__.py', 'impl/projects/llm_probe/eval_axes/sources/es_client.py', 'impl/projects/llm_probe/eval_axes/sources/es_tools.py'),
)
