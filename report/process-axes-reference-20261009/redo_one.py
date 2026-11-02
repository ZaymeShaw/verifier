"""Re-run one failed (case, axis) of a blind-pass repetition: stage 1 for that axis, then its stage 2.
usage: python redo_one.py <provider> <rep> <case> <axis>"""
import json, sys
import blind_pass as b

provider, rep, cname, axis = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
b.use_provider(provider)
case = json.load(open(b.HERE / f'case_files/case_{cname}.json'))
d = b.HERE / 'B_runs' / f'{provider}_rep{rep}' / cname / axis
name, part, io, aspects = b.AXES[axis]
items, nc = [], []
for k, (inst, material) in enumerate(b.stage1_tasks(axis, case)):
    obj = b.ask(b.STAGE1.format(name=name, part=part, io=io, aspects=aspects, material=material), d / f'stage1_{k}.json', 'items')
    if obj is None:
        raise SystemExit(f'stage1 {k} failed again')
    items += [dict(id=f"{inst}.{it['id']}", type=it.get('type'), statement=it.get('statement'), basis=it.get('basis')) for it in obj['items']]
    nc += obj.get('not_covered') or []
(d / 'frozen_items.json').write_text(json.dumps(dict(items=items, not_covered=nc), ensure_ascii=False, indent=1))
obj = b.ask(b.STAGE2.format(name=name, part=part, items=json.dumps(items, ensure_ascii=False, indent=1), casefile=json.dumps(case, ensure_ascii=False)), d / 'stage2.json', 'results')
print('redo', cname, axis, 'items', len(items), 'stage2', 'ok' if obj else 'FAILED')
