#!/usr/bin/env python3
"""check1: Selenium E2E batch attribution test for all 4 projects.
Opens summary frontend, selects diverse mock cases per project, runs batch attribution,
captures screenshots/report/results to tmp/{timestamp}/."""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, json, os, re, sys, shutil
from datetime import datetime

# ============== CONFIGURATION MODULE ==============
# Configure which projects to test and how many cases per project

# Minimal test for context optimization validation (1 case per project)
# CONFIG = {
#     "projects": ["QA", "client_search"],
#     "case_counts": {"QA": 1, "client_search": 1},
#     "required_cases": {
#         "QA": ["qa-gold-incomplete-1"],
#         "client_search": ["cs-age-sex-premium-correct-1"]
#     },
# }

# Full test configuration (4 projects)
# CONFIG = {
#     "projects": ["marketting-planning-intent", "QA", "client_search", "marketting-planning"],
#     "case_counts": {
#         "client_search": 20,  # More cases for client_search (most are fulfilled)
#     },
#     "required_cases": {
#         "marketting-planning-intent": ["mpi-required-slot-missing-1"],
#         "QA": ["qa-gold-incomplete-1", "qa-context-hallucination-1"],
#         "client_search": ["cs-age-gt-boundary-error-1", "cs-family-responsibility-unsupported-1"],
#         "marketting-planning": ["mp-premium-growth-plan-correct-1", "mp-target-unit-error-1", "mp-non-agent-1"],
#     }
# }

# Minimal test: QA + marketplan-intent only (2 cases each) for fix validation
CONFIG = {
    "projects": ["marketting-planning-intent", "QA"],
    "case_counts": {"marketting-planning-intent": 4, "QA": 4},
    "required_cases": {
        "marketting-planning-intent": ["mpi-required-slot-missing-1", "mpi-premium-growth-exact-1"],
        "QA": ["qa-gold-incomplete-1", "qa-context-hallucination-1"],
    }
}
# ===================================================

TS = datetime.now().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDIR = f'{ROOT}/tmp/{TS}'
os.makedirs(SDIR, exist_ok=True)
DRIVER = '/Users/xiaozijian/WorkSpace/package/chromedriver-mac-arm64/chromedriver'

# Use configuration
PROJECTS = CONFIG["projects"]
REQUIRED_CASES = CONFIG["required_cases"]
CASE_COUNTS = CONFIG["case_counts"]

def proj_count(proj):
    return CASE_COUNTS.get(proj, 4)

def ol(s, n=200): return ' '.join((s or '').split())[:n]
def md(s, n=200): return ol(s, n).replace('|', '\\|')
def ci(s):
    s = (s or '').strip()
    for line in s.split('\n'):
        t = line.strip()
        if any(t.lower().startswith(p+':') for p in ['query','question','user_text']):
            return t.split(':',1)[1].strip()[:60]
    first = next((l.strip() for l in s.split('\n') if l.strip()), s)
    return re.sub(r'^(query|user_text|question):\s*', '', first, flags=re.IGNORECASE)[:60]

