"""Atomic process judgments, issues and aggregation (process-axes §3–6)."""
from __future__ import annotations

from typing import Any, Mapping
from ...process_contract import AXIS_DESCRIPTIONS

AXES = frozenset(AXIS_DESCRIPTIONS)
OUTCOMES = ('pass', 'fail', 'insufficient_evidence', 'input_invalid', 'not_applicable', 'contract_missing')
UNIT_OUTCOME_PRIORITY = ('fail', 'insufficient_evidence', 'pass', 'input_invalid', 'not_applicable', 'contract_missing')

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


def validate_units(results: list[Mapping[str, Any]], axis_id: str = '') -> None:
    for r in results:
        outcome = r['outcome']
        if outcome not in OUTCOMES:
            raise ValueError(f'非法 outcome: {outcome}')
        problems, upstream = r.get('problems') or [], r.get('upstream_issue_ids') or []
        invalid = outcome == 'input_invalid' or any(c['outcome'] == 'input_invalid' for c in r.get('criterion_checks', []))
        if invalid and not upstream:
            raise ValueError('input_invalid 必须指向已记录的上游问题')
        if not invalid and upstream:
            raise ValueError('只有 input_invalid 判准可以引用上游问题')
        for check in r.get('criterion_checks', []):
            if check['outcome'] == 'input_invalid' and not check.get('upstream_issue_ids'):
                raise ValueError('每条 input_invalid 判准必须保留上游问题')
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
            if p['outcome'] == 'fail' and len(axes) != 1:
                raise ValueError('归因未定位不能判 fail')
            if p['outcome'] == 'insufficient_evidence' and len(axes) < 2:
                raise ValueError('缺证问题须保留至少两个未定位候选轴')
            if p['outcome'] not in {'fail', 'insufficient_evidence'}:
                raise ValueError('问题必须来自失败或未定位缺证判准')
            if p['impact'] not in {'yes', 'no', 'unknown'}:
                raise ValueError('非法影响取值')


_UNIT_LOCAL = {'units', 'input_refs', 'output_refs', 'source_refs', 'expected'}


def issues_for(axis_id: str, results: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    validate_units(results, axis_id)
    issues = {}
    for r in results:
        for p in r.get('problems') or []:
            issue = {**p, 'attribution': 'local' if p['outcome'] == 'fail' else 'unresolved',
                     'units': [{'axis_id': axis_id, 'obligation_id': r['obligation_id'],
                                'link_id': r['link_id'], 'origin': r.get('origin', 'runtime_recall')}]}
            prior = issues.get(p['problem_id'])
            if prior:
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
    registry, units = {}, {}
    for output in outputs.values():
        for issue in output.get('issues', []):
            units.setdefault(issue['problem_id'], []).extend(issue['units'])
            body = {k: v for k, v in issue.items() if k != 'units'}
            if registry.setdefault(issue['problem_id'], body) != body:
                raise ValueError(f"问题 ID 冲突：{issue['problem_id']}")
    for axis, output in outputs.items():
        for unit in output.get('results', []):
            for r in unit.get('checks', [unit]):
                for ref in r.get('upstream_issue_ids', []):
                    issue = registry.get(ref)
                    self_ref = any(u['axis_id'] == axis and u['obligation_id'] == r['obligation_id'] and u['link_id'] == r['link_id'] for u in units.get(ref, []))
                    if not issue or issue['attribution'] != 'local' or self_ref:
                        raise ValueError(f'{axis}/{r["link_id"]}: 上游问题 {ref} 不存在、未定位或引用自身单位')


def composition(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Unit counts and atomic counts are distinct; partial invalid input stays visible."""
    atomic, invalid = [], []
    for unit in results:
        for row in unit.get('checks', [unit]):
            checks = row.get('criterion_checks') or [row]
            atomic.extend(checks)
            for check in checks:
                if check['outcome'] == 'input_invalid':
                    invalid.append(dict(obligation_id=row['obligation_id'], link_id=row['link_id'],
                                        criterion_ref=check.get('criterion_ref'),
                                        upstream_issue_ids=list(check['upstream_issue_ids'])))
    return {'counts': {value: sum(r['outcome'] == value for r in results) for value in OUTCOMES},
            'criterion_counts': {value: sum(c['outcome'] == value for c in atomic) for value in OUTCOMES},
            'input_invalid': invalid}
