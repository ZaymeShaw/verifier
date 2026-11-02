// 扩展轴汇总：对当前筛选结果做用例之外的汇总（各轴星图 + 口径诊断 + 问题分组 + 用例×轴矩阵）。
// 只读 table_view.eval_axes_summary 已有的结果（status / verdict / items[key,value,reason]），不重新判断，
// 也不把取值折算成好坏：每条轴按它自己的枚举计数。枚举顺序取 /api/eval_axes/types 的 verdict_enum，
// 条目取值（如过程轴 outcome）类型声明里没有，按数据里首次出现的顺序。
(function (global) {
  'use strict';

  const OFF_MAP = '地图外';
  const NOT_RUN = '未跑成';
  // 类别色，只按枚举下标取，不带好坏含义。
  const PALETTE = ['#2563eb', '#dc2626', '#d97706', '#059669', '#7c3aed', '#0891b2', '#db2777', '#4b5563'];

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  }

  // 过程轴的 key 是「义务 @ link_id」；其他轴的 key 是本例条目（期望编号、断言原文），没有 link。
  function parseItemKey(key) {
    const text = String(key || '');
    const at = text.lastIndexOf(' @ ');
    if (at < 0) {return {label: text, linkId: ''};}
    return {label: text.slice(0, at), linkId: text.slice(at + 3).trim()};
  }

  // 环节实例 → 跨用例可比的环节类型：`κ:input:<id>`→κ:input，`χ:<id>`→χ，`new:N`→地图外。
  function linkFamily(linkId) {
    const id = String(linkId || '');
    if (!id) {return '';}
    if (id.startsWith('new:')) {return OFF_MAP;}
    const parts = id.split(':');
    return parts.length >= 3 ? parts[0] + ':' + parts[1] : parts[0];
  }

  function bump(map, key, by = 1) {
    map[key] = (map[key] || 0) + by;
  }

  // 声明的枚举在前（含本批没出现的值），数据里出现但没声明的追加在后。
  function ordered(declared, counts) {
    const keys = [...(declared || [])];
    for (const key of Object.keys(counts)) {if (!keys.includes(key)) {keys.push(key);}}
    return keys;
  }

  function newAxis(id, type) {
    return {
      id, title: type?.title || id, scope: type?.verdict_scope || '',
      verdictEnum: (type?.verdict_enum || []).map(v => v.value),
      descriptions: Object.fromEntries((type?.verdict_enum || []).map(v => [v.value, v.description || ''])),
      runs: {}, casesRun: 0, verdicts: {}, caseValues: {}, unitValues: {}, itemValues: {},
      units: 0, linked: false, repeatedInUnit: {}, offMap: {},
    };
  }

  function aggregate(cases, types) {
    const list = Array.isArray(cases) ? cases : [];
    const typeOf = Object.fromEntries((types || []).map(t => [t.type_id, t]));
    const axes = new Map();
    const groups = new Map();
    const matrix = [];
    for (const kase of list) {
      const row = {id: String(kase.id || ''), fulfillment: kase.fulfillment || '', cells: {}};
      for (const source of kase.axes || []) {
        const id = String(source.type_id || source.axis_id || '');
        const status = String(source.status || '');
        if (!id || status === 'disabled' || source.role === 'analysis' || typeOf[id]?.role === 'analysis') {continue;}
        const axis = axes.get(id) || newAxis(id, typeOf[id]);
        if (!typeOf[id] && source.title) {axis.title = source.title;}
        axes.set(id, axis);
        bump(axis.runs, status);
        const verdict = source.verdict === null || source.verdict === undefined ? '' : String(source.verdict);
        const cell = {status, verdict, values: {}};
        row.cells[id] = cell;
        if (status !== 'succeeded') {
          bump(axis.verdicts, NOT_RUN);
          continue;
        }
        axis.casesRun += 1;
        if (verdict) {bump(axis.verdicts, verdict);}
        // 判定单元：带 link 的条目按 link 实例归并（一个环节一个单元），其余每个条目自成一个单元。
        const units = new Map();
        (source.items || []).forEach((item, index) => {
          const {label, linkId} = parseItemKey(item.key);
          const unitId = linkId ? 'link:' + linkId : 'item:' + index;
          const unit = units.get(unitId) || {linkId, values: {}};
          const value = String(item.value || '');
          bump(unit.values, value);
          units.set(unitId, unit);
          bump(axis.itemValues, value);
          bump(cell.values, value);
          const family = linkFamily(linkId);
          if (family === OFF_MAP) {bump(axis.offMap, value);}
          // 分组只用跨用例可比的字段：轴、取值、过程轴的义务和环节类型。期望编号、断言原文只在本例有意义，进明细。
          const groupLabel = linkId ? label : '';
          const groupKey = [id, value, groupLabel, family].join('\u0000');
          const group = groups.get(groupKey) || {axisId: id, value, label: groupLabel, family, cases: new Set(), items: []};
          group.cases.add(row.id);
          group.items.push({caseId: row.id, subject: linkId || label, reason: String(item.reason || '')});
          groups.set(groupKey, group);
        });
        for (const unit of units.values()) {
          axis.units += 1;
          if (unit.linkId) {axis.linked = true;}
          for (const [value, n] of Object.entries(unit.values)) {
            bump(axis.unitValues, value);
            if (n > 1) {bump(axis.repeatedInUnit, value, n - 1);}
          }
        }
        for (const value of Object.keys(cell.values)) {bump(axis.caseValues, value);}
      }
      matrix.push(row);
    }
    const axisList = [...axes.values()].map(axis => ({
      ...axis,
      verdictOrder: ordered(axis.verdictEnum, axis.verdicts).filter(v => v !== NOT_RUN || axis.verdicts[NOT_RUN]),
      // 条目取值没有类型声明：item 级轴的条目就是 verdict_enum；axis 级轴按出现顺序。
      valueOrder: ordered(axis.scope === 'item' ? axis.verdictEnum : [], axis.itemValues),
    }));
    const groupList = [...groups.values()]
      .map(group => ({...group, caseCount: group.cases.size, cases: [...group.cases]}))
      .sort((a, b) => b.caseCount - a.caseCount || b.items.length - a.items.length);
    const fulfillment = {};
    for (const row of matrix) {bump(fulfillment, row.fulfillment || '-');}
    return {caseCount: list.length, fulfillment, axes: axisList, groups: groupList, matrix};
  }

  function pct(num, den) {
    return den ? Math.round(num * 100 / den) + '%' : '—';
  }

  // 单条轴的星图：辐条直接标原始枚举值，半径固定按 0–100% 绘制，不随本批最大值缩放。
  function renderStar(spokes, denominator, color, width = 560) {
    const n = spokes.length, c = width / 2, r = 110, cy = 166;
    const height = 338;
    const point = (i, v) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
      return [c + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
    };
    const poly = values => values.map((v, i) => point(i, v).map(x => x.toFixed(1)).join(',')).join(' ');
    const rings = [0.25, 0.5, 0.75, 1].map(level =>
      `<polygon points="${poly(spokes.map(() => level))}" fill="none" stroke="#e2e8f0"/>` +
      `<text x="${c + 6}" y="${(cy - r * level + 12).toFixed(1)}" font-size="10" fill="#64748b">${level * 100}%</text>`).join('');
    const lines = spokes.map((_, i) => {
      const [x, y] = point(i, 1);
      return `<line x1="${c}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e2e8f0"/>`;
    }).join('');
    const shape = `<polygon class="star-values" points="${poly(spokes.map(s => s.count / denominator))}" fill="${color}" fill-opacity="0.18" stroke="${color}" stroke-width="2"/>`;
    const labels = spokes.map((s, i) => {
      const [x, y] = point(i, 1.2);
      const anchor = Math.abs(x - c) < 4 ? 'middle' : (x > c ? 'start' : 'end');
      return `<text class="star-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" font-size="13" font-weight="700" fill="#334155"><title>${escapeHtml(s.title || s.value)}</title>` +
        `<tspan>${escapeHtml(s.value || '(空)')}</tspan>` +
        `<tspan x="${x.toFixed(1)}" dy="16" font-size="12" font-weight="400" fill="#64748b">${s.count} · ${pct(s.count, denominator)}</tspan></text>`;
    }).join('');
    return `<svg class="star" role="img" aria-label="星图（固定 0–100%）" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">${rings}${lines}${shape}${labels}</svg>`;
  }

  // 枚举不足 3 个时星图退化成线段，改画横条。
  function renderBars(spokes, denominator, color) {
    return '<div class="bars">' + spokes.map(s =>
      `<div class="bar" title="${escapeHtml(s.title || s.value)}"><span class="bar-label">${escapeHtml(s.value)}</span>` +
      `<span class="bar-track"><span style="width:${denominator ? (s.count * 100 / denominator).toFixed(1) : 0}%;background:${color}"></span></span>` +
      `<span class="bar-num">${s.count} · ${pct(s.count, denominator)}</span></div>`).join('') + '</div>';
  }

  function chart(spokes, denominator, color) {
    if (!spokes.length || !denominator) {return '<p class="muted">本批没有数据</p>';}
    return spokes.length >= 3 ? renderStar(spokes, denominator, color) : renderBars(spokes, denominator, color);
  }

  function counts(map, order) {
    return (order || Object.keys(map)).filter(k => map[k]).map(k => `${escapeHtml(k || '(空)')} ${map[k]}`).join(' · ') || '—';
  }

  function axisCard(a) {
    const casesTotal = Object.values(a.runs).reduce((s, v) => s + v, 0);
    // 用例层：axis 级轴看轴结论；item 级轴没有轴结论，看「出现过该取值的用例数」（一例可出现多个取值，合计可超过用例数）。
    const caseSpokes = a.scope === 'item'
      ? a.valueOrder.map(v => ({value: v, count: a.caseValues[v] || 0, title: a.descriptions[v]}))
      : a.verdictOrder.map(v => ({value: v, count: a.verdicts[v] || 0, title: a.descriptions[v] || (v === NOT_RUN ? '轴没跑成（blocked / failed）' : '')}));
    const caseDen = a.scope === 'item' ? a.casesRun : casesTotal;
    const unitSpokes = a.valueOrder.map(v => ({value: v, count: a.unitValues[v] || 0, title: a.descriptions[v]}));
    const unitName = a.linked ? '环节' : '条目';
    const caseTitle = a.scope === 'item' ? `用例中出现过该取值（分母：跑成 ${a.casesRun} 例）` : `轴结论（分母：${casesTotal} 例，含未跑成）`;
    const unitBlock = a.units
      ? `<div><h3>${unitName}取值（分母：${a.units} 个${unitName}）</h3>${chart(unitSpokes, a.units, PALETTE[1])}</div>`
      : `<div><h3>条目</h3><p class="muted">这条轴不产出条目</p></div>`;
    return `<section class="axis-card"><h2>${escapeHtml(a.title)} <span class="muted">${escapeHtml(a.id)} · ${escapeHtml(a.scope || '未声明')} 级</span></h2>` +
      `<div class="pair"><div><h3>${caseTitle}</h3>${chart(caseSpokes, caseDen, PALETTE[0])}</div>${unitBlock}</div></section>`;
  }

  function cellText(axis, cell) {
    if (cell.status !== 'succeeded') {return escapeHtml(cell.status);}
    if (cell.verdict) {return escapeHtml(cell.verdict);}
    return counts(cell.values, axis.valueOrder) || '—';
  }

  function cellColor(axis, cell) {
    if (cell.status !== 'succeeded') {return '#f1f5f9';}
    const index = cell.verdict ? axis.verdictOrder.indexOf(cell.verdict) : -1;
    return index >= 0 ? PALETTE[index % PALETTE.length] + '22' : '#fff';
  }

  function renderPage(summary, meta = {}) {
    const axes = summary.axes;
    const titleOf = Object.fromEntries(axes.map(a => [a.id, a.title]));
    const axisRows = axes.map(a => {
      const notRun = Object.fromEntries(Object.entries(a.runs).filter(([k]) => k !== 'succeeded'));
      const offMapTotal = Object.values(a.offMap).reduce((s, v) => s + v, 0);
      const repeated = Object.values(a.repeatedInUnit).reduce((s, v) => s + v, 0);
      return `<tr><td><b>${escapeHtml(a.title)}</b><div class="muted">${escapeHtml(a.id)}</div></td><td>${escapeHtml(a.scope || '未声明')}</td>` +
        `<td>${a.casesRun}</td><td>${counts(notRun)}</td><td class="small">${counts(a.verdicts, a.verdictOrder)}</td>` +
        `<td>${a.units}${a.units ? (a.linked ? ' 环节' : ' 条目') : ''}</td><td class="small">${counts(a.itemValues, a.valueOrder)}</td>` +
        `<td class="small ${repeated ? 'hl' : ''}">${repeated ? counts(a.repeatedInUnit, a.valueOrder) : 0}</td>` +
        `<td class="small ${offMapTotal ? 'hl' : ''}">${offMapTotal ? counts(a.offMap, a.valueOrder) : 0}</td></tr>`;
    }).join('');
    const groupRows = summary.groups.map((g, index) => {
      const details = g.items.map(it =>
        `<tr><td>${escapeHtml(it.caseId)}</td><td class="mono">${escapeHtml(it.subject)}</td><td>${escapeHtml(it.reason)}</td></tr>`).join('');
      return `<tr data-axis="${escapeHtml(g.axisId)}" data-value="${escapeHtml(g.value)}"><td>${index + 1}</td><td>${escapeHtml(titleOf[g.axisId] || g.axisId)}</td>` +
        `<td>${escapeHtml(g.value || '(空)')}</td><td>${escapeHtml(g.label || '—')}</td>` +
        `<td class="mono ${g.family === OFF_MAP ? 'hl' : ''}">${escapeHtml(g.family || '—')}</td><td><b>${g.caseCount}</b></td><td>${g.items.length}</td>` +
        `<td><details><summary>${escapeHtml(g.cases.slice(0, 4).join('、'))}${g.cases.length > 4 ? ' …' : ''}</summary>` +
        `<table class="inner"><thead><tr><th>用例</th><th>条目 / 环节</th><th>理由</th></tr></thead><tbody>${details}</tbody></table></details></td></tr>`;
    }).join('');
    const axisOptions = axes.map(a => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.title)}</option>`).join('');
    const valueOptions = [...new Set(summary.groups.map(g => g.value))].map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v || '(空)')}</option>`).join('');
    const matrixHead = axes.map(a => `<th>${escapeHtml(a.title)}</th>`).join('');
    const matrixRows = summary.matrix.map(row => `<tr><td class="mono">${escapeHtml(row.id)}</td><td>${escapeHtml(row.fulfillment || '-')}</td>` +
      axes.map(a => {
        const cell = row.cells[a.id];
        if (!cell) {return '<td class="cell muted" title="未跑">·</td>';}
        const title = `${a.title}：${cell.verdict || '无轴结论'}；条目 ${counts(cell.values, a.valueOrder)}`;
        return `<td class="cell" style="background:${cellColor(a, cell)}" title="${escapeHtml(title)}">${cellText(a, cell)}</td>`;
      }).join('') + '</tr>').join('');
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>扩展轴汇总 · ${escapeHtml(meta.project || '')}</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f6f8fb;color:#172033}
header{background:linear-gradient(135deg,#0f172a,#1d4ed8);color:#fff;padding:18px 28px}header h1{margin:0 0 4px;font-size:20px}
main{max-width:1600px;margin:0 auto;padding:18px}.card,.axis-card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin-bottom:16px}
h2{font-size:16px;margin:0 0 10px}h3{font-size:13px;margin:0 0 6px;color:#334155}.muted{color:#64748b;font-size:12px;font-weight:400}.small{font-size:12px;color:#475569}.hint{color:#475569;font-size:13px;line-height:1.6;margin:6px 0}
.axes-grid{display:grid;grid-template-columns:1fr;gap:16px}.axis-card{margin:0;min-width:0}.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:12px}.pair>div{min-width:0}
.star{display:block;width:100%;max-width:560px;height:auto;margin:0 auto}
.bars{display:flex;flex-direction:column;gap:6px;padding:8px 0}.bar{display:grid;grid-template-columns:150px 1fr 90px;gap:8px;align-items:center;font-size:12px}
.bar-track{height:12px;background:#f1f5f9;border-radius:6px;overflow:hidden}.bar-track>span{display:block;height:100%}.bar-num{color:#64748b}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top;font-size:13px}th{background:#f8fafc;position:sticky;top:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;word-break:break-all}.hl{background:#fef3c7}
.cell{text-align:center;font-family:ui-monospace,Menlo,monospace;font-size:12px}
details>summary{cursor:pointer;color:#2563eb}.inner td,.inner th{font-size:12px}.scroll{max-height:640px;overflow:auto}
.filters{display:flex;gap:10px;margin:8px 0}select{padding:5px 8px;border:1px solid #cbd5e1;border-radius:8px}
@media(max-width:800px){.axes-grid,.pair{grid-template-columns:1fr}}
</style></head><body>
<header><h1>扩展轴汇总</h1><div>${escapeHtml(meta.project || '')} · ${escapeHtml(meta.generatedAt || '')} · 当前筛选 ${summary.caseCount} 个用例 · ${axes.length} 条轴</div></header>
<main>
<section class="card"><p class="hint">生产裁决：${counts(summary.fulfillment)}</p>
<p class="hint">每条轴按它自己的枚举计数，不折算成好坏、不合成分数。星图外圈固定为 100%，50% 位于半径的一半，不按本批最大值放大。辐条直接显示原始枚举标签，顺序是该轴类型声明的 verdict_enum，本批没出现的值也画出来（计 0）；条目取值类型里没有声明，按出现顺序。
左图是用例层：axis 级轴看轴结论（含未跑成）；item 级轴没有轴结论，看出现过该取值的用例数。右图是单元层：过程轴一个环节一个单元，同一环节同一取值的多条义务只计 1 次；其他轴一个条目一个单元。</p></section>

<div class="axes-grid">${axes.map(axisCard).join('')}</div>

<section class="card" style="margin-top:16px"><h2>各轴口径</h2>
<p class="hint">「同环节重复」= 同一环节上同一取值多出来的条数，按取值分开列（例如 fail 3 = 同一事件被多条义务各判了一次 fail）。「地图外」= 分析轴临时起名的环节（new:N），跨用例对不上。这两栏越大，单元层计数越需要谨慎看。</p>
<div class="scroll"><table><thead><tr><th>轴</th><th>结论级别</th><th>跑成用例</th><th>未跑成</th><th>轴结论分布</th><th>单元</th><th>条目取值分布</th><th>同环节重复</th><th>地图外</th></tr></thead><tbody>${axisRows}</tbody></table></div></section>

<section class="card"><h2>分组（轴 × 取值 × 义务 × 环节类型）</h2>
<p class="hint">只按跨用例可比的字段分组，没做语义合并。期望编号、断言原文只在本例有意义，放在明细里。</p>
<div class="filters"><select id="fAxis" aria-label="按轴筛选"><option value="">全部轴</option>${axisOptions}</select>
<select id="fValue" aria-label="按取值筛选"><option value="">全部取值</option>${valueOptions}</select></div>
<div class="scroll"><table id="groups"><thead><tr><th>#</th><th>轴</th><th>取值</th><th>义务</th><th>环节类型</th><th>用例数</th><th>条数</th><th>用例 / 明细</th></tr></thead><tbody>${groupRows || '<tr><td colspan="8" class="muted">没有条目</td></tr>'}</tbody></table></div></section>

<section class="card"><h2>用例 × 轴</h2><p class="hint">有轴结论显示轴结论，没有显示条目取值计数；底色按该轴枚举的顺序取类别色，不表示好坏；· 表示该轴未跑。</p>
<div class="scroll"><table><thead><tr><th>用例</th><th>生产裁决</th>${matrixHead}</tr></thead><tbody>${matrixRows}</tbody></table></div></section>
</main>
<script>
(function(){
  const axis=document.getElementById('fAxis'),value=document.getElementById('fValue');
  function apply(){for(const tr of document.querySelectorAll('#groups tbody>tr[data-axis]')){
    tr.style.display=(!axis.value||tr.dataset.axis===axis.value)&&(!value.value||tr.dataset.value===value.value)?'':'none';}}
  axis.addEventListener('change',apply);value.addEventListener('change',apply);
})();
</script></body></html>`;
  }

  global.AxesOverview = Object.freeze({OFF_MAP, NOT_RUN, parseItemKey, linkFamily, aggregate, renderStar, renderBars, renderPage});
})(typeof globalThis === 'undefined' ? window : globalThis);