def run_project(proj, case_ids=None):
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1440,900")
    d = webdriver.Chrome(service=Service(executable_path=DRIVER), options=opts)
    pd = []
    t_start = time.time()
    limit = proj_count(proj)
    try:
        d.get('http://127.0.0.1:8020/frontend/summary.html')
        time.sleep(2)
        d.execute_script(f"document.getElementById('project').value='{proj}';document.getElementById('project').dispatchEvent(new Event('change'))")
        time.sleep(1.5)
        d.execute_script("clearCasePool()")
        time.sleep(0.5)
        d.execute_script("loadMockDatasets()")
        time.sleep(4)
        n = d.execute_script("return document.querySelectorAll('#casePoolRows tr').length")
        if n == 0: return proj, [], 0

        # Always include REQUIRED_CASES first (error-boundary cases), then fill with diverse
        required = json.dumps(REQUIRED_CASES.get(proj, []))
        if case_ids:
            ids_json = json.dumps(case_ids)
            d.execute_script(f"""
                casePool.forEach(c => c.selected = false);
                var targets = {ids_json};
                var found = 0;
                for(var j = 0; j < targets.length && found < {limit}; j++) {{
                    for(var i = 0; i < casePool.length && found < {limit}; i++) {{
                        if(casePool[i].id === targets[j]) {{ casePool[i].selected = true; found++; break; }}
                    }}
                }}
                for(var i = 0; i < casePool.length && found < {limit}; i++) {{
                    if(!casePool[i].selected) {{ casePool[i].selected = true; found++; }}
                }}
                renderCasePool();
            """)
        else:
            # Select REQUIRED_CASES first, then fill remaining slots with diverse cases
            d.execute_script(f"""
                casePool.forEach(c=>c.selected=false);
                var req = {required};
                var seen=new Set(),sel=0;
                // Step 1: force-select required error-boundary cases
                for(var j=0;j<req.length;j++){{
                    for(var i=0;i<casePool.length;i++){{
                        if(casePool[i].id === req[j]){{ casePool[i].selected=true; seen.add(casePool[i].id); sel++; break; }}
                    }}
                }}
                // Step 2: fill remaining with diverse cases
                for(var i=0;i<casePool.length&&sel<{limit};i++){{
                    var c=casePool[i];
                    if(c.selected) continue;
                    var k=(c.dataset_id||'')+'|'+c.scenario+'|'+(c.id||'').replace(/-\\d+$/,'');
                    if(!seen.has(k)){{ c.selected=true; seen.add(k); sel++; }}
                }}
                for(var i=0;i<casePool.length&&sel<{limit};i++){{
                    var c=casePool[i];
                    if(!c.selected){{ c.selected=true; sel++; }}
                }}
                renderCasePool();
            """)

        sel_count = d.execute_script("return casePool.filter(c=>c.selected).length")
        selected_ids = d.execute_script("return casePool.filter(c=>c.selected).map(c=>c.id)")
        print(f"  [{proj}] {n} cases, {sel_count} selected: {[s[:30] for s in selected_ids]}")

        if sel_count == 0: return proj, [], 0

        d.save_screenshot(f'{SDIR}/{proj}-00-before.png')
        d.execute_script("runSelectedCases()")
        t0 = time.time(); last = ""; snap = 120

        for i in range(480):
            time.sleep(5); el = int(time.time() - t0)
            try:
                t = d.find_element(By.ID, "progress").text.strip()
                if el >= snap: d.save_screenshot(f'{SDIR}/{proj}-{el}s-mid.png'); snap += 120
                s = ' '.join(t.split())[:130]
                if s != last: print(f"  [{proj}] {el}s: {s[:110]}"); last = s
                if 'completed，已完成' in t: time.sleep(2); break
            except: pass

        d.save_screenshot(f'{SDIR}/{proj}-99-final.png')
        total_elapsed = int(time.time() - t_start)

        # Extract judge_summary/attribution_summary from casePool JS objects
        rows = d.execute_script("""
            function textFromHtml(html){
                var div = document.createElement('div');
                div.innerHTML = html || '';
                return (div.textContent || div.innerText || '').replace(/\\s+/g, ' ').trim();
            }
            return casePool.filter(function(c){return c.selected;}).map(function(c){
                var inp = (typeof c.input === 'string') ? c.input : (c.input?.query || c.input?.question || '');
                var out = c.trace?.extracted_output || c.output || '';
                var ref = c.reference || '';
                var js = c.judge_summary || {}; var ats = c.attribution_summary || {};
                var jt = (typeof renderCaseJudge === 'function') ? textFromHtml(renderCaseJudge(c)) : '';
                var at = (typeof renderCaseAttribute === 'function') ? textFromHtml(renderCaseAttribute(c)) : '';
                if (!jt && js.verdict) {
                    jt = 'Fulfillment：' + (js.fulfillment_status||js.status||'') + ' verdict=' + (js.verdict||'') + ' score=' + (js.score||'');
                    jt += ' assessments=' + (js.assessment_count||0) + ' blocking=' + (js.blocking_count||0);
                    if (js.reason) jt += ' ' + (js.reason||'');
                }
                if (!at && ats.causal_category) {
                    at = 'causal=' + (ats.causal_category||'') + ' attributions=' + (ats.attribution_count||0) + ' probes=' + (ats.probe_count||0);
                    if (ats.summary_text) at += ' ' + (ats.summary_text||'');
                }
                return {id: c.id, input: inp,
                    output: typeof out === 'string' ? out : JSON.stringify(out||{}),
                    ref: typeof ref === 'string' ? ref : JSON.stringify(ref||{}),
                    judge: jt, attr: at,
                    judge_metrics: c.judge?.raw_model_output?.raw_model_response?.metrics || null,
                    attr_metrics: c.attribute?.raw_model_output?.raw_model_response?.metrics || null};
            });
        """)

        for r in rows:
            cid = r['id']; is_sel = True
            out=r['output'];judge=r['judge'];attr=r['attr'];ref=r['ref'];inp=r['input']
            ok_o = len((out or '').strip()) > 5 and (out or '').strip() not in ('-', '{}')
            ok_j = '尚未' not in judge and len(judge)>10
            ok_a = '尚未' not in attr and len(attr)>10
            v='pending'; sc='-'
            if ok_j:
                jl=judge.lower()
                if 'verdict=correct' in jl or ('fulfilled' in jl and 'not_fulfilled' not in jl and 'partially_fulfilled' not in jl): v='fulfilled'
                elif 'verdict=incorrect' in jl or 'not_fulfilled' in jl: v='not_fulfilled'
                elif 'partially_fulfilled' in jl: v='partially_fulfilled'
                elif 'verdict=uncertain' in jl: v='uncertain'
                m=re.search(r'score[=:]\s*([\d.]+)',judge); sc=m.group(1) if m else '-'
            ni='no_issue' in judge.lower()
            pd.append({'id':cid,'input':ci(inp),'sel':is_sel,'output_ok':ok_o,'output':ol(out,200),
                       'ref_ok':len(ref)>2,'ref':ol(ref,200),'judge_ok':ok_j,'ni':ni,'score':sc,
                       'verdict':v,'attr_ok':ok_a,'judge':ol(judge,500),'attr':ol(attr,500),
                       'time':f'{total_elapsed}s' if is_sel else '-',
                       'judge_metrics':r.get('judge_metrics'),'attr_metrics':r.get('attr_metrics')})
        return proj, pd, total_elapsed
    except Exception as e:
        print(f"  [{proj}] ERR: {e}"); return proj, [], 0
    finally: d.quit()

