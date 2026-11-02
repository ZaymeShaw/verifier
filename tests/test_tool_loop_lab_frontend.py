import copy
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from impl.tool_loop_lab import connection, service, store
from impl.tool_loop_lab.connection import Connection
from impl.tool_loop_lab.store import LabStore
from impl.tool_loop_lab.__main__ import create_app


def test_lab_browser_run_observe_reload_and_overwrite(tmp_path, monkeypatch):
    cli = shutil.which('playwright-cli')
    if not cli: pytest.skip('requires playwright-cli')
    module = Path(cli).resolve().parent / 'node_modules' / 'playwright'
    if not module.exists(): pytest.skip('requires Playwright library')
    monkeypatch.setattr(store, 'STORE', LabStore(tmp_path / 'lab.sqlite3'))
    monkeypatch.setattr(connection, 'ENV_PATH', tmp_path / '.env.tool_loop')
    for key in connection.NAMES: monkeypatch.delenv(key, raising=False)
    # 整个供应商连接在进程内模拟，浏览器运行不允许发出真实模型请求。
    import httpx
    from impl.core import llm_client, context_store
    sdk = llm_client.OpenAI
    provider_calls = []
    def reject(request):
        provider_calls.append(request)
        return httpx.Response(401, json={'error': {'message': 'invalid API key: sk-browser-secret'}})
    monkeypatch.setattr(llm_client, 'OpenAI', lambda **kw: sdk(http_client=httpx.Client(transport=httpx.MockTransport(reject)), **kw))
    monkeypatch.setattr(context_store, 'save_context', lambda record: '')
    # 在本地脚本的有效提交前插入一份结构合法但成员重叠的提交，验证真实 hook/UI 链路。
    from tests.test_tool_loop_clustering_overlap import with_overlapping_class
    original_examples = service.load_examples
    def examples_with_overlap():
        module = original_examples()
        factory = module['EXAMPLES']['clustering']['script_client']
        def scripted():
            client = factory()
            messages = list(client.steps)
            index = max(i for i, m in enumerate(messages) if any(
                c['function']['name'] == 'submit_clustering' for c in m.get('tool_calls', [])))
            overlapping = copy.deepcopy(messages[index])
            fn = overlapping['tool_calls'][0]['function']
            fn['arguments'] = json.dumps(with_overlapping_class(json.loads(fn['arguments'])), ensure_ascii=False)
            messages.insert(index, overlapping)
            client.steps = iter(messages)
            return client
        module['EXAMPLES']['clustering']['script_client'] = scripted
        return module
    monkeypatch.setattr(service, 'load_examples', examples_with_overlap)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    from tests.test_tool_loop_alignment import source_reader, workspace
    source_workspace = workspace()
    read_source, source_calls = source_reader(source_workspace)
    app = create_app()

    @app.post('/api/run_workspace')
    def source_cases(payload: dict): return read_source('/api/run_workspace', payload)

    @app.post('/api/eval_axes/types')
    def source_types(payload: dict): return read_source('/api/eval_axes/types', payload)

    @app.post('/api/axes_clustering/state')
    def source_clusters(payload: dict): return read_source('/api/axes_clustering/state', payload)

    @app.post('/test/source-update')
    def update_source():
        source_workspace['runs'][0]['trace']['input'] = {'q': 'updated source'}
        return {'ok': True}

    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.02)
        assert server.started
        script = r'''
const {chromium}=require(process.env.PLAYWRIGHT_MODULE),assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({channel:'chrome',headless:true});let p;try{
 p=await b.newPage({viewport:{width:1400,height:1000}});
 const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(process.env.LAB_URL);
 await p.waitForFunction(()=>document.querySelector('#example').options.length===3&&!document.querySelector('#run').disabled);
 assert.equal(await p.inputValue('#mode'),'scripted');
 assert((await p.locator('#model-info').textContent()).includes('未配置'));
 await p.selectOption('#mode','model');assert.equal(await p.isDisabled('#run'),true);
 await p.selectOption('#mode','scripted');
 await p.selectOption('#example','checked');
 assert((await p.locator('#definition').textContent()).includes('RequireDone'));
 assert((await p.locator('#source').textContent()).includes('completion_hook=RequireDone'));
 const input='<img src=x onerror=alert(1)> this is a literal test input';
 await p.fill('#input',input);await p.click('#run');
 await p.waitForSelector('#status[data-state=complete]');
 const events=p.locator('.event');
 assert((await p.locator('#timeline').textContent()).includes('Continue'));
 assert((await p.locator('#timeline').textContent()).includes('Deny'));
 assert((await p.locator('#timeline').textContent()).includes('提交未被接受'));
 assert((await p.locator('#timeline').textContent()).includes('Done'));
 assert.equal(await p.locator('img').count(),0);
 const output=JSON.parse(await p.locator('#output').textContent());
 assert.deepEqual(output.evidence_ids,['note']);
 assert.notEqual(await p.locator('#last-message').textContent(),output.answer);
 const count=await events.count();
 const config=(await p.locator('#config-source').textContent());assert(config.includes('冻结'));
 await p.reload();await p.waitForSelector('#status[data-state=complete]');
 assert.equal(await p.inputValue('#example'),'checked');assert.equal(await p.inputValue('#input'),input);
 assert.equal(await events.count(),count);
 assert.deepEqual(JSON.parse(await p.locator('#output').textContent()),output);
 await p.selectOption('#example','basic');await p.click('#run');
 await p.waitForFunction(()=>document.querySelector('#status').dataset.state==='complete'&&!document.querySelector('#timeline').textContent.includes('RequireDone'));
 assert((await p.locator('#output').textContent()).includes('周三'));
 assert((await p.locator('#mode-note').textContent()).includes('脚本演示'));
 await p.selectOption('#example','clustering');await p.click('#run');
 await p.waitForSelector('#artifact-card:not([hidden])');
 const report=p.frameLocator('#artifact-preview');
 await report.locator('.cluster-name').first().waitFor();
 assert.equal(await report.locator('.cluster-name').count(),5);
 assert((await p.locator('.event[data-kind=hook] .event-note').allTextContents()).some(t=>t.includes('Hook 拒绝提交：')&&t.includes('重叠率')));
 assert((await p.locator('.event[data-kind=tool_result] .event-note').allTextContents()).some(t=>t.includes('工具校验通过（最终是否接受还需后续 Hook 检查）')));
 assert((await report.locator('.artifact-banner').textContent()).includes('脚本演示'));
 assert.equal(await report.locator('.clustering-controls').isVisible(),false);
 for(const width of [1400,390]){
  await p.setViewportSize({width,height:1000});
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);
  assert.equal(await report.locator('html').evaluate(el=>el.scrollWidth),await report.locator('html').evaluate(()=>innerWidth));
 }
 await p.setViewportSize({width:1400,height:1000});
 const calls=[];p.context().on('request',r=>{if(r.url().includes('/api/'))calls.push(new URL(r.url()).pathname)});
 await report.locator('.type-entry').filter({hasText:'工具结果在交接中丢失'}).click();
 assert.equal(await report.locator('.group-member').count(),2);
 assert.equal(await report.locator('.member-evidence-quote').count(),2);
 assert((await report.locator('.member-evidence').first().textContent()).includes('仅校验出处'));
 assert((await report.locator('.member-evidence-quote').first().textContent()).includes('后续模型输入缺少这次工具消息'));
 assert((await report.locator('.group-reason-text').first().textContent()).includes('库存数'));
 await report.locator('.group-case-open').first().click();
 assert.equal(JSON.parse(await report.locator('.case-input-value').textContent()).query,'现在有库存吗？');
 assert.equal(JSON.parse(await report.locator('.case-output-value').textContent()).answer,'我无法获得库存信息。');
 const tabPromise=p.context().waitForEvent('page');await p.click('#artifact-link');const tab=await tabPromise;
 await tab.waitForSelector('.cluster-name');assert.equal(await tab.locator('.cluster-name').count(),5);
 await tab.reload();await tab.waitForSelector('.cluster-name');
 assert((await tab.locator('.member-evidence-quote').count())>0);
 await p.reload();await p.waitForSelector('#artifact-card:not([hidden])');
 await p.frameLocator('#artifact-preview').locator('.cluster-name').first().waitFor();
 assert.equal(await p.frameLocator('#artifact-preview').locator('.cluster-name').count(),5);
 assert((await p.locator('.event[data-kind=hook] .event-note').allTextContents()).some(t=>t.includes('Hook 拒绝提交：')&&t.includes('重叠率')));
 assert(!calls.includes('/api/tool_loop_lab/start')&&!calls.includes('/api/axes_clustering/start'));
 await p.selectOption('#example','basic');await p.click('#run');
 await p.waitForSelector('#artifact-card[hidden]',{state:'attached'});
 await p.waitForSelector('#status[data-state=complete]');
 await tab.reload();await tab.waitForFunction(()=>document.querySelector('#artifact-loading')?.textContent.includes('已被替换'));
 assert.equal(await tab.locator('.cluster-name').count(),0);
 await tab.close();
 // 再留下一个两轴合成产物，验证它不会冒充之后对齐的真实材料。
 await p.selectOption('#example','clustering');await p.click('#run');
 await p.waitForSelector('#artifact-card:not([hidden])');
 await p.frameLocator('#artifact-preview').locator('.cluster-name').first().waitFor();
 // 手动对齐：不调用模型，先核对真正复制来的 case，再显式更新。
 await p.fill('#source-url',new URL(process.env.LAB_URL).origin);
 await p.click('#sync-cases');
 await p.waitForFunction(()=>document.querySelector('#alignment-status').textContent.includes('2 个 case')&&!document.querySelector('#sync-cases').disabled);
 assert.equal(await p.inputValue('#data-source'),'aligned');
 assert.equal(await p.inputValue('#mode'),'model');
 assert.equal(await p.isDisabled('#run'),true); // 独立模型没有配置，但仍能看对齐预览。
 assert.equal(await p.locator('#aligned-data-card').isVisible(),true);
 assert.equal(await p.locator('.aligned-axis').count(),1);
 assert((await p.locator('#aligned-data-title').textContent()).includes('2 个 case / 1 个轴'));
 assert((await p.locator('#artifact-title').textContent()).includes('当前聚类工作区 · 1 轴'));
 assert((await p.locator('#previous-artifact-link').textContent()).includes('2轴'));
 assert.equal(await p.locator('#artifact-preview').isVisible(),true);
 await p.frameLocator('#artifact-preview').locator('.type-scope').first().waitFor();
 assert.equal(await p.frameLocator('#artifact-preview').locator('.type-scope').count(),1);
 assert.equal(await p.frameLocator('#artifact-preview').locator('.cluster-name').count(),0);
 assert.equal(await p.locator('#artifact-card').getAttribute('data-phase'),'pending');
 const callsBeforeReload=calls.filter(path=>path==='/api/tool_loop_lab/start').length;
 await p.reload();
 await p.waitForFunction(()=>document.querySelector('#aligned-data-card')?.hidden===false&&document.querySelectorAll('.aligned-axis').length===1);
 assert.equal(await p.inputValue('#data-source'),'aligned');assert.equal(await p.inputValue('#mode'),'model');
 assert.equal(await p.locator('#artifact-preview').isVisible(),true);
 await p.frameLocator('#artifact-preview').locator('.type-scope').first().waitFor();
 assert.equal(await p.frameLocator('#artifact-preview').locator('.type-scope').count(),1);
 assert.equal(calls.filter(path=>path==='/api/tool_loop_lab/start').length,callsBeforeReload);
 // 用户实际点错的旧产物链接必须标清来源，并直接提供当前材料入口。
 const oldOpen=p.context().waitForEvent('page');await p.click('#previous-artifact-link');const oldArtifact=await oldOpen;
 await oldArtifact.waitForSelector('#page-provenance');
 assert((await oldArtifact.locator('#page-provenance h1').textContent()).includes('8 个 case / 2 个轴'));
 assert.equal(await oldArtifact.locator('.cluster-name').count(),5);
 await oldArtifact.click('#current-materials');
 await oldArtifact.waitForFunction(()=>document.querySelector('#page-provenance h1')?.textContent.includes('聚类工作区'));
 assert((await oldArtifact.locator('#page-provenance h1').textContent()).includes('2 个 case / 1 个轴'));
 assert.equal(await oldArtifact.locator('.axis-row').count(),1);
 assert.equal(await oldArtifact.locator('#group-view').isVisible(),true);
 assert.equal(await oldArtifact.locator('.type-scope').count(),1);
 await oldArtifact.click('#matrix-mode');
 assert.equal(await oldArtifact.locator('.clustering-controls').isVisible(),false);
 assert.equal(await oldArtifact.locator('.cluster-name').count(),0);
 await oldArtifact.locator('.case-open').first().click();
 assert.equal(JSON.parse(await oldArtifact.locator('.case-input-value').textContent()).q,'actual-0');
 await oldArtifact.reload();await oldArtifact.waitForSelector('#page-provenance');
 assert.equal(await oldArtifact.locator('.axis-row').count(),1);
 assert.equal(calls.filter(path=>path==='/api/tool_loop_lab/start').length,callsBeforeReload);
 await oldArtifact.close();
 await p.click('#source-criteria');assert.equal(await p.inputValue('#input'),'source criteria');
 const previewOpen=p.context().waitForEvent('page');await p.click('#alignment-preview');const preview=await previewOpen;
 await preview.waitForSelector('.case-link');assert.equal(await preview.locator('.case-link').count(),2);
 await preview.locator('.case-link').first().click();
 assert.equal(JSON.parse(await preview.locator('.case-input').textContent()).q,'actual-0');
 assert.equal(await preview.locator('.case-output').textContent(),'0');
 assert((await preview.locator('#comparison-rows').textContent()).includes('DO_NOT_FEED_BASELINE'));
 assert((await preview.locator('#comparison-rows').textContent()).includes('不在源聚类范围内'));
 await p.request.post(new URL('/test/source-update',process.env.LAB_URL).href);
 await preview.reload();await preview.waitForSelector('.case-link');await preview.locator('.case-link').first().click();
 assert.equal(JSON.parse(await preview.locator('.case-input').textContent()).q,'actual-0'); // 不自动跟源侧漂移。
 const previousLink=await p.locator('#alignment-preview').getAttribute('href');
 await p.click('#sync-cases');
 await p.waitForFunction(old=>document.querySelector('#alignment-preview').getAttribute('href')!==old&&!document.querySelector('#sync-cases').disabled,previousLink);
 await preview.reload();await preview.waitForFunction(()=>document.querySelector('#error').textContent.includes('已被替换'));
 const nextOpen=p.context().waitForEvent('page');await p.click('#alignment-preview');const next=await nextOpen;
 await next.waitForSelector('.case-link');await next.locator('.case-link').first().click();
 assert.equal(JSON.parse(await next.locator('.case-input').textContent()).q,'updated source');
 await next.close();await preview.close();
 // 在本页面保存独立模型；不调用供应商，不回显或存储 Key。
 await p.fill('#model-url','https://supplier.example/v1');
 await p.fill('#model-name','strong-model');
 await p.fill('#model-key','sk-browser-secret');
 await p.locator('#model-form details summary').click();
 await p.fill('#model-temperature','1');
 const savedResponse=p.waitForResponse(r=>r.url().endsWith('/api/tool_loop_lab/model')&&r.request().method()==='POST');
 await p.click('#save-model');const saved=await savedResponse;
 assert.equal(saved.status(),200);assert(!(await saved.text()).includes('sk-browser-secret'));
 await p.waitForFunction(()=>document.querySelector('#model-config-status').textContent.includes('已保存到独立配置'));
 assert.equal(await p.inputValue('#model-key'),'');
 assert.equal(await p.isDisabled('#run'),false);
 assert(!(await p.locator('body').textContent()).includes('sk-browser-secret'));
 assert.equal(await p.evaluate(()=>localStorage.length+sessionStorage.length),0);
 await p.reload();await p.waitForFunction(()=>document.querySelector('#model-name')?.value==='strong-model');
 assert.equal(await p.inputValue('#model-url'),'https://supplier.example/v1');
 assert.equal(await p.inputValue('#model-temperature'),'1');
 assert.equal(await p.inputValue('#model-key'),'');
 assert((await p.getAttribute('#model-key','placeholder')).includes('已保存'));
 await p.fill('#model-name','stronger-model');await p.click('#save-model');
 await p.waitForFunction(()=>document.querySelector('#model-config-status').textContent.includes('已保存到独立配置'));
 assert.equal(await p.inputValue('#model-key'),'');
 // 实际错误必须在主页面可见，刷新保留且不自动发起第二次运行。
 await p.click('#run');await p.waitForSelector('#status[data-state=failed]');
 assert((await p.locator('#status').textContent()).includes('401'));
 assert((await p.locator('#status').textContent()).includes('invalid API key'));
 assert((await p.locator('#status').textContent()).includes('健康检查失败'));
 assert(!(await p.locator('body').textContent()).includes('sk-browser-secret'));
 const failedStarts=calls.filter(path=>path==='/api/tool_loop_lab/start').length;
 await p.reload();await p.waitForSelector('#status[data-state=failed]');
 assert((await p.locator('#status').textContent()).includes('invalid API key'));
 assert.equal(calls.filter(path=>path==='/api/tool_loop_lab/start').length,failedStarts);
 assert.equal(await p.frameLocator('#artifact-preview').locator('.cluster-name').count(),0);
 for(const width of [1400,390]){await p.setViewportSize({width,height:1000});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);}
 assert.deepEqual(errors,[]);
}catch(error){if(p){console.error('UI',await p.evaluate(()=>({state:document.querySelector('#status-title')?.textContent,cardHidden:document.querySelector('#artifact-card')?.hidden,frameHeight:document.querySelector('#artifact-preview')?.getBoundingClientRect().height,artifactError:document.querySelector('#artifact-error')?.textContent})));}throw error;}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], env={**os.environ, 'PLAYWRIGHT_MODULE': str(module),
                                'LAB_URL': f'http://127.0.0.1:{port}/frontend/tool_loop_lab.html'},
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(provider_calls) == 1
        assert json.loads(provider_calls[0].content)['temperature'] == 1
        assert {path for path, _ in source_calls} == {'/api/run_workspace', '/api/eval_axes/types', '/api/axes_clustering/state'}
    finally:
        server.should_exit = True;thread.join(10);sock.close()
