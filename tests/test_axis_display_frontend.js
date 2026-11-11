const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../impl/frontend/summary.html'), 'utf8');
for (const script of source.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
  new vm.Script(script[1]);
}
const button = {textContent: '导出', disabled: false};
const messages = [], downloads = [];
let selectedProject = 'demo';
let entries = [];
const context = vm.createContext({
  workspaceEpoch: 0,
  document: {getElementById: () => button},
  project: () => selectedProject,
  currentFilteredCaseViews: () => entries,
  setStatus: text => messages.push(text),
  // Existing non-axis case columns are outside this test's scope.
  runModeLabel: () => '', caseInputPayload: () => ({}), caseReference: () => null,
  exportStatusText: () => '', exportJudgeSummary: () => '', exportAttributionSummary: () => '',
  exportTraceSummary: () => '',
  CasePoolExporter: {download: async options => {
    downloads.push(options);
    return {rowCount: options.rows.length, fileName: 'test.xlsx'};
  }},
});
for (const name of ['tableRow', 'evalAxesRows', 'axisShown', 'inferCaseScenario', 'carrierPlacementText',
  'executionFailureMarkers', 'flagsFromQuality', 'flagsFromRun', 'exportCaseFulfillment',
  'exportAxisProblemTag', 'exportProblemTags', 'exportEvalAxes', 'exportEvalAxesSummaryRows', 'exportEvalAxesDetailRows',
  'buildCasePoolExportRows', 'exportCurrentCasePoolXlsx']) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  const tail = source.slice(start);
  const next = tail.search(/\n(?:async )?function /);
  assert.ok(next >= 0, name);
  vm.runInContext(tail.slice(0, next), context);
}
const policy = {axes: {
  custom_axis: {attention_verdicts: ['bad', 'untested']},
  another_axis: {attention_verdicts: ['not_evaluable']},
}};
const view = {id: 'case-1', table_row: {id: 'case-1', fulfillment_status: 'not_fulfilled', eval_axes_summary: [
  {type_id: 'custom_axis', axis_id: 'run-1', display: 'collapsed', status: 'succeeded', verdict: 'bad'},
  {type_id: 'custom_axis', status: 'succeeded', verdict: 'bad'},
  {axis_id: 'another_axis', status: 'succeeded', verdict: 'not_evaluable'},
  {type_id: 'custom_axis', status: 'failed', verdict: 'untested'},
  {type_id: 'custom_axis', status: 'running', verdict: 'untested'},
  {type_id: 'custom_axis', status: 'disabled', verdict: 'untested'},
  {type_id: 'custom_axis', status: 'succeeded', items: [{value: 'untested'}]},
  {type_id: 'unconfigured', status: 'succeeded', verdict: 'bad'},
]}};
const expected = '[custom_axis:bad]\n[another_axis:not_evaluable]';
assert.equal(context.exportProblemTags(view, policy), expected);
assert.equal(context.exportProblemTags(view, {axes: {}}), '');
assert.equal(context.exportProblemTags({}, policy), '');
assert.equal(context.exportProblemTags({eval_axes_summary: [{type_id: 'custom_axis', status: 'succeeded', verdict: 'untested'}]}, policy), '[custom_axis:untested]');
for (const status of ['fulfilled', 'not_fulfilled', 'not_evaluable']) {
  assert.equal(context.exportCaseFulfillment({table_row: {fulfillment_status: status}}), status);
  assert.equal(context.exportCaseFulfillment({judge: {overall_fulfillment: {status}}}), status);
}
for (const invalid of [
  {}, {status: 'fulfilled'}, {table_row: {fulfillment_status: 'fail'}},
  {...view, status: 'running'}, {...view, status: 'error'}, {...view, error: 'failed'},
  {table_row: {fulfillment_status: 'not_evaluable', quality_flags: ['evaluation_execution_failed']}},
  {judge: {overall_fulfillment: {status: 'not_evaluable'}, evidence: ['llm_call_failed']}},
]) {
  assert.equal(context.exportCaseFulfillment(invalid), '');
}
assert.ok(context.exportEvalAxesSummaryRows(view, policy).every(row => row.caseFulfillment === 'not_fulfilled'));
assert.equal(context.exportEvalAxesSummaryRows(view, policy).map(row => row.problemTag).join(','), '是,是,是,否,否,否,否');
assert.ok(context.exportEvalAxesSummaryRows(view, {axes: {}}).every(row => row.problemTag === '否'));
const projectPolicy = JSON.parse(fs.readFileSync(path.join(__dirname, '../impl/data/llm_probe_loop/axis_display.json'), 'utf8'));
for (const verdict of ['做成了', '没做成', '做不了', '不确定']) {
  const mainView = {eval_axes_summary: [{type_id: 'main_verdict', status: 'succeeded', verdict}]};
  const expectedTag = verdict === '做成了' ? '' : '[main_verdict:' + verdict + ']';
  assert.equal(context.exportProblemTags(mainView, projectPolicy), expectedTag);
  assert.equal(context.exportEvalAxesSummaryRows(mainView, projectPolicy)[0].problemTag, expectedTag ? '是' : '否');
}

async function main() {
  entries = [{item: {id: view.id}, view}];
  let requests = 0;
  context.post = async (url, payload) => {
    assert.equal(url, '/api/axis_display');
    assert.equal(payload.project, 'demo');
    requests++;
    return policy;
  };
  await context.exportCurrentCasePoolXlsx();
  assert.equal(downloads[0].rows[0].problemTags, expected);
  assert.ok(downloads[0].axisRows.every(row => row.caseFulfillment === 'not_fulfilled'));
  assert.equal(downloads[0].axisRows.length, 7); // disabled omitted, all other axes retained
  assert.equal(downloads[0].axisRows.filter(row => row.problemTag === '是').length, 3);
  assert.equal(button.disabled, false);
  await context.exportCurrentCasePoolXlsx();
  assert.equal(requests, 2); // config is read for every export
  context.post = async () => ({axes: {}});
  await context.exportCurrentCasePoolXlsx();
  assert.equal(downloads[2].rows[0].problemTags, '');
  assert.ok(downloads[2].axisRows.every(row => row.problemTag === '否'));
  const count = downloads.length;
  context.post = async () => {throw new Error('axis_display.json invalid');};
  await context.exportCurrentCasePoolXlsx();
  assert.equal(downloads.length, count);
  assert.match(messages.at(-1), /导出失败.*axis_display.json invalid/);
  context.post = async () => {selectedProject = 'other'; context.workspaceEpoch++; return policy;};
  await context.exportCurrentCasePoolXlsx();
  assert.equal(downloads.length, count);
  assert.match(messages.at(-1), /项目已切换/);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, '导出');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
