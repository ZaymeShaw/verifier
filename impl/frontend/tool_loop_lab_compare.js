(function(global){
  'use strict';
  const key=ref=>JSON.stringify([ref.pool_index,ref.request_key??null]);
  function memberships(clustering){
    const out=new Map();
    if(!clustering)return out;
    for(const axis of clustering.axes||[])for(const label of axis.labels||[])for(const cluster of label.clusters||[]){
      const members=new Set();
      for(const id of cluster.member_refs||[]){
        const ref=clustering.refs?.[id];
        if(!ref||ref.axis_id!==axis.axis_id||ref.value!==label.value)throw new Error('聚类成员归属不一致，不能生成对照');
        const member=key(ref);if(members.has(member))continue;members.add(member);
        const list=out.get(member)||[];
        list.push({axis:axis.axis_id,value:label.value,name:cluster.name,description:cluster.description});out.set(member,list);
      }
    }
    return out;
  }
  global.LabCaseComparison={memberships};
  if(typeof document==='undefined')return;
  const $=id=>document.getElementById(id);
  function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  const text=v=>v==null?'未提供':typeof v==='string'?v:JSON.stringify(v,null,2);
  async function load(){
    const query=new URLSearchParams(location.search);let snapshot,experiment=null;
    if(query.has('run_id')){
      const response=await fetch('/api/tool_loop_lab/state?run_id='+encodeURIComponent(query.get('run_id')));
      if(!response.ok)throw new Error('无法读取试验结果');
      const {run}=await response.json();
      if(!run||run.id!==query.get('run_id'))throw new Error('试验结果已被新运行替换');
      const value=run.result?.value;
      if(run.status!=='complete'||value?.kind!=='axes_clustering'||!value.alignment)throw new Error('此运行没有对齐真实案例的聚类产物');
      snapshot={...value.alignment,cases:value.cases,types:value.types,baseline:value.baseline};
      experiment={clustering:value.clustering,criteria:value.criteria};
    }else if(query.has('snapshot_id')){
      const response=await fetch('/api/tool_loop_lab/alignment/preview?snapshot_id='+encodeURIComponent(query.get('snapshot_id')));
      const value=await response.json();if(!response.ok)throw new Error(value.detail||'无法读取对齐快照');snapshot=value;
    }else throw new Error('请从试验台打开 case 对照');
    const baseline=snapshot.baseline||{},old=memberships(baseline.clustering),fresh=memberships(experiment?.clustering);
    const sourceScope=new Set((baseline.selections||[]).map(key));
    const titles=new Map((snapshot.types||[]).map(t=>[t.type_id,t.title]));
    $('error').hidden=true;$('provenance').hidden=false;
    $('source').textContent=snapshot.source_url+' / '+snapshot.project+'\n对齐时间：'+new Date(snapshot.synced_at*1000).toLocaleString()+' · 快照 '+snapshot.id;
    const sameCriteria=experiment&&experiment.criteria===baseline.criteria;
    $('coverage').textContent=snapshot.cases.length+' 条同源案例。'+(baseline.clustering?'源侧已有可对照聚类。':baseline.note||'源侧暂无可用聚类。')+
      (experiment?(sameCriteria?'实验沿用了相同标准。':'实验与源标准不同，不应把差异只归因于模型或 ToolLoop。'):'实验尚未运行；这里先核对 case、输入输出与源结果。');
    $('old-criteria').textContent=baseline.criteria||'未提供';$('new-criteria').textContent=experiment?.criteria||'尚未运行';
    function detail(kase,index){
      const root=$('case-detail');root.replaceChildren(el('h2','#'+(kase.pool_index+1)+' · '+kase.id),el('p',kase.scenario,'muted'));
      root.append(el('h3','实际输入'),el('pre',text(kase.input),'case-input'),el('h3','实际输出'),el('pre',text(kase.output),'case-output'));
      for(const axis of kase.axes||[]){const box=el('details');box.append(el('summary',(titles.get(axis.type_id||axis.axis_id)||axis.type_id||axis.axis_id)+' · '+(axis.verdict||axis.status||'无结论')));
        if(axis.text)box.append(el('p',axis.text,'reason'));for(const item of axis.items||[])box.append(el('strong',(item.value||'')+' · '+item.key),el('p',item.reason||'未提供理由','reason'));root.append(box);}
      document.querySelectorAll('#comparison-rows tr').forEach((r,i)=>r.classList.toggle('selected',i===index));
    }
    function addMembership(cell,items,missing){
      if(!items?.length){cell.append(el('span',missing,'muted'));return;}
      for(const item of items){const box=el('div',undefined,'membership');box.append(el('small',(titles.get(item.axis)||item.axis)+' / '+item.value),el('strong',item.name));
        const description=el('details');description.append(el('summary','共同情况'),el('p',item.description,'reason'));box.append(description);cell.append(box);}
    }
    snapshot.cases.forEach((kase,index)=>{
      const row=el('tr'),name=el('td'),left=el('td'),right=el('td');
      const open=el('button','#'+(kase.pool_index+1)+' · '+kase.id,'case-link');open.addEventListener('click',()=>detail(kase,index));name.append(open,el('p',(kase.inputPreview||text(kase.input)).slice(0,150),'muted'));
      addMembership(left,old.get(key(kase)),baseline.clustering?(sourceScope.has(key(kase))?'此记录没有枚举聚类成员':'不在源聚类范围内'):'源侧无可用聚类');
      addMembership(right,fresh.get(key(kase)),experiment?'此记录没有可聚类的枚举结果':'实验尚未运行');
      row.append(name,left,right);$('comparison-rows').append(row);
    });
  }
  load().catch(error=>{$('error').hidden=false;$('error').textContent='无法显示对照：'+error.message;});
})(globalThis);
