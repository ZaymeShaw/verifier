"""把 cases/ 生成供人审的 inputs.md：总表 + 每条的完整对话与回答。"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def fence(text):
    run = max([len(r) for r in text.split('\n') for r in [r[:len(r) - len(r.lstrip('`'))]]] + [0])
    return '`' * max(3, run + 1)


cases = [json.loads(f.read_text()) for f in sorted((HERE / 'cases').glob('*.json'))]
lines = ['# 主轴三态评测：样本清单', '', f'共 {len(cases)} 条；验收集（holdout）{sum(c["split"] == "holdout" for c in cases)} 条，改规则时不看。',
         '', '| # | id | 来源 | 集 | 最后一轮问题 | 回答开头 |', '|---|---|---|---|---|---|']
for i, c in enumerate(cases, 1):
    q = (c['turns'][-1] if c['turns'] else '').replace('|', '\\|').replace('\n', ' ')
    a = c['answer'][:50].replace('|', '\\|').replace('\n', ' ')
    lines.append(f"| {i} | {c['id']} | {c['source']} | {c['split']} | {q[:50]} | {a} |")
for i, c in enumerate(cases, 1):
    lines += ['', f"## {i}. {c['id']}（{c['source']}，{c['split']}）", '']
    for k, t in enumerate(c['turns'], 1):
        f = fence(t); lines += [f'用户第 {k} 轮：', f, t, f]
    f = fence(c['answer']); lines += ['回答：', f, c['answer'], f]
(HERE / 'inputs.md').write_text('\n'.join(lines) + '\n')
print(len(cases))
