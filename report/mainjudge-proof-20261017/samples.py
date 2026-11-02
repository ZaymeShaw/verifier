"""主轴重放实验的样本：(name, trace, report)。只读正式代码与数据，不写回。"""
import copy, glob, json, sqlite3
from pathlib import Path

ROOT = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
LF = ROOT / 'report/business-trace-langfuse-20261015'


def target_samples():
    from impl.core.schema import RunTrace
    turns = json.loads((LF / 'real/turns.json').read_text())
    out = []
    for provider in ('agno', 'langfuse'):
        report = json.loads((LF / f'rerun-20261017/{provider}-r1-judge.json').read_text())['axes']
        t = turns[0]
        row = {k: copy.deepcopy(v) for k, v in t.items() if k not in {'snapshots', 'seconds'}}
        row['extracted_output'] = {'output_text': json.dumps(row['raw_response'], ensure_ascii=False)}
        row['project_fields'] = {'business_trace': t['snapshots'][provider]}
        name = f'target-{provider}'
        trace = RunTrace(trace_id=name, project_id='llm_probe', case_id=name, normalized_request=row['request'],
                         input=row['request'], raw_response=row['raw_response'], extracted_output=row['extracted_output'],
                         project_fields=row['project_fields'], turn_records=[row], final_output_turn=1,
                         interaction_mode='single_turn', session_id=row['request']['body']['session_id'],
                         scenario='insurance-agno-e2e')
        out.append((name, trace, report))
    return out


def control_samples():
    """当前实例用例池里的 32 条（批次 6dd73371，insurance-agno-e2e），自带 trace 与过程轴报告。"""
    from impl.server.service import normalize_run_trace
    db = sqlite3.connect(f"file:{ROOT}/.runtime/instances/inst-16fa340ac786414f/data/latest_runs.sqlite3?mode=ro", uri=True)
    out = []
    for pos, rj in db.execute("SELECT position, run_json FROM current_cases WHERE project='llm_probe' AND run_json IS NOT NULL ORDER BY position"):
        run = json.loads(rj)
        out.append((f"ctl-{pos}", normalize_run_trace(run['trace']), run['eval_axes'],
                    {'case_id': run['case_id'], 'batch_overall': ((run.get('judge') or {}).get('overall_fulfillment') or {}).get('status')}))
    return out
