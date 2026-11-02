"""六轴消费 E：语义 join 显式提交，程序展开单位；不回写需求轴。"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Literal

from ..process_contract import AXIS_GUIDE, source_in_inputs

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.eval_axes.types import raise_for_error_payload
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import UNIT_OUTCOME_PRIORITY

AXIS_KIND = dict(intent_understanding='intent_understanding', planning_routing='planning_routing', tool_execution='tool_execution',
                 knowledge_data='knowledge_data', model_capability='model_capability', context_memory='context_memory')


@dataclass
class DataNeed:
    expectation_id: str
    need: Literal['tool', 'none', 'not_provided', 'unknown']
    tool_expectation_ids: list[str]
    reason: str


@dataclass
class ContractBinding:
    expectation_id: str
    obligation_id: str = field(metadata={'description': '从 obligations 目录选一个子能力 ID；这条承诺约束的就是它的产出。'})


@dataclass
class Join:
    data_needs: list[DataNeed]
    contracts: list[ContractBinding]


JOIN_SPEC = StructuredOutputSpec.from_dataclass(Join)
JOIN_SYSTEM = '''你负责六轴材料准备，只读取已经提取完成的 expectations 期望清单，不看业务运行、不修改或补写期望。
每条 want 期望给 data_needs：tool 有工具声明可提供；none 明显无需外部数据；not_provided 完整设计未提供；unknown 承诺材料缺失无法判断。
tool_expectation_ids 只能引用实际声明相应工具能力的 commitment 期望；不能把“要求核实”当作工具存在。
每条 commitment 期望给 contracts.obligation_id：从 obligations 目录选恰好一个子能力，即这条规则约束其产出的那一项。
部件口径：模型响应格式、字段怎么用、事实口径 → 模型；走哪条路、何时停、是否重复请求、选哪个工具 → 编排；调用参数与执行、工具返回含什么 → 执行；
数据存在与版本匹配 → 数据源；历史怎么带、组装与交付 → 传递；用户原文怎么表达成任务 → 表达。不下业务结论。
每个源期望恰好出现一次；history 不产独立映射。不要从关键词猜工具，依据完整 expectations 的 about（对象）、statement（要求）、condition（条件）和 source_refs 对应原文。
want 是用户要求；commitment 是系统或工具声明的能力与规则；history 是解释指代的历史。sources.side 标明这些类别。
只输出 data_needs 和 contracts 两个数组。缺失清单 missing 表示采集缺口，不能当作业务没有该能力的证据。
''' + '\n轴 ID 与职责：\n' + AXIS_GUIDE


def obligation_catalog():
    """六轴内置子能力（不含场景项目义务）：承诺挂判准的唯一落点。"""
    from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS
    return {ob.obligation_id: dict(axis=axis, situation=ob.situation, duty=ob.duty)
            for axis, spec in PROCESS_SPECS.items() for ob in spec.obligations}


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
    catalog = obligation_catalog()
    unknown = sorted({x['obligation_id'] for x in payload['contracts']} - catalog.keys())
    if unknown:
        raise ValueError(f'contracts.obligation_id 必须取自 obligations 目录；未知：{unknown}')


def prepare(e, client, trace_id):
    """一次 consumer-owned 语义 join；不把六轴信息带回 e 的调用。"""
    catalog = [{'obligation_id': k, **v} for k, v in obligation_catalog().items()]
    prompt = json.dumps({**e, 'obligations': catalog}, ensure_ascii=False)
    request = prompt
    for attempt in range(2):
        try:
            raw = client.complete_json(JOIN_SYSTEM, request, trace_id=trace_id,
                                      stage='llm_probe_expectations_process_projection', output_spec=JOIN_SPEC)
            raise_for_error_payload(raw)
            payload = {k: v for k, v in raw.items() if k not in {'raw_model_response', 'metrics', '_tool_call_log'}}
            validate_join(payload, e)
            return {**copy.deepcopy(payload), 'expectations_sha256': e['sha256']}
        except ValueError as exc:
            if attempt:
                raise
            request = prompt + '\n修正无效投影：' + str(exc)


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


def _turn(value):
    """环节写 turnN，期望出处写 tN；空轮次（分析轴补出的表外环节）不限轮次。"""
    return value.replace('turn', 't', 1) if value and value.startswith('turn') else value


def called_tools(tool_links):
    """每轮实际发出的工具调用名；工具承诺只对用过该工具的轮次成立。"""
    out = {}
    for link in tool_links:
        name = (link.get('facts') or {}).get('tool')
        if name:
            out.setdefault(_turn(link.get('turn', '')), set()).add(name)
    return out


def attach_criteria(pairs, links, obligations, e, projection, tools=None):
    """挂判准（expectations.md §6.1）：每个 (义务, 行使) 只拿部件对得上的定格期望。

    应发生单位挂它展开自的要求；运行单位挂映射到本义务的承诺，工具承诺只挂用过该工具的轮次/调用
    （编排单位除外；tools=None 表示看不到调用名，不按工具收窄）。通用义务和项目义务本身也是判准；
    source=trace/case 的义务模板没有挂到期望时只能缺判准。条件成不成立由评测模型对运行核对。
    """
    sources = {s['id']: s for s in e['sources']}
    entries = {x['expectation_id']: x for x in e['expectations']}
    by_ob = {}
    for item in projection['contracts']:
        by_ob.setdefault(item['obligation_id'], []).append(item['expectation_id'])
    criteria = {}
    for ob_id, link_id in pairs:
        link, ob = links[link_id], obligations[ob_id]
        if link.get('origin') == 'expectation_deduction':
            criteria[(ob_id, link_id)] = ['expectation:' + x for x in link['expectation_ids']]
            continue
        turn = _turn(link.get('turn', ''))
        attached = []
        for ident in by_ob.get(ob_id, []):
            refs = [sources[r] for r in entries[ident]['source_refs']]
            if turn and not any(r['turn'] in {turn, 'case'} for r in refs):
                continue
            names = {r['tool'] for r in refs if r.get('tool')}
            # 编排要在全部工具间选路：没被调用的工具的适用规则正是"该不该选它"的判准，不按调用收窄。
            if names and tools is not None and link.get('link_type') != 'planning_routing':
                used = (link.get('facts') or {}).get('tool')
                available = {used} if used else {n for k, v in tools.items() if not turn or k == turn for n in v}
                if not names & available:
                    continue
            attached.append('expectation:' + ident)
        own = ob_id if ob.source == 'project' else 'obligation:' + ob_id
        criteria[(ob_id, link_id)] = attached + [own] if ob.source in {'agno', 'project'} or not attached else attached
    return criteria


def unattached(obligations, criteria, projection):
    """映射到本轴子能力、却没挂到任何单位的承诺：本次没有对应行使（或没调用该工具），显式留档不静默。"""
    attached = {ref.removeprefix('expectation:') for refs in criteria.values() for ref in refs}
    return sorted(x['expectation_id'] for x in projection['contracts']
                  if x['obligation_id'] in obligations and x['expectation_id'] not in attached)


def check_criteria(results, criteria):
    """每个单位恰好核对挂给它的判准，不多不少；条件不成立也要逐条写 not_applicable。"""
    errors = []
    for r in results:
        # transcript 路径可把占位换成确切事件编号，沿用该义务占位单位的判准。
        need = criteria.get((r['obligation_id'], r['link_id']), criteria.get((r['obligation_id'], 'transcript')))
        if need is None:
            errors.append(f"{r['obligation_id']} @ {r['link_id']}：不是待判单位，没有挂接判准")
            continue
        got = r['criterion_refs']
        if set(got) != set(need):
            missing, extra = sorted(set(need) - set(got)), sorted(set(got) - set(need))
            errors.append(f"{r['obligation_id']} @ {r['link_id']}：判准须恰好为 criteria 所列"
                          + (f"，缺 {missing}" if missing else '') + (f"，多 {extra}" if extra else ''))
    if errors:
        raise ValueError('；'.join(errors[:12]))


def bind_results(results, obligations, e, required=(), *, runtime_links=None):
    """校验 E 引用，expected 由定格 E 派生，不信任模型改写。"""
    entries = {x['expectation_id']: x for x in e['expectations']}
    required_by_id = {x['link_id']: x for x in required}
    for r in results:
        refs = r['expectation_ids']
        cited = r['source_refs'] + r['evidence']['input'] + r['evidence']['output']
        if any(ref.startswith('expectation:') and ref.removeprefix('expectation:') not in refs for ref in cited):
            raise ValueError('期望出处必须属于本单位已核对的期望')
        if len(refs) != len(set(refs)) or set(refs) - entries.keys():
            raise ValueError('判准必须引用唯一的已定格期望 id')
        ob = obligations[r['obligation_id']]
        if not refs and ob.source in {'trace', 'case'} and r['outcome'] in {'pass', 'fail'}:
            raise ValueError(f'{ob.obligation_id} @ {r["link_id"]}: source={ob.source} 的 pass/fail 必须在 criterion_checks 使用 expectation:<ID> 核对已定格判准；义务模板不能代替具体要求，确无判准才报告 contract_missing')
        if ob.source == 'project' and r['outcome'] in {'pass', 'fail'} and ob.obligation_id not in r['source_refs']:
            raise ValueError(f'项目义务必须引用已确认的出处 {ob.obligation_id}')
        checks = r['expectation_checks']
        check_ids = [c.get('expectation_id') for c in checks]
        if len(check_ids) != len(set(check_ids)) or set(check_ids) != set(refs):
            raise ValueError('每条引用期望必须有独立核对结果')
        for c in checks:
            if set(c) != {'expectation_id', 'outcome', 'observed'} or not isinstance(c['observed'], str) or not c['observed'].strip():
                raise ValueError('期望核对必须含 expectation_id/outcome/observed')
            if c['outcome'] not in {'pass', 'fail', 'input_invalid', 'insufficient_evidence', 'contract_missing', 'not_applicable'}:
                raise ValueError('非法期望核对 outcome')
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
                    turn = actual.get('turn', r['matched_link_id'].split('.')[0])
                    # 空轮次是分析轴补出的表外环节，不限轮次；其余必须对接出处所在轮次。
                    if needed['turn'] != 'case' and turn and turn.replace('turn', 't', 1) != needed['turn']:
                        raise ValueError('应发生单位必须对接出处所在轮次的事件')
                    if needed['link_type'] == 'model_capability' and actual.get('kind') and actual['kind'] != 'response':
                        raise ValueError('模型期望必须对接该次 response，不能借目录或请求冒充行使')
        elif r['matched_link_id']:
            raise ValueError('只有应发生单位需要 matched_link_id')
        for p in r.get('problems', []):
            if not p['expectation_ids'] and ob.source not in {'agno', 'project'}:
                raise ValueError('source=trace/case 义务的问题必须引用已核对的期望')
            if ob.source == 'project' and not p['expectation_ids'] and ob.obligation_id not in p['source_refs']:
                raise ValueError(f'项目义务问题必须引用已确认的出处 {ob.obligation_id}')
            p['expected'] = '\n'.join(entries[x]['statement'] for x in p['expectation_ids']) or ob.duty
            criterion_ref = ob.obligation_id if ob.source == 'project' else 'obligation:' + ob.obligation_id
            p['source_refs'] = list(dict.fromkeys(p['source_refs'] + (['expectation:' + x for x in p['expectation_ids']] or [criterion_ref])))
    missing = [(ob, unit['link_id']) for unit in required for ob in unit['obligation_ids']
               if not any(r['obligation_id'] == ob and r['link_id'] == unit['link_id'] for r in results)]
    if missing:
        raise ValueError(f'应发生单位未覆盖：{missing[:10]}')


def validate_dossier_expectations(results, obligations, e, links, dossier):
    """model_capability only gets criteria present in this invocation, not collected configuration."""
    from ..business_trace.dossier import expand_content
    rows = {r['id']: r for r in dossier.get('records', [])}
    entries = {x['expectation_id']: x for x in e['expectations']}
    sources = {x['id']: x for x in e['sources']}

    for r in results:
        if obligations[r['obligation_id']].link_type != 'model_capability' or r['outcome'] not in {'pass', 'fail'}:
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
                if not source_in_inputs(source, actual):
                    raise ValueError(f"期望原文未证实进入本次模型输入：expectation_id={check['expectation_id']}, source_ref={ref}, input_refs={sorted(own)}；采集时定义不能替代调用原文")


def coalesce(results):
    """组成按真实行使计数；期望检查保留在 checks，不丢逐项证据。"""
    groups = {}
    for r in results:
        key = (r['obligation_id'], r.get('matched_link_id') or r['link_id'])
        groups.setdefault(key, []).append(r)
    output = []
    rank = {x: i for i, x in enumerate(UNIT_OUTCOME_PRIORITY)}
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
【定格期望】expectations 是已提取完成、不可改写的期望清单，criterion_checks 使用 expectation:<ID> 引用它，不得新增或改写 expected。
每个待判单位的 criteria 是程序挂给它的全部判准：criterion_checks 恰好逐条核对这些引用，不多不少；条件不成立写 not_applicable 及依据。
criterion_checks 对每条判准分别写 outcome/observed，完整核对条件与陈述。单位总结果和期望 ID 列表由程序派生，不重复提交。
每条结果必须保留 matched_link_id：普通运行单位填写空字符串 ""；应发生单位填写匹配的实际事件编号，无法定位时也填 ""。空字符串是合法值，不能省略此字段。
expectation_units 是程序展开的应发生单位：全部覆盖；matched_link_id 写匹配的实际行使编号，找不到留空并按上游无效/缺证处理。
规划已收到目标却漏安排工作时，对接真实规划/收尾产出，记录规划 fail；依赖它的未发查询引用该上游问题。
具体规则、字段要求不能根据实际输出缩写。criteria 只有 source=trace/case 义务模板时说明缺判准，不把当前运行中新发现的规则偷偷补进期望清单。
对采集时定义保留版本限制，不能当作模型当次已收到的规则。model_capability 的期望出处必须在该次实际输入中找到对应原文，不能用外部定义替代。
核对整段响应，包括前置说明、代码围栏、附加文本；某片段字段齐全不证明整个响应满足 JSON 契约。
model_capability 忠实性核对须同时读数据值、字段解释、gaps 与警告。字段有值不等于它能证明用户要的事实；字段解释限制了含义或明确未确认时，不能靠年份、常识或其他字段看似相符把未确认变成确定。保留限定与不确定性。
缺失最终实收时，对最终交付影响只能 unknown。部分正常不能抵消另一条期望违约；accepted 仅代表程序校验通过。
'''
