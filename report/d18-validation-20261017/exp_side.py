"""D18 越界检查：注入固定真实性结果（核心 verified + 附带细节 unverifiable），只跑 fulfillment 新旧提示词各 3 次。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.argv = [sys.argv[0], "0", str(Path(__file__).parent / "unused")]
import exp_d18 as e
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
ful = e.ful
CASES = {
    "hr-annual-side": [("年休假十天", "verified"), ("没休完的年假可以在年底折算成现金发放", "unverifiable")],
    "hr-probation-side": [("试用期不超过二个月", "verified"), ("试用期内每月要向直属上级提交一次书面工作总结", "unverifiable")],
    "hr-resign-side": [("正式员工须提前三十日以书面形式通知公司", "verified"), ("发邮件给直属上级即视为书面通知", "unverifiable")],
}
spec = load_project('llm_probe'); axes, _ = load_scenario_axes('llm_probe', 'hr-handbook-qa')
ful_axis = next(a for a in axes if a.type_id == 'fulfillment')
samples = {s[0]: s for s in e.samples()}
out = {}
for cid, claims in CASES.items():
    trace = samples[cid][2]
    truth = {'claims': [{'claim_id': str(i + 1), 'text': t, 'context': [], 'verdict': v,
                         'reason': '人工注入', 'citations': []} for i, (t, v) in enumerate(claims)], 'coverage': {}}
    res = {}
    for variant in ('old', 'new'):
        res[variant] = []
        for k in range(3):
            ful.build_context = e.build_old if variant == 'old' else e._orig
            rt = AxisRuntime(spec=spec, run_id=f'side-{variant}-{k}', trace_id=f'side-{variant}-{k}:{cid}', scenario_id='hr-handbook-qa',
                             case_id=cid, enabled_axes=('truthfulness', 'fulfillment'))
            res[variant].append(e.status_of(ful.run_fulfillment({'trace': trace, 'truth': truth}, ful_axis, rt)))
    ful.build_context = e._orig
    out[cid] = res
    print(cid, res, flush=True)
Path(__file__).with_name('side_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
