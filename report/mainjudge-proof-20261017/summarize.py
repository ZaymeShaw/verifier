import json, glob, sys, collections
from pathlib import Path
base = Path(__file__).parent / 'out'
def statuses(x):
    if 'error' in x: return ('ERROR',)
    return tuple(a['status'] for a in x['judge'].get('fulfillment_assessments') or [])
def overall(st):
    if 'ERROR' in st: return 'ERROR'
    if 'not_fulfilled' in st: return 'not_fulfilled'
    if 'not_evaluable' in st: return 'not_evaluable'
    return 'fulfilled' if st else 'empty'
variants = sys.argv[1:] or sorted(p.name for p in base.iterdir())
table = collections.defaultdict(dict)
for v in variants:
    for f in glob.glob(str(base / v / '*.json')):
        x = json.load(open(f)); table[x['name']].setdefault(v, []).append(overall(statuses(x)))
short = {'fulfilled': 'F', 'not_fulfilled': 'NF', 'not_evaluable': 'NE', 'ERROR': 'ERR', 'empty': '-'}
print('sample'.ljust(18) + ''.join(v.ljust(16) for v in variants))
for name in sorted(table, key=lambda n: (not n.startswith('target'), int(n.split('-')[1]) if n.startswith('ctl') else 0)):
    print(name.ljust(18) + ''.join(','.join(short[s] for s in table[name].get(v, [])).ljust(16) for v in variants))
for v in variants:
    c = collections.Counter(s for n in table if n.startswith('ctl') for s in table[n].get(v, []))
    print(v, 'control totals', dict(c))
