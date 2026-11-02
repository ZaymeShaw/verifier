"""Process unit/issue contract shared by both execution paths (process-axes §3–6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from ...process_contract import AxisId, AXIS_DESCRIPTIONS, AXIS_GUIDE

AXES = frozenset(AXIS_DESCRIPTIONS)
OUTCOMES = ('pass', 'fail', 'insufficient_evidence', 'input_invalid', 'not_applicable', 'contract_missing')
# 单位内逐项判断和同一次行使合并使用同一优先序，不让模型重复计算。
UNIT_OUTCOME_PRIORITY = ('fail', 'insufficient_evidence', 'pass', 'input_invalid', 'not_applicable', 'contract_missing')


@dataclass
class Problem:
    problem_id: str
    phenomenon: str
    expectation_ids: list[str]
    observed: str
    source_refs: list[str] = field(metadata={'description': '判准引用，只用 obligation:<义务ID>、expectation:<期望ID>、project:<项目义务ID>、case 或已读的案卷证据 ID；不能填 expectation_sources.id。'})
    input_refs: list[str]
    output_refs: list[str]
    attribution_axes: list[AxisId] = field(metadata={'description': '只填英文轴 ID：' + '；'.join(f'{k}={v}' for k, v in AXIS_DESCRIPTIONS.items())})
    impact: Literal['yes', 'no', 'unknown']


# 与提交格式无关的业务规则：新旧两种提交格式的提示词都从这里取，避免改一边漏一边。
EVIDENCE_GUIDE = """
【证据使用】
传递是否无损必须比较传递前后两端；合理压缩不等于改义。原始模型请求优先于重建消息；重建只能在已说明的范围内使用。
HTTP/span 成功不证明语义正确；落库结果不等于调用方实收；采集时定义不证明当次版本或模型已收到。
不可见不证明未发生。缺少与当前义务无关的端点不妨碍本项判定；缺少必要端点必须说明具体影响。
模型行为只对照本次调用自己的实际输入和完整输出；输入没包含的外部规则不能拿来判模型违约。
系统准入、容量、预算的拒绝先看规划策略，不自动当作工具执行故障。单次耗时只按该调用的适用时限判断，无判准填 contract_missing。
"""

JUDGING_GUIDE = """
【判定范围】
忠实性须核对完整输出中的业务声明，包括前置说明、草稿、正文和结尾；保留对象、数值、单位、范围、否定和不确定性。后文正确不抵消前文错误。
规则里的能力、允许、建议、必须和禁止不能互换。条件不成立须解释依据，不能静默跳过；没有偏差证据不强行找错。
输入已证实无效的子能力按 input_invalid 及其上游问题处理；其他不依赖该坏输入的义务仍须判断，不能整轴免检。
"""

PROTOCOL_PROMPT = """
【统一能力口径】每个单位比较实际产出与在实际拿到的输入下本应产出的内容。
outcome 六值：pass 做到；fail 输入有效且没做到；input_invalid 依赖的输入不存在或已错；
insufficient_evidence 看不清产出或输入有效性；contract_missing 没有判准出处；not_applicable 有正面证据证明本次不需要。
input_invalid 必须在 upstream_issue_ids 指向本案已记录的具体上游问题 problem_id，不能指向本单位或空泛的轴名。
没有可引用的上游问题就用 insufficient_evidence 并写明缺什么。只影响依赖坏输入的子能力：提示缺失不免除独立的不编造检查。
应发生而未发生的行使用 input_invalid（有上游问题）或 insufficient_evidence，不能用 not_applicable。
输入已坏不能按最终结果判本轴 fail；如实传递错误输入不代表传递能力有缺陷。同一事件可在不同轴分别记录独立问题。
产出偏差已证实但输入有效性/归因不可见：insufficient_evidence + problems，attribution_axes 列出候选轴（至少两个），不得把两轴都判 fail。
fail 必须有 problems。每个 problem 只描述一个具体问题：phenomenon、expectation_ids（具体判准引用定格期望；agno 通用义务或已确认项目义务可为空并引用自身判准）、observed（带 input_refs/output_refs）、attribution_axes、impact。
fail 的 attribution_axes 只能是本轴；未定位问题的候选轴必须包含本轴。problem_id 在本案唯一；多个轴引用同一未定位问题须使用同一个 id 和完全一致的问题正文。
每条问题必须有 trace 原文依据；不要用整段 reason 作为一条问题。可以在一个单位的 problems 中分开记录多个独立问题。
origin=runtime_recall 表示从运行召回；origin=expectation_deduction 表示从期望/设计倒推。无问题时 problems=[]；非 input_invalid 时 upstream_issue_ids=[]。
只引用当前材料 recorded_issues 已提供的已定位问题；各轴调度由程序负责，不要求你调用尚未提供的轴。评测器格式错误、超时、预算耗尽不是业务缺证，不能写进 outcome。
verdict 由程序按 fail > insufficient_evidence > pass > input_invalid > not_applicable 汇总；缺判准单列，组成始终保留。
""" + "\n【轴 ID 与职责】\n" + AXIS_GUIDE


def validate_units(results: list[Mapping[str, Any]], axis_id: str = '') -> None:
    for r in results:
        outcome = r['outcome']
        if outcome not in OUTCOMES:
            raise ValueError(f'非法 outcome: {outcome}')
        problems = r.get('problems') or []
        upstream = r.get('upstream_issue_ids') or []
        if outcome == 'input_invalid' and not upstream:
            raise ValueError('input_invalid 必须指向已记录的上游问题')
        if outcome != 'input_invalid' and upstream:
            raise ValueError('只有 input_invalid 可以引用上游问题')
        if outcome == 'fail' and not problems:
            raise ValueError('fail 必须生成至少一条独立问题记录')
        if problems and outcome not in {'fail', 'insufficient_evidence'}:
            raise ValueError('只有没做到或未定位缺证产生问题')
        if outcome == 'insufficient_evidence' and not r['missing']:
            raise ValueError('insufficient_evidence 必须说明 missing')
        for p in problems:
            if any(not str(p[k]).strip() for k in ('problem_id', 'phenomenon', 'expected', 'observed')):
                raise ValueError('问题标识、现象、预期和实际不能为空')
            if not (p['input_refs'] or p['output_refs']):
                raise ValueError('问题必须带 trace 引用')
            if not set(p['input_refs']) <= set(r['evidence']['input']) or not set(p['output_refs']) <= set(r['evidence']['output']):
                raise ValueError('问题引用必须属于本单位已核对的输入输出')
            if not p['source_refs']:
                raise ValueError('问题预期必须带判准出处（通用义务使用 obligation:<id>）')
            axes = p['attribution_axes']
            if not axes or len(axes) != len(set(axes)) or not set(axes) <= AXES:
                raise ValueError(f'problems.attribution_axes={axes!r} 非法或重复；合法值为 {sorted(AXES)}')
            if axis_id and axis_id not in axes:
                raise ValueError('问题归因必须包含本轴')
            if outcome == 'fail' and len(axes) != 1:
                raise ValueError('归因未定位不能判 fail')
            if outcome == 'insufficient_evidence' and len(axes) < 2:
                raise ValueError('缺证问题须保留至少两个未定位候选轴')
            if p['impact'] not in {'yes', 'no', 'unknown'}:
                raise ValueError('非法影响取值')


_UNIT_LOCAL = {'units', 'input_refs', 'output_refs', 'source_refs', 'expected'}


def issues_for(axis_id: str, results: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    validate_units(results, axis_id)
    issues: dict[str, dict[str, Any]] = {}
    for r in results:
        for p in r.get('problems') or []:
            issue = {**p, 'attribution': 'local' if r['outcome'] == 'fail' else 'unresolved',
                     'units': [{'axis_id': axis_id, 'obligation_id': r['obligation_id'],
                                'link_id': r['link_id'], 'origin': r.get('origin', 'runtime_recall')}]}
            prior = issues.get(p['problem_id'])
            if prior:
                # 一个问题涉及多个单位时，各单位只带自己的证据端点；正文须一致，证据取并集。
                if {k: v for k, v in prior.items() if k not in _UNIT_LOCAL} != {k: v for k, v in issue.items() if k not in _UNIT_LOCAL}:
                    raise ValueError('同一 problem_id 的问题正文不一致')
                prior['units'].extend(issue['units'])
                for key in ('input_refs', 'output_refs', 'source_refs'):
                    prior[key] = list(dict.fromkeys([*prior[key], *issue[key]]))
                prior['expected'] = '\n'.join(dict.fromkeys([prior['expected'], issue['expected']]))
            else:
                issues[p['problem_id']] = issue
    return list(issues.values())


def validate_issue_references(outputs: Mapping[str, Mapping[str, Any]]) -> None:
    """Case-local validation; forward references are allowed only until all axes finish."""
    registry: dict[str, dict[str, Any]] = {}
    units: dict[str, list] = {}
    for output in outputs.values():
        for issue in output.get('issues', []):
            units.setdefault(issue['problem_id'], []).extend(issue['units'])
            body = {k: v for k, v in issue.items() if k != 'units'}
            old = registry.setdefault(issue['problem_id'], body)
            if old != body:
                raise ValueError(f"问题 ID 冲突：{issue['problem_id']}")
    for axis, output in outputs.items():
        for unit in output.get('results', []):
          for r in unit.get("checks", [unit]):
            for ref in r.get('upstream_issue_ids', []):
                issue = registry.get(ref)
                self_ref = any(u['axis_id'] == axis and u['obligation_id'] == r['obligation_id'] and u['link_id'] == r['link_id'] for u in units.get(ref, []))
                if not issue or issue['attribution'] != 'local' or self_ref:
                    raise ValueError(f'{axis}/{r["link_id"]}: 上游问题 {ref} 不存在、未定位或引用自身单位')


def composition(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {'counts': {value: sum(r['outcome'] == value for r in results) for value in OUTCOMES},
            'input_invalid': [{'obligation_id': r['obligation_id'], 'link_id': r['link_id'],
                               'upstream_issue_ids': list(r['upstream_issue_ids'])}
                              for r in results if r['outcome'] == 'input_invalid']}
