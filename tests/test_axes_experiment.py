import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_js(code, cases, types):
    script = """
const fs = require('fs');
const vm = require('vm');
const context = {globalThis:{}};
vm.createContext(context);
for (const name of ['axes_overview.js','axes_experiment.js']) {
  vm.runInContext(fs.readFileSync('impl/frontend/' + name,'utf8'),context);
}
const A=context.globalThis.AxesExperiment;
const input=JSON.parse(fs.readFileSync(0,'utf8'));
""" + code
    result = subprocess.run(['node', '-e', script], cwd=ROOT,
                            input=json.dumps({'cases': cases, 'types': types}),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_axis_distribution_counts_verdicts_not_obligations_or_execution_failures():
    cases = [{'id': 'same', 'axes': [{'type_id': 'tool', 'status': 'succeeded', 'verdict': v,
              'items': [{'key': 'obligation @ χ:1', 'value': 'fail', 'reason': 'original'}] * 3}]} for v in ['sound', 'problematic']]
    cases.append({'id': 'failed', 'axes': [{'type_id': 'tool', 'status': 'failed'}]})
    types = [{'type_id': 'tool', 'verdict_scope': 'axis', 'verdict_enum': [{'value': v} for v in ['sound', 'problematic', 'not_evaluable']]}]
    out = run_js('process.stdout.write(JSON.stringify(A.prepare(input.cases,input.types)));', cases, types)[0]
    assert out['total'] == 2 and out['recorded'] == 3 and out['succeeded'] == 2
    assert [(b['value'], b['count']) for b in out['buckets']] == [('sound', 1), ('problematic', 1), ('not_evaluable', 0)]
    assert out['buckets'][1]['entries'] == [{'position': 1}]
    # 分组只引用案例位置；条目原文由单例详情读取，不在各分组重复拷贝。


def test_item_distribution_keeps_original_enums_and_distinct_case_records():
    types = [{'type_id': 'truth', 'verdict_scope': 'item', 'verdict_enum': [{'value': v} for v in ['verified', 'refuted']]}]
    cases = [{'id': 'duplicate', 'axes': [{'type_id': 'truth', 'status': 'succeeded',
              'items': [{'key': 'claim', 'value': 'refuted', 'reason': 'original'}]}]} for _ in range(2)]
    out = run_js('process.stdout.write(JSON.stringify(A.prepare(input.cases,input.types)));', cases, types)[0]
    assert out['total'] == 2 and out['itemScope']
    bucket = out['buckets'][1]
    assert bucket['count'] == 2 and len(bucket['entries']) == 2
    assert [e['position'] for e in bucket['entries']] == [0, 1]


def test_missing_verdict_and_undeclared_scope_are_not_invented_scores():
    cases = [{'id': 'a', 'axes': [{'type_id': 'declared', 'status': 'succeeded'},
                                 {'type_id': 'unknown', 'status': 'succeeded', 'verdict': 'novel'}]}]
    types = [{'type_id': 'declared', 'verdict_scope': 'axis', 'verdict_enum': [{'value': 'pass'}]}]
    out = run_js('process.stdout.write(JSON.stringify(A.prepare(input.cases,input.types)));', cases, types)
    assert out[0]['missingVerdicts'] == 1 and out[0]['total'] == 0
    assert not out[1]['declared']


def test_render_is_safe_standalone_and_keeps_small_segments_clickable_in_legend():
    cases = [{'id': '<img src=x onerror=alert(1)>', 'axes': [{'type_id': 'a', 'status': 'succeeded',
              'verdict': '</script><script>alert(1)</script>', 'text': '<b>original</b>', 'items': []}]}]
    types = [{'type_id': 'a', 'title': '<unsafe>', 'verdict_scope': 'axis', 'verdict_enum': []}]
    out = run_js('process.stdout.write(JSON.stringify(A.renderPage(input.cases,input.types)));', cases, types)
    assert '<unsafe>' not in out and '&lt;unsafe&gt;' in out
    assert '</script><script>alert(1)' not in out
    assert '<img src=x' not in out and '<b>original</b>' not in out
    assert 'class="segment"' in out and 'class="legend-item"' in out
    assert 'textContent' in out and '100%' in out
    assert '<script src=' not in out


def test_original_overview_remains_and_experiment_is_separate():
    source = (ROOT / 'impl/frontend/summary.html').read_text()
    assert 'onclick="openAxesOverview()"' in source
    assert 'onclick="openAxesExperiment()"' in source
    assert 'axes_experiment.html' in source
    start = source.index('async function openAxesExperiment()')
    end = source.index('async function exportCurrentCasePoolXlsx()', start)
    body = source[start:end]
    assert 'currentFilteredCaseViews()' in body and 'request_key:item.request_key' in body
    assert 'pool_index:poolIndex' in body and 'createObjectURL' not in body
    assert '/api/batch_start' not in body and '/api/run_workspace/' not in body
    loader = (ROOT / 'impl/frontend/axes_experiment.html').read_text()
    assert 'axes_experiment.js' in loader and 'fromWorkspace(workspace,scope.selections)' in loader


def test_independent_page_restores_scoped_case_data_from_backend():
    workspace = {'cases': [{'case': {'id': 'same', 'live_request': {'q': 'request'}, 'output': None}, 'request_key': 'j:0'}],
                 'runs': [{'request_key': 'j:0', 'trace': {'input': {'q': 'actual'}, 'extracted_output': False},
                           'table_row': {'input': 'actual preview', 'fulfillment_status': 'not_fulfilled', 'eval_axes_summary': []}}]}
    restored = run_js('process.stdout.write(JSON.stringify(A.fromWorkspace(input.cases,input.types)));', workspace, [{'pool_index': 0, 'request_key': 'j:0'}])
    assert restored[0]['input'] == {'q': 'actual'} and restored[0]['output'] is False
    assert restored[0]['inputPreview'] == 'actual preview' and restored[0]['pool_index'] == 0
    failed = run_js("try{A.fromWorkspace(input.cases,input.types)}catch(e){process.stdout.write(JSON.stringify({message:e.message,code:e.code}))}", workspace, [{'pool_index': 0, 'request_key': 'old'}])
    assert '候选区已更新' in failed['message']
    assert failed['code'] == 'WORKSPACE_CHANGED'


def test_semantic_tree_preserves_llm_order_and_maps_refs_not_duplicate_case_ids():
    cases, types = case_detail_fixture()
    cases = cases[:2]
    for index, case in enumerate(cases):
        case.update(pool_index=index + 7, request_key=f'j:{index}')
    result = {'refs': {'r0': {'pool_index': 7, 'request_key': 'j:0', 'axis_id': 'alpha', 'value': 'problematic'},
                       'r1': {'pool_index': 8, 'request_key': 'j:1', 'axis_id': 'alpha', 'value': 'problematic'},
                       'r2': {'pool_index': 7, 'request_key': 'j:0', 'axis_id': 'beta', 'value': 'sound'}},
              'axes': [{'axis_id': 'beta', 'priority_reason': 'first axis', 'labels': [{'value': 'sound', 'priority_reason': 'label', 'clusters': [
                  {'name': 'normal handling', 'description': 'normal case class', 'priority_reason': 'important', 'member_refs': ['r2']}]}]},
                       {'axis_id': 'alpha', 'priority_reason': 'second axis', 'labels': [{'value': 'problematic', 'priority_reason': 'label', 'clusters': [
                  {'name': 'second row first', 'description': 'one situation', 'priority_reason': 'attention', 'member_refs': ['r1']},
                  {'name': 'first row last', 'description': 'another situation', 'priority_reason': 'later', 'member_refs': ['r0']}]}]}]}
    out = run_js('const data=input.cases;process.stdout.write(JSON.stringify(A.semanticGroups(data.result,A.prepare(data.cases,input.types),data.cases)));',
                 {'result': result, 'cases': cases}, types)
    assert [g['name'] for g in out] == ['normal handling', 'second row first', 'first row last']
    assert [g['members'][0]['position'] for g in out] == [0, 1, 0]
    result['refs']['r1']['request_key'] = 'stale'
    error = run_js('const d=input.cases;try{A.semanticGroups(d.result,A.prepare(d.cases,input.types),d.cases)}catch(e){process.stdout.write(JSON.stringify(e.message))}',
                   {'result': result, 'cases': cases}, types)
    assert '不一致' in error


def case_detail_fixture():
    types = [{'type_id': key, 'title': key, 'verdict_scope': 'axis',
              'verdict_enum': [{'value': 'problematic'}, {'value': 'sound'}]} for key in ['alpha', 'beta']]
    cases = [{'id': 'duplicate', 'input': {'q': text}, 'output': output, 'fulfillment': 'not_fulfilled',
              'trace': {'secret': 'DO_NOT_COPY_TRACE'},
              'axes': [{'type_id': 'alpha', 'status': 'succeeded', 'verdict': 'problematic',
                        'items': [{'key': 'requirement @ link', 'value': 'fail', 'reason': text}]},
                       {'type_id': 'beta', 'status': 'succeeded', 'verdict': 'sound', 'text': 'other axis reason'}]}
             for text, output in [('first case', {'answer': '</script><img src=x onerror="alert(1)">'}),
                                  ('second case', False), ('third case', 0)]]
    cases.append({'id': 'missing', 'axes': [{'type_id': 'alpha', 'status': 'succeeded', 'verdict': 'problematic'}]})
    return cases, types


def test_case_context_is_embedded_once_and_keeps_falsy_values_without_trace():
    cases, types = case_detail_fixture()
    out = run_js('process.stdout.write(JSON.stringify(A.renderPage(input.cases,input.types)));', cases, types)
    data = json.loads(re.search(r'\)\((\{"axes":.*\})\);</script>', out).group(1))
    assert len(data['cases']) == 4
    assert data['cases'][0]['input'] == cases[0]['input']
    assert data['cases'][0]['output'] == cases[0]['output']
    assert data['cases'][1]['output'] is False
    assert data['cases'][2]['output'] == 0
    assert data['cases'][3]['input'] is None and data['cases'][3]['output'] is None
    assert len(data['cases'][0]['axes']) == 2
    assert 'DO_NOT_COPY_TRACE' not in out and '<img src=x' not in out


@pytest.mark.parametrize('axis,source,kind,label', [
    ({'itemScope': False}, None, 'absent', '未运行'),
    ({'itemScope': False}, {'status': 'disabled'}, 'disabled', '未启用'),
    ({'itemScope': False}, {'status': 'failed', 'verdict': 'sound'}, 'execution', 'failed'),
    ({'itemScope': False}, {'status': 'blocked'}, 'execution', 'blocked'),
    ({'itemScope': False}, {'status': 'succeeded', 'items': [{'value': 'fail'}]}, 'missing', '无轴结论'),
    ({'itemScope': False}, {'status': 'succeeded', 'verdict': 'not_evaluable'}, 'verdict', 'not_evaluable'),
    ({'itemScope': True}, {'status': 'succeeded', 'items': []}, 'missing', '无条目结论'),
])
def test_matrix_keeps_execution_states_separate_from_verdicts(axis, source, kind, label):
    result = run_js('process.stdout.write(JSON.stringify(A.cellState(input.types,input.cases)));', source, axis)
    assert result['kind'] == kind and result['label'] == label


def test_matrix_item_scope_preserves_each_enum_count():
    result = run_js('process.stdout.write(JSON.stringify(A.cellState(input.types,input.cases)));',
                    {'status': 'succeeded', 'items': [{'value': 'refuted'}, {'value': 'verified'}, {'value': 'refuted'}]},
                    {'itemScope': True})
    assert result['kind'] == 'items'
    assert result['tokens'] == [{'value': 'refuted', 'count': 2}, {'value': 'verified', 'count': 1}]


@pytest.mark.parametrize('source,label,text,count', [
    ({'text': '原始轴说明', 'items': [{'reason': '另一条逐项理由'}]}, '轴说明（原文）', '原始轴说明', 1),
    ({'items': [{'key': 'obligation', 'reason': '逐项原文'}, {'reason': '第二条'}]}, '首条条目理由（原文）', '逐项原文', 2),
    ({'text': ' ', 'items': []}, '理由', '未提供判断理由', 0),
    (None, '说明', '该轴未运行，没有判断理由。', 0),
])
def test_reason_preview_is_existing_text_not_a_generated_summary(source, label, text, count):
    result = run_js('process.stdout.write(JSON.stringify(A.reasonSummary(input.cases)));', source, [])
    assert result['label'] == label and result['text'] == text and result['detailCount'] == count


def test_group_membership_is_only_axis_and_enum_not_label_or_reason():
    types = [{'type_id': axis, 'verdict_scope': 'axis', 'verdict_enum': [{'value': v} for v in ['problematic', 'sound']]}
             for axis in ['alpha', 'beta']]
    cases = [{'id': 'same-id', 'axes': [
        {'type_id': 'alpha', 'status': 'succeeded', 'verdict': 'problematic',
         'text': reason, 'items': [{'key': label, 'value': 'fail', 'reason': reason}]},
        {'type_id': 'beta', 'status': 'succeeded', 'verdict': verdict, 'text': 'independent reason'},
    ]} for label, reason, verdict in [('label-a', 'first mechanism', 'problematic'), ('label-b', 'different mechanism', 'sound')]]
    axes = run_js('process.stdout.write(JSON.stringify(A.prepare(input.cases,input.types)));', cases, types)
    assert axes[0]['buckets'][0]['entries'] == [{'position': 0}, {'position': 1}]
    assert axes[1]['buckets'][0]['entries'] == [{'position': 0}]
    assert axes[1]['buckets'][1]['entries'] == [{'position': 1}]


def test_item_group_reasons_exclude_other_enum_values():
    source = {'status': 'succeeded', 'text': 'summary mixes all values', 'items': [
        {'key': 'first', 'value': 'verified', 'reason': 'unrelated'},
        {'key': 'second', 'value': 'refuted', 'reason': 'refuted reason A'},
        {'key': 'third', 'value': 'refuted', 'reason': 'refuted reason B'},
    ]}
    result = run_js("process.stdout.write(JSON.stringify(A.groupReasons({itemScope:true},'refuted',input.cases)));", source, [])
    assert [item['reason'] for item in result] == ['refuted reason A', 'refuted reason B']
    assert [item['key'] for item in result] == ['second', 'third']


def test_task_progress_distinguishes_counts_time_and_unknown_model_progress():
    batch = {'status': 'running', 'done': 1, 'total': 4, 'progress':
             {'stage': 'executing_cases', 'started_at': 1000, 'last_event_at': 1005}}
    info = run_js("process.stdout.write(JSON.stringify(A.taskProgress(input.cases,'batch',1010)));", batch, [])
    assert info['elapsed'] == 10 and info['idle'] == 5 and info['eta'] == 30
    model = {'status': 'running', 'progress': {'stage': 'model_request', 'started_at': 1000,
             'last_event_at': 1005, 'request_timeout_seconds': 600}}
    info = run_js("process.stdout.write(JSON.stringify(A.taskProgress(input.cases,'clustering',1010)));", model, [])
    assert info['eta'] is None and info['done'] is None and info['requestTimeout'] == 600
    unknown = run_js("process.stdout.write(JSON.stringify(A.taskProgress(input.cases,'batch',1010)));", {'status': 'completed', 'done': 4, 'total': 4}, [])
    assert not unknown['timing'] and unknown['started'] is None and unknown['elapsed'] is None
    stale = run_js("process.stdout.write(JSON.stringify(A.taskProgress(input.cases,'clustering',1010)));", {'status': 'stale', 'progress': {'stage': 'completed','started_at': 1000,'last_event_at': 1005,'finished_at': 1005}}, [])
    assert stale['stage'] == '结果已失效'


def test_browser_case_input_output_and_other_axes_are_accessible():
    cli = shutil.which('playwright-cli')
    if not cli:
        pytest.skip('browser regression requires playwright-cli')
    module = Path(cli).resolve().parent / 'node_modules' / 'playwright'
    if not module.exists():
        pytest.skip('Playwright library is unavailable')
    cases, types = case_detail_fixture()
    cases.extend([
        {'id': 'failed-only', 'input': 'failed input', 'output': 'failed output', 'axes': [
            {'type_id': 'alpha', 'status': 'failed', 'verdict': 'sound', 'text': 'synthetic service error'}]},
        {'id': 'empty-axis', 'input': 'no verdict input', 'axes': [{'type_id': 'alpha', 'status': 'succeeded'}]},
        {'id': 'no-axis', 'input': 'no axis input', 'axes': []},
        {'id': 'disabled-axis', 'input': 'disabled input', 'axes': [{'type_id': 'alpha', 'status': 'disabled'}]},
    ])
    html = run_js('process.stdout.write(JSON.stringify(A.renderPage(input.cases,input.types)));', cases, types)
    code = f"const {{chromium}}=require({json.dumps(str(module))});" + r'''
const fs=require('fs'), assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const page=await browser.newPage();
    let dialogs=0;page.on('dialog',d=>{dialogs++;d.dismiss();});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const html=fs.readFileSync(0,'utf8');
    await page.setContent(html);
    assert.equal(await page.locator('.matrix-row').count(),8);
    // 类型目录先验证布局：不声称已做语义聚类，每次只展开一个候选范围。
    assert.equal(await page.locator('#group-view').isVisible(),true);
    assert.equal(await page.locator('#matrix-view').isVisible(),false);
    assert.equal(await page.locator('#experiment-details').isVisible(),false);
    assert.equal(await page.locator('.type-entry').count(),2);
    assert.equal(await page.locator('.enum-group').count(),1);
    assert((await page.locator('#group-summary').textContent()).includes('尚未做语义聚类'));
    const alphaEntry=page.locator('.type-entry[data-axis="0"][data-bucket="0"]');
    const betaEntry=page.locator('.type-entry[data-axis="1"][data-bucket="1"]');
    assert.equal(await alphaEntry.getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#distribution-overview').evaluate(e=>e.open),true);
    assert.equal(await page.locator('#distribution-overview .overview-grid').isVisible(),true);
    assert.equal(await page.locator('.type-scope').count(),2);
    assert.equal(await page.locator('.type-scope > .type-label > .type-clusters > .type-entry').count(),2);
    assert.equal(await alphaEntry.locator('.pending-type').textContent(),'待聚类');
    assert.equal(await alphaEntry.evaluate(e=>e.closest('.type-label').parentElement.className),'type-scope');
    assert.equal(await page.locator('.type-breadcrumb').textContent(),'alpha / problematic / 待聚类');
    const alphaGroup=page.locator('.enum-group[data-axis="0"][data-bucket="0"]');
    const betaGroup=page.locator('.enum-group[data-axis="1"][data-bucket="1"]');
    assert.equal(await alphaGroup.locator('.group-member').count(),4);
    assert.deepEqual(await alphaGroup.locator('.group-reason-text').allTextContents(),['first case','second case','third case','未提供判断理由']);
    assert.equal(await alphaGroup.locator('.group-reason-text').first().isVisible(),true);
    await alphaGroup.locator('.group-member[data-position="1"] .group-case-open').click();
    assert.equal(JSON.parse(await page.locator('.case-input-value').textContent()).q,'second case');
    assert.equal(await page.locator('.case-output-value').textContent(),'false');
    assert.equal(await page.locator('#experiment-details').isVisible(),true);
    await page.click('.close-case-detail');
    assert.equal(await page.locator('#experiment-details').isVisible(),false);
    assert.equal(await page.locator('.case-input-value').count(),0);
    await betaEntry.click();
    assert.equal(await page.locator('.enum-group').count(),1);
    assert.equal(await betaGroup.locator('.group-member').count(),3);
    assert.equal(await betaEntry.getAttribute('aria-pressed'),'true');
    // 分布概览默认可见，直接点色块，无须先展开。
    await page.locator('.legend-item[data-axis="1"][data-bucket="1"]').click();
    assert.equal(await page.locator('.type-entry').count(),1);
    assert.equal(await betaGroup.locator('.group-member').count(),3);
    assert.equal(await page.locator('#experiment-details').isVisible(),false);
    await page.click('#all-cases');
    assert.equal(await page.locator('.type-entry').count(),2);
    await page.fill('#case-search','second case');
    assert.equal(await alphaEntry.locator('.type-count').textContent(),'1 例');
    assert.equal(await betaEntry.locator('.type-count').textContent(),'1 例');
    assert.equal(await betaGroup.locator('.group-member').count(),1);
    await alphaEntry.click();
    assert.equal(await alphaGroup.locator('.group-member').count(),1);
    await page.fill('#case-search','not a real case');
    assert.equal(await page.locator('.type-entry').count(),0);
    assert.equal(await page.locator('.enum-group').count(),0);
    assert.equal(await page.locator('#experiment-details').isVisible(),false);
    await page.click('#all-cases');
    for(const width of [1400,390]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    await page.setViewportSize({width:1280,height:720});
    await page.click('#matrix-mode');
    assert.equal(await page.locator('#matrix-view').isVisible(),true);
    assert.equal(await page.locator('.matrix-row').count(),8);
    const initialReason=page.locator('.matrix-row[data-position="0"] .matrix-cell[data-axis-id="alpha"] .matrix-reason-text');
    assert.equal(await initialReason.textContent(),'first case');
    assert(await initialReason.isVisible());
    const initialWidth=(await initialReason.boundingBox()).width;
    assert.equal(await page.locator('.matrix-row[data-position="0"] .matrix-cell[data-axis-id="beta"] .matrix-reason-text').textContent(),'other axis reason');
    await page.locator('.legend-item[data-axis="0"][data-bucket="0"]').click();
    assert.equal(await page.locator('.matrix-row').count(),4);
    assert.equal(await page.locator('#matrix-head th').count(),3);
    assert((await initialReason.boundingBox()).width>initialWidth);
    assert.equal(await initialReason.evaluate(el=>getComputedStyle(el).display),'block');
    assert.equal(JSON.parse(await page.locator('.case-input-value').textContent()).q,'first case');
    assert((await page.locator('.case-output-value').textContent()).includes('<img src=x'));
    assert.equal(await page.locator('img').count(),0);assert.equal(dialogs,0);
    await page.locator('.matrix-row[data-position="1"] .case-open').click();
    assert.equal(JSON.parse(await page.locator('.case-input-value').textContent()).q,'second case');
    assert.equal(await page.locator('.case-output-value').textContent(),'false');
    await page.locator('.axis-tab[data-axis-id="beta"]').click();
    assert.equal(await page.locator('.case-axis-detail .original-text').textContent(),'other axis reason');
    assert.equal(await page.locator('.case-output-value').textContent(),'false');
    await page.locator('.matrix-row[data-position="2"] .case-open').click();
    assert.equal(await page.locator('.case-output-value').textContent(),'0');
    await page.locator('.matrix-row[data-position="3"] .case-open').click();
    assert.equal(await page.locator('.case-input-value').textContent(),'未提供实际输入');
    assert.equal(await page.locator('.case-output-value').textContent(),'未提供实际输出');

    await page.click('#all-cases');
    assert.equal(await page.locator('.matrix-row').count(),8);
    const failed=page.locator('.matrix-row[data-position="4"] .matrix-cell[data-axis-id="alpha"]');
    assert.equal(await failed.locator('.state-label').textContent(),'failed');
    await failed.click();
    assert.equal(await page.locator('.case-input-value').textContent(),'failed input');
    assert.equal(await page.locator('.case-output-value').textContent(),'failed output');
    assert.equal(await page.locator('.case-axis-detail .original-text').textContent(),'synthetic service error');
    const missing=page.locator('.matrix-row[data-position="5"] .matrix-cell[data-axis-id="alpha"]');
    assert.equal(await missing.locator('.state-label').textContent(),'无轴结论');await missing.click();
    assert.equal(await page.locator('.case-input-value').textContent(),'no verdict input');
    const absent=page.locator('.matrix-row[data-position="6"] .matrix-cell[data-axis-id="alpha"]');
    assert.equal(await absent.locator('.state-label').textContent(),'未运行');await absent.click();
    assert.equal(await page.locator('.case-input-value').textContent(),'no axis input');
    const disabled=page.locator('.matrix-row[data-position="7"] .matrix-cell[data-axis-id="alpha"]');
    assert.equal(await disabled.locator('.state-label').textContent(),'未启用');await disabled.click();
    assert.equal(await page.locator('.case-input-value').textContent(),'disabled input');

    await page.locator('.axis-focus[data-axis-id="beta"]').click();
    assert.equal(await page.locator('#matrix-head th').count(),3);
    assert.equal(await page.locator('.matrix-row').count(),8);
    await page.click('#all-cases');
    await page.locator('.matrix-row[data-position="0"] .case-open').click();
    assert.equal(await page.locator('.axis-reason-summary').count(),2);
    assert.equal(await page.locator('.axis-reason-summary .reason').first().textContent(),'first case');
    assert(await page.evaluate(()=>!!(document.querySelector('.case-axis-detail').compareDocumentPosition(document.querySelector('.case-io'))&Node.DOCUMENT_POSITION_FOLLOWING)));
    await page.fill('#case-search','synthetic service error');
    assert.equal(await page.locator('.matrix-row').count(),1);
    assert.equal(await page.locator('.matrix-row').getAttribute('data-position'),'4');
    await page.fill('#case-search','second case');
    assert.equal(await page.locator('.matrix-row').count(),1);
    assert.equal(await page.locator('.matrix-row').getAttribute('data-position'),'1');
    await page.locator('.case-open').click();
    await page.fill('#case-search','no such case');
    assert.equal(await page.locator('.matrix-row').count(),0);
    assert.equal(await page.locator('.case-input-value').count(),0);
    await page.click('#all-cases');
    for(const width of [1400,390]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', code], input=html, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_browser_process_composition_and_quoted_evidence():
    cli = shutil.which('playwright-cli')
    if not cli:
        pytest.skip('browser regression requires playwright-cli')
    module = Path(cli).resolve().parent / 'node_modules' / 'playwright'
    if not module.exists():
        pytest.skip('Playwright library is unavailable')
    issue = dict(problem_id='context_memory-B1-P1', phenomenon='Policy omitted', expected='Include policy',
                 observed='Policy missing', source_refs=[], input_refs=[], output_refs=['prompt'],
                 quotes=[dict(ref='prompt', quote='no policy here')],
                 attribution='local', attribution_detail='本轴', impact='用户看不到保单')
    cases = [dict(id='local-test', input='request', output='answer', axes=[
        dict(type_id='context_memory', status='succeeded', verdict='problematic', issues=[issue],
             composition={'counts': {'没达到': 1}}, evidence_records={'prompt': 'ACTUAL PROMPT BODY'}),
        dict(type_id='model_capability', status='succeeded', verdict='untested', issues=[],
             composition={'counts': {'没达到': 1, '问题·上游': 1}}, items=[{
                 'key': '输出忠实于输入 @ call1', 'value': '没达到', 'reason': '本应：…；实际：…'}])])]
    types = [dict(type_id=a, verdict_scope='axis', verdict_enum=[{'value': v}])
             for a, v in [('context_memory', 'problematic'), ('model_capability', 'untested')]]
    html = run_js('process.stdout.write(JSON.stringify(A.renderPage(input.cases,input.types)));', cases, types)
    code = f"const {{chromium}}=require({json.dumps(str(module))});" + r"""
const fs=require('fs'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.setContent(fs.readFileSync(0,'utf8'));
  await page.click('#matrix-mode');
  assert((await page.locator('.matrix-cell[data-axis-id="model_capability"]').textContent()).includes('问题·上游 1'));
  await page.locator('.matrix-cell[data-axis-id="context_memory"]').click();
  assert.equal(await page.locator('#issue-context_memory-B1-P1').count(),1);
  assert((await page.locator('.case-axis-detail').textContent()).includes('归因：本轴；对最终交付的影响：用户看不到保单'));
  await page.locator('.issue-evidence').filter({hasText:'引文 · prompt'}).locator('summary').click();
  assert.equal(await page.locator('.issue-evidence').filter({hasText:'引文 · prompt'}).locator('pre').textContent(),'ACTUAL PROMPT BODY');
  assert.deepEqual(errors,[]);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node', '-e', code], input=html, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
