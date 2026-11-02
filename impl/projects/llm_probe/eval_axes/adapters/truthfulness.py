"""真实性：读知识案卷，逐条判定回答里的说法与取回的原文是否一致；不抽取、不检索。

待查项由本轴声明的来源（knowledge_loop.extract.extract_claims）交给知识查证轴，查证只取证；
这里只看每条的引用原文及其前后窗口，判 verified / refuted / unverifiable（spec/alg/knowledge-evidence.md §5）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.knowledge_loop.extract import extract_claims
from impl.projects.llm_probe.knowledge_loop.loop import FOUND
from ..llm import axis_llm, merge_usage
from ..types import AxisTimeout, AxisType, AxisSummary, Dependency, ExecutionLimits, Field, Input, RunOutcome, Verdict
from .knowledge_evidence import item_label


@dataclass
class ClaimVerdict:
    # reason 在前：先写比对，再落结论；实测 verdict 在前时出现过「理由写支持、结论填 refuted」。
    reason: str = ''
    verdict: str = ''
    basis: list[int] = field(default_factory=list)
    gap: str = field(default='', metadata={'allow_empty': True,
                     'description': 'unverifiable 时必填：object_absent / item_absent / mismatch；其余为空字符串'})


_VERDICTS = ('verified', 'refuted', 'unverifiable')
# 查不到缺的是哪一格（demand/claims.md §3.3）：对象不在、对象在而这一项不在、原文对不上（对象或口径不符、没读全、没有算法）。
_GAPS = ('object_absent', 'item_absent', 'mismatch')
_JUDGE_SYSTEM = '''判定回答里的一条说法是否属实：拿它和知识源取回的原文比对。原文是查证阶段取回的，你不需要也不能再检索。

输入：
- claim：text 是这条说法的主张，context 是它归属的对象与成立条件；判的是「context 之下的 text」。
  span 是这条主张在回答里的原文出处，只用来理解主张说的是什么；同一段 span 可能还对应别的主张，span 里主张没说到的内容不判。
- citations：编号列表。每项 tool/args 是取回这段原文的那次查询（查的哪个工具、按什么条件查的），
  quote 是摘出的原文，window 是 quote 所在的整条记录或前后上下文。
- search_note：查证人的检索说明（查了什么、结果全不全），不含结论。
- source_notes：知识源登记方写的读法说明（字段含义、数据怎么读）。
- guidance：场景补充的判定口径，可能为空。

先拆说法：context 给出对象与成立条件，text 给出属性与值。合起来是「某对象（在某条件下）的某属性 = 某值」。
说法若只是回答自己的编号、排序、指代，不是任何对象的属性，直接 unverifiable。

原文里的话按作用分三种：
① 关于对象的事实：某个对象的某个属性是什么值——数据记录里的字段值，条款与业务规定（如"犹豫期二十日""退保需提交申请书"）。
② 数据怎么读：说明数据本身——字段是什么意思、属于谁、按什么口径、单位、结果全不全（数据里的总数与已读条数也是这一种）。
③ 对使用者的要求：告诉回答者该怎么写、能不能怎么展示。
只有 ① 能定对错；② 用来确定 ① 说的是哪个对象、哪个属性、什么口径；③ 与对错无关。

用 ② 读 ①：
- 对象：数据属于按哪个对象查回来的（看 args；姓名是密文时也按此归属）、属于哪条记录。
  对象的组成部分（客户名下某张保单、保单里某一行险种）不是对象本身。
- 属性：字段、术语的含义以 ② 为准；② 没说的含义不凭常识认定。
- 算出来的值：原文写明了算法（字段说明、知识库文档），或说法自己写明了用哪些数怎么算，才照算法用 ① 的数算出这个值；
  没有算法，就是 ① 没有给出这个值（不要凭常识假设"总额=名下全部相加"）。
- 全不全：属性涉及"全部"（共几张、全部合计）时，按 ② 判断 ① 是否读全；总数与已读条数相等就是读全了。

结论：
- verified：① 里有同一对象、同一属性、同一条件下的值，与说法的值一致。
- refuted：① 里有同一对象、同一属性、同一条件下的值，与说法的值不同。reason 里写出原文给的那个值。
- unverifiable：① 里没有同一对象、同一属性、同一条件下的值——对象或口径对不上、没有算法、没读全，
  或说法的值比原文多出原文没给的部分（多出的部分既不能确认也不冲突）。
② 和 ③ 不给任何对象的属性赋值，不能作为 refuted 的依据。
说法断言某对象没有某项、或对象不存在时：
- ① 里有同一对象的这一项（有值）→ refuted，reason 写出原文给的值；
- ② 明确表明按这个对象查过、结果读全了，而对象不存在、或对象在但没有这一项 → verified；
- 查回来的是别的对象、没读全、或没有按这个对象查 → unverifiable：没查到不等于不存在。
反过来，说法断言某对象的某项是某值，而 ② 明确表明按这个对象查过、结果读全了、对象本身不存在 → refuted：
对象都不存在，它的任何值都不成立，reason 写明查询结果为空（demand/claims.md §3：对象本身不存在也是有矛盾）。对象在、只是没有这一项时仍是 unverifiable。
值一致的判断：阿拉伯数字与中文数字、%与百分之、天与日、万与万元互为等价写法。
知识库对同一事项有互相矛盾的说法时，不替知识库裁定：说法与其中一种一致即 verified，reason 写明另有不同说法及其原文。

输出 reason/verdict/basis/gap：先在 reason 写原文怎么说、与说法是否一致，再按 reason 的结论填 verdict，两者不得矛盾。
basis 是作为依据的 citations 编号：verified 和 refuted 必须至少一个；unverifiable 时为 []。
gap 只在 unverifiable 时填，写缺的是哪一格：object_absent = 原文里没有这个对象；item_absent = 对象在，没有这一项；
mismatch = 原文对不上（对象或口径不符、没读全、没有算法）。其余结论 gap 为空字符串。'''


def _judgement(payload: Any, count: int) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError('判定模型调用失败（无返回）')
    if payload.get('error'):
        detail = str(payload.get('raw_text') or '').strip()[:200]
        raise ValueError(f"判定模型调用失败（{payload['error']}）" + (f'：{detail}' if detail else ''))
    verdict, reason, basis, gap = payload.get('verdict'), payload.get('reason'), payload.get('basis'), payload.get('gap') or ''
    if verdict not in _VERDICTS or not isinstance(reason, str) or not reason.strip() or not isinstance(basis, list):
        raise ValueError('判定结果缺少合法 verdict/reason/basis')
    if (verdict == 'unverifiable') != (gap in _GAPS):
        raise ValueError(f'unverifiable 时 gap 必须是 {"/".join(_GAPS)} 之一，其余结论 gap 为空字符串')
    if any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < count for i in basis):
        raise ValueError(f'basis 只能是 citations 的编号 0..{count - 1}')
    if verdict != 'unverifiable' and not basis:
        raise ValueError('verified/refuted 必须在 basis 里给出依据的引用编号')
    return {'verdict': verdict, 'reason': reason, 'basis': sorted(set(basis)) if verdict != 'unverifiable' else [], 'gap': gap}


def _judge(item, guidance, notes, runtime, usage):
    citations = [{'id': i, 'tool': c.get('tool'), 'args': c.get('args'), 'quote': c['quote'], 'window': c['window']}
                 for i, c in enumerate(item['citations'])]
    cited = {c['source'] for c in item['citations']}
    user = json.dumps({'claim': {'text': item['text'], 'context': item['context'], 'span': item['span']}, 'citations': citations,
                       'search_note': item.get('note', ''),
                       'source_notes': {uri: text for uri, text in notes.items() if uri in cited and text},
                       'guidance': guidance}, ensure_ascii=False)
    spec = StructuredOutputSpec.from_dataclass(ClaimVerdict, required_nonempty=['verdict', 'reason'])
    client = axis_llm(runtime.spec, role='truthfulness', tools=[])
    try:
        try:
            return _judgement(client.complete_json(_JUDGE_SYSTEM, user, trace_id=runtime.trace_id, stage='truthfulness_judge',
                                                   reasoning_effort='low', output_spec=spec), len(citations))
        except ValueError as exc:
            # 结构不合规只做一次带具体错误的修复，不是语义重试。
            return _judgement(client.complete_json(
                _JUDGE_SYSTEM, user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出。',
                trace_id=runtime.trace_id, stage='truthfulness_judge', reasoning_effort='low', output_spec=spec), len(citations))
    finally:
        merge_usage(usage, client.usage())


def _claim(item, judged):
    cited = [item['citations'][i] for i in judged['basis']]
    return {'claim_id': item['item_id'].split(':', 1)[1], 'text': item['text'], 'span': item['span'], 'context': item['context'],
            'qualifies': item.get('qualifies') or '',
            'verdict': judged['verdict'], 'reason': judged['reason'], 'gap': judged['gap'],
            'citations': [{'source': c['source'], 'ref': c['call_id'], 'note': c['quote']} for c in cited]}


def _outcome(claims, extracted, sources, errors, usage):
    coverage = {'extracted': extracted, **{v: sum(c['verdict'] == v for c in claims) for v in _VERDICTS}}
    # key 放断言原文而不是 claim_id：表格和导出里读者要看的是"哪句话"，id 只对机器有意义。
    items = [{'key': item_label(c), 'value': c['verdict'], 'reason': c['reason'], 'claim_id': c['claim_id'], 'citations': c['citations'],
              'gap': c['gap']} for c in claims]
    groups = []
    for verdict in ('refuted', 'unverifiable', 'verified'):
        lines = [f"{c['claim_id']}（{c['reason']}）" for c in claims if c['verdict'] == verdict]
        if lines:
            groups.append('$' + verdict + '\n' + '\n'.join(lines))
    text = '\n\n'.join(groups) or ('真实性判定失败' if errors else '回答不含可核验的事实断言')
    output = {'claims': claims, 'sources': sources, 'coverage': coverage, 'errors': errors}
    return RunOutcome(output=output, summary=AxisSummary(text, items), failed=bool(errors),
                      failure_reason='；'.join(e['last_error'] for e in errors), usage=usage)


def run_truthfulness(inputs, axis, runtime):
    evidence = inputs['evidence']
    items = [item for item in evidence['items'] if item['origin'] == 'truthfulness']
    usage: dict[str, Any] = {'llm_calls': 0, 'tool_calls': 0}
    notes = {s['uri']: s.get('notes', '') for s in evidence['sources']}
    claims, errors = [], []
    for item in items:
        if item['status'] != FOUND:
            # 没找到相关原文：程序直接给，不调模型。
            claims.append(_claim(item, {'verdict': 'unverifiable', 'reason': '知识查证没找到相关原文：' + item['note'], 'basis': [],
                                        'gap': item['gap']}))
            continue
        try:
            runtime.ensure_time_left(f"断言 {item['item_id']}")
            claims.append(_claim(item, _judge(item, axis.description, notes, runtime, usage)))
        except AxisTimeout as exc:
            usage['timed_out'] = True
            errors.append({'claim_id': item['item_id'], 'last_error': str(exc)})
            break
        except Exception as exc:
            errors.append({'claim_id': item['item_id'], 'last_error': str(exc)})
    return _outcome(claims, len(items), evidence['sources'], errors, usage)


AXIS_TYPE = AxisType(
    type_id='truthfulness', title='真实性', summary='从回答里提取事实断言交知识查证取证，逐条对照取回的原文判定',
    verdict_scope='item', verdict_enum=(Verdict('verified', '知识库中有原文支持该断言'), Verdict('refuted', '知识库原文与该断言矛盾'), Verdict('unverifiable', '知识库中找不到能支持或反驳的原文')),
    item_path='claims[].verdict', depend_on=(Dependency('knowledge_evidence'),), trigger_when=None,
    inputs=(Input('evidence', source='axis.knowledge_evidence.output', fields=('items', 'sources')),),
    output_fields=('claims', 'sources', 'coverage', 'errors'),
    # 知识源引用写在知识查证框；这里的描述只作判定口径补充。
    scenario_fields=(Field('description', required=False, expand='prompt_load'),),
    limits=ExecutionLimits(seconds=600), run=run_truthfulness, knowledge_items=extract_claims,
)
