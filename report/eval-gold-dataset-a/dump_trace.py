"""把业务 trace（Langfuse observation）整理成可读文本：只留类型、名称、输入、输出，按时间排序。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from impl.projects.llm_probe_loop.business_trace.providers import langfuse as lf

CFG = {**lf.describe()['default_connection']}


def observations(trace_id):
    rows, errs, _ = lf._pages(CFG, '/observations', {'traceId': trace_id})
    assert not errs, errs
    return sorted(rows, key=lambda o: o.get('startTime') or '')


def text(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def render(trace_id, limit=6000):
    """业务这一轮实际调的后端（backend.*）及其入参、返回；chat.turn 给出这一轮的用户输入。注意：trace 里手机号、姓名等已被 [REDACTED]。"""
    out = []
    for o in observations(trace_id):
        name = (o.get('name') or '').replace('agentic-insurance-qa-agent.', '')
        if not name.startswith(('backend.', 'chat.turn')) or (o.get('input') is None and o.get('output') is None):
            continue
        out.append(f"### {name}\n输入：{text(o.get('input'))[:limit]}\n输出：{text(o.get('output'))[:limit]}\n")
    return '\n'.join(out)

if __name__ == '__main__':
    print(render(sys.argv[1]))
