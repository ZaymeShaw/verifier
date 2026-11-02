// Called by test_latest_run_frontend.py against an isolated API + SQLite database.
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);
const base = process.env.LATEST_RUN_TEST_URL;

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  let page;
  try {
    page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    const ready = () => page.waitForFunction(() => workspaceReady && !workspaceBusy);
    const snapshot = () => page.evaluate(() => casePool.map(item => {
      const v = caseView(item);
      return {key: item.request_key, status: executionStatus(v), output: v.output,
        judge: v.judge || null, axes: evalAxesRows(v), attribute: v.attribute || null};
    }));
    await page.goto(base + '/frontend/summary.html');
    await ready();
    assert.equal(await page.isDisabled('#batchTraceButton'), true);
    const cases = ['first input', 'second input'].map(text => ({id: 'duplicate-id', project_id: 'client_search',
      scenario: 'synthetic', intent: null, live_request: {user_text: text}, output: null, reference: null}));
    await page.fill('#casePoolText', JSON.stringify(cases));
    await page.getByRole('button', {name: '导入候选区', exact: true}).click();
    await page.waitForFunction(() => casePool.length === 2 && !workspaceBusy);
    await page.click('#batchRunButton');
    await page.waitForFunction(() => activeBatch && Object.keys(caseResults).length === 1);
    await page.reload();
    await page.waitForFunction(() => workspaceReady && activeBatch && Object.keys(caseResults).length === 1);
    const running = await snapshot();
    assert.deepEqual(running.map(r => r.status), ['done', 'running']);
    assert.equal(await page.isDisabled('#clearResultsButton'), true);
    const denied = await page.request.post(base + '/api/run_workspace/clear', {data: {project: 'client_search', keep_cases: true}});
    assert.equal(denied.status(), 409);
    await page.request.post(base + '/test/complete');
    await ready();
    const complete = await snapshot();
    assert.equal(complete.length, 2);
    assert(complete.every(r => r.status === 'done' && r.output && r.judge && r.axes.length === 1));
    await page.reload();
    await ready();
    assert.deepEqual(await snapshot(), complete);
    const firstTraceJob = await page.evaluate(() => traceBatch.job_id);
    assert.equal(firstTraceJob, complete[0].key.split(':')[0]);
    const opened = page.context().waitForEvent('page');
    await page.click('#batchTraceButton');
    const report = await opened;
    await report.waitForLoadState();
    assert.equal(new URL(report.url()).searchParams.get('job_id'), firstTraceJob);
    assert.equal(new URL(report.url()).searchParams.get('project'), 'client_search');
    assert.equal(await report.locator('h1').textContent(), 'Trace client_search');
    await report.close();
    await page.selectOption('#project', 'QA');
    await ready();
    assert.equal(await page.isDisabled('#batchTraceButton'), true);
    await page.selectOption('#project', 'client_search');
    await ready();
    assert.equal(await page.evaluate(() => traceBatch.job_id), firstTraceJob);

    // 新浏览器上下文没有 sessionStorage，也能取回后端当前候选区和结果。
    const fresh = await browser.newContext();
    const freshPage = await fresh.newPage();
    await freshPage.goto(base + '/frontend/summary.html');
    await freshPage.waitForFunction(() => workspaceReady && !workspaceBusy);
    assert.equal(await freshPage.evaluate(() => Object.keys(caseResults).length), 2);
    await fresh.close();

    await page.click('#manualAttributeButton');
    await page.waitForFunction(() => !workspaceBusy && Object.values(caseResults).every(r => r.attribute?.unresolved_reason === 'synthetic attribution'));
    const attributed = await snapshot();
    await page.reload();
    await ready();
    assert.deepEqual(await snapshot(), attributed);

    await page.evaluate(() => { selectAllCases(false); toggleCaseAt(1, true); });
    await page.click('#batchRunButton');
    await page.waitForFunction(oldKey => !workspaceBusy && casePool[1].request_key !== oldKey && Object.keys(caseResults).length === 2, complete[1].key);
    const partial = await snapshot();
    assert.equal(partial[0].key, complete[0].key);
    assert.notEqual(partial[1].key, complete[1].key);
    assert.equal(partial[0].attribute.unresolved_reason, 'synthetic attribution');
    await page.reload();
    await ready();
    assert.deepEqual(await snapshot(), partial);
    assert.equal(await page.evaluate(() => traceBatch.job_id), partial[1].key.split(':')[0]);
    assert.notEqual(await page.evaluate(() => traceBatch.job_id), firstTraceJob);

    // 批次中断是可显示的运行结果，不应被 HTTP helper 提前吞掉，也不能复活旧成功。
    await page.request.post(base + '/test/fail_next');
    await page.evaluate(() => selectAllCases(true));
    await page.click('#batchRunButton');
    await page.waitForFunction(() => !workspaceBusy && !activeBatch && casePool[1].status === 'error');
    const interrupted = await snapshot();
    assert.deepEqual(interrupted.map(r => r.status), ['done', 'error']);
    assert.equal(interrupted[1].judge, null);
    await page.reload();
    await ready();
    assert.deepEqual(await snapshot(), interrupted);
    await page.click('#rerunFailuresButton');
    await page.waitForFunction(() => !workspaceBusy && casePool.every(item => executionStatus(caseView(item)) === 'done'));
    assert.equal((await snapshot())[0].key, interrupted[0].key);

    await page.click('#clearResultsButton');
    await page.waitForFunction(() => !workspaceBusy && Object.keys(caseResults).length === 0);
    await page.reload();
    await ready();
    assert.equal(await page.isDisabled('#batchTraceButton'), true);
    const cleared = await snapshot();
    assert.deepEqual(cleared.map(r => r.status), ['pending', 'pending']);
    assert(cleared.every(r => !r.key && !r.judge && !r.output && !r.axes.length));
    await page.evaluate(() => selectAllCases(true));
    await page.click('#batchRunButton');
    await page.waitForFunction(() => !workspaceBusy && Object.keys(caseResults).length === 2);
    await page.click('#clearPoolButton');
    await page.waitForFunction(() => !workspaceBusy && casePool.length === 0);
    await page.reload();
    await ready();
    assert.equal(await page.evaluate(() => casePool.length), 0);
    assert.equal(await page.evaluate(() => Object.keys(caseResults).length), 0);
    assert.deepEqual(errors, []);
    console.log('latest-workspace-browser: passed (running/completed reload, new tab, attribution, partial rerun, clear results, clear pool)');
  } catch (error) {
    if(page){console.error('browser state', await page.evaluate(() => ({status:document.querySelector('#progressText')?.textContent,log:document.querySelector('#progressLog')?.textContent,ready:workspaceReady,busy:workspaceBusy,cases:casePool.length,results:Object.keys(caseResults).length,active:activeBatch})));}
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