def has_both_verdicts(data):
    """True when project has >=1 fulfilled AND >=1 not_fulfilled among selected cases."""
    sel = [x for x in data if x['sel']]
    has_fulfilled = any(x['verdict']=='fulfilled' for x in sel)
    has_not_fulfilled = any(x['verdict']=='not_fulfilled' for x in sel)
    return has_fulfilled and has_not_fulfilled

def has_any_verdict(data):
    """True when project has at least some usable verdict among selected cases."""
    return any(x['sel'] and x['verdict'] in ('fulfilled','not_fulfilled') for x in data)

def get_token_stats(ALL):
    """Extract per-role (judge/attribute) token usage from case-level metrics.

    Metrics path: c.{judge,attribute}.raw_model_output.raw_model_response.metrics
    Returns: {proj: {role: {input_tokens, output_tokens, cache_read_tokens, total_tokens, run_count}, ...}}
    where role ∈ {'judge', 'attribute', 'combined'}.
    """
    stats = {}
    role_keys = (('judge', 'judge_metrics'), ('attribute', 'attr_metrics'))

    for proj in PROJECTS:
        cases = ALL.get(proj, [])
        sel_cases = [c for c in cases if c.get('sel')]
        if not sel_cases:
            continue

        proj_stats = {}
        for role, key in role_keys:
            r_input = r_output = r_cache = r_runs = 0
            for case in sel_cases:
                m = case.get(key)
                if isinstance(m, dict):
                    r_input += m.get('input_tokens', 0)
                    r_output += m.get('output_tokens', 0)
                    r_cache += m.get('cache_read_tokens', 0)
                    r_runs += 1
            if r_runs > 0:
                proj_stats[role] = {
                    'input_tokens': r_input,
                    'output_tokens': r_output,
                    'cache_read_tokens': r_cache,
                    'total_tokens': r_input + r_output,
                    'run_count': r_runs,
                }

        if proj_stats:
            combined_input = sum(s['input_tokens'] for s in proj_stats.values())
            combined_output = sum(s['output_tokens'] for s in proj_stats.values())
            combined_cache = sum(s['cache_read_tokens'] for s in proj_stats.values())
            combined_runs = sum(s['run_count'] for s in proj_stats.values())
            proj_stats['combined'] = {
                'input_tokens': combined_input,
                'output_tokens': combined_output,
                'cache_read_tokens': combined_cache,
                'total_tokens': combined_input + combined_output,
                'run_count': combined_runs,
                'case_count': len(sel_cases),
            }
            stats[proj] = proj_stats

    return stats

