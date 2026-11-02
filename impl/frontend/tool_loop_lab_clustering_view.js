// 试验台专用的待聚类工作区。复用现有目录渲染，不伪造语义类别，也不启动任何请求。
(function(global){
  'use strict';
  function renderPending(snapshot){
    const axes=global.AxesOverview.aggregate(snapshot.cases,snapshot.types).axes;
    const html=global.AxesExperiment.renderPage(snapshot.cases,snapshot.types,{
      project:snapshot.project||'ToolLoop Lab',generatedAt:new Date(snapshot.synced_at*1000).toLocaleString(),
      artifact:{clustering:null,data_source:'aligned-verifier',criteria:snapshot.criteria||''},
    });
    const doc=new DOMParser().parseFromString(html,'text/html');
    doc.title='聚类工作区 · 等待生成';
    doc.querySelector('header h1').textContent='轴 → 标签 → 聚类';
    const banner=doc.querySelector('.artifact-banner');banner.replaceChildren();
    const title=doc.createElement('h2');title.textContent='聚类工作区 · '+snapshot.cases.length+' 个 case / '+axes.length+' 个轴';
    const note=doc.createElement('p');note.textContent='所有轴均按当前快照实际记录展示。第三层“待聚类”不是聚类结果；运行模型后，同一工作区会显示真实语义类别。现在可以点击标签下的节点查看 case 和原始 reason。';
    banner.append(title,note);
    const help=doc.createElement('p');help.textContent='请在试验台左侧配置独立模型、选择真实案例并点击运行。这里不调用模型，也不使用旧演示产物替代结果。';banner.append(help);
    return '<!doctype html>'+doc.documentElement.outerHTML;
  }
  global.LabClusteringView=Object.freeze({renderPending});
})(globalThis);
