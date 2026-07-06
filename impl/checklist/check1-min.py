#!/usr/bin/env python3
"""check1-min: Minimal version of check1 - tests 1-2 cases from client_search project only.
Used for quick debugging and session isolation verification."""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time, json, os, re, sys
from datetime import datetime
from impl.core.config import get_uat_base_url

TS = datetime.now().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDIR = f'{ROOT}/tmp/{TS}-min'
os.makedirs(SDIR, exist_ok=True)
DRIVER = '/Users/xiaozijian/WorkSpace/package/chromedriver-mac-arm64/chromedriver'

# Minimal test: just 2 cases from client_search
PROJECT = 'client_search'
TEST_CASES = ['cs-age-sex-premium-correct-1', 'cs-premium-unit-error-1']

def ol(s, n=200): return ' '.join((s or '').split())[:n]
def md(s, n=200): return ol(s, n).replace('|', '\\|')

def main():
    print("=" * 60)
    print(f"Check1-Min: Testing {len(TEST_CASES)} cases from {PROJECT}")
    print(f"Output: {SDIR}")
    print("=" * 60)

    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1440,900")
    d = webdriver.Chrome(service=Service(executable_path=DRIVER), options=opts)

    try:
        # Load frontend
        d.get(f'{get_uat_base_url()}/frontend/summary.html')
        time.sleep(2)

        # Select project
        d.execute_script(f"document.getElementById('project').value='{PROJECT}';document.getElementById('project').dispatchEvent(new Event('change'))")
        time.sleep(1.5)

        # Load cases
        d.execute_script("clearCasePool()")
        time.sleep(0.5)
        d.execute_script("loadMockDatasets()")
        time.sleep(4)

        # Select specific test cases
        ids_json = json.dumps(TEST_CASES)
        d.execute_script(f"""
            casePool.forEach(c => c.selected = false);
            var targets = {ids_json};
            targets.forEach(target => {{
                for(var i = 0; i < casePool.length; i++) {{
                    if(casePool[i].id === target) {{
                        casePool[i].selected = true;
                        break;
                    }}
                }}
            }});
            renderCasePool();
        """)
        time.sleep(1)

        # Take before screenshot
        d.save_screenshot(f'{SDIR}/00-before.png')
        sel_count = d.execute_script("return casePool.filter(c=>c.selected).length")
        print(f"\n✓ Selected {sel_count} cases")

        # Run selected cases (batch attribution)
        d.execute_script("runSelectedCases()")
        print("✓ Started batch attribution")

        # Wait for completion (poll every 5s, check progress text)
        max_wait = 300  # 5 minutes
        elapsed = 0
        last_msg = ""
        while elapsed < max_wait:
            time.sleep(5)
            elapsed += 5
            try:
                progress = d.find_element(By.ID, "progress").text.strip()
                msg = ' '.join(progress.split())[:100]
                if msg != last_msg:
                    print(f"  [{elapsed}s] {msg}")
                    last_msg = msg
                if 'completed，已完成' in progress or '批量任务已完成' in progress:
                    print(f"  ✓ Batch completed in {elapsed}s")
                    time.sleep(2)
                    break
            except:
                pass

        # Take final screenshot
        d.save_screenshot(f'{SDIR}/99-final.png')

        # Get results
        results = d.execute_script("return batchResults")
        with open(f'{SDIR}/results.json', 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Test completed in {elapsed}s")
        print(f"✓ Results saved to {SDIR}/results.json")

        # Print summary
        print("\n" + "=" * 60)
        print("Results Summary:")
        print("=" * 60)
        for case_id in TEST_CASES:
            if case_id in results:
                r = results[case_id]
                verdict = r.get('judge', {}).get('verdict', 'unknown')
                causal = r.get('attribute', {}).get('causal_category', 'unknown')
                print(f"  {case_id}: {verdict} → {causal}")

        # Check session files
        print("\n" + "=" * 60)
        print("Session File Check:")
        print("=" * 60)
        session_file = f'{ROOT}/impl/knowledge/{PROJECT}/agno_memory.json/agno_sessions.json'
        if os.path.exists(session_file):
            with open(session_file) as f:
                sessions = json.load(f)
            print(f"  Total sessions: {len(sessions)}")
            print("  Last 5 session IDs:")
            for sess in sessions[-5:]:
                sid = sess.get('session_id', '')
                parts = sid.split(':')
                metrics = sess.get('session_data', {}).get('session_metrics', {})
                total = metrics.get('input_tokens', 0) + metrics.get('output_tokens', 0)
                status = "✓" if len(parts) == 3 and len(parts[1]) > 20 else "✗"
                print(f"    {status} {sid} ({total:,} tokens)")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        d.save_screenshot(f'{SDIR}/error.png')
    finally:
        d.quit()

if __name__ == '__main__':
    main()