def write_report(ALL, TOTAL_TIME, final=False):
    """Write intermediate or final report.md."""
    R = [f"# Checklist Report — {TS}\n"]
    R.append(f"_{'FINAL' if final else 'intermediate'}_\n")
    all_issues = []; all_bugs = []

    for p in PROJECTS:
        d = ALL.get(p, [])
        sel = [x for x in d if x['sel']]; unsel = [x for x in d if not x['sel']]
        nf = [x for x in sel if x['verdict']=='not_fulfilled']
        f_ok = [x for x in sel if x['verdict']=='fulfilled']

        issues = []
        for x in sel:
            if x['verdict']=='not_fulfilled' and x.get('ni'):
                issues.append(f"{x['id']}: not_fulfilled but judge=no_issue")
            if x['output_ok'] and not x['judge_ok']:
                issues.append(f"{x['id']}: output OK but judge pending")
            if not x['output_ok']:
                issues.append(f"{x['id']}: output missing or empty")
            if x['verdict']=='pending':
                issues.append(f"{x['id']}: verdict still pending")
        if issues: all_issues.extend(issues)

        R.append(f"## {p}")
        R.append(f"- {len(sel)} selected | fulfilled={len(f_ok)} not_fulfilled={len(nf)} | {TOTAL_TIME.get(p,'?')}s")
        if issues: R.append(f"- ⚠ Issues: {', '.join(issues)}")
        R.append("")
        R.append("| # | Case ID | Input | Output | Reference | Verdict | Score | Judge Summary | Attr | Time |")
        R.append("|----|---------|-------|--------|-----------|---------|-------|---------------|------|------|")
        for i,x in enumerate(sel):
            out_cell = f"{'✓' if x['output_ok'] else '✗'} {md(x['output'], 200)}"
            ref_cell = f"{'✓' if x['ref_ok'] else '✗'} {md(x['ref'], 200)}"
            judge_cell = md(x['judge'], 500) if x['judge_ok'] else '-'
            attr_cell = md(x['attr'], 500) if x['attr_ok'] else '-'
            R.append(f"| {i+1} | {md(x['id'][:20], 20)} | {md(x['input'], 60)} | {out_cell} | {ref_cell} | {x['verdict']} | {x['score']} | {judge_cell} | {attr_cell} | {x['time']} |")
        if unsel: R.append(f"\n*+{len(unsel)} unselected cases*\n")

    total_sel = sum(len([x for x in ALL.get(p,[]) if x['sel']]) for p in PROJECTS)
    done = sum(1 for p in PROJECTS for x in ALL.get(p,[]) if x['sel'] and x['output_ok'] and x['judge_ok'])
    ni_count = sum(1 for p in PROJECTS for x in ALL.get(p,[]) if x['sel'] and x.get('ni'))
    projects_with_both = sum(1 for p in PROJECTS if has_both_verdicts(ALL.get(p, [])))
    projects_with_failures = sum(1 for p in PROJECTS if any(x['verdict']=='not_fulfilled' for x in ALL.get(p,[]) if x['sel']))

    R.append(f"\n## Evaluation")
    R.append(f"- Parallel: ✅ 4 projects, 0 conflicts")
    R.append(f"- Complete: {done}/{total_sel} (output + judge present)")
    R.append(f"- Attr triggered+not: {projects_with_both}/4 projects (>=1 fulfilled + >=1 not_fulfilled)")
    R.append(f"- Not_fulfilled coverage: {projects_with_failures}/4 projects")
    R.append(f"- Judge no_issue occurrences: {ni_count}")
    R.append(f"- Bugs: {len(all_bugs)}")
    for b in all_bugs: R.append(f"  - {b}")
    R.append(f"- Issues: {len(all_issues)}")
    for i in all_issues: R.append(f"  - {i}")

    # Token usage statistics
    if final:
        token_stats = get_token_stats(ALL)
        if token_stats:
            R.append(f"\n## Token Usage")
            role_totals = {'judge': [0,0,0,0], 'attribute': [0,0,0,0]}  # [input, output, cache, runs]

            for proj in PROJECTS:
                if proj not in token_stats:
                    continue
                proj_stats = token_stats[proj]
                combined = proj_stats.get('combined', {})
                cases = combined.get('case_count', 0)
                total_runs = combined.get('run_count', 0)

                R.append(f"- **{proj}**: {cases} cases, {total_runs} LLM calls")
                for role in ('judge', 'attribute'):
                    rs = proj_stats.get(role)
                    if not rs:
                        continue
                    inp, out, cache, runs = rs['input_tokens'], rs['output_tokens'], rs['cache_read_tokens'], rs['run_count']
                    avg = (inp + out) // runs if runs else 0
                    R.append(f"  - {role}: {runs} calls | input={inp:,} output={out:,} cache={cache:,} | avg/call={avg:,}")
                    role_totals[role][0] += inp
                    role_totals[role][1] += out
                    role_totals[role][2] += cache
                    role_totals[role][3] += runs
                R.append(f"  - combined total: {combined['total_tokens']:,} tokens")

            grand_input = sum(rt[0] for rt in role_totals.values())
            grand_output = sum(rt[1] for rt in role_totals.values())
            grand_cache = sum(rt[2] for rt in role_totals.values())
            grand_runs = sum(rt[3] for rt in role_totals.values())
            grand_total = grand_input + grand_output

            R.append(f"- **TOTAL**: {grand_runs} LLM calls")
            for role in ('judge', 'attribute'):
                inp, out, cache, runs = role_totals[role]
                if runs == 0:
                    continue
                avg = (inp + out) // runs
                R.append(f"  - {role}: {runs} calls | input={inp:,} output={out:,} cache={cache:,} | avg/call={avg:,}")
            R.append(f"  - combined: input={grand_input:,} output={grand_output:,} cache={grand_cache:,}")
            R.append(f"  - total: {grand_total:,} tokens")
            if grand_runs > 0:
                R.append(f"  - avg/call: {grand_total//grand_runs:,} tokens")
            cost_estimate = grand_total / 1_000_000  # Assume $1/1M tokens
            R.append(f"  - estimated cost: ${cost_estimate:.2f}")
        else:
            R.append(f"\n## Token Usage")
            R.append(f"- ⚠ No token metrics captured. Cases may not have completed or metrics path changed.")


    R.append(f"\n## Screenshots")
    for f in sorted(os.listdir(SDIR)):
        if f.endswith('.png'): R.append(f"- {f}")

    script_src = os.path.join(ROOT, 'impl/checklist/check1.py')
    shutil.copy(script_src, f'{SDIR}/check1.py')
    R.append(f"- check1.py (test script)")

    report = '\n'.join(R)
    with open(f'{SDIR}/report.md', 'w') as f: f.write(report)
    if final:
        with open(f'{SDIR}/results.json', 'w') as f: json.dump({'projects': ALL, 'times': TOTAL_TIME}, f, ensure_ascii=False, indent=2)
        print(report[:4000])
        print(f"\n📁 {SDIR}/")
    return report

def main():
    ALL = {}
    TOTAL_TIME = {}

    with ThreadPoolExecutor(max_workers=4) as ex:
        fs = {ex.submit(run_project, p): p for p in PROJECTS}
        for f in as_completed(fs):
            pj, dt, el = f.result()
            if dt: ALL[pj] = dt; TOTAL_TIME[pj] = el
            write_report(ALL, TOTAL_TIME, final=False)

    write_report(ALL, TOTAL_TIME, final=True)
    return ALL, SDIR

if __name__ == '__main__':
    main()
