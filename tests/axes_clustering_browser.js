const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.CLUSTER_TEST_URL;
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 let page;
 try {
  const context=await browser.newContext();
  const parent=await context.newPage();
  await parent.goto(base+'/frontend/summary.html');
  await parent.waitForFunction(()=>workspaceReady);
  const opened=parent.waitForEvent('popup');
  await parent.getByRole('button',{name:'展示试验：轴分布',exact:true}).click();
  page=await opened;
  assert(page.url().includes('axes_experiment.html#'));
  const ready=()=>page.waitForFunction(()=>{const criteria=document.querySelector('#clustering-criteria');return criteria && !criteria.disabled;});
  const calls=async()=> (await (await page.request.get(base+'/test/calls')).json()).criteria;
  await ready();
  const cold=await page.inputValue('#clustering-criteria');assert(cold.length>30);
  assert.deepEqual(await calls(),[]);
  await page.fill('#clustering-criteria','saved without model');
  await page.click('#save-clustering-criteria');
  await page.waitForFunction(()=>document.querySelector('#criteria-version').textContent.includes('v2')&&!document.querySelector('#clustering-criteria').disabled);
  assert.deepEqual(await calls(),[]);
  await page.reload();await ready();
  assert.equal(await page.inputValue('#clustering-criteria'),'saved without model');
  await page.fill('#clustering-criteria','pause standard');
  await page.click('#start-clustering');
  await page.waitForFunction(()=>document.querySelector('#clustering-status').textContent.includes('正在按标准 v3'));
  assert.equal(await page.isDisabled('#start-clustering'),true);
  assert.equal(await page.locator('#start-clustering').textContent(),'聚类中…');
  assert.equal(await page.locator('#clustering-feedback').getAttribute('data-phase'),'running');
  assert.equal(await page.locator('#model-progress progress').getAttribute('value'),null);
  assert((await page.locator('#model-progress').textContent()).includes('等待模型返回'));
  assert((await page.locator('#model-progress').textContent()).includes('单次模型请求时限'));
  assert((await page.locator('#model-progress').textContent()).includes('暂不能可靠估计'));
  assert((await page.locator('#batch-progress').textContent()).includes('2 / 2'));
  assert.equal(await page.locator('#view-clustering-result').isVisible(),false);
  await page.reload();await ready();
  assert.equal(await page.inputValue('#clustering-criteria'),'pause standard');
  assert.deepEqual(await calls(),['pause standard']);
  // 模型运行时改标准，旧任务完成后不能覆盖最新标准或发布过期聚类。
  await page.fill('#clustering-criteria','new standard');
  await page.click('#save-clustering-criteria');
  await page.waitForFunction(()=>document.querySelector('#criteria-version').textContent.includes('v4')&&!document.querySelector('#clustering-criteria').disabled);
  await page.request.post(base+'/test/release');
  await page.waitForFunction(()=>document.querySelector('#clustering-status').textContent.includes('旧聚类不再使用'));
  assert.equal(await page.locator('.cluster-name').count(),0);
  assert.equal(await page.inputValue('#clustering-criteria'),'new standard');
  await page.click('#start-clustering');
  await page.waitForFunction(()=>document.querySelector('#clustering-status').textContent.includes('完成聚类'));
  assert.deepEqual(await calls(),['pause standard','new standard']);
  assert.equal(await page.locator('.cluster-name').count(),4);
  assert.equal(await page.locator('#clustering-headline').textContent(),'聚类完成 · 4 类情况 / 2 个案例');
  assert.equal(await page.locator('#clustering-feedback').getAttribute('data-phase'),'completed');
  assert.equal(await page.locator('#view-clustering-result').isVisible(),true);
  // 结果按钮只清除本页筛选并定位目录，不再调用模型。
  await page.click('#matrix-mode');
  await page.fill('#case-search','nothing matches this');
  await page.click('#view-clustering-result');
  assert.equal(await page.locator('#group-view').isVisible(),true);
  assert.equal(await page.inputValue('#case-search'),'');
  assert.equal(await page.locator('.cluster-name').count(),4);
  assert.deepEqual(await calls(),['pause standard','new standard']);
  const names=await page.locator('.cluster-name').allTextContents();
  assert.deepEqual(names,['situation-R4','situation-R2','situation-R3','situation-R1']);
  assert.equal(await page.locator('.type-label').count(),2);
  assert.equal(await page.locator('.type-entry[aria-pressed=true] .cluster-name').textContent(),'situation-R4');
  await page.locator('.group-case-open').first().click();
  assert.equal(JSON.parse(await page.locator('.case-input-value').textContent()).q,'input-1');
  assert.equal(JSON.parse(await page.locator('.case-output-value').textContent()).answer,'output-1');
  await page.reload();await ready();
  assert.equal(await page.locator('#view-clustering-result').isVisible(),true);
  assert.deepEqual(await page.locator('.cluster-name').allTextContents(),names);
  assert.deepEqual(await calls(),['pause standard','new standard']);
  // 父页关闭后，新页仍可刷新读取后端结果，不依赖 Blob 或父页内存。
  await parent.close();await page.reload();await ready();
  assert.deepEqual(await page.locator('.cluster-name').allTextContents(),names);
  await page.fill('#clustering-criteria','local unsaved');
  const external=await page.request.post(base+'/api/axes_clustering/criteria',{data:{project:'llm_probe',criteria:'external standard',expected_version:4}});
  assert.equal(external.status(),200);
  await page.click('#save-clustering-criteria');
  await page.waitForFunction(()=>document.querySelector('#clustering-status').textContent.includes('其他页面更新'));
  assert.equal(await page.inputValue('#clustering-criteria'),'local unsaved');
  assert.equal(await page.locator('.cluster-name').count(),0);
  page.once('dialog',d=>d.accept());
  await page.click('#reload-clustering');await page.waitForFunction(()=>document.querySelector('#clustering-criteria').value==='external standard');
  assert((await page.locator('#criteria-version').textContent()).includes('v5'));
  assert.deepEqual(await calls(),['pause standard','new standard']);
  // 旧快照不可冒充新结果，但页面必须提供明确的恢复入口。
  async function replaceCurrent(ids) {
    const response=await page.request.post(base+'/api/run_workspace/replace',{data:{project:'llm_probe',source:'test replacement',cases:ids.map(id=>({id,project_id:'llm_probe',scenario:'test',intent:null,live_request:{q:id},output:null,reference:null}))}});
    assert.equal(response.status(),200);
  }
  await replaceCurrent(['replacement-1']);
  await page.reload();
  await page.waitForSelector('#open-current:not([hidden])');
  assert.equal(await page.locator('#loading-title').textContent(),'旧筛选已过期');
  assert((await page.locator('#recovery-note').textContent()).includes('不沿用旧筛选'));
  assert.equal(await page.locator('.cluster-name').count(),0);
  await page.click('#open-current');await ready();
  assert.equal(new URL(page.url()).searchParams.get('project'),'llm_probe');
  assert.equal(new URL(page.url()).hash,'');
  await page.click('#matrix-mode');
  assert.equal(await page.locator('.matrix-row').count(),1);
  await page.locator('.case-open').click();
  assert.equal(JSON.parse(await page.locator('.case-input-value').textContent()).q,'replacement-1');
  // 主动选择“当前候选区”后，之后刷新始终读取当前记录，不再绑定旧 run 编号。
  await replaceCurrent(['replacement-2','replacement-3']);
  await page.reload();await ready();
  await page.click('#matrix-mode');
  assert.equal(await page.locator('.matrix-row').count(),2);
  assert.equal(await page.locator('#open-current').count(),0);
  assert.deepEqual(await calls(),['pause standard','new standard']);
  // 聚类暂时被运行中的批次阻止，不应阻断原始案例页面。
  await page.route('**/api/axes_clustering/state',route=>route.fulfill({status:409,json:{error:'synthetic running batch'}}));
  await page.reload();await page.waitForSelector('#clustering-feedback[data-phase="blocked"]');
  assert.equal(await page.locator('.matrix-row').count(),2);
  assert((await page.locator('#clustering-headline').textContent()).includes('最后已知进度'));
  await page.unroute('**/api/axes_clustering/state');
  await page.request.post(base+'/test/hold-batch');
  await page.reload();await ready();
  assert.equal(await page.locator('#batch-progress').getAttribute('data-status'),'running');
  assert((await page.locator('#batch-progress').textContent()).includes('0 / 2'));
  assert.equal(await page.isDisabled('#start-clustering'),true);
  await page.request.post(base+'/test/finish-batch');
  // 无需手动刷新，批次完成后自动收到 2/2。刷新数据前禁止拿旧页面材料去聚类。
  await page.waitForSelector('#batch-progress[data-status="completed"]');
  assert((await page.locator('#batch-progress').textContent()).includes('2 / 2'));
  assert((await page.locator('#clustering-headline').textContent()).includes('刷新运行结果'));
  assert.equal(await page.isDisabled('#start-clustering'),true);
  assert.deepEqual(await calls(),['pause standard','new standard']);
  await page.click('#refresh-run-results');await ready();
  assert.equal(await page.isDisabled('#start-clustering'),false);
  await replaceCurrent([]);
  await page.reload();await page.waitForSelector('#loading-actions:not([hidden])');
  assert.equal(await page.locator('#loading-title').textContent(),'当前没有用例');
  assert.equal(await page.locator('#open-current').isVisible(),false);
  console.log('clustering frontend: passed');
 } catch(e) {
  if(page&&!page.isClosed()){console.error(await page.evaluate(()=>({status:document.querySelector('#clustering-status')?.textContent,version:document.querySelector('#criteria-version')?.textContent,clusters:document.querySelectorAll('.cluster-name').length})));}
  throw e;
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
