"""Extract embedded DATA json from llm_trace.html. usage: extract.py <html> <out.json>"""
import sys
s = open(sys.argv[1], encoding='utf-8').read()
a = s.index('<script id="DATA" type="application/json">') + len('<script id="DATA" type="application/json">')
b = s.index('</script>', a)
open(sys.argv[2], 'w', encoding='utf-8').write(s[a:b])
