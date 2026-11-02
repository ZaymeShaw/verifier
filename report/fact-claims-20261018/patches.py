"""进程内替换的补丁，供各步脚本组合使用。正式文件不改。"""
import json
import impl.projects.llm_probe.knowledge_loop.loop as lp
import impl.projects.llm_probe.knowledge_loop.extract as ex
import impl.projects.llm_probe.eval_axes.adapters.truthfulness as tr
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.eval_axes.llm import axis_llm, merge_usage


# ---------- 第 2 步：回执 lookups + found（第一轮已过，原样沿用） ----------
FOUND_SCHEMA = {'type': 'object', 'description': '查询返回里看到了什么（只记看到的，不判对错）',
                'properties': {'object': {'type': 'boolean', 'description': '返回里有没有说法所说的那个对象（那个人、那张单、那款产品那个版本）'},
                               'attribute': {'type': 'boolean', 'description': '对象在时，返回里有没有说法说的那一项（那个字段、那条规定、那个单位）；对象不在时填 false'}},
                'required': ['object', 'attribute'], 'additionalProperties': False}


def apply_step2():
    lp._SUBMIT_PARAMETERS = {**lp._SUBMIT_PARAMETERS,
                             'properties': {**lp._SUBMIT_PARAMETERS['properties'], 'found': FOUND_SCHEMA},
                             'required': [*lp._SUBMIT_PARAMETERS['required'], 'found']}
    lp.SYSTEM = lp.SYSTEM.replace('提交：每查完一条', 'found 字段记查询返回里看到了什么：对象在不在、对象的这一项在不在；found 和 not_found 都要填，只记看到的，不判对错。\n\n提交：每查完一条')
    assert 'found 字段记' in lp.SYSTEM
    end = lp.KnowledgeLoop._end

    def end_with_receipts(self, history):
        dossier = end(self, history)
        accepted = self.checklist.accepted(history)
        by_ref = {s['call_id']: s for s in dossier['searches']}
        for item in dossier['items']:
            item['found'] = accepted[item['item_id']].args.get('found')
            item['lookups'] = [{'source': by_ref[r]['source'], 'ref': r, 'tool': by_ref[r]['tool'], 'args': by_ref[r]['args']}
                               for r in item['search_calls'] if r in by_ref]
        return dossier

    lp.KnowledgeLoop._end = end_with_receipts
    claim = tr._claim

    def claim_with_receipts(item, judged):
        return {**claim(item, judged), 'span': item.get('span'), 'lookups': item.get('lookups', []), 'found': item.get('found')}

    tr._claim = claim_with_receipts


# ---------- 第 1 步重做：说法 = 主张 + 原文片段 ----------
EXTRACT_SYSTEM_CLAIMS = (
    '提取回答中可核验的事实说法。输出对象只有 claims 一个键，不要输出 schema 里的其他词（如 required）。'
    'claims 每项只含 claim_id（唯一非空标识）、claim、span、context 四个键。'
    'span：这条说法在回答里的出处，逐字摘自 output_text 的连续原文，不改写；几条说法可以共用同一段 span。'
    'claim：主张，用一句话写清这条说法断言了什么（某一项是什么值）；可以自己组织语言，但不得包含 span 里没有的内容，不推测，不补充。'
    '没有事实说法返回 claims=[]。用户问题仅作背景。'
    '什么算一条说法：一个能拿去和原文比对的具体值——数字、期限、比例、金额、年龄、状态、日期，或明确的有/无某项责任。'
    '一句话里有几个这样的值就是几条，每条 claim 只说自己那个值及其事项。'
    '数和单位：期限、次数、年龄这类量，单位是量本身的一部分，"二十天""三十日""一次""提前一天""十八周岁"各是一条，不拆。'
    '金额、保额、保费这类数据值带的单位、币种，以及一个值带的时点（截至某日）、所属对象，各自另成一条主张，与那个数值分开，共用同一段 span。'
    '没有具体值的套话、建议、评价（如“视情况而定”“建议另行确认”“适合大多数人”）不是说法，不要抽。'
    '回答自己给内容编的序号、排列顺序、指代（如“方式一”“保单一”“第二张”“上面这张”）不是关于对象的事实，不单独抽成说法。'
    'claim 加 context 合起来要能单独成立：离开这个回答单独读，意思和在回答里一样。'
    'context 是核验这条 claim 所需的最少上下文片段列表，每段逐字摘自 output_text，只放两种：事实归属对象的标识（姓名、保单号、产品名或产品代码、办理事项的名称），'
    '和成立条件（如“犹豫期内”“非0退保金时”）；不放任何被断言的数量和属性（张数、金额、状态、日期、“投保人：某某”这类，它们是说法本身）。'
    '回答自己编的序号、指代不放进 context，换成它所指对象的标识在回答里的原文写法；回答里找不到它所指对象的标识，这条就不抽。不需要上下文就填 []。'
    '例如“甲产品投保年龄十八周岁，年交保费五千元”抽三条，context 都是[“甲产品”]：'
    'claim=“投保年龄是十八周岁” span=“投保年龄十八周岁”；claim=“年交保费的数值是五千” span=“年交保费五千元”；'
    'claim=“年交保费的单位是元” span=“年交保费五千元”。'
    '例如“乙产品在条件C下给付百分之八十”抽一条：claim=“给付比例是百分之八十” span=“给付百分之八十” context=[“乙产品”,“条件C”]。')


