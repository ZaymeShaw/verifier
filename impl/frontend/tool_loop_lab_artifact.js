// 同一查看入口明确区分：run_id = 冻结的运行产物，snapshot_id = 对齐材料，绝不相互冒充。
(async function(){
  'use strict';
  const query=new URLSearchParams(location.search);
  let latest=null;
  async function get(path){
    const response=await fetch('/api/tool_loop_lab/'+path,{signal:AbortSignal.timeout(30000)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||('HTTP '+response.status));
    return data;
  }
  const materialUrl=id=>'tool_loop_lab_artifact.html?snapshot_id='+encodeURIComponent(id)+'&view=clustering';
  function provenance(doc,title,description,snapshotId,compareUrl){
    const box=doc.createElement('section');box.id='page-provenance';
    const heading=doc.createElement('h1');heading.textContent=title;box.append(heading);
    const note=doc.createElement('p');note.textContent=description;box.append(note);
    const actions=doc.createElement('div');actions.className='source-actions';
    for(const [label,href,id] of [
      ['返回试验台','tool_loop_lab.html','back-to-lab'],
      ...(latest&&latest.id!==snapshotId ? [['打开当前聚类工作区（'+latest.counts.cases+' 个 case）',materialUrl(latest.id),'current-materials']] : []),
      ...(compareUrl ? [['按 case 对照源结果',compareUrl,'compare-source']] : []),
    ]){
      const link=doc.createElement('a');link.textContent=label;link.href=href;link.id=id;actions.append(link);
    }
    box.append(actions);doc.body.prepend(box);
    const style=doc.createElement('style');style.textContent='#page-provenance{padding:20px max(20px,calc((100vw - 1760px)/2));background:#fff8e7;border-bottom:1px solid #e5cd93;color:#493e21}#page-provenance h1{font-size:21px;margin:0 0 10px}#page-provenance p{font-size:14px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}.source-actions{display:flex;gap:10px;flex-wrap:wrap}.source-actions a{display:inline-block;background:white;color:#294dab;border:1px solid #cbd5e1;border-radius:7px;padding:9px 12px;font-size:13px;text-decoration:none}#current-materials{background:#4263eb;color:white}';
    doc.head.append(style);
  }
  try{
    latest=(await get('alignment')).snapshot;
    const runId=query.get('run_id'),snapshotId=query.get('snapshot_id');
    if(!!runId===!!snapshotId)throw new Error('请明确选择运行产物或对齐材料，从试验台对应入口打开');
    let html,title,description,compareUrl;
    if(runId){
      const {run}=await get('state?run_id='+encodeURIComponent(runId));
      if(!run||run.id!==runId)throw new Error('本试验台只保留最新一次运行，这个产物已被替换');
      if(run.status!=='complete')throw new Error('此运行尚无成功交付的产物，当前状态：'+run.status);
      const value=run.result.value;
      html=AxesExperiment.renderArtifact(value,{project:'ToolLoop Lab',mode:run.metadata.mode,runId:run.id,generatedAt:new Date(run.started*1000).toLocaleString()});
      title=(run.metadata.mode==='scripted'?'脚本演示产物':'ToolLoop 运行产物')+' · '+value.cases.length+' 个 case / '+value.clustering.axes.length+' 个轴';
      description='本链接固定查看运行 '+run.id+' 的产物，不会随着“对齐案例”而变成新聚类结果。'+
        (run.metadata.mode==='scripted'?'这是合成演示，不是已对齐真实案例的聚类。':'这是该次运行使用的冻结材料与有效提交。');
      if(latest&&value.alignment?.id!==latest.id)description+='\n目前另有已对齐的 '+latest.counts.cases+' 条真实案例；请使用下面的“打开当前聚类工作区”，不要把两份内容混在一起。';
      compareUrl=value.alignment?'tool_loop_lab_compare.html?run_id='+encodeURIComponent(runId):null;
    }else{
      const snapshot=await get('alignment/preview?snapshot_id='+encodeURIComponent(snapshotId));
      const axes=AxesOverview.aggregate(snapshot.cases,snapshot.types).axes;
      if(query.get('view')==='clustering'){
        const {run}=await get('state');
        const value=run?.result?.value;
        const ready=run?.status==='complete'&&value?.kind==='axes_clustering'&&value.alignment?.id===snapshotId;
        html=ready?AxesExperiment.renderArtifact(value,{project:snapshot.project,mode:run.metadata.mode,runId:run.id,generatedAt:new Date(run.started*1000).toLocaleString()}):LabClusteringView.renderPending(snapshot);
        title='聚类工作区 · '+snapshot.cases.length+' 个 case / '+axes.length+' 个轴';
        description=ready?'已展示这份快照的 ToolLoop 聚类结果。':'当前 '+axes.length+' 轴目录已经就绪，第三层待聚类；不是旧演示，也不隐藏工作区。请回试验台配置模型并运行。';
      }else{
        html=AxesExperiment.renderPage(snapshot.cases,snapshot.types,{project:snapshot.project,generatedAt:new Date(snapshot.synced_at*1000).toLocaleString()});
        title='对齐材料预览 · '+snapshot.cases.length+' 个 case / '+axes.length+' 个轴';
        description='来源：'+snapshot.source_url+' / '+snapshot.project+'。这里展示已对齐的输入输出、各轴原始判定和 reason，不是新生成的 ToolLoop 聚类产物。\n要生成实验聚类，需要回试验台选择这份真实材料并运行模型。';
      }
      compareUrl='tool_loop_lab_compare.html?snapshot_id='+encodeURIComponent(snapshotId);
    }
    const doc=new DOMParser().parseFromString(html,'text/html');
    provenance(doc,title,description,snapshotId,compareUrl);
    if(snapshotId&&query.get('view')!=='clustering'){
      // 材料预览不提供运行/聚类控制，不把待聚类占位树当成结果。
      for(const selector of ['.task-progress','.clustering-controls','#group-mode'])doc.querySelector(selector).hidden=true;
    }
    document.open();document.write('<!doctype html>'+doc.documentElement.outerHTML);document.close();
    if(snapshotId&&query.get('view')!=='clustering')document.getElementById('matrix-mode').click();
  }catch(error){
    const label=document.getElementById('artifact-loading')||document.body.appendChild(document.createElement('p'));
    label.textContent='无法显示：'+error.message;
    if(latest){const link=document.getElementById('current-materials');if(link){link.href=materialUrl(latest.id);link.hidden=false;}}
  }
})();
