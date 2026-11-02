"""核事实实验公共部分：样本 A–D、环境。代码与数据取合并工作区（与 main 同一提交 3c58be3a）及 8031 实例数据，只读。"""
import copy, glob, json, os, sys, time
from datetime import datetime
from pathlib import Path

CODE = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier-integrate')
MAIN = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
os.environ.setdefault('VERIFIER_INSTANCE_ID', 'inst-f105511930554648')
sys.path.insert(0, str(CODE))

from impl.server.service import normalize_run_trace  # noqa: E402

HR = [  # (id, 问题, 回答, 类别, 预期)；同 report/d18-validation-20261017/exp_d18.py
    ("hr-annual-ok", "我在公司累计工龄3年，年休假有几天？", "年休假十天。", "correct", "fulfilled"),
    ("hr-annual-wrong", "我在公司累计工龄3年，年休假有几天？", "年休假十五天。", "wrong", "not_fulfilled"),
    ("hr-annual-side", "我在公司累计工龄3年，年休假有几天？", "年休假十天，没休完的年假可以在年底折算成现金发放。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-probation-ok", "劳动合同签两年，试用期最长多久？", "试用期不超过二个月。", "correct", "fulfilled"),
    ("hr-probation-wrong", "劳动合同签两年，试用期最长多久？", "试用期不超过六个月。", "wrong", "not_fulfilled"),
    ("hr-probation-side", "劳动合同签两年，试用期最长多久？", "试用期不超过二个月，试用期内每月要向直属上级提交一次书面工作总结。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-resign-ok", "正式员工辞职要提前多久通知公司？", "正式员工须提前三十日以书面形式通知公司。", "correct", "fulfilled"),
    ("hr-resign-wrong", "正式员工辞职要提前多久通知公司？", "正式员工须提前十五日通知公司。", "wrong", "not_fulfilled"),
    ("hr-resign-side", "正式员工辞职要提前多久通知公司？", "正式员工须提前三十日以书面形式通知公司，发邮件给直属上级即视为书面通知。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-housing-core", "公司有没有住房补贴？每月多少？", "有，每月住房补贴一千五百元，随工资发放。", "core_unverifiable", "not_evaluable"),
    ("hr-petleave-core", "宠物去世可以请几天丧假？", "宠物丧假一天，需提前一天申请。", "core_unverifiable", "not_evaluable"),
]
CLAUSE_EXPECT = {"clause-verified-kn-hesitation": ("correct", "fulfilled"), "clause-refuted-xx-hesitation-stale": ("wrong", "not_fulfilled"),
                 "clause-unverifiable-kn-cashvalue": ("core_unverifiable", "not_evaluable"), "clause-multi-ax": ("multi", "?"),
                 "clause-noclaim-opinion": ("no_claim", "?")}
# D 组：单位缺失。D1 保单在、金额在、无单位字段；D2 保单根本不存在。
UNIT = [
    ("unit-policy-present", "保单P260922000009116累计已交保费多少？", "保单 P260922000009116 的累计已交保费为 1089.1 元。", "unit_missing_object_present", "?"),
    ("unit-policy-absent", "保单P260922000099999累计已交保费多少？", "保单 P260922000099999 的累计已交保费为 1089.1 元。", "object_absent", "not_evaluable"),
]


SHORT = [  # F 组合成短答：对象只在问题里
    ("F-annual-ok", "hr-handbook-qa", "按公司员工手册，我累计工龄3年，年休假有几天？只回答天数。", "10天。", "verified"),
    ("F-hes-ok", "policy-clause-qa", "鑫享至尊年金险的犹豫期是多少天？只回答天数。", "十五天。", "verified"),
    ("F-hes-wrong", "policy-clause-qa", "康宁终身险的犹豫期是多少天？只回答天数。", "10天。", "refuted"),
]
AFTER_SWITCH = Path('/private/tmp/claude-501/-Users-xiaozijian-WorkSpace-projects-claude-code-verifier-runC-verifier/8cdcbbf5-2569-45cb-b97f-edc17fde16b1/scratchpad/e2e/after_switch')


