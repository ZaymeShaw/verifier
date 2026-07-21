#!/usr/bin/env python3
"""复现脚本:加载 client_search 的 cs-family-property_20 数据集,抓取前端 reference 到底来自哪里。

不改 check1 原文件,独立脚本,用 check1-min 的 selenium 模版。
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time, json, os, sys
from datetime import datetime

from impl.core.config import get_browser_config, get_server_base_url

TS = datetime.now().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDIR = f'{ROOT}/tmp/{TS}-repro-ref'
os.makedirs(SDIR, exist_ok=True)
DRIVER = get_browser_config().driver_path

PROJECT = 'client_search'
BASE_URL = get_server_base_url()


def main():
    print("=" * 60)
    print(f"Repro: 抓取 {PROJECT} reference 来源")
    print(f"Output: {SDIR}")
    print("=" * 60)

    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1440,900")
    d = webdriver.Chrome(service=Service(executable_path=DRIVER), options=opts)

    # 抓 network 请求,看加载了哪些 API
    perf_logs = []
    try:
        # 先看 mock_datasets API 返回的原始 case 数据里有没有 reference
        d.get(f'{BASE_URL}/frontend/summary.html')
        time.sleep(2)

        # 选项目
        d.execute_script(
            f"document.getElementById('project').value='{PROJECT}';"
            f"document.getElementById('project').dispatchEvent(new Event('change'))"
        )
        time.sleep(1.5)

        # 清空用例池
        d.execute_script("clearCasePool()")
        time.sleep(0.5)

        # 直接调 mock_datasets API,看返回的 case 是否自带 reference
        api_data = d.execute_script("""
            return (async () => {
                const resp = await fetch('/api/mock_datasets', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({project: '""" + PROJECT + """'})
                });
                const data = await resp.json();
                return data;
            })();
        """)
        time.sleep(1)
        with open(f'{SDIR}/mock_datasets_raw.json', 'w') as f:
            json.dump(api_data, f, indent=2, ensure_ascii=False)
        datasets = api_data.get('datasets', [])
        print(f"\n[API mock_datasets] 返回 {len(datasets)} 个 dataset")
        for ds in datasets:
            cases = ds.get('cases', [])
            ref_cnt = sum(1 for c in cases if c.get('reference') is not None)
            out_cnt = sum(1 for c in cases if c.get('output') is not None)
            print(f"  dataset={ds.get('dataset_id')} cases={len(cases)} ref={ref_cnt} out={out_cnt}")

        # 也调 mock_cases API
        cases_data = d.execute_script("""
            return (async () => {
                const resp = await fetch('/api/mock_cases', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({project: '""" + PROJECT + """'})
                });
                return await resp.json();
            })();
        """)
        time.sleep(1)
        with open(f'{SDIR}/mock_cases_raw.json', 'w') as f:
            json.dump(cases_data, f, indent=2, ensure_ascii=False)
        cases = cases_data.get('cases', [])
        ref_cnt = sum(1 for c in cases if c.get('reference') is not None)
        print(f"[API mock_cases] 返回 {len(cases)} 条 case, ref={ref_cnt}")

        # 用前端的 loadMockDatasets() 正常加载
        d.execute_script("loadMockDatasets()")
        time.sleep(4)

        # 抓取前端 casePool 里每条 case 的 reference 来源
        pool_info = d.execute_script("""
            return casePool.map(c => ({
                id: c.id,
                source: c.source,
                has_reference_field: c.reference !== null && c.reference !== undefined,
                has_input_reference: c.input && c.input.reference ? true : false,
                has_judge_expected: c.judge && c.judge.expected ? true : false,
                has_frontend_view_ref: c.frontend_view && c.frontend_view.reference_panel && c.frontend_view.reference_panel.reference ? true : false,
                reference_keys: c.reference ? Object.keys(c.reference).slice(0, 5) : [],
                reference_source: c.frontend_view && c.frontend_view.reference_panel ? c.frontend_view.reference_panel.source : null
            }));
        """)
        with open(f'{SDIR}/casepool_reference_sources.json', 'w') as f:
            json.dump(pool_info, f, indent=2, ensure_ascii=False)
        print(f"\n[前端 casePool] {len(pool_info)} 条,reference 来源统计:")
        ref_field_cnt = sum(1 for p in pool_info if p['has_reference_field'])
        input_ref_cnt = sum(1 for p in pool_info if p['has_input_reference'])
        judge_exp_cnt = sum(1 for p in pool_info if p['has_judge_expected'])
        fv_ref_cnt = sum(1 for p in pool_info if p['has_frontend_view_ref'])
        print(f"  case.reference 字段非空: {ref_field_cnt}")
        print(f"  case.input.reference 非空: {input_ref_cnt}")
        print(f"  case.judge.expected 非空: {judge_exp_cnt}")
        print(f"  case.frontend_view.reference_panel.reference 非空: {fv_ref_cnt}")
        for p in pool_info[:5]:
            print(f"  {p['id']}: ref_field={p['has_reference_field']} input_ref={p['has_input_reference']} judge_exp={p['has_judge_expected']} fv_ref={p['has_frontend_view_ref']} ref_source={p['reference_source']} ref_keys={p['reference_keys']}")

        d.save_screenshot(f'{SDIR}/01-loaded.png')

        # 调用 caseReference 看前端实际渲染取的值
        rendered_ref = d.execute_script("""
            return casePool.slice(0, 3).map(c => ({
                id: c.id,
                caseReference_result: caseReference(c),
                inputReference_result: inputReference(c)
            }));
        """)
        with open(f'{SDIR}/rendered_reference.json', 'w') as f:
            json.dump(rendered_ref, f, indent=2, ensure_ascii=False)
        print(f"\n[前端 caseReference() 实际取值] 前 3 条:")
        for r in rendered_ref:
            cr = r.get('caseReference_result')
            print(f"  {r['id']}: caseReference={type(cr).__name__} keys={list(cr.keys())[:5] if isinstance(cr, dict) else cr}")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        d.save_screenshot(f'{SDIR}/error.png')
    finally:
        d.quit()
    print(f"\n✓ 输出目录: {SDIR}")


if __name__ == '__main__':
    main()
