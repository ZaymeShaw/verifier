"""六轴消费 E：语义 join 显式提交，程序展开单位；不回写需求轴。"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Literal

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.eval_axes.types import raise_for_error_payload

AXIS_KIND = dict(intent_understanding='ι', planning_routing='ρ', tool_execution='χ',
                 knowledge_data='σ', model_capability='μ', context_memory='κ')


@dataclass
class DataNeed:
    expectation_id: str
    need: Literal['tool', 'none', 'not_provided', 'unknown']
    tool_expectation_ids: list[str]
    reason: str


@dataclass
class ContractBinding:
    expectation_id: str
    axes: list[str]


@dataclass
class Join:
    data_needs: list[DataNeed]
    contracts: list[ContractBinding]


JOIN_SPEC = StructuredOutputSpec.from_dataclass(Join)
JOIN_SYSTEM = '''你负责六轴材料准备，只消费已经定格的期望 E，不看业务运行、不修改或补写期望。
每条 want 期望给 data_needs：tool 有工具声明可提供；none 明显无需外部数据；not_provided 完整设计未提供；unknown 承诺材料缺失无法判断。
tool_expectation_ids 只能引用实际声明相应工具能力的 commitment 期望；不能把“要求核实”当作工具存在。
每条 commitment 期望给 contracts.axes，允许多个相关部件：表达 intent_understanding、编排 planning_routing、执行 tool_execution、数据源 knowledge_data、模型 model_capability、传递 context_memory。
数据存在/版本匹配属于知识，工具参数执行属于工具；模型输出格式/事实口径属于模型；历史传递属于上下文。不下业务结论。
每个源期望恰好出现一次；history 不产独立映射。不要从关键词猜工具，依据完整 E 的关于、陈述、条件和原文。'''


def sides(e):
    sources = {s['id']: s for s in e['sources']}
    return {x['expectation_id']: next(sources[r]['side'] for r in x['source_refs']
                                    if sources[r]['side'] != 'history') for x in e['expectations']}


def validate_join(payload, e):
    enforce_output(payload, JOIN_SPEC, caller='expectations.process_projection')
    kind = sides(e)
    for key, side in [('data_needs', 'want'), ('contracts', 'commitment')]:
        ids = [x['expectation_id'] for x in payload[key]]
        if len(ids) != len(set(ids)) or set(ids) != {k for k, v in kind.items() if v == side}:
            raise ValueError('消费投影必须恰好覆盖每条期望：' + key)
    for item in payload['data_needs']:
        refs = item['tool_expectation_ids']
        if any(kind.get(r) != 'commitment' for r in refs):
            raise ValueError('工具能力必须引用承诺侧期望')
        entries = {x['expectation_id']: x for x in e['expectations']}
        sources = {x['id']: x for x in e['sources']}
        if any(not any(sources[s]['component'] == 'tools' for s in entries[r]['source_refs']) for r in refs):
            raise ValueError('取数能力必须来自工具声明，不能来自系统行为要求')
        if (item['need'] == 'tool') != bool(refs):
            raise ValueError('tool 需要工具承诺出处；其他状态不得捏造工具映射')
        if item['need'] == 'not_provided' and any(m['component'] == 'tools' for m in e['missing']):
            raise ValueError('工具声明缺失时不能断言设计未提供')
    for item in payload['contracts']:
        if not item['axes'] or len(item['axes']) != len(set(item['axes'])) or set(item['axes']) - AXIS_KIND.keys():
            raise ValueError('承诺投影必须指向有效部件')


def prepare(e, client, trace_id):
    """一次 consumer-owned 语义 join；不把六轴信息带回 e 的调用。"""
    prompt = json.dumps(e, ensure_ascii=False)
    for attempt in range(2):
        try:
            raw = client.complete_json(JOIN_SYSTEM, prompt, trace_id=trace_id,
                                      stage='llm_probe_expectations_process_projection', output_spec=JOIN_SPEC)
            raise_for_error_payload(raw)
            payload = {k: v for k, v in raw.items() if k not in {'raw_model_response', 'metrics', '_tool_call_log'}}
            validate_join(payload, e)
            return {**copy.deepcopy(payload), 'expectations_sha256': e['sha256']}
        except ValueError as exc:
            if attempt:
                raise
            prompt = json.dumps(e, ensure_ascii=False) + '\n修正无效投影：' + str(exc)


WANT_OBLIGATIONS = {
    'intent_understanding': ('objects_and_fields', 'subquestions', 'constraints', 'reference_resolution', 'ambiguity'),
    'planning_routing': ('work_coverage',),
    'tool_execution': ('executed_without_error', 'result_matches_request'),
    'knowledge_data': ('data_per_subquestion', 'object_version_timepoint'),
    'model_capability': ('output_faithful',),
    'context_memory': ('delivered_intact',),
}


def required_units(axis, e, projection):
    """程序展开，独立于观察到的调用；一项要求可以对接同一真实行使。"""
    sources = {s['id']: s for s in e['sources']}
    entries = {x['expectation_id']: x for x in e['expectations']}
    units = []
    for item in projection['data_needs']:
        want = entries[item['expectation_id']]
        if axis in {'tool_execution', 'knowledge_data'} and item['need'] in {'none', 'not_provided'}:
            continue
        refs = [sources[r] for r in want['source_refs']]
        turn = next(r['turn'] for r in refs if r['side'] == 'want')
        units.append(dict(link_id=f"{AXIS_KIND[axis]}:expected:{want['expectation_id']}",
                          link_type=AXIS_KIND[axis], turn=turn, origin='expectation_deduction',
                          expectation_ids=[want['expectation_id']],
                          input=[], output=[], facts={'required': True}, basis=want['about'],
                          obligation_ids=list(WANT_OBLIGATIONS[axis]),
                          contract_missing=axis in {'tool_execution', 'knowledge_data'} and item['need'] == 'unknown'))
        if axis == 'context_memory' and any(r['side'] == 'history' for r in refs):
            units.append({**units[-1], 'link_id': units[-1]['link_id'] + ':history',
                          'obligation_ids': ['history_and_state']})
    return units


def contracts_for(axis, e, projection):
    ids = {x['expectation_id'] for x in projection['contracts'] if axis in x['axes']}
    ids.update(x['expectation_id'] for x in projection['data_needs'])
    return [x for x in e['expectations'] if x['expectation_id'] in ids]


def bind_results(results, obligations, e, required=(), *, runtime_links=None):
    """校验 E 引用，expected 由定格 E 派生，不信任模型改写。"""
    entries = {x['expectation_id']: x for x in e['expectations']}
    required_by_id = {x['link_id']: x for x in required}
    for r in results:
        refs = r['expectation_ids']
        cited = r['source_refs'] + r['evidence']['input'] + r['evidence']['output']
        for problem in r.get('problems', []):
            cited += problem['source_refs'] + problem['input_refs'] + problem['output_refs']
        if any(ref.startswith('expectation:') and ref.removeprefix('expectation:') not in refs for ref in cited):
            raise ValueError('期望出处必须属于本单位已核对的期望')
        if len(refs) != len(set(refs)) or set(refs) - entries.keys():
            raise ValueError('判准必须引用唯一的已定格期望 id')
        ob = obligations[r['obligation_id']]
        if not refs and ob.source in {'trace', 'case', 'project'} and r['outcome'] in {'pass', 'fail'}:
            raise ValueError('没有已定格判准不能判通过或违约；应报告缺判准')
        checks = r['expectation_checks']
        check_ids = [c.get('expectation_id') for c in checks]
        if len(check_ids) != len(set(check_ids)) or set(check_ids) != set(refs):
            raise ValueError('每条引用期望必须有独立核对结果')
        for c in checks:
            if set(c) != {'expectation_id', 'outcome', 'observed'} or not isinstance(c['observed'], str) or not c['observed'].strip():
                raise ValueError('期望核对必须含 expectation_id/outcome/observed')
            if c['outcome'] not in {'pass', 'fail', 'input_invalid', 'insufficient_evidence', 'contract_missing', 'not_applicable'}:
                raise ValueError('非法期望核对 outcome')
        priority = ['fail', 'insufficient_evidence', 'pass', 'input_invalid', 'not_applicable', 'contract_missing']
        if checks and r['outcome'] != min((c['outcome'] for c in checks), key=priority.index):
            raise ValueError('单位结论必须保留期望逐项核对中的偏差/缺证')
        r['expected'] = '\n'.join(f"{entries[x]['about']}：{entries[x]['statement']}（条件：{entries[x]['condition']}）" for x in refs) or ob.duty
        r['source_refs'] = list(dict.fromkeys(r['source_refs'] + ['expectation:' + x for x in refs]))
        needed = required_by_id.get(r['link_id'])
        if needed:
            if not set(needed['expectation_ids']) <= set(refs):
                raise ValueError('应发生单位漏掉其期望出处')
            r['origin'] = 'expectation_deduction'
            if needed['contract_missing'] and r['outcome'] != 'contract_missing':
                raise ValueError('取数设计未定的单位必须缺判准')
            # Scope-only subabilities can legitimately be inapplicable despite
            # expression being required; whole required exercises cannot disappear.
            scoped = r['obligation_id'] in {'reference_resolution', 'ambiguity', 'constraints'}
            if r['outcome'] == 'not_applicable' and not scoped:
                raise ValueError('应发生单位不能用未发生跳过')
            if not r['matched_link_id'] and r['outcome'] not in {'input_invalid', 'insufficient_evidence', 'contract_missing', 'not_applicable'}:
                raise ValueError('未对接实际行使，不能判 pass/fail；规划遗漏要对接实际安排/收尾')
            if r['matched_link_id']:
                if runtime_links is not None and r['matched_link_id'] not in runtime_links:
                    raise ValueError('对接的实际行使不存在')
                if isinstance(runtime_links, dict):
                    actual = runtime_links[r['matched_link_id']]
                    turn = actual.get('turn') or r['matched_link_id'].split('.')[0]
                    if needed['turn'] != 'case' and turn.replace('turn', 't', 1) != needed['turn']:
                        raise ValueError('应发生单位必须对接出处所在轮次的事件')
                    if needed['link_type'] == 'μ' and actual.get('kind') and actual['kind'] != 'response':
                        raise ValueError('模型期望必须对接该次 response，不能借目录或请求冒充行使')
        elif r['matched_link_id']:
            raise ValueError('只有应发生单位需要 matched_link_id')
        for p in r.get('problems', []):
            if (not p['expectation_ids'] and ob.source != 'agno') or not set(p['expectation_ids']) <= set(refs):
                raise ValueError('问题必须引用本单位已核对的期望')
            p['expected'] = '\n'.join(entries[x]['statement'] for x in p['expectation_ids']) or ob.duty
            p['source_refs'] = list(dict.fromkeys(p['source_refs'] + (['expectation:' + x for x in p['expectation_ids']] or ['obligation:' + ob.obligation_id])))
    missing = [(ob, unit['link_id']) for unit in required for ob in unit['obligation_ids']
               if not any(r['obligation_id'] == ob and r['link_id'] == unit['link_id'] for r in results)]
    if missing:
        raise ValueError(f'应发生单位未覆盖：{missing[:10]}')


def validate_contract_coverage(results, axis, projection):
    needed = {x['expectation_id'] for x in projection['contracts'] if axis in x['axes']}
    seen = {x for r in results for x in r.get('expectation_ids', [])}
    if needed - seen:
        raise ValueError(f'承诺侧期望未核对：{sorted(needed - seen)}；条件不成立也须说明，不能静默漏判')


def validate_dossier_expectations(results, obligations, e, links, dossier):
    """μ only gets criteria present in this invocation, not collected configuration."""
    from ..business_trace.dossier import expand_content
    rows = {r['id']: r for r in dossier.get('records', [])}
    entries = {x['expectation_id']: x for x in e['expectations']}
    sources = {x['id']: x for x in e['sources']}

    def contains(body, value):
        if body == value:
            return True
        if isinstance(body, str) and isinstance(value, str):
            return value in body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return False
        if isinstance(body, dict):
            if isinstance(value, dict) and all(k in body and contains(body[k], v) for k, v in value.items()):
                return True
            return any(contains(v, value) for v in body.values())
        if isinstance(body, list):
            return any(contains(v, value) for v in body)
        return False

    for r in results:
        if obligations[r['obligation_id']].link_type != 'μ' or r['outcome'] not in {'pass', 'fail'}:
            continue
        link = links.get(r.get('matched_link_id') or r['link_id'], {})
        own = {end['ref'] for end in link.get('input', [])}
        raw_refs = r['source_refs'] + r['evidence']['input']
        outside = [ref for ref in raw_refs if ref not in own and ref != 'case'
                   and not ref.startswith(('expectation:', 'obligation:', 'project:'))]
        if outside:
            raise ValueError(f'模型引用不属于该次实际输入端点：{outside}')
        actual = [expand_content((rows.get(end['ref'], {}).get('fields', {}).get(end['field']) or {}).get('value'),
                                 dossier.get('contents', {})) for end in link.get('input', [])]
        for check in r.get('expectation_checks', []):
            if check['outcome'] not in {'pass', 'fail'}:
                continue
            for ref in entries[check['expectation_id']]['source_refs']:
                source = sources[ref]
                if source['side'] == 'history':
                    continue
                if not any(contains(body, source['value']) for body in actual):
                    raise ValueError('期望原文未证实进入本次模型输入；采集时定义不能替代调用原文')


def coalesce(results):
    """组成按真实行使计数；期望检查保留在 checks，不丢逐项证据。"""
    groups = {}
    for r in results:
        key = (r['obligation_id'], r.get('matched_link_id') or r['link_id'])
        groups.setdefault(key, []).append(r)
    output = []
    rank = {x: i for i, x in enumerate(('fail', 'insufficient_evidence', 'pass', 'input_invalid', 'not_applicable', 'contract_missing'))}
    for (ob, link), checks in groups.items():
        chosen = min(checks, key=lambda r: rank[r['outcome']])
        item = copy.deepcopy(chosen)
        item['link_id'] = link
        item['checks'] = copy.deepcopy(checks)
        for key in ('expectation_ids', 'source_refs', 'missing'):
            item[key] = list(dict.fromkeys(x for c in checks for x in c.get(key, [])))
        item['expected'] = '\n'.join(dict.fromkeys(c['expected'] for c in checks))
        item['observed'] = '\n'.join(dict.fromkeys(c['observed'] for c in checks))
        item['evidence'] = {side: list(dict.fromkeys(x for c in checks for x in c['evidence'][side])) for side in ('input', 'output')}
        # If one subcheck has invalid input, do not erase its upstream dependency.
        # Unit-level references obey the existing outcome protocol; checks retain all.
        item['upstream_issue_ids'] = list(dict.fromkeys(x for c in checks for x in c.get('upstream_issue_ids', []))) if item['outcome'] == 'input_invalid' else []
        issues = {}
        for c in checks:
            for p in c.get('problems', []):
                if p['problem_id'] in issues and issues[p['problem_id']] != p:
                    raise ValueError('合并行使时问题 ID 正文冲突')
                issues[p['problem_id']] = p
        item['problems'] = list(issues.values())
        output.append(item)
    return output


CONSUMER_PROMPT = '''
【定格期望】expectations 是需求轴已定格的 E，只能引用 expectation_ids，不得新增或改写 expected。
每条结果必须保留 matched_link_id：普通运行单位填写空字符串 ""；应发生单位填写匹配的实际事件编号，无法定位时也填 ""。空字符串是合法值，不能省略此字段。
每条结果同时给 expectation_checks：对引用的每条期望分别写 observed/outcome，完整核对条件与陈述。
expectation_units 是程序展开的应发生单位：全部覆盖；matched_link_id 写匹配的实际行使编号，找不到留空并按上游无效/缺证处理。
规划已收到目标却漏安排工作时，对接真实规划/收尾产出，记录规划 fail；依赖它的未发查询引用该上游问题。
通用子能力仍按义务判；具体规则、字段要求不能根据实际输出缩写。缺判准时明确写 missing，不把当前运行中新发现的规则偷偷补进 E。
对采集时定义保留版本限制，不能当作模型当次已收到的规则。μ 的期望出处必须在该次实际输入中找到对应原文，不能用外部定义替代。
每个分配到本轴的 commitment 期望至少核对一次，条件不成立也需明确说明。
核对整段响应，包括前置说明、代码围栏、附加文本；某片段字段齐全不证明整个响应满足 JSON 契约。
μ 忠实性核对须同时读数据值、字段解释、gaps 与警告。字段有值不等于它能证明用户要的事实；字段解释限制了含义或明确未确认时，不能靠年份、常识或其他字段看似相符把未确认变成确定。保留限定与不确定性。
缺失最终实收时，对最终交付影响只能 unknown。部分正常不能抵消另一条期望违约；accepted 仅代表程序校验通过。
'''
