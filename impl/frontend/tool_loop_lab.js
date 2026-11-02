(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  let modelSettings=null,modelSaving=false,modelDirty=false,alignedView=null,aligned=null,syncing=false,artifactRun=null,catalog=null,current=null,runId=null,after=0,pollTimer=null,submitting=false,receivedAt=null,serverNow=null,lastEvent=null,eventCount=0,stopped=false,networkError='';
  const names={run_start:'运行开始',model_request:'模型请求',model_response:'模型返回',model_error:'模型请求失败',
    tool_start:'执行工具',tool_result:'工具返回',tool_error:'工具执行错误',hook:'Hook 检查',hook_error:'Hook 执行错误',run_end:'运行结束',run_error:'运行失败'};
  const text=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
  function node(tag,content,cls){const el=document.createElement(tag);if(content!==undefined)el.textContent=content;if(cls)el.className=cls;return el;}
  async function request(path,body,timeout=15000){
    const res=await fetch('/api/tool_loop_lab/'+path,{...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(timeout)});
    const data=await res.json();if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));return data;
  }
  function selected(){return catalog?.examples.find(e=>e.id===$('example').value);}
  function controls(){
    const busy=current?.status==='running';
    const clustering=$('example').value==='clustering',realCases=clustering&&$('data-source').value==='aligned';
    $('data-source-control').hidden=$('alignment-panel').hidden=!clustering;
    $('example').disabled=$('mode').disabled=$('input').disabled=$('data-source').disabled=busy||submitting||syncing;
    $('sync-cases').disabled=$('source-url').disabled=$('source-project').disabled=busy||submitting||syncing;
    $('source-criteria').disabled=busy||submitting||syncing||!aligned?.criteria;
    $('sync-cases').textContent=syncing?'正在读取并核对源案例…':'对齐 / 更新案例快照';
    $('run').disabled=!catalog||busy||submitting||syncing||(realCases&&(!aligned||!aligned.counts.reasons||$('mode').value!=='model'))||($('mode').value==='model'&&!catalog.model.ready);
    $('stop').disabled=!busy||current.cancel_requested||submitting;
    $('run').textContent=submitting?'正在提交…':busy?'运行中…':'运行';
    $('mode-note').textContent=realCases&&$('mode').value==='scripted'?'已对齐的真实案例不能使用预置脚本。请配置独立模型并切换到真实模型；对齐预览不需要 Key。':$('mode').value==='scripted'?'脚本演示：模型回复已预设，不理解输入、不代表真实模型效果，也不花模型费用。工具、hook 和循环由真实 ToolLoop 执行。':(realCases?'真实案例：运行会把所选案例材料和 reason 发送到你配置的独立供应商，请确认这些数据可以外发。':'真实模型：会向独立供应商发送任务输入、Harness prompt 和工具返回。')+' 点击运行会产生模型请求费用。';
    const locked=!modelSettings?.editable||modelSaving;
    for(const id of ['model-url','model-name','model-key','model-effort','model-temperature','model-timeout','save-model'])$(id).disabled=locked;
    $('reload-model').disabled=modelSaving;
    $('save-model').textContent=modelSaving?'正在保存…':'保存模型配置';
    showAlignedData();showArtifact();
  }
  function showDefinition(example){
    const target=$('definition');target.replaceChildren();
    if(!example)return;
    const d=example.definition;
    $('config-source').textContent=example.path||'本次运行冻结的 Python 配置';
    $('source').textContent=example.source||'';
    const prompt=node('details');prompt.append(node('summary','System prompt'),node('pre',d.system_prompt));target.append(prompt);
    for(const tool of d.tools){const row=node('details',undefined,'component');row.append(node('summary','工具 · '+tool.id),node('p',tool.description,'muted'),node('pre',text(tool.parameters)));target.append(row);}
    const completion=node('div',undefined,'component');completion.append(node('strong','核心结束 Hook · '+d.completion_hook.type),node('p',d.completion_hook.description,'muted'));target.append(completion);
    for(const [event,hooks] of Object.entries(d.hooks)){target.append(node('p',event+'：'+hooks.map(h=>h.type).join(' → '),'muted'));}
    target.append(node('p','预算：工具 '+d.budget.tool_calls+' 次，结束拦回 '+d.budget.max_blocked+' 次；结果提取：'+d.end,'muted'));
  }
  function showSelectedDefinition(){
    const e=selected();if(!e)return;
    const useAligned=e.id==='clustering'&&$('data-source').value==='aligned';
    if(useAligned&&e.aligned_definition&&e.alignment_id===aligned?.id)showDefinition({...e,definition:e.aligned_definition});
    else if(useAligned){$('definition').replaceChildren(node('p','请先对齐有 reason 的案例，再读取实际配置。','muted'));$('source').textContent=e.source;}
    else showDefinition(e);
  }
  function choose(){const e=selected();if(e){$('input').value=e.input;$('example-description').textContent=e.description;showSelectedDefinition();}controls();}
  function displayAlignment(){
    const link=$('alignment-preview');link.hidden=!aligned;
    if(!aligned){$('alignment-status').textContent='尚未对齐。只读取源服务，不修改原框架，不调用模型。';return;}
    link.href='tool_loop_lab_compare.html?snapshot_id='+encodeURIComponent(aligned.id);
    $('alignment-status').textContent='快照 '+aligned.id.slice(0,8)+' · '+new Date(aligned.synced_at*1000).toLocaleString()+'\n'+aligned.source_url+' / '+aligned.project+'\n'+aligned.counts.cases+' 个 case，其中 '+aligned.counts.with_reasons+' 个 case 有可聚类 reason（'+aligned.counts.reasons+' 条）。\n'+aligned.baseline_note;
  }
  async function loadAlignedView(){
    if(!aligned){alignedView=null;return;}
    if(alignedView?.id===aligned.id)return;
    alignedView=null;
    const id=aligned.id;
    const data=await request('alignment/preview?snapshot_id='+encodeURIComponent(id));
    if(aligned?.id!==id)return;
    const titles=new Map((data.types||[]).map(t=>[t.type_id,t.title]));
    const axes=new Map();
    for(const kase of data.cases||[])for(const axis of kase.axes||[]){
      const key=axis.type_id||axis.axis_id;if(!key)continue;
      const entry=axes.get(key)||{id:key,title:titles.get(key)||axis.title||key,records:0};
      entry.records++;axes.set(key,entry);
    }
    alignedView={id,axes:[...axes.values()],snapshot:data};
  }
  function showAlignedData(){
    const visible=$('example').value==='clustering'&&$('data-source').value==='aligned'&&!!aligned;
    $('aligned-data-card').hidden=!visible;
    if(!visible)return;
    const axes=alignedView?.id===aligned.id?alignedView.axes:[];
    $('aligned-data-title').textContent='当前已对齐材料 · '+aligned.counts.cases+' 个 case'+(alignedView?' / '+axes.length+' 个轴':'');
    $('aligned-data-axes').replaceChildren();
    for(const axis of axes){const item=node('div',undefined,'aligned-axis');item.append(node('strong',axis.title),node('span',axis.records+' 条轴记录','muted'));$('aligned-data-axes').append(item);}
    const hasResult=current?.status==='complete'&&current?.result?.value?.alignment?.id===aligned.id;
    $('aligned-data-note').textContent=hasResult?'已有使用这份快照生成的 ToolLoop 聚类产物，见下方。':
      '这些是已复制的原始材料，还没有这份快照的 ToolLoop 聚类结果。'+(catalog?.model.ready?'配置就绪，点击运行才会生成。':'独立模型未配置；可在左侧“独立模型连接”表单填写，也可直接查看原始 case 和 reason。');
    $('aligned-data-link').href='tool_loop_lab_artifact.html?snapshot_id='+encodeURIComponent(aligned.id)+'&view=clustering';
  }
  async function loadAlignment(initial=false){
    const data=await request('alignment');aligned=data.snapshot;
    if(initial&&aligned){$('source-url').value=aligned.source_url;$('source-project').value=aligned.project;}
    await loadAlignedView();displayAlignment();controls();
  }
  async function loadCatalog(){
    catalog=await request('catalog');const old=$('example').value;$('example').replaceChildren();
    for(const e of catalog.examples){const o=node('option',e.title);o.value=e.id;$('example').append(o);}
    if(catalog.examples.some(e=>e.id===old))$('example').value=old;
    displayModel(catalog.model);
    if(!$('input').value)choose();else controls();
  }
  function displayModel(m){
    const info=$('model-info');info.replaceChildren(node('div','协议：'+(m.protocol||'OpenAI-compatible')),
      node('div','模型：'+(m.model||'未配置')),node('div','地址：'+(m.base_url||'未配置')),node('div','Key：'+(m.key_configured?'已配置（不返回内容）':'未配置')));
    if(m.errors?.length)info.append(node('p',m.errors.join('；'),'notice'));
  }
  function applyModelSettings(data){
    modelSettings=data;modelDirty=false;
    const m=data.config;
    $('model-url').value=m.base_url||'';$('model-name').value=m.model||'';
    $('model-key').value='';$('model-key').placeholder=m.key_configured?'已保存 Key；留空保留，输入新值则替换':'首次使用请填写 API Key';
    $('model-temperature').value=m.temperature??0;
    $('model-effort').value=m.reasoning_effort||'';$('model-timeout').value=m.request_timeout_seconds||300;
    if(catalog)catalog.model=m;
    displayModel(m);
    $('model-config-status').textContent=data.editable?(m.ready?'配置已加载；Key 不回显。':'请填写独立模型配置，保存后再运行。'):
      '由进程环境变量管理，页面只读：'+data.managed_by_environment.join('、');
    controls();
  }
  async function loadModelSettings(){
    try{applyModelSettings(await request('model'));}
    catch(error){$('model-config-status').textContent='读取模型配置失败：'+error.message;controls();}
  }
  function appendEvent(event){
    lastEvent=event;eventCount++;
    const data=event.data,card=node('article',undefined,'event');card.dataset.kind=event.kind;card.dataset.seq=event.seq;
    const head=node('div',undefined,'event-title');
    const label=event.kind==='hook'?(data.core_completion?'核心结束 Hook':'Hook')+' · '+data.event+' · '+data.hook+' → '+data.decision:
      (names[event.kind]||event.kind)+(data.tool?' · '+data.tool:data.step?' #'+data.step:'');
    head.append(node('strong',label),node('span',new Date(event.at*1000).toLocaleTimeString(),'event-time'));card.append(head);
    let note='';
    if(event.kind==='model_response')note=data.message.content||('请求调用：'+(data.message.tool_calls||[]).map(c=>c.function.name).join('、'));
    else if(event.kind==='model_request')note='发送 '+data.messages.length+' 条上下文消息；等待模型返回。';
    else if(event.kind==='hook')note=data.result?.reason||(data.event==='post_tool'&&data.result?.accepted===false?'Hook 拒绝提交：'+data.result.error:'');
    else if(event.kind==='tool_result')note=data.result?.accepted===false?'提交未被接受：'+data.result.error:data.result?.accepted===true?'工具校验通过（最终是否接受还需后续 Hook 检查）':text(data.result);
    else note=data.error||data.reason||'';
    if(note)card.append(node('div',note,'event-note'));
    const detail=node('details');detail.append(node('summary','实际数据'),node('pre',text(data)));card.append(detail);
    $('timeline').append(card);$('event-count').textContent=eventCount+' 条事件';
  }
  function renderStatus(){
    const age=receivedAt===null?null:Math.max(0,(performance.now()-receivedAt)/1000);
    const now=serverNow===null?Date.now()/1000:serverNow+(age||0);
    const seconds=n=>Math.floor(Math.max(0,n))+' 秒';
    $('status').dataset.state=current?.status||'idle';
    const labels={running:'运行中',complete:'已完成',failed:'运行失败',cancelled:'已停止'};
    const label=current?.status==='running'&&lastEvent?.kind==='model_request'?'等待第 '+lastEvent.data.step+' 次模型返回':labels[current?.status]||'尚未运行';
    $('status-title').textContent=submitting?'正在提交试验…':(current?.status==='complete'?'上次'+(current.metadata.mode==='scripted'?'脚本演示':'模型运行')+' · ':'')+label;
    if(current){
      const end=current.status==='running'?now:current.updated;
      $('status-times').textContent='开始 '+new Date(current.started*1000).toLocaleTimeString()+' · 已耗时 '+seconds(end-current.started)+' · 距最近事件 '+seconds(now-current.updated)+(age===null?'':' · 状态接口 '+seconds(age)+'前响应');
      $('status-message').textContent=networkError||current.error||(current.cancel_requested&&current.status==='running'?'已请求停止，当前模型请求或工具返回后停止后续步骤。':current.status==='running'?'接口可达不等于模型有新输出；时间线只记录真实事件。':'');
    }else{$('status-times').textContent='';$('status-message').textContent=networkError||'先选一个示例，用脚本模式体验；无需配置模型。';}
  }
  function showArtifact(){
    const value=current?.result?.value;
    const available=current?.status==='complete'&&value?.kind==='axes_clustering';
    const realWorkspace=$('example').value==='clustering'&&$('data-source').value==='aligned'&&alignedView?.id===aligned?.id&&!!alignedView?.snapshot;
    const alignedResult=available&&value.alignment?.id===aligned?.id;
    $('previous-artifact-link').hidden=!realWorkspace||!available||alignedResult;
    if(realWorkspace&&available&&!alignedResult){
      $('previous-artifact-link').href='tool_loop_lab_artifact.html?run_id='+encodeURIComponent(current.id);
      $('previous-artifact-link').textContent='上次'+(value.data_source==='synthetic-demo'?'演示':'运行')+'产物（'+value.clustering.axes.length+'轴，非本材料）↗';
    }
    if(realWorkspace&&!alignedResult){
      $('artifact-card').hidden=false;$('artifact-preview').hidden=false;$('artifact-error').hidden=true;
      $('artifact-card').dataset.phase='pending';
      $('artifact-title').textContent='当前聚类工作区 · '+alignedView.axes.length+' 轴';
      $('artifact-note').textContent=current?.status==='running'&&current.metadata.alignment?.id===aligned.id
        ?'ToolLoop 正在处理这份材料；先保留 '+alignedView.axes.length+' 轴目录，完成后在这里显示类别。'
        :'这份真实材料尚无 ToolLoop 聚类结果。目录保留全部实际轴，第三层显示待聚类；不是原来的两轴演示。'+(!catalog?.model.ready?'独立模型还未配置。':'');
      $('artifact-link').href='tool_loop_lab_artifact.html?snapshot_id='+encodeURIComponent(aligned.id)+'&view=clustering';
      $('artifact-link').textContent='新窗口打开当前聚类工作区 ↗';
      $('comparison-link').hidden=true;
      const stamp='pending:'+aligned.id;
      if(artifactRun!==stamp){
        $('artifact-card').scrollIntoView({block:'start'});
        $('artifact-preview').srcdoc=LabClusteringView.renderPending(alignedView.snapshot);
        artifactRun=stamp;
      }
      return;
    }
    $('artifact-card').dataset.phase=available?'complete':'empty';
    $('artifact-card').hidden=!available;
    $('comparison-link').hidden=!available||!value?.alignment;
    if(available&&value.alignment)$('comparison-link').href='tool_loop_lab_compare.html?run_id='+encodeURIComponent(current.id);
    if(!available){artifactRun=null;$('artifact-preview').srcdoc='';$('artifact-link').removeAttribute('href');return;}
    const matches=$('example').value==='clustering'&&($('data-source').value==='aligned'?value.alignment?.id===aligned?.id:!value.alignment);
    $('artifact-preview').hidden=!matches;
    $('artifact-title').textContent=matches?'最近一次聚类产物':'上次产物（不属于当前所选材料）';
    $('artifact-link').href='tool_loop_lab_artifact.html?run_id='+encodeURIComponent(current.id);
    $('artifact-link').textContent=matches?'新窗口查看本次产物 ↗':'仅查看上次产物（'+value.clustering.axes.length+' 轴）↗';
    if(!matches){
      artifactRun=null;$('artifact-preview').srcdoc='';
      $('artifact-note').textContent='这是上次'+(value.data_source==='synthetic-demo'?'合成演示':'模型运行')+'产物：'+value.cases.length+' 个 case / '+value.clustering.axes.length+' 个轴，不是当前对齐材料的结果。原结果保留，可通过链接单独打开。';
      return;
    }
    if(artifactRun===current.id)return;
    $('artifact-error').hidden=true;
    try{
      const html=AxesExperiment.renderArtifact(value,{project:'ToolLoop Lab',mode:current.metadata.mode,runId:current.id,generatedAt:new Date(current.started*1000).toLocaleString()});
      // 产物出现时让它进入可见区域，避免完成后用户还停在长事件列表里。
      $('artifact-card').scrollIntoView({block:'start'});
      $('artifact-preview').srcdoc=html;
      $('artifact-link').href='tool_loop_lab_artifact.html?run_id='+encodeURIComponent(current.id);
      $('artifact-note').textContent=current.metadata.mode==='scripted'
        ?'脚本演示产物 · 合成材料 · 固定渲染器。下面是真正提交后生成的页面，不是模型效果评测。'
        :'本次有效提交的可视化产物。模型负责聚类与排序，页面排版固定；查看详情不会再次调用模型。';
      artifactRun=current.id;
    }catch(error){
      $('artifact-preview').srcdoc='';$('artifact-link').removeAttribute('href');
      $('artifact-error').hidden=false;$('artifact-error').textContent='产物渲染失败：'+error.message+'。原始提交仍在下方，可检查前端契约。';
    }
  }
  async function poll(restoreForm=false){
    clearTimeout(pollTimer);
    try{
      const response=await request('state?after='+after+(runId?'&run_id='+encodeURIComponent(runId):''));
      if(stopped)return;
      networkError='';receivedAt=performance.now();serverNow=response.server_time;
      current=response.run;
      if(response.reset){after=0;eventCount=0;lastEvent=null;$('timeline').replaceChildren();$('event-count').textContent='0 条事件';runId=current?.id||null;}
      for(const event of response.events){appendEvent(event);after=event.seq;}
      if(current){
        const meta=current.metadata;
        if(restoreForm){
          $('example').value=meta.example_id;$('input').value=meta.input;$('mode').value=meta.mode;$('data-source').value=meta.data_source||'demo';
          if(meta.example_id==='clustering'&&aligned&&current.status!=='running'){
            $('data-source').value='aligned';$('mode').value='model';
          }
        }
        displayAlignment();
        if(meta.alignment&&aligned&&meta.alignment.id!==aligned.id){$('alignment-status').textContent+='\n上次运行使用快照 '+meta.alignment.id.slice(0,8)+'，与当前对齐快照不同；对照页仍使用该运行自己的冻结材料。';}
        if(restoreForm&&$('data-source').value==='aligned'&&current.status!=='running')showSelectedDefinition();
        else if(restoreForm||response.reset||current.status==='running')showDefinition({definition:meta.definition,source:meta.source});
        $('output').textContent=current.result?text(current.result.value??null):current.status==='running'?'等待正式交付':current.error||'无正式产物';
        $('last-message').textContent=current.result?.final_message||'尚未产生最终回复';
      }else{$('timeline').append(node('p','尚未运行，可从脚本演示开始。','empty'));}
      showArtifact();controls();renderStatus();
      if(current?.status==='running')pollTimer=setTimeout(()=>poll(),800);
    }catch(error){networkError='读取状态失败：'+error.message+'。会自动重试查询，不重新提交任务。';renderStatus();if(!stopped)pollTimer=setTimeout(()=>poll(),3000);}
  }
  $('model-form').addEventListener('input',()=>{modelDirty=true;$('model-config-status').textContent='有未保存的配置；当前运行不受影响。';});
  $('reload-model').addEventListener('click',()=>{
    if(modelDirty&&!confirm('读取当前配置会丢弃本页未保存的模型编辑，继续？'))return;
    loadModelSettings();
  });
  $('model-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!modelSettings?.editable||modelSaving)return;
    modelSaving=true;controls();
    const payload={base_url:$('model-url').value,model:$('model-name').value,api_key:$('model-key').value,
      temperature:Number($('model-temperature').value),reasoning_effort:$('model-effort').value,request_timeout_seconds:Number($('model-timeout').value),expected_revision:modelSettings.revision};
    try{
      const saved=await request('model',payload);applyModelSettings(saved);
      $('model-config-status').textContent='已保存到独立配置，下次运行使用新模型。仅校验了配置格式，尚未发起供应商请求验证。';
    }catch(error){$('model-config-status').textContent='未保存：'+error.message+'。原配置未被改写。';}
    finally{payload.api_key='';modelSaving=false;controls();}
  });
  $('example').addEventListener('change',choose);$('mode').addEventListener('change',controls);
  $('data-source').addEventListener('change',()=>{if($('data-source').value==='aligned')$('mode').value='model';showSelectedDefinition();controls();});
  $('source-criteria').addEventListener('click',()=>{if(aligned)$('input').value=aligned.criteria;});
  $('sync-cases').addEventListener('click',async()=>{
    syncing=true;controls();$('alignment-status').textContent='正在单向读取源 case、reason 和可用聚类，并检查读取期间是否发生变化；不调用模型。';
    try{
      const data=await request('alignment/sync',{source_url:$('source-url').value,project:$('source-project').value},300000);
      aligned=data.snapshot;$('data-source').value='aligned';$('mode').value='model';await loadAlignedView();displayAlignment();await loadCatalog();showSelectedDefinition();
    }catch(error){$('alignment-status').textContent='对齐未完成：'+error.message+'。旧快照未被替换，可重新对齐。';}
    finally{syncing=false;controls();}
  });
  $('run').addEventListener('click',async()=>{
    if(!$('input').value.trim()){$('status-message').textContent='请填写任务输入。';return;}
    submitting=true;controls();renderStatus();
    try{const dataSource=$('example').value==='clustering'?$('data-source').value:'demo';await request('start',{example_id:$('example').value,input:$('input').value,mode:$('mode').value,data_source:dataSource,alignment_id:dataSource==='aligned'?aligned?.id:null});await poll();}
    catch(error){await poll();networkError='提交未完成：'+error.message;}
    finally{submitting=false;controls();renderStatus();}
  });
  $('stop').addEventListener('click',async()=>{try{await request('stop',{run_id:current.id});await poll();}catch(error){networkError=error.message;renderStatus();}});
  $('refresh').addEventListener('click',async()=>{try{await Promise.all([loadCatalog(),loadAlignment()]);if(!current||current.status!=='running')showSelectedDefinition();await poll();}catch(error){networkError=error.message;renderStatus();}});
  const clock=setInterval(renderStatus,1000);window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(pollTimer);clearInterval(clock);});
  Promise.all([loadCatalog(),loadAlignment(true)]).then(()=>loadModelSettings()).then(()=>poll(true)).catch(error=>{networkError='加载配置失败：'+error.message;renderStatus();});
})();