def parse_claims_v2(payload, output_text):
    if not isinstance(payload, dict) or payload.get('error') or not isinstance(payload.get('claims'), list):
        raise ValueError('说法提取失败：缺少 claims 列表')
    seen, result = set(), []
    plain_out = ex._plain(output_text)
    for c in payload['claims']:
        if not isinstance(c, dict):
            raise ValueError('说法必须是对象')
        key, claim, span, context = c.get('claim_id'), c.get('claim'), c.get('span'), c.get('context', [])
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError('claim_id 必须唯一且非空')
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError(f'说法 {key} 的 claim 不能为空')
        if not isinstance(span, str) or not span.strip() or ex._plain(span) not in plain_out:
            raise ValueError(f'说法 {key} 的 span {span!r} 不是 output_text 的逐字连续原文')
        if not isinstance(context, list):
            raise ValueError(f'说法 {key} 的 context 必须是字符串列表')
        bad = [x for x in context if not isinstance(x, str) or not x.strip() or ex._plain(x) not in plain_out]
        if bad:
            raise ValueError(f'说法 {key} 的 context 段 {bad[0]!r} 不是 output_text 的逐字连续原文')
        seen.add(key)
        result.append({'claim_id': key, 'claim': claim.strip(), 'span': span, 'context': [x.strip() for x in context]})
    # 隔离：context 只放定位用的对象标识；整段别的片段塞进 context 等于把整句塞回来。
    for a in result:
        for b in result:
            if b['span'] != a['span'] and any(ex._contains_value(x, b['span']) for x in a['context']):
                raise ValueError(f"说法 {a['claim_id']} 的 context 含了说法 {b['claim_id']} 的片段 {b['span']!r}，只放定位所需的上下文")
    return result


def apply_claims_extraction(counter=None):
    """提取输出 claim + span；待查项 text = 主张，span 随行到判定。counter(list) 收集被打回的原因。"""
    def parse(payload, output_text):
        try:
            return parse_claims_v2(payload, output_text)
        except ValueError as exc:
            if counter is not None:
                counter().append(str(exc)[:300])
            raise

    def extract_claims(trace, runtime, usage):
        output_text = (trace.extracted_output or {}).get('output_text')
        if not isinstance(output_text, str):
            raise ValueError('output_text 缺失或不是文本')
        client = axis_llm(runtime.spec, role='truthfulness', tools=[])
        request = trace.normalized_request or {}
        user = json.dumps({'output_text': output_text, 'question': request.get('body') or {}}, ensure_ascii=False)
        spec = StructuredOutputSpec.from_dataclass(ex.ExtractedClaims)
        try:
            try:
                claims = parse(client.complete_json(EXTRACT_SYSTEM_CLAIMS, user, trace_id=runtime.trace_id, stage='knowledge_extract',
                                                    reasoning_effort='low', output_spec=spec), output_text)
            except ValueError as exc:
                claims = parse(client.complete_json(
                    EXTRACT_SYSTEM_CLAIMS, user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出只含 claims 键的 JSON。',
                    trace_id=runtime.trace_id, stage='knowledge_extract', reasoning_effort='low', output_spec=spec), output_text)
        finally:
            merge_usage(usage, client.usage())
        return [{'item_id': c['claim_id'], 'kind': 'claim', 'text': c['claim'], 'context': c['context'], 'span': c['span']} for c in claims]

    ex.extract_claims = extract_claims
    # 轴类型在 import 时已把 knowledge_items 绑定到原函数，替换类型上的引用
    object.__setattr__(tr.AXIS_TYPE, 'knowledge_items', extract_claims)
    from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
    assert AXIS_TYPES['truthfulness'].knowledge_items is extract_claims

    tr._JUDGE_SYSTEM = tr._JUDGE_SYSTEM.replace(
        '- claim：text 是事实本身，context 是它归属的对象与成立条件；判的是「context 之下的 text」。',
        '- claim：text 是这条说法的主张，context 是它归属的对象与成立条件；判的是「context 之下的 text」。'
        'span 是这条主张在回答里的原文出处，只用来理解主张说的是什么；同一段 span 可能还对应别的主张，span 里主张没说到的内容不判。')
    assert 'span 是这条主张' in tr._JUDGE_SYSTEM

    def judge_with_span(item, guidance, notes, runtime, usage):
        """同 truthfulness._judge，claim 里多带 span。"""
        citations = [{'id': i, 'tool': c.get('tool'), 'args': c.get('args'), 'quote': c['quote'], 'window': c['window']}
                     for i, c in enumerate(item['citations'])]
        cited = {c['source'] for c in item['citations']}
        user = json.dumps({'claim': {'text': item['text'], 'context': item['context'], 'span': item.get('span')}, 'citations': citations,
                           'search_note': item.get('note', ''),
                           'source_notes': {uri: text for uri, text in notes.items() if uri in cited and text},
                           'guidance': guidance}, ensure_ascii=False)
        spec = StructuredOutputSpec.from_dataclass(tr.ClaimVerdict, required_nonempty=['verdict', 'reason'])
        client = axis_llm(runtime.spec, role='truthfulness', tools=[])
        try:
            try:
                return tr._judgement(client.complete_json(tr._JUDGE_SYSTEM, user, trace_id=runtime.trace_id, stage='truthfulness_judge',
                                                          reasoning_effort='low', output_spec=spec), len(citations))
            except ValueError as exc:
                return tr._judgement(client.complete_json(
                    tr._JUDGE_SYSTEM, user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出。',
                    trace_id=runtime.trace_id, stage='truthfulness_judge', reasoning_effort='low', output_spec=spec), len(citations))
        finally:
            merge_usage(usage, client.usage())

    tr._judge = judge_with_span
