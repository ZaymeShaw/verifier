"""Re-run only the item matchings whose first attempt came back empty, with a larger output cap."""
import concurrent.futures as cf, json, sys
import blind_pass as b
import match_items as m

b.use_provider(sys.argv[1]); b.MAX_TOKENS = 64000
out = b.HERE / 'B_runs' / 'match'
todo = []
for f in sorted(out.glob('*.json')):
    if '"error"' in f.read_text():
        # case names contain no underscore; axis names do -> rebuild robustly
        parts = f.stem.split('_')
        x, y, c = parts[0], parts[1], parts[2]
        a = '_'.join(parts[3:])
        todo.append((f, m.PROMPT.format(rule=m.RULES["strict"], x=m.fmt(m.items(x, c, a)), y=m.fmt(m.items(y, c, a)))))
print('redo', [t[0].stem for t in todo])
with cf.ThreadPoolExecutor(3) as ex:
    res = list(ex.map(lambda t: b.ask(t[1], t[0], 'x_to_y'), todo))
print('redo done', sum(r is not None for r in res), '/', len(res))
