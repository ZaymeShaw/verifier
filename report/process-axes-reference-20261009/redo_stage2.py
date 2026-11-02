"""Re-run only stage 2 of one (case, axis) with a larger output cap (the first run was truncated at 24000 tokens).
usage: python redo_stage2.py <provider> <rep> <case> <axis>"""
import json, sys
import blind_pass as b

provider, rep, cname, axis = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
b.use_provider(provider); b.MAX_TOKENS = 64000
case = json.load(open(b.HERE / f'case_files/case_{cname}.json'))
d = b.HERE / 'B_runs' / f'{provider}_rep{rep}' / cname / axis
items = json.load(open(d / 'frozen_items.json'))['items']
name, part = b.AXES[axis][0], b.AXES[axis][1]
(d / 'stage2_truncated.json').write_text((d / 'stage2.json').read_text())
obj = b.ask(b.STAGE2.format(name=name, part=part, items=json.dumps(items, ensure_ascii=False, indent=1), casefile=json.dumps(case, ensure_ascii=False)), d / 'stage2.json', 'results')
print('redo stage2', cname, axis, 'rep', rep, 'ok' if obj else 'FAILED', 'problems' in (obj or {}))
