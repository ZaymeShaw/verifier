"""Parse A_stage1_frozen.md into {case: {axis: [{id,type,statement,basis,tainted}]}} (no model involved)."""
import json, re
from pathlib import Path

AXIS_BY_TITLE = {'意图理解': 'intent_understanding', '规划路由': 'planning_routing', '工具执行': 'tool_execution',
                 '知识数据': 'knowledge_data', '模型能力': 'model_capability', '上下文管理': 'context_memory'}
TYPE = {'推': '推出', '守': '守恒', '外': '外部真值'}


def parse(path):
    out, case, axis = {}, None, None
    for line in Path(path).read_text().splitlines():
        if line.startswith('## Case 1'):
            case = 'renyanlin'
        elif line.startswith('## Case 2'):
            case = 'D01'
        elif line.startswith('### '):
            axis = next((v for k, v in AXIS_BY_TITLE.items() if k in line), None)
        m = re.match(r'- ([IPTKMC]\d+) \[(推|守|外)\](◇)? ?(.*)', line)
        if case and axis and m:
            body = m.group(4)
            basis = ''
            b = re.search(r'〔(.*?)〕\s*$', body)
            if b:
                basis, body = b.group(1), body[:b.start()].rstrip()
            out.setdefault(case, {}).setdefault(axis, []).append(
                dict(id=m.group(1), type=TYPE[m.group(2)], statement=body.lstrip('◇ '), basis=basis, tainted='◇' in line[:12] or bool(m.group(3))))
    return out


if __name__ == '__main__':
    d = parse(Path(__file__).parent / 'A_stage1_frozen.md')
    (Path(__file__).parent / 'A_items.json').write_text(json.dumps(d, ensure_ascii=False, indent=1))
    for c, axes in d.items():
        print(c, {a: len(v) for a, v in axes.items()}, 'total', sum(len(v) for v in axes.values()))