def f_samples():
    """F 组：C8 / C9 两条 10-19 实跑回答 + 3 条合成短答。"""
    out, template = [], None
    for cid, name, exp in (("F-c8", "es-hr-annual", "refuted"), ("F-c9", "es-clause-cashvalue", "unverifiable")):
        t = json.loads((AFTER_SWITCH / f'{name}.json').read_text())['trace']
        template = template or t
        t['case_id'] = t['trace_id'] = cid
        out.append((cid, t['normalized_request']['capability_ref'], normalize_run_trace(t), 'F', 'short_or_rule', exp))
    for cid, scenario, q, a, exp in SHORT:
        t = copy.deepcopy(template)
        t['trace_id'] = t['case_id'] = cid
        t['normalized_request']['capability_ref'] = scenario
        t['normalized_request']['body']['input']['messages'] = [{"role": "user", "content": q}]
        t['input'] = copy.deepcopy(t['normalized_request'])
        t['extracted_output'] = {'output_text': json.dumps({"output": {"choices": [{"message": {"role": "assistant", "content": a}}]}}, ensure_ascii=False)}
        t['raw_response'] = [json.loads(t['extracted_output']['output_text'])]
        out.append((cid, scenario, normalize_run_trace(t), 'F', 'short', exp))
    return out


def samples():
    out, template = [], None
    for f in sorted(glob.glob(str(MAIN / 'report/axes-validation-20260909/live/clause/clause-*.json'))):
        x = json.loads(Path(f).read_text()); t = x['trace']; template = template or t
        cat, exp = CLAUSE_EXPECT[x['compact']['case_id']]
        out.append((x['compact']['case_id'], 'policy-clause-qa', normalize_run_trace(t), 'A', cat, exp))
    for cid, q, a, cat, exp in HR:
        t = copy.deepcopy(template)
        t['trace_id'] = t['case_id'] = cid
        req = t['normalized_request']; req['capability_ref'] = 'hr-handbook-qa'
        req['body']['input']['messages'] = [{"role": "user", "content": q}]
        t['input'] = req
        t['extracted_output'] = {'output_text': json.dumps({"output": {"choices": [{"message": {"role": "assistant", "content": a}}]}}, ensure_ascii=False)}
        t['raw_response'] = json.loads(t['extracted_output']['output_text'])
        out.append((cid, 'hr-handbook-qa', normalize_run_trace(t), 'B', cat, exp))
    mcp_template = None
    for name in ('mcp-bizno', 'mcp-fuyunping-policies'):
        t = json.loads((MAIN / f'report/integrate-verify-20261018/insurance/{name}.json').read_text())['trace']
        mcp_template = mcp_template or t
        t['case_id'] = t['trace_id'] = name
        out.append((name, 'verify-insurance-mcp', normalize_run_trace(t), 'C', 'real', '?'))
    for cid, q, a, cat, exp in UNIT:
        t = copy.deepcopy(mcp_template)
        t['trace_id'] = t['case_id'] = cid
        t['normalized_request']['body']['messages'] = [{"role": "user", "content": q}]
        t['input'] = copy.deepcopy(t['normalized_request'])
        t['extracted_output'] = {'output_text': json.dumps({"answer": a}, ensure_ascii=False)}
        t['raw_response'] = [[{"answer": a}]]
        out.append((cid, 'verify-insurance-mcp', normalize_run_trace(t), 'D', cat, exp))
    return out


def answer_of(trace):
    data = json.loads(trace.extracted_output['output_text'])
    return data['answer'] if 'answer' in data else data['output']['choices'][0]['message']['content']


def elapsed_ms(result):
    try:
        a, b = (datetime.fromisoformat(result[k].replace('Z', '+00:00')) for k in ('started_at', 'finished_at'))
        return int((b - a).total_seconds() * 1000)
    except Exception:
        return None
