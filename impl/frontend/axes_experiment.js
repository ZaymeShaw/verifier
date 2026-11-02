// 只读展示原型：分布图 → 案例×轴矩阵 → 单例详情。不重新判定，不携带完整 Trace。
(function (global) {
  'use strict';
  const COLORS = ['#4263eb', '#7950b8', '#99651a', '#087f7b', '#a74379', '#526178'];
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const percent = (count, total) => total ? (100 * count / total).toFixed(1).replace(/\.0$/, '') + '%' : '—';

  function prepare(cases, types) {
    return global.AxesOverview.aggregate(cases, types).axes.map(axis => {
      const itemScope = axis.scope === 'item';
      const declared = axis.scope === 'axis' || itemScope;
      const counts = itemScope ? axis.itemValues : axis.verdicts;
      const order = (itemScope ? axis.valueOrder : axis.verdictOrder).filter(v => itemScope || v !== global.AxesOverview.NOT_RUN);
      const total = order.reduce((n, value) => n + (counts[value] || 0), 0);
      const buckets = order.map((value, index) => {
        const entries = [];
        cases.forEach((kase, position) => {
          const source = (kase.axes || []).find(a => (a.type_id || a.axis_id) === axis.id && a.status === 'succeeded');
          if (!source) {return;}
          const matches = itemScope ? (source.items || []).some(item => String(item.value || '') === value) : String(source.verdict ?? '') === value;
          if (matches) {entries.push({position});}
        });
        return {value, count: counts[value] || 0, color: COLORS[index % COLORS.length], entries};
      });
      const recorded = Object.values(axis.runs).reduce((a, b) => a + b, 0);
      return {id: axis.id, title: axis.title, declared, itemScope, total, buckets,
        recorded, succeeded: axis.casesRun, missingVerdicts: itemScope ? 0 : axis.casesRun - total};
    });
  }

  // 原始枚举与运行状态分开；不把条目结论推成一个自创的轴结论。
  function cellState(axis, source) {
    if (!source) {return {kind: 'absent', label: '未运行', tokens: []};}
    if (source.status === 'disabled') {return {kind: 'disabled', label: '未启用', tokens: []};}
    if (source.status !== 'succeeded') {return {kind: 'execution', label: source.status || '状态未提供', tokens: []};}
    if (source.verdict !== null && source.verdict !== undefined && source.verdict !== '') {
      return {kind: 'verdict', label: String(source.verdict), composition: compositionText(source), tokens: [{value: String(source.verdict)}]};
    }
    if (axis.itemScope) {
      const counts = new Map();
      for (const item of source.items || []) {
        const value = String(item.value ?? '');
        if (value) {counts.set(value, (counts.get(value) || 0) + 1);}
      }
      if (counts.size) {return {kind: 'items', label: '条目结论', tokens: [...counts].map(([value, count]) => ({value, count}))};}
    }
    return {kind: 'missing', label: axis.itemScope ? '无条目结论' : '无轴结论', tokens: []};
  }

  // 只选取已有原文作预览，不推断问题、不把条目结论重新分成好坏。
  function compositionText(source) {
    return source?.composition ? Object.entries(source.composition.counts).map(([key, count]) => `${key} ${count}`).join(' · ') : '';
  }
  function issueReason(issue) {return issue.phenomenon + '；预期：' + issue.expected + '；实际：' + issue.observed;}
  function reasonSummary(source) {
    if (!source) {return {label: '说明', text: '该轴未运行，没有判断理由。', detailCount: 0};}
    const items = source.items || [];
    if (String(source.text || '').trim()) {
      return {label: '轴说明（原文）', text: source.text, detailCount: items.length};
    }
    const first = items.find(item => String(item.reason || '').trim());
    if (first) {
      return {label: '首条条目理由（原文）', text: first.reason, subject: first.key || '', detailCount: items.length};
    }
    return {label: '理由', text: '未提供判断理由', detailCount: items.length};
  }

  // 同轴同枚举组内保留每个 case 的原文；条目级只展示命中该枚举的条目。
  function groupReasons(axis, value, source) {
    if (!source || source.status !== 'succeeded') {return [];}
    if (axis.itemScope) {
      return (source.items || []).filter(item => String(item.value ?? '') === value)
        .map(item => ({key: item.key || '', value: item.value, reason: item.reason || '未提供判断理由'}));
    }
    if (String(source.verdict ?? '') !== value) {return [];}
    if (String(source.text || '').trim()) {return [{key: '轴判断理由（原文）', value, reason: source.text}];}
    const items = source.items || [];
    return items.length ? items.map(item => ({key: item.key || '', value: item.value, reason: item.reason || '未提供判断理由'}))
      : [{key: '轴判断理由', value, reason: '未提供判断理由'}];
  }

  // 把后端有序树映射到本页案例位置；严禁把过期引用静默映射到另一个 case。
  function semanticGroups(result, axes, cases) {
    const positions = new Map(cases.map((kase, position) => [kase.pool_index, position]));
    const groups = [];
    result.axes.forEach(axisResult => {
      const axisIndex = axes.findIndex(axis => axis.id === axisResult.axis_id);
      if (axisIndex < 0) {throw new Error('聚类引用了本页不存在的轴');}
      const axis = axes[axisIndex];
      axisResult.labels.forEach(label => {
        const bucketIndex = axis.buckets.findIndex(bucket => bucket.value === label.value);
        if (bucketIndex < 0) {throw new Error('聚类引用了本页不存在的枚举');}
        label.clusters.forEach((cluster, index) => {
          const members = new Map();
          cluster.member_refs.forEach(id => {
            const ref = result.refs[id], position = ref && positions.get(ref.pool_index);
            if (position === undefined || cases[position].request_key !== ref.request_key || ref.axis_id !== axis.id || ref.value !== label.value) {
              throw new Error('聚类引用与当前页面结果不一致，请回主页刷新');
            }
            const member = members.get(position) || {position, itemIndexes: [], issueIds: [], evidence: []};
            if (cluster.member_evidence && Object.hasOwn(cluster.member_evidence, id)) {
              member.evidence.push({ref: id, quote: cluster.member_evidence[id]});
            }
            if (ref.item_index !== null && ref.item_index !== undefined) {member.itemIndexes.push(ref.item_index);}
            if (ref.issue_id) {
              if (!(cases[position].axes || []).find(a => (a.type_id || a.axis_id) === axis.id)?.issues?.some(i => i.problem_id === ref.issue_id)) {throw new Error('问题记录已变化，请重新聚类');}
              member.issueIds.push(ref.issue_id);
            }
            members.set(position, member);
          });
          groups.push({axis, axisIndex, bucket: axis.buckets[bucketIndex], bucketIndex,
            key: JSON.stringify([axis.id, label.value, index]), members: [...members.values()], semantic: true,
            name: cluster.name, description: cluster.description,
            axisPriority: axisResult.priority_reason, labelPriority: label.priority_reason, priority: cluster.priority_reason});
        });
      });
    });
    return groups;
  }

  // 进度只来自已记录的事件。接口响应时间不是模型输出活动，缺失时间不补造。
  function taskProgress(task, kind, now) {
    if (!task) {return {status: 'idle', stage: '未取得任务状态', timing: false, eta: null};}
    const p = task.progress;
    const names = {submitted:'任务已提交', preparing:'准备模型请求', model_request:'等待模型返回', validating:'校验聚类结果',
      saving:'保存结果', executing_cases:'执行用例', finalizing:'汇总批次', completed:'已完成', failed:'已失败 / 中断', stale:'结果已失效',
      running:'进行中（阶段未记录）', pending:'等待启动', idle:'尚未开始'};
    const elapsed = p ? Math.max(0, (p.finished_at ?? now) - p.started_at) : null;
    const running = task.status === 'running' || task.status === 'pending';
    const done = kind === 'batch' ? task.done : null, total = kind === 'batch' ? task.total : null;
    const eta = p && running && kind === 'batch' && p.stage === 'executing_cases' && done > 0 && total > done
      ? elapsed * (total - done) / done : null;
    return {status: task.status, stage: running ? names[p?.stage] || names[task.status] || task.status : names[task.status] || task.status,
      detail: p?.detail || task.error || '', timing: !!p, started: p?.started_at ?? null, finished: p?.finished_at ?? null,
      elapsed, idle: p ? Math.max(0, now - p.last_event_at) : null, done, total, eta,
      requestTimeout: p?.request_timeout_seconds ?? null};
  }

  // 全部案例内容通过 textContent 写入；用数组位置绑定，重复 case ID 不串数据。
  function wireInteractions({axes, cases, api, artifact}) {
    const matrixBody = document.getElementById('matrix-body');
    const panel = document.getElementById('experiment-details');
    const search = document.getElementById('case-search');
    const filterLabel = document.getElementById('matrix-filter');
    const matrix = document.getElementById('case-matrix');
    let selectedCase = null, selectedAxis = null, filter = null, focusedAxis = null;
    let groupedView = true, activeGroup = null;
    let semanticResult = artifact?.clustering || null;
    let visible = [];
    const axisId = a => a.type_id || a.axis_id;
    const sourceFor = (kase, axis) => (kase.axes || []).find(a => axisId(a) === axis.id);
    const sourceAxes = kase => axes.concat((kase.axes || []).filter(a => !axes.some(axis => axis.id === axisId(a)))
      .map(a => ({id: axisId(a), title: a.title || axisId(a), buckets: [], itemScope: false})));

    function element(tag, text, className) {
      const node = document.createElement(tag);
      if (text !== undefined) {node.textContent = text;}
      if (className) {node.className = className;}
      return node;
    }
    function valueText(value, missing) {
      if (value === null || value === undefined) {return missing;}
      if (value === '') {return '（空字符串）';}
      return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }
    function button(text, className, action) {
      const node = element('button', text, className);
      node.type = 'button';
      node.addEventListener('click', action);
      return node;
    }
    function paintState(node, axis, state) {
      node.classList.add('state-' + state.kind);
      if (!state.tokens.length) {node.append(element('span', state.label, 'state-label'));return;}
      for (const token of state.tokens) {
        const color = axis.buckets.find(b => b.value === token.value)?.color || '#526178';
        const chip = element('span', token.value + (token.count ? ' ×' + token.count : ''), 'enum-chip');
        chip.style.backgroundColor = color + '16';
        chip.style.borderColor = color + '55';
        chip.style.color = color;
        node.append(chip);
      }
      if (state.composition) {node.append(element("small", state.composition, "unit-composition"));}
    }
    function appendJudgments(parent, source) {
      if (!source) {parent.append(element('p', '该用例没有这条轴的运行记录。', 'empty-reason'));return;}
      if (source.status !== 'succeeded') {parent.append(element('p', '运行状态：' + (source.status || '未提供'), 'execution-note'));}
      if (source.composition) {parent.append(element('p', compositionText(source), 'unit-composition'));}
      if (source.text) {parent.append(element('p', source.text, 'original-text'));}
      (source.issues || []).forEach(issue => {
        const row = element('section', undefined, 'process-issue');
        row.id = 'issue-' + issue.problem_id;
        row.append(element('strong', issue.problem_id + ' · ' + issue.phenomenon),
          element('p', issueReason(issue)), element('p', '归因：' + issue.attribution_detail + '；对最终交付的影响：' + issue.impact));
        (issue.quotes || []).forEach(quote => {
          const details = element('details', undefined, 'issue-evidence');
          details.append(element('summary', '引文 · ' + quote.ref + '：「' + quote.quote + '」'));
          details.append(element('pre', valueText(source.evidence_records?.[quote.ref], '记录 ' + quote.ref)));
          row.append(details);
        });
        parent.append(row);
      });
      (source.items || []).forEach(item => {
        const row = element('div', undefined, 'judgment');
        const title = element('div', undefined, 'judgment-title');
        title.append(element('span', item.value ?? '(空值)', 'value-tag'), element('strong', item.key || '未提供条目标识'));
        row.append(title, element('p', item.reason || '未提供判断理由', 'reason'));
        parent.append(row);
      });
      if (!source.text && !(source.items || []).length) {parent.append(element('p', '未提供判断理由或条目。', 'empty-reason'));}
    }
    function updateLayout() {
      panel.hidden = groupedView && selectedCase === null;
      const workspace = document.getElementById('workspace');
      workspace.classList.toggle('directory-mode', groupedView);
      workspace.classList.toggle('case-open-layout', groupedView && selectedCase !== null);
    }
    function clearDetail() {
      selectedCase = null; selectedAxis = null;
      panel.replaceChildren(element('div', '← 选一行看整个案例，点一个格子看该轴判断。', 'detail-placeholder'));
      updateLayout();
    }
    function highlightSelection() {
      document.querySelectorAll('.matrix-row, .group-member').forEach(row => {
        row.classList.toggle('selected', Number(row.dataset.position) === selectedCase &&
          (!row.classList.contains('group-member') || row.dataset.axisId === selectedAxis));
        row.querySelectorAll('button').forEach(node => node.setAttribute('aria-pressed', String(
          Number(row.dataset.position) === selectedCase && (!node.dataset.axisId || node.dataset.axisId === selectedAxis))));
      });
    }
    function showCase(position, axisIdToShow = null, bringIntoView = false) {
      selectedCase = position; selectedAxis = axisIdToShow;
      const kase = cases[position];
      const caseAxes = sourceAxes(kase);
      panel.replaceChildren();
      const head = element('div', undefined, 'detail-head');
      head.append(element('span', 'CASE ' + String(position + 1).padStart(2, '0'), 'eyebrow'),
        element('h2', kase.id || '未命名用例'), element('p', kase.scenario || '未提供场景', 'muted'));
      if (kase.fulfillment) {head.append(element('div', '生产裁决：' + kase.fulfillment, 'case-verdict'));}
      head.append(button('收起案例详情', 'close-case-detail', () => {clearDetail();highlightSelection();}));
      panel.append(head);
      const nav = element('div', undefined, 'case-axis-summary');
      caseAxes.forEach(axis => {
        const tab = button(undefined, 'axis-tab', () => showCase(position, axis.id));
        tab.dataset.axisId = axis.id;
        tab.setAttribute('aria-pressed', String(selectedAxis === axis.id));
        tab.append(element('strong', axis.title));
        paintState(tab, axis, cellState(axis, sourceFor(kase, axis)));
        nav.append(tab);
      });
      panel.append(nav);
      const io = element('div', undefined, 'case-io');
      for (const [key, label] of [['input', '实际输入'], ['output', '实际输出']]) {
        const pane = element('section', undefined, 'io-pane');
        pane.append(element('h3', label), element('pre', valueText(kase[key], '未提供' + label), 'case-' + key + '-value'));
        io.append(pane);
      }
      panel.append(io);
      const reason = element('section', undefined, 'case-axis-detail');
      const axis = caseAxes.find(a => a.id === selectedAxis);
      if (axis) {
        reason.append(element('h3', axis.title + ' · 原始判断', 'current-axis-title'));
        appendJudgments(reason, sourceFor(kase, axis));
      } else {
        const existing = caseAxes.filter(a => sourceFor(kase, a));
        if (!existing.length) {reason.append(element('p', '这个案例没有扩展轴记录。', 'empty-reason'));}
        existing.forEach(a => {
          const summary = reasonSummary(sourceFor(kase, a));
          const section = element('section', undefined, 'axis-reason-summary');
          section.append(button(a.title + ' · 查看逐项理由', 'reason-axis-link', () => showCase(position, a.id)),
            element('p', summary.label, 'reason-label'), element('p', summary.text, 'reason'));
          reason.append(section);
        });
      }
      // 理由是本次点击要看的内容，不再埋在长输入输出后面。
      panel.insertBefore(reason, io);
      panel.scrollTop = 0;
      updateLayout();
      highlightSelection();
      if (bringIntoView && window.innerWidth <= 1150) {panel.scrollIntoView({behavior: 'smooth', block: 'start'});}
    }
    const searchText = cases.map(kase => [kase.id, kase.scenario, kase.inputPreview, valueText(kase.input, ''),
      ...(kase.axes || []).flatMap(a => [a.text || '', ...(a.items || []).map(item => item.reason || '')])].join(' ').toLocaleLowerCase());
    function renderGroups() {
      const directory = document.getElementById('type-directory');
      const container = document.getElementById('enum-groups');
      directory.replaceChildren();container.replaceChildren();
      const allowed = new Set(visible);
      let groups = [];
      if (semanticResult) {
        groups = semanticGroups(semanticResult, axes, cases)
          .filter(group => !filter || (group.axisIndex === filter.axis && group.bucketIndex === filter.bucket))
          .map(group => ({...group, members: group.members.filter(entry => allowed.has(entry.position))}))
          .filter(group => group.members.length);
      } else {
        axes.forEach((axis, axisIndex) => {
          if (!axis.declared) {return;}
          axis.buckets.forEach((bucket, bucketIndex) => {
            if (filter && (axisIndex !== filter.axis || bucketIndex !== filter.bucket)) {return;}
            const members = bucket.entries.filter(entry => allowed.has(entry.position));
            if (members.length) {groups.push({axis, axisIndex, bucket, bucketIndex, members,
              key: JSON.stringify([axis.id, bucket.value]), name: '待聚类', semantic: false});}
          });
        });
      }
      const covered = new Set(groups.flatMap(group => group.members.map(entry => entry.position)));
      document.getElementById('group-summary').textContent = semanticResult
        ? groups.length + ' 个情况类型 · 涉及 ' + covered.size + ' 个案例。目录按 LLM 给出的同级阅读优先级排列；语义归纳不等于重新裁决。'
        : groups.length + ' 个候选范围 · 涉及 ' + covered.size + ' 个案例记录。尚未做语义聚类；请保存标准并重新聚类。';
      if (!groups.some(group => group.key === activeGroup)) {
        activeGroup = groups[0]?.key || null;
        if (selectedCase !== null) {clearDetail();}
      }
      let scopeSection = null, lastAxis = null, lastLabel = null, clusters = null;
      groups.forEach(group => {
        if (group.axis.id !== lastAxis) {
          scopeSection = element('details', undefined, 'type-scope');
          scopeSection.open = true;
          const scopeHead = element('summary');
          scopeHead.append(element('span', '轴', 'tree-level'), element('strong', group.axis.title));
          scopeHead.title = group.axisPriority || '';
          scopeSection.append(scopeHead);
          directory.append(scopeSection);lastAxis = group.axis.id;lastLabel = null;
        }
        const labelKey = JSON.stringify([group.axis.id, group.bucket.value]);
        if (labelKey !== lastLabel) {
          const labelSection = element('details', undefined, 'type-label');
          labelSection.open = true;
          const labelHead = element('summary');
          const tag = element('span', group.bucket.value || '(空值)', 'type-enum');
          tag.style.color = group.bucket.color;
          const labelCases = new Set(groups.filter(g => g.axis.id === group.axis.id && g.bucket.value === group.bucket.value)
            .flatMap(g => g.members.map(m => m.position)));
          labelHead.append(element('span', '标签', 'tree-level'), tag,
            element('span', labelCases.size + ' 例', 'label-count'));
          labelHead.title = group.labelPriority || '';
          labelSection.append(labelHead);
          clusters = element('div', undefined, 'type-clusters');
          labelSection.append(clusters);scopeSection.append(labelSection);lastLabel = labelKey;
        }
        const choose = button(undefined, 'type-entry', () => {
          if (activeGroup === group.key) {return;}
          activeGroup = group.key;clearDetail();renderGroups();highlightSelection();
        });
        choose.dataset.axis = String(group.axisIndex);choose.dataset.bucket = String(group.bucketIndex);
        choose.setAttribute('aria-pressed', String(group.key === activeGroup));
        choose.dataset.clusterKey = group.key;
        choose.title = group.priority || '尚未生成语义类别';
        choose.append(element('span', '聚类', 'tree-level'), element('span', group.name, group.semantic ? 'cluster-name' : 'pending-type'),
          element('strong', group.members.length + ' 例', 'type-count'));
        clusters.append(choose);
      });
      const current = groups.find(group => group.key === activeGroup);
      if (!current) {
        directory.append(element('p', '没有匹配的候选范围。', 'directory-empty'));
        container.append(element('p', '没有可显示的枚举结果。未运行、执行失败和无结论的案例，可切回“按案例看”查看。', 'empty'));
        return;
      }
      const {axis, axisIndex, bucket, bucketIndex, members} = current;
      const group = element('section', undefined, 'enum-group');
      group.dataset.axis = String(axisIndex);group.dataset.bucket = String(bucketIndex);
      const head = element('div', undefined, 'type-content-head');
      head.append(element('p', axis.title + ' / ' + (bucket.value || '(空值)') + ' / ' + current.name, 'type-breadcrumb'),
        element('h2', current.name), element('span', members.length + (current.semantic ? ' 个案例 · LLM 语义归纳' : ' 个案例 · 尚未生成语义类型'), 'group-case-count'));
      group.append(head);
      const common = element('section', undefined, 'type-common');
      common.append(element('h3', '共同情况'), element('p', current.description || '尚未生成语义归纳。请在上方编辑标准后，点击“保存并重新聚类”。'));
      if (current.semantic) {
        const priority = element('details', undefined, 'priority-explanation');
        priority.append(element('summary', '为什么这样排序'));
        for (const [label, text] of [['轴', current.axisPriority], ['标签', current.labelPriority], ['聚类', current.priority]]) {
          priority.append(element('p', label + '：' + text));
        }
        common.append(priority);
      }
      group.append(common);
      group.append(element('h3', '案例与具体问题对照', 'member-list-title'));
      const memberList = element('div', undefined, 'group-members');
      members.forEach(({position, itemIndexes, issueIds, evidence}) => {
        const kase = cases[position], source = sourceFor(kase, axis);
        const member = element('article', undefined, 'group-member');
        member.dataset.position = String(position);member.dataset.axisId = axis.id;
        const identity = element('div', undefined, 'member-identity');
        const open = button('#' + (position + 1) + ' · ' + (kase.id || '未命名用例') + ' → 查看输入输出', 'group-case-open',
          () => showCase(position, axis.id, true));
        open.dataset.axisId = axis.id;identity.append(open);
        const preview = kase.inputPreview || valueText(kase.input, '未提供实际输入');
        identity.append(element('p', preview.replace(/\s+/g, ' ').slice(0, 180), 'group-input-preview'));
        member.append(identity);
        const original = element('div', undefined, 'member-reasons');
        if (evidence?.length) {
          const basis = element('section', undefined, 'member-evidence');
          basis.append(element('div', '入类依据 · 模型摘录（仅校验出处，不代表语义已审定）', 'group-reason-key'));
          evidence.forEach(item => {
            const quote = element('blockquote', item.quote, 'member-evidence-quote');
            quote.dataset.ref = item.ref;
            basis.append(quote);
          });
          original.append(basis);
        }
        const reasons = current.semantic && issueIds?.length
          ? issueIds.map(id => source.issues.find(i => i.problem_id === id)).map(issue => ({key: issue.problem_id, value: source.verdict, reason: issueReason(issue)}))
          : current.semantic && axis.itemScope
          ? (itemIndexes || []).map(i => source.items[i]).map(item => ({key: item.key || '', value: item.value, reason: item.reason || '未提供判断理由'}))
          : groupReasons(axis, bucket.value, source);
        reasons.forEach(item => {
          const detail = element('div', undefined, 'group-reason');
          detail.append(element('div', (item.value ?? '(空值)') + (item.key ? ' · ' + item.key : ''), 'group-reason-key'),
            element('p', item.reason, 'group-reason-text'));
          original.append(detail);
        });
        member.append(original);memberList.append(member);
      });
      group.append(memberList);container.append(group);
    }
    function renderMatrix() {
      const query = search.value.trim().toLocaleLowerCase();
      const allowed = filter ? new Set(axes[filter.axis].buckets[filter.bucket].entries.map(e => e.position)) : null;
      visible = cases.map((_, i) => i).filter(i => (!allowed || allowed.has(i)) && (!query || searchText[i].includes(query)));
      const scope = filter ? axes[filter.axis].title + ' · ' + axes[filter.axis].buckets[filter.bucket].value : '全部案例';
      const displayedAxes = focusedAxis === null ? axes : axes.filter(a => a.id === focusedAxis);
      const focusedTitle = focusedAxis === null ? '' : displayedAxes[0]?.title || focusedAxis;
      filterLabel.textContent = scope + ' · ' + visible.length + ' / ' + cases.length + ' 条' + (!groupedView && focusedTitle ? ' · ' + focusedTitle + '理由展开' : '');
      document.getElementById('matrix-view').hidden = groupedView;
      document.getElementById('group-view').hidden = !groupedView;
      document.getElementById('view-title').textContent = groupedView ? '情况类型浏览' : '案例 × 轴';
      document.getElementById('all-cases').textContent = groupedView ? '全部范围' : '全部案例';
      document.getElementById('matrix-help').hidden = groupedView;
      document.getElementById('matrix-mode').setAttribute('aria-pressed', String(!groupedView));
      document.getElementById('group-mode').setAttribute('aria-pressed', String(groupedView));
      matrix.classList.toggle('reason-focus', focusedAxis !== null);
      matrix.style.minWidth = (focusedAxis !== null ? 640 : 300 + axes.length * 110) + 'px';
      const columns = document.getElementById('matrix-columns');
      columns.replaceChildren();
      [210, 90, ...displayedAxes.map(() => focusedAxis !== null ? null : 110)].forEach(width => {
        const col = element('col');
        if (width) {col.style.width = width + 'px';}
        columns.append(col);
      });
      const head = document.getElementById('matrix-head');
      const header = element('tr');
      ['案例 / 输入预览', '生产裁决'].forEach(label => {
        const th = element('th', label);th.scope = 'col';header.append(th);
      });
      displayedAxes.forEach(axis => {
        const th = element('th');th.scope = 'col';
        const focus = button(axis.title + (focusedAxis === axis.id ? ' · 收起' : ' · 看理由'), 'axis-focus', () => {
          focusedAxis = focusedAxis === axis.id ? null : axis.id;
          renderMatrix();
          if (selectedCase !== null && focusedAxis !== null) {showCase(selectedCase, focusedAxis);}
        });
        focus.dataset.axisId = axis.id;
        focus.setAttribute('aria-pressed', String(focusedAxis === axis.id));
        th.append(focus);header.append(th);
      });
      head.replaceChildren(header);
      matrixBody.replaceChildren();
      visible.forEach(position => {
        const kase = cases[position];
        const row = element('tr', undefined, 'matrix-row');
        row.dataset.position = String(position);
        const name = element('td', undefined, 'case-name');
        const opener = button(undefined, 'case-open', () => showCase(position, focusedAxis, true));
        opener.append(element('span', '#' + (position + 1) + ' · ' + (kase.id || '未命名用例'), 'case-id'));
        const preview = kase.inputPreview || valueText(kase.input, '未提供实际输入');
        opener.append(element('span', preview.replace(/\s+/g, ' ').slice(0, 180), 'input-preview'));
        opener.append(element('span', kase.scenario || '未提供场景', 'case-scenario'));
        name.append(opener);row.append(name);
        const verdict = element('td', undefined, 'production-cell');
        verdict.append(button(kase.fulfillment || '未判定', 'production-value', () => showCase(position, null, true)));
        row.append(verdict);
        displayedAxes.forEach(axis => {
          const cell = element('td');
          const source = sourceFor(kase, axis);
          const state = cellState(axis, source);
          const open = button(undefined, 'matrix-cell', () => showCase(position, axis.id, true));
          open.dataset.axisId = axis.id;
          open.setAttribute('aria-label', '#' + (position + 1) + ' ' + (kase.id || '未命名用例') + ' · ' + axis.title + ' · ' + state.label);
          paintState(open, axis, state);
          if (source) {
            const summary = reasonSummary(source);
            const preview = element('span', undefined, 'matrix-reason');
            preview.append(element('span', summary.label, 'reason-label'));
            if (summary.subject) {preview.append(element('span', summary.subject, 'reason-subject'));}
            preview.append(element('span', summary.text, 'matrix-reason-text'));
            open.append(preview, element('span', summary.detailCount ? '查看全部 ' + summary.detailCount + ' 条逐项理由 →' : '查看案例 →', 'reason-more'));
          }
          cell.append(open);row.append(cell);
        });
        matrixBody.append(row);
      });
      if (!visible.length) {
        const row = element('tr'), cell = element('td', '没有匹配的案例。点击“全部案例”恢复。', 'empty');
        cell.colSpan = displayedAxes.length + 2;row.append(cell);matrixBody.append(row);
      }
      if (selectedCase !== null && !visible.includes(selectedCase)) {clearDetail();}
      if (groupedView) {renderGroups();} else {document.getElementById('enum-groups').replaceChildren();}
      updateLayout();
      highlightSelection();
      document.querySelectorAll('.segment[data-bucket], .legend-item[data-bucket]').forEach(node => node.setAttribute('aria-pressed',
        String(!!filter && Number(node.dataset.axis) === filter.axis && Number(node.dataset.bucket) === filter.bucket)));
    }
    document.getElementById('matrix-mode').addEventListener('click', () => {groupedView = false;renderMatrix();});
    document.getElementById('group-mode').addEventListener('click', () => {groupedView = true;clearDetail();renderMatrix();});
    search.addEventListener('input', renderMatrix);
    document.getElementById('all-cases').addEventListener('click', () => {filter = null;focusedAxis = null;search.value = '';renderMatrix();});
    document.querySelectorAll('.segment[data-bucket], .legend-item[data-bucket]').forEach(node => node.addEventListener('click', () => {
      filter = {axis: Number(node.dataset.axis), bucket: Number(node.dataset.bucket)};
      focusedAxis = axes[filter.axis].id;
      search.value = '';renderMatrix();
      if (visible.length && !groupedView) {showCase(visible[0], axes[filter.axis].id);}
      document.getElementById('workspace').scrollIntoView({behavior: 'smooth', block: 'start'});
    }));
    clearDetail();renderMatrix();
    if (!artifact) {setupClustering();}

    function setupClustering() {
      const editor = document.getElementById('clustering-criteria');
      const message = document.getElementById('clustering-status');
      const version = document.getElementById('criteria-version');
      const save = document.getElementById('save-clustering-criteria');
      const start = document.getElementById('start-clustering');
      const reload = document.getElementById('reload-clustering');
      const feedback = document.getElementById('clustering-feedback');
      const headline = document.getElementById('clustering-headline');
      const viewResult = document.getElementById('view-clustering-result');
      const reloadRuns = document.getElementById('refresh-run-results');
      let lastReceived = null, progressTimer = null;
      let editorVersion = null, baseline = '', current = null, busy = false, timer = null, stopped = false, stamp = '', readEpoch = 0, action = null;
      const selections = cases.map(kase => ({pool_index: kase.pool_index, request_key: kase.request_key}));
      function showFeedback(phase, title, text) {
        feedback.dataset.phase = phase;
        headline.textContent = title;
        message.textContent = text;
      }
      function renderProgress() {
        const age = lastReceived === null ? null : Math.max(0, (performance.now() - lastReceived) / 1000);
        const serverNow = current?.server_time ? current.server_time + (age || 0) : Date.now() / 1000;
        const duration = value => value === null || value === undefined ? '未记录' :
          value < 60 ? Math.floor(value) + ' 秒' : Math.floor(value / 60) + ' 分 ' + Math.floor(value % 60) + ' 秒';
        const clock = value => value == null ? '未记录' : new Date(value * 1000).toLocaleTimeString();
        for (const [kind, task, target] of [['batch', current?.batch, 'batch-progress'], ['clustering', current, 'model-progress']]) {
          const root = document.getElementById(target), info = taskProgress(task, kind, serverNow);
          root.replaceChildren();root.dataset.status = info.status;
          const title = kind === 'batch' ? '业务批次' : 'LLM 聚类';
          const snapshot = kind === 'batch' && !task ? api?.batchSnapshot : null;
          root.append(element('h3', title + ' · ' + (snapshot ? '页面打开时的快照' : info.stage)));
          if (snapshot) {
            root.append(element('strong', snapshot.done + ' / ' + snapshot.total + ' 条已有结果', 'task-count'),
              element('p', '打开页面时的状态：' + snapshot.status + '。尚未取得实时批次进度，不能据此判断之后是否有新进展。', 'task-detail'));
          }
          const active = info.status === 'running' || info.status === 'pending';
          if (kind === 'batch' && task) {
            root.append(element('strong', info.done + ' / ' + info.total + ' 条已有结果', 'task-count'));
            const bar = element('progress');bar.max = Math.max(1, info.total);bar.value = info.done;
            root.append(bar, element('p', '尚未完成 ' + Math.max(0, info.total - info.done) + ' 条。此处是完成数量，不是业务通过率。', 'task-detail'));
          } else if (active) {
            const bar = element('progress');bar.removeAttribute('value');root.append(bar);
          }
          if (info.detail) {root.append(element('p', info.detail, 'task-detail'));}
          if (task) {
            const times = element('dl', undefined, 'task-times');
            for (const [label, text] of [['开始', clock(info.started)], ['已耗时', duration(info.elapsed)],
              [active ? '距最近任务事件' : '结束', active ? duration(info.idle) : clock(info.finished)]]) {
              times.append(element('dt', label), element('dd', text));
            }
            root.append(times);
            if (info.eta !== null) {
              root.append(element('p', '预计剩余约 ' + duration(info.eta) + '（按当前平均完成速度粗估，长尾用例会偏离）', 'task-estimate'));
            } else if (active) {
              root.append(element('p', kind === 'clustering' ? '预计剩余：暂不能可靠估计；当前接口不提供逐 token / 逐理由进度。' :
                '预计剩余：暂无可用耗时样本，或正在批次汇总阶段。', 'task-estimate'));
            }
            if (info.requestTimeout !== null && active) {
              root.append(element('p', '单次模型请求时限 ' + duration(info.requestTimeout) + '；若发生重试会延长，这不是整个任务的结束倒计时。', 'task-detail'));
              if (task.progress?.stage === 'model_request' && info.idle >= info.requestTimeout) {
                root.append(element('p', '本阶段无新事件的时长已超过一次请求的时限，可能包含重试。当前没有更细的模型活动信号，不能据此确认仍在推进；请检查调用日志。', 'task-warning'));
              }
            }
            if (!info.timing) {root.append(element('p', '此任务尚无可用的起止时间记录，不用页面打开时间冒充任务开始时间。', 'task-detail'));}
          }
        }
        document.getElementById('task-connection').textContent = age === null ? '尚未取得后端状态。' :
          '状态接口上次响应：' + duration(age) + '前。接口可达不代表模型有新输出；请同时看“最近任务事件”。';
      }
      function snapshotOutdated() {
        const old = api?.batchSnapshot, batch = current?.batch;
        return !!(old && batch && (old.job_id !== batch.job_id || old.done !== batch.done || old.status !== batch.status));
      }
      function controls() {
        editor.disabled = !editorVersion || busy;
        save.disabled = !editorVersion || busy;
        start.disabled = !editorVersion || busy || current?.status === 'running' ||
          ['running','pending'].includes(current?.batch?.status) || current?.scope_valid === false || snapshotOutdated();
        reload.disabled = busy;
        save.textContent = action === 'save' ? '正在保存…' : '仅保存标准';
        start.textContent = action === 'cluster' ? '正在提交…' : current?.status === 'running' ? '聚类中…' : '保存并重新聚类（LLM）';
        viewResult.hidden = busy || current?.status !== 'completed' || !current?.scope_matches || !semanticResult;
        const dirty = editor.value !== baseline;
        version.textContent = editorVersion ? '编辑标准 v' + editorVersion + (dirty ? ' · 未保存' : ' · 已保存') +
          (current && current.criteria_version !== editorVersion ? ' · 后端已有新版本' : '') : '正在读取后端标准';
      }
      async function request(path, data) {
        const res = await fetch(new URL(path, api.base), {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project:api.project,...data})});
        const value = await res.json();
        if (!res.ok) {const error = new Error(value.error || ('HTTP ' + res.status));error.status = res.status;throw error;}
        return value;
      }
      function accept(state, resetEditor = false) {
        current = state;
        lastReceived = performance.now();
        renderProgress();
        if (resetEditor || editorVersion === null || editor.value === baseline) {
          editor.value = state.criteria;baseline = state.criteria;editorVersion = state.criteria_version;
        }
        const nextStamp = [state.job_id, state.status, state.criteria_version, state.data_revision, state.scope_matches].join('|');
        if (stamp !== nextStamp) {
          const result = state.status === 'completed' && state.scope_matches ? state.result : null;
          if (result) {semanticGroups(result, axes, cases);}
          semanticResult = result;activeGroup = null;clearDetail();renderMatrix();stamp = nextStamp;
        }
        if (state.scope_valid === false) {
          showFeedback('blocked', '页面数据已更新，请刷新运行结果', state.scope_error + '。下方进度仍会自动查询，不会把新聚类套用到旧案例。');
        } else if (['running','pending'].includes(state.batch?.status) && state.status !== 'running') {
          showFeedback('blocked', '业务批次进行中 · ' + state.batch.done + '/' + state.batch.total,
            '聚类尚未启动。页面会自动更新进度；批次完成后可手动聚类，不会自动调用模型。');
        } else if (snapshotOutdated()) {
          showFeedback('stale', '批次进度已更新，请刷新运行结果', '任务进度已经更新，但本页案例仍是打开时的快照。请先保存未保存的标准，再点上方“刷新运行结果”，然后按最新数据聚类。');
        } else if (state.status === 'running') {
          showFeedback('running', '正在进行语义聚类，请稍候',
            '正在按标准 v' + state.job_version + ' 聚类；当前保存标准为 v' + state.criteria_version + '。无需重复点击，刷新不会重复调用。');
        } else if (state.status === 'completed' && state.scope_matches) {
          const clusterCount = state.result.axes.reduce((n, axis) => n + axis.labels.reduce((sum, label) => sum + label.clusters.length, 0), 0);
          const caseCount = new Set(Object.values(state.result.refs).map(ref => ref.pool_index)).size;
          showFeedback('completed', '聚类完成 · ' + clusterCount + ' 类情况 / ' + caseCount + ' 个案例',
            '已按标准 v' + state.job_version + ' 完成聚类。结果在下方“语义类型目录”；点击“查看聚类结果”可直接跳转。');
        } else if (state.status === 'completed') {
          showFeedback('stale', '已有结果属于其他筛选范围', '请对当前范围重新聚类；没有把其他范围的结果混入本页。');
        } else if (state.status === 'failed') {
          showFeedback('failed', '聚类失败', state.error || '未返回可用结果，请检查后重试。');
        } else if (state.status === 'stale') {
          showFeedback('stale', '当前标准或数据需要重新聚类', '标准或运行结果已改变，旧聚类不再使用。请重新聚类。');
        } else {
          showFeedback('idle', '尚未生成语义聚类', '标准已保存。点击“保存并重新聚类（LLM）”才会调用模型。');
        }
        controls();
      }
      async function refresh(resetEditor = false) {
        const epoch = ++readEpoch;
        clearTimeout(timer);
        try {
          const state = await request('/api/axes_clustering/state', {selections});
          if (stopped || epoch !== readEpoch) {return;}
          accept(state, resetEditor);
          if (state.status === 'running' || ['pending','running'].includes(state.batch?.status)) {
            timer = setTimeout(() => refresh(), 2500);
          }
        } catch (error) {
          if (stopped || epoch !== readEpoch) {return;}
          semanticResult = null;activeGroup = null;renderMatrix();
          const retryable = !error.status || error.status >= 500 || [409,429].includes(error.status);
          showFeedback(error.status === 409 ? 'blocked' : 'failed', '暂未取得最新状态，保留最后已知进度',
            error.message + (retryable ? '。会自动重试状态查询，不重新提交业务或聚类任务。' : '。请刷新运行结果或检查服务。'));
          if (retryable) {timer = setTimeout(() => refresh(), 5000);}
          controls();
        }
      }
      async function submit(run) {
        if (!editor.value.trim()) {showFeedback('failed', '尚未提交', '请填写聚类与优先级标准。');return;}
        const draft = editor.value;
        action = run ? 'cluster' : 'save';
        busy = true;++readEpoch;controls();clearTimeout(timer);
        showFeedback('submitting', run ? '正在提交聚类任务…' : '正在保存标准…',
          run ? '正在保存本次标准并提交到后端，请勿重复点击。' : '仅保存标准，不调用模型。');
        try {
          const response = await request(run ? '/api/axes_clustering/start' : '/api/axes_clustering/criteria',
            {criteria:draft,expected_version:editorVersion,...(run ? {selections} : {})});
          editor.value = response.criteria;baseline = response.criteria;editorVersion = response.criteria_version;
          await refresh();
        } catch (error) {
          if (error.status === 409) {await refresh();}
          showFeedback('failed', '操作未完成', error.message + '。编辑内容已保留；可读取最新标准后重试。');
          if (current?.status === 'running') {timer = setTimeout(() => refresh(), 2500);}
        } finally {busy = false;action = null;controls();}
      }
      viewResult.addEventListener('click', () => {
        if (!semanticResult) {return;}
        groupedView = true;filter = null;focusedAxis = null;search.value = '';
        clearDetail();renderMatrix();
        document.getElementById('workspace').scrollIntoView({behavior:'smooth',block:'start'});
        document.getElementById('view-title').focus({preventScroll:true});
      });
      reloadRuns.addEventListener('click', () => {
        if (editor.value !== baseline && !window.confirm('刷新页面会丢弃尚未保存的标准编辑，继续？')) {return;}
        location.reload();
      });
      editor.addEventListener('input', controls);
      save.addEventListener('click', () => submit(false));
      start.addEventListener('click', () => submit(true));
      reload.addEventListener('click', () => {
        if (editor.value !== baseline && !window.confirm('读取后端最新标准会覆盖本页未保存的编辑，继续？')) {return;}
        refresh(true);
      });
      window.addEventListener('pagehide', () => {stopped = true;clearTimeout(timer);clearInterval(progressTimer);});
      renderProgress();
      if (!api?.base || selections.some(s => s.pool_index === null)) {
        editor.disabled = save.disabled = start.disabled = reload.disabled = true;
        version.textContent = '离线查看';showFeedback('idle', '离线查看模式', '请从主页打开试验页，才能编辑后端标准并调用 LLM 聚类。');
      } else {controls();refresh();progressTimer = setInterval(renderProgress, 1000);}
    }
  }

  // 独立页面刷新时，从后端当前候选区恢复同一筛选范围；不在浏览器保存完整运行记录。
  function fromWorkspace(workspace, selections) {
    const runs = new Map((workspace.runs || []).map(run => [run.request_key, run]));
    return selections.map(selection => {
      const entry = (workspace.cases || [])[selection.pool_index];
      if (!entry || (entry.request_key ?? null) !== (selection.request_key ?? null)) {
        const error = new Error('候选区已更新，旧筛选关联的运行记录已被替换');
        error.code = 'WORKSPACE_CHANGED';
        throw error;
      }
      const kase = entry.case, run = runs.get(entry.request_key);
      const row = run?.table_row || run?.frontend_view?.table_row || {};
      const input = run?.trace?.input || kase.live_request || null;
      return {id: row.id || kase.id, pool_index: selection.pool_index, request_key: entry.request_key ?? null,
        scenario: row.scenario || kase.scenario || '',
        inputPreview: ['string','number','boolean'].includes(typeof row.input) ? String(row.input) : JSON.stringify(input),
        input, output: run ? run.trace?.extracted_output ?? null : kase.output ?? null,
        fulfillment: row.fulfillment_status || row.status || entry.status || '', axes: row.eval_axes_summary || []};
    });
  }

  function renderArtifact(value, meta = {}) {
    if (!value || value.kind !== 'axes_clustering') {throw new Error('不是聚类可视化产物');}
    const axes = prepare(value.cases, value.types);
    semanticGroups(value.clustering, axes, value.cases);
    return renderPage(value.cases, value.types, {...meta, artifact: value});
  }

  function renderPage(cases, types, meta = {}) {
    const artifact = meta.artifact || null;
    const axes = prepare(cases, types);
    const rows = axes.map((axis, axisIndex) => {
      const unit = axis.itemScope ? '条目' : '轴结论';
      const bar = axis.declared && axis.total ? axis.buckets.filter(b => b.count).map(bucket => {
        const index = axis.buckets.indexOf(bucket);
        const label = `${bucket.value || '(空值)'} · ${bucket.count} · ${percent(bucket.count, axis.total)}`;
        return `<button class="segment" data-axis="${axisIndex}" data-bucket="${index}" aria-pressed="false" aria-label="${escapeHtml(axis.title + '：' + label)}" title="${escapeHtml(label)}" style="width:${bucket.count * 100 / axis.total}%;background:${bucket.color}"><span>${percent(bucket.count, axis.total)}</span></button>`;
      }).join('') : '<span class="no-data">' + (axis.declared ? '无可绘制的结论' : '未声明统计口径') + '</span>';
      const legend = axis.declared ? axis.buckets.map((bucket, index) =>
        `<button class="legend-item" data-axis="${axisIndex}" data-bucket="${index}" aria-pressed="false" ${bucket.count ? '' : 'disabled'}><i style="background:${bucket.color}"></i><span>${escapeHtml(bucket.value || '(空值)')}</span><b>${bucket.count}</b><span class="muted">${percent(bucket.count, axis.total)}</span></button>`).join('') : '';
      return `<section class="axis-row"><div class="axis-name"><h2>${escapeHtml(axis.title)}</h2><span class="muted">${axis.total} 个${unit}</span></div><div class="axis-chart"><div class="bar">${bar}</div><div class="legend">${legend}</div><div class="coverage">运行记录 ${axis.recorded} / ${cases.length} 例 · 未跑成 ${axis.recorded - axis.succeeded}${axis.missingVerdicts ? ' · 无轴结论 ' + axis.missingVerdicts : ''}</div></div></section>`;
    }).join('');
    const details = cases.map(kase => ({id: kase.id || '', pool_index: kase.pool_index ?? null, request_key: kase.request_key ?? null,
      scenario: kase.scenario || '', inputPreview: kase.inputPreview || '',
      input: kase.input ?? null, output: kase.output ?? null, fulfillment: kase.fulfillment || '',
      axes: (kase.axes || []).map(a => ({type_id: a.type_id || a.axis_id, title: a.title, status: a.status, verdict: a.verdict,
        text: a.text || '', composition: a.composition, issues: a.issues || [], evidence_records: a.evidence_records || {},
        execution_trace_ref: a.execution_trace_ref,
        items: (a.items || []).map(item => ({key: item.key, value: item.value, reason: item.reason || '',
          problem_ids: item.problem_ids || [], upstream_issue_ids: item.upstream_issue_ids || []})),
      }))}));
    const data = JSON.stringify({axes, cases: details, api: {base: meta.apiBase || null, project: meta.project || '', batchSnapshot: meta.batchSnapshot || null},
      artifact: artifact ? {clustering: artifact.clustering} : null}).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>展示试验 · 案例与各轴结论</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid #4263eb;outline-offset:2px}
header{background:#15223b;color:white;padding:22px max(20px,calc((100vw - 1760px)/2))}header h1{font-size:23px;margin:8px 0}header p{font-size:13px;color:#c5cfdf;margin:0}.badge{border:1px solid #607297;border-radius:20px;padding:3px 9px;font-size:11px}main{max-width:1800px;margin:auto;padding:20px}.muted,.coverage{font-size:11px;color:#64748b}.intro{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.intro strong{font-size:16px}
.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:12px}.axis-row{min-width:0;background:white;border:1px solid #e0e5ee;border-radius:12px;padding:14px}.axis-name{display:flex;gap:8px;align-items:baseline;justify-content:space-between;margin-bottom:10px}.axis-name h2{font-size:14px;margin:0;overflow-wrap:anywhere}.axis-chart{min-width:0}.bar{display:flex;width:100%;height:28px;background:#edf1f7;border-radius:6px;overflow:hidden}.segment{flex:none;min-width:0;padding:0;border:0;color:white;overflow:hidden}.segment span{display:block;margin:0 4px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:11px}.segment:hover{filter:brightness(1.12)}.segment[aria-pressed=true]{box-shadow:inset 0 0 0 2px #172033}.legend{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}.legend-item{display:flex;align-items:center;gap:5px;max-width:100%;border:1px solid #e4e8ef;border-radius:5px;background:white;color:#334155;padding:4px 6px;font-size:10px;overflow-wrap:anywhere}.legend-item span{min-width:0}.legend-item i{flex:none;width:7px;height:7px;border-radius:2px}.legend-item:disabled{opacity:.4;cursor:default}.legend-item[aria-pressed=true]{border-color:#334155;background:#edf2ff}.coverage{margin-top:8px}.no-data{padding:6px;color:#64748b;font-size:11px}
#workspace{display:grid;grid-template-columns:minmax(0,1fr) 450px;align-items:start;gap:16px;margin-top:20px;scroll-margin-top:12px}.matrix-panel,.detail-panel{min-width:0;background:white;border:1px solid #dfe5ef;border-radius:12px}.matrix-toolbar{padding:16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}.matrix-toolbar h2{font-size:17px;margin:0}.matrix-toolbar label{margin-left:auto}.matrix-toolbar input{width:220px;max-width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:7px;font-size:12px}#all-cases{background:#edf2ff;border:1px solid #cad7f5;color:#294dab;border-radius:7px;padding:8px 10px;font-size:12px}.matrix-help{padding:0 16px 12px;margin:0;color:#64748b;font-size:12px}.matrix-scroll{overflow:auto;max-height:72vh;border-top:1px solid #e5eaf2;border-radius:0 0 12px 12px}.matrix{border-collapse:separate;border-spacing:0;width:100%;min-width:${280 + axes.length * 110}px;table-layout:fixed;font-size:12px}.matrix th,.matrix td{border-bottom:1px solid #e8edf4;border-right:1px solid #f0f3f8;padding:0;vertical-align:middle}.matrix th{position:sticky;top:0;z-index:2;padding:12px 6px;background:#edf2f9;color:#475569;font-size:11px}.matrix th:first-child,.case-name{position:sticky;left:0;background:white;z-index:1}.matrix th:first-child{z-index:3;background:#edf2f9}.matrix .case-name{vertical-align:top}.case-open{border:0;background:none;display:block;text-align:left;padding:10px 12px;width:100%}.case-id{font-size:10px;font-weight:700;color:#526178;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.input-preview{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:12px;line-height:1.5;margin:5px 0;color:#172033}.case-scenario{display:block;font-size:10px;color:#718096;overflow-wrap:anywhere}.matrix-cell{border:0;background:transparent;min-height:68px;width:100%;padding:8px 6px;display:block;text-align:center}.matrix-reason{display:block;text-align:left;margin-top:8px}.reason-label,.reason-subject,.reason-more{display:block;font-size:10px;line-height:1.5;color:#64748b}.reason-subject{overflow-wrap:anywhere;margin:3px 0}.matrix-reason-text{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;line-height:1.65;color:#334155;margin:4px 0}.reason-more{margin-top:6px;color:#4263eb}.reason-focus .matrix-cell{text-align:left;padding:12px}.reason-focus .matrix-reason-text{display:block;-webkit-line-clamp:unset;max-height:280px;overflow:auto;font-size:13px}.axis-focus{border:0;background:transparent;padding:3px;color:#334155;font-size:11px;width:100%}.axis-focus:hover{color:#4263eb}.axis-focus[aria-pressed=true]{color:#294dab;font-weight:700}.axis-reason-summary+.axis-reason-summary{border-top:1px solid #e0e5ee;padding-top:10px}.reason-axis-link{border:0;background:none;padding:0;color:#294dab;text-align:left;font-size:12px;font-weight:700}.matrix-cell:hover,.case-open:hover{background:#edf2ff}.matrix-row.selected td{background:#f2f6ff}.matrix-row.selected .case-name{background:#eaf0ff;border-left:3px solid #4263eb}.matrix-cell[aria-pressed=true]{box-shadow:inset 0 0 0 2px #4263eb}.enum-chip{display:inline-block;font-size:10px;padding:3px 5px;border:1px solid;border-radius:5px;overflow-wrap:anywhere;max-width:100%;line-height:1.4}.state-label{font-size:10px;color:#718096;overflow-wrap:anywhere}.state-execution .state-label{border:1px dashed #64748b;background:#f1f5f9;padding:4px 7px;border-radius:5px;color:#334155}.state-missing .state-label{border-bottom:1px dotted #64748b}.state-absent .state-label,.state-disabled .state-label{color:#94a3b8}.production-value{border:0;background:none;width:100%;padding:8px 4px;font-size:10px;color:#475569;overflow-wrap:anywhere}.empty{padding:28px!important;color:#64748b;text-align:center}
.detail-panel{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto;padding:18px;scroll-margin-top:12px}.detail-placeholder{padding:48px 12px;line-height:1.8;color:#64748b;font-size:14px;text-align:center}.eyebrow{font-size:10px;font-weight:800;letter-spacing:1.5px;color:#4263eb}.detail-head h2{font-size:16px;overflow-wrap:anywhere;margin:6px 0}.detail-head p{margin:4px 0}.case-verdict{font-size:12px;margin:10px 0;color:#334155}.case-axis-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin:14px 0}.axis-tab{border:1px solid #e0e5ee;background:white;border-radius:7px;padding:8px;text-align:left;display:flex;flex-wrap:wrap;gap:4px;align-items:center;min-width:0}.axis-tab strong{display:block;width:100%;font-size:11px}.axis-tab[aria-pressed=true]{border:2px solid #4263eb;background:#f3f6ff;padding:7px}.case-io{display:grid;gap:12px}.io-pane{min-width:0;border:1px solid #dce3ef;border-radius:8px;overflow:hidden}.io-pane h3{font-size:12px;margin:0;padding:9px 12px;background:#edf3fb}.io-pane pre{margin:0;padding:12px;max-height:230px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace}.case-axis-detail{margin:14px 0;border-top:1px solid #e0e5ee;padding:14px 4px 0 0;max-height:360px;overflow:auto}.current-axis-title{font-size:14px;margin:0 0 12px}.original-text,.reason,.empty-reason,.execution-note{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.7}.empty-reason{color:#64748b}.execution-note{padding:8px;background:#f1f5f9}.judgment{padding:12px 0;border-top:1px solid #edf0f5}.judgment-title{display:flex;gap:8px;align-items:start;font-size:12px}.judgment-title strong{min-width:0;overflow-wrap:anywhere}.value-tag{border-radius:5px;background:#edf1f7;padding:2px 5px;font-size:10px;overflow-wrap:anywhere;max-width:45%}.reason{margin:8px 0 0}
[hidden]{display:none!important}.view-modes{display:flex;gap:3px;background:#edf2f9;border-radius:8px;padding:3px}.view-modes button{border:0;background:transparent;color:#526178;padding:6px 8px;border-radius:6px;font-size:12px}.view-modes button[aria-pressed=true]{background:white;color:#294dab;box-shadow:0 1px 4px #1e35551a}.group-view{padding:0 14px 16px}.group-summary{font-size:12px;line-height:1.6;color:#64748b}.enum-groups{min-width:0}.enum-group{min-width:0}.group-case-count{font-size:12px;color:#526178}.group-members{max-height:65vh;overflow:auto;border-top:1px solid #e2e8f0}.group-member{padding:16px 0;border-bottom:1px solid #e8edf4;display:grid;grid-template-columns:minmax(140px,24%) minmax(0,1fr);gap:20px}.member-identity,.member-reasons{min-width:0}.group-member.selected{background:#eef3ff;box-shadow:inset 3px 0 #4263eb}.group-case-open{border:0;background:none;padding:0;color:#294dab;text-align:left;font-size:12px;overflow-wrap:anywhere}.group-input-preview{font-size:11px;line-height:1.5;color:#64748b;overflow-wrap:anywhere;margin:6px 0 10px}.member-evidence{background:#f0f6ff;border-left:3px solid #6d92cf;padding:10px 12px;margin-bottom:12px}.member-evidence-quote{margin:6px 0;font-size:12px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere}.group-reason+.group-reason{border-top:1px dashed #dfe5ef;margin-top:10px;padding-top:10px}.group-reason-key{font-size:10px;color:#64748b;overflow-wrap:anywhere}.group-reason-text{font-size:12px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0 0}
.distribution-section{margin-bottom:16px}.distribution-section>summary{cursor:pointer;font-size:13px;color:#475569;padding:10px 0}.distribution-section .overview-grid{margin-top:8px}#workspace.directory-mode:not(.case-open-layout){grid-template-columns:1fr}.type-layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:24px;align-items:start}.type-directory-panel{background:#f6f8fc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;min-width:0}.type-directory-panel>h3{font-size:14px;margin:0 0 5px}.type-directory-panel>p{font-size:11px;color:#64748b;margin:0 0 10px}.type-directory{max-height:70vh;overflow:auto}.type-scope+.type-scope{margin-top:16px}.type-scope>summary{font-size:13px;color:#334155;cursor:pointer;padding:5px 0;overflow-wrap:anywhere}.type-label{margin:6px 0 8px 9px;padding-left:9px;border-left:1px solid #dce3ef}.type-label>summary{font-size:12px;cursor:pointer;padding:6px 0;overflow-wrap:anywhere}.tree-level{display:inline-block;font-size:9px;line-height:1.5;color:#64748b;background:#e8edf5;border-radius:3px;padding:1px 3px;margin-right:5px;font-weight:400}.label-count{font-size:10px;color:#64748b;margin-left:6px}.type-clusters{margin:2px 0 0 11px;padding-left:8px;border-left:1px dashed #cbd5e1}.type-entry{display:flex;align-items:center;gap:4px;width:100%;padding:8px 5px;border:1px solid #e2e8f0;border-radius:7px;background:white;text-align:left;margin:5px 0;flex-wrap:wrap}.type-entry[aria-pressed=true]{border-color:#4263eb;background:#eef3ff;box-shadow:inset 3px 0 #4263eb}.type-enum{font-size:12px;overflow-wrap:anywhere}.pending-type{font-size:11px;color:#334155}.type-count{font-size:10px;color:#526178;margin-left:auto}.directory-empty{font-size:12px;color:#64748b}.type-content-head{padding:3px 0 16px}.type-breadcrumb{font-size:12px;color:#64748b;margin:0 0 8px}.type-content-head h2{font-size:22px;margin:0 0 10px;color:#172033}.type-common{background:#f7f9fc;border:1px dashed #cbd5e1;border-radius:9px;padding:14px 16px;margin-bottom:22px}.type-common h3{font-size:13px;margin:0 0 7px}.type-common p{font-size:12px;color:#64748b;line-height:1.7;margin:0}.member-list-title{font-size:14px;margin:0 0 10px}.close-case-detail{border:1px solid #dce3ef;border-radius:6px;background:white;color:#475569;padding:5px 8px;font-size:11px;margin:6px 0}.directory-mode.case-open-layout .group-member{grid-template-columns:1fr;gap:4px}
.clustering-controls{background:white;border:1px solid #dfe5ef;border-radius:12px;padding:16px;margin:16px 0}.clustering-controls label{font-size:14px;font-weight:700}.clustering-controls textarea{display:block;width:100%;min-height:135px;resize:vertical;margin:10px 0;padding:12px;border:1px solid #cbd5e1;border-radius:8px;font-family:inherit;font-size:13px;line-height:1.7;color:#172033}.clustering-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.clustering-actions button{border:1px solid #cbd5e1;border-radius:7px;padding:8px 11px;background:#f5f7fb;color:#334155;font-size:12px}.clustering-actions button.primary{background:#4263eb;border-color:#4263eb;color:white}.clustering-actions button:disabled{opacity:.45;cursor:default}.clustering-status{font-size:12px;line-height:1.6;color:#475569;margin:10px 0 0}.priority-explanation{margin-top:12px;font-size:12px;color:#475569}.priority-explanation summary{cursor:pointer}.priority-explanation p{margin:8px 0}.cluster-name{font-size:12px;color:#172033;overflow-wrap:anywhere}
.clustering-feedback{display:flex;gap:12px;align-items:center;padding:14px 16px;margin:12px 0;border:1px solid #cbd5e1;border-radius:9px;background:#f5f7fb}.feedback-text{flex:1;min-width:0}.clustering-feedback strong{display:block;font-size:16px}.clustering-feedback .clustering-status{margin:5px 0 0}.clustering-feedback[data-phase=running],.clustering-feedback[data-phase=submitting]{background:#edf3ff;border-color:#b9caf4}.clustering-feedback[data-phase=running] strong:before,.clustering-feedback[data-phase=submitting] strong:before{content:'';display:inline-block;width:13px;height:13px;border:2px solid #bccafa;border-top-color:#4263eb;border-radius:50%;margin-right:8px;vertical-align:-1px;animation:cluster-spin 1s linear infinite}.clustering-feedback[data-phase=completed]{background:#edf8f3;border-color:#a8d7c3}.clustering-feedback[data-phase=failed]{background:#fff1f0;border-color:#edb8b4}.clustering-feedback[data-phase=stale],.clustering-feedback[data-phase=blocked]{background:#fff8e8;border-color:#e4cc8d}.view-clustering-result{flex:none;background:#294dab;color:white;border:0;border-radius:7px;padding:10px 13px;font-size:13px;font-weight:700}.view-clustering-result:hover{background:#203f91}@keyframes cluster-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.clustering-feedback strong:before{animation:none!important}}@media(max-width:600px){.clustering-feedback{flex-wrap:wrap}.view-clustering-result{width:100%}}
.artifact-banner{padding:16px;background:#eef3ff;border:1px solid #cad7f5;border-radius:10px;margin-bottom:16px}.artifact-banner h2{font-size:18px;margin:0 0 8px}.artifact-banner p{font-size:13px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}.artifact-banner summary{cursor:pointer;font-size:12px}.task-progress{margin:0 0 18px;padding:14px 16px;background:white;border:1px solid #dfe5ef;border-radius:12px}.task-progress-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.task-progress-head h2{margin:0;font-size:17px}.task-progress-head button{border:1px solid #cbd5e1;border-radius:6px;background:#f5f7fb;padding:7px 10px;color:#334155;font-size:12px}.task-progress-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:10px}.task-progress-grid>div{min-width:0;padding:12px;border:1px solid #e4eaf3;border-radius:9px;background:#f8fafd}.task-progress-grid h3{font-size:14px;margin:0 0 8px}.task-progress-grid progress{display:block;width:100%;height:10px;margin:9px 0;accent-color:#4263eb}.task-count{font-size:20px}.task-detail,.task-estimate{font-size:11px;line-height:1.6;color:#64748b;margin:6px 0;overflow-wrap:anywhere}.task-estimate{color:#334155}.task-warning{font-size:12px;line-height:1.7;color:#854d0e;background:#fff7dc;border:1px solid #e4cc8d;border-radius:6px;padding:9px}.task-times{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:11px;margin:8px 0}.task-times dt{color:#64748b}.task-times dd{margin:0;font-variant-numeric:tabular-nums}.task-connection{font-size:11px;color:#64748b;margin:10px 0 0}@media(max-width:700px){.task-progress-grid{grid-template-columns:1fr}}
@media(max-width:1150px){#workspace{grid-template-columns:1fr}.detail-panel{position:static;max-height:none}.case-io{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.case-axis-summary{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}}@media(max-width:600px){.type-layout{grid-template-columns:1fr;gap:16px}.type-directory{max-height:230px}.group-member{grid-template-columns:1fr;gap:6px}main{padding:12px}.matrix-toolbar label{margin-left:0;width:100%}.matrix-toolbar input{width:100%}.case-io{grid-template-columns:1fr}.detail-panel{padding:14px}.matrix{min-width:${280 + axes.length * 110}px}}
</style></head><body><header><span class="badge">展示试验 · 只读</span><h1>先看整批，再看同一个案例</h1><p>${escapeHtml(meta.project || '')} · 当前筛选 ${cases.length} 条 · ${escapeHtml(meta.generatedAt || '')}</p></header><main>${artifact ? '<section class="artifact-banner"><h2>ToolLoop 聚类产物</h2><p>' + escapeHtml(meta.mode === 'scripted' ? '脚本演示：分类由预置回复产生，只验证流程与页面，不代表真实模型效果。' : '由本次 ToolLoop 被接受的提交生成。固定前端只展示内容，不重新归类。') + '</p><p>材料来源：' + escapeHtml(artifact.data_source || '未声明') + ' · 运行：' + escapeHtml(meta.runId || '未提供') + '</p><details><summary>本次聚类标准</summary><p>' + escapeHtml(artifact.criteria || '') + '</p></details></section>' : ''}<section class="task-progress" aria-label="任务进度" ${artifact ? 'hidden' : ''}><div class="task-progress-head"><h2>任务进度</h2><button id="refresh-run-results" type="button">刷新运行结果</button></div><div class="task-progress-grid"><div id="batch-progress"></div><div id="model-progress"></div></div><p id="task-connection" class="task-connection"></p></section><details id="distribution-overview" class="distribution-section" open><summary>各轴分布概览 · ${axes.length} 轴（点击可收起）</summary><div class="overview-grid">${rows || '<p class="empty">没有扩展轴记录；仍可在下方查看案例。</p>'}</div></details><section class="clustering-controls" ${artifact ? 'hidden' : ''}><label for="clustering-criteria">聚类与优先级标准</label> <span id="criteria-version" class="muted"></span><div id="clustering-feedback" class="clustering-feedback" data-phase="loading" role="status" aria-live="polite"><div class="feedback-text"><strong id="clustering-headline">正在读取聚类状态…</strong><p class="clustering-status" id="clustering-status">普通刷新只读取已有结果，不调用模型。</p></div><button id="view-clustering-result" class="view-clustering-result" hidden>查看聚类结果 ↓</button></div><textarea id="clustering-criteria" placeholder="正在读取后端保存的标准" disabled></textarea><div class="clustering-actions"><button id="save-clustering-criteria" disabled>仅保存标准</button><button id="start-clustering" class="primary" disabled>保存并重新聚类（LLM）</button><button id="reload-clustering">读取最新标准</button></div></section><section id="workspace"><div class="matrix-panel"><div class="matrix-toolbar"><h2 id="view-title" tabindex="-1">案例 × 轴</h2><div class="view-modes" role="group" aria-label="查看方式"><button id="matrix-mode" aria-pressed="true">按案例看</button><button id="group-mode" aria-pressed="false">语义类型目录</button></div><span id="matrix-filter" class="muted"></span><label><input id="case-search" type="search" aria-label="搜索案例" placeholder="搜索案例、输入或理由"></label><button id="all-cases">全部案例</button></div><p id="matrix-help" class="matrix-help">横着对照各轴结论与原始理由。点击列标题或色块，展开该轴的宽列理由；长说明可滚动。点格子查看全部逐项理由及输入输出。failed / blocked 是运行状态。</p><div id="group-view" class="group-view" hidden><p id="group-summary" class="group-summary"></p><div class="type-layout"><aside class="type-directory-panel"><h3>轴 → 标签 → 聚类</h3><p>按保存的标准归纳情况，同级按关注度排序</p><nav id="type-directory" class="type-directory" aria-label="候选类型目录"></nav></aside><div id="enum-groups" class="enum-groups"></div></div></div><div id="matrix-view" class="matrix-scroll"><table id="case-matrix" class="matrix"><colgroup id="matrix-columns"></colgroup><thead id="matrix-head"></thead><tbody id="matrix-body"></tbody></table></div></div><aside id="experiment-details" class="detail-panel" aria-label="案例详情"></aside></section><p class="muted">图表保持原始筛选范围，搜索只过滤目录和矩阵，不重新聚类。输入输出与判断原文只读展示，不重跑业务、不回写裁决、不保存完整 Trace。</p></main><script>const compositionText=${compositionText.toString()};const issueReason=${issueReason.toString()};const taskProgress=${taskProgress.toString()};const semanticGroups=${semanticGroups.toString()};const groupReasons=${groupReasons.toString()};const reasonSummary=${reasonSummary.toString()};const cellState=${cellState.toString()};(${wireInteractions.toString()})(${data});</script></body></html>`;
  }

  global.AxesExperiment = Object.freeze({prepare, cellState, reasonSummary, groupReasons, semanticGroups, taskProgress, fromWorkspace, renderArtifact, renderPage});
})(globalThis);
