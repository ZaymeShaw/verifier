from pathlib import Path
src=Path('report/axes-validation-20260909/fixed/run_fixed.py').read_text()
start=src.index('CASES=[');end=src.index('\nPRESET=',start)
src=src[:start]+'''CASES=[{'id':'fixed-cashvalue-context','question':'康宁终身险的现金价值是怎么计算的？请给出具体比例。','answer':'康宁终身险的现金价值计算方式通常为保费的一定比例，具体比例因产品条款而异。','expect':['unverifiable','unverifiable']}]'''+src[end:]
src=src.replace("(OUT/'summary.json')","(OUT/'cashvalue-summary.json')")
exec(compile(src,'fixed-cashvalue-run','exec'))
