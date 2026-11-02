(function (global) {
  'use strict';

  const MAX_EXCEL_CELL_LENGTH = 32767;
  const TRUNCATION_MARKER = '[已因 Excel 单元格 32767 字符上限截断]';
  const MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  const SHEET_NAME = '用例池候选区';
  // 第二张 sheet：一行一件事（live / 生产 judge / 生产轴2 / 每个扩展轴的每一条 item），理由全文和耗时都在这里。
  const DETAIL_SHEET_NAME = '扩展轴明细';
  const DETAIL_COLUMNS = [
    {header: 'case_id', key: 'caseId', width: 28},
    {header: 'scenario', key: 'scenario', width: 20},
    {header: '阶段/轴', key: 'stage', width: 20},
    {header: 'status', key: 'status', width: 12},
    {header: 'verdict', key: 'verdict', width: 16},
    {header: '对象（断言/期望）', key: 'subject', width: 40},
    {header: '理由', key: 'reason', width: 80},
    {header: '引用', key: 'citations', width: 48},
    {header: '模型', key: 'model', width: 22},
    {header: 'llm_calls', key: 'llmCalls', width: 10},
    {header: 'tool_calls', key: 'toolCalls', width: 10},
    {header: '秒', key: 'seconds', width: 8},
  ];
  const COLUMNS = [
    {header: 'ID', key: 'id', width: 24},
    {header: '来源', key: 'source', width: 20},
    {header: '执行模式', key: 'executionMode', width: 22},
    {header: 'Scenario', key: 'scenario', width: 24},
    {header: 'Input / Live Request', key: 'input', width: 48},
    {header: 'Output / 被评估输出', key: 'output', width: 48},
    {header: 'Reference', key: 'reference', width: 48},
    {header: '状态', key: 'status', width: 22},
    {header: 'Judge 摘要', key: 'judgeSummary', width: 42},
    {header: 'Judge JSON', key: 'judgeJson', width: 54},
    {header: '归因摘要', key: 'attributionSummary', width: 42},
    {header: 'Attribute JSON', key: 'attributeJson', width: 54},
    {header: 'Trace 摘要', key: 'traceSummary', width: 54},
    {header: '裁决', key: 'carrierPlacement', width: 42},
    // 每轴一行 `[轴id:值×n]` 令牌；Excel 筛选「包含 truthfulness:refuted」即可定位。理由在「扩展轴明细」sheet。
    {header: '扩展轴结论', key: 'evalAxes', width: 40},
  ];

  function lastColumnLetter(count) {
    let remaining = Number(count) || 0;
    let letters = '';
    while (remaining > 0) {
      const offset = (remaining - 1) % 26;
      letters = String.fromCharCode(65 + offset) + letters;
      remaining = Math.floor((remaining - 1) / 26);
    }
    return letters || 'A';
  }

  function fieldValueText(field) {
    if (!field || !field.found) {
      return '无值';
    }
    if (field.value === null) {
      return 'null';
    }
    if (field.value === undefined || field.value === '') {
      return field.value === '' ? '' : '无值';
    }
    if (typeof field.value === 'object') {
      return JSON.stringify(field.value);
    }
    return String(field.value);
  }

  function fieldLabel(field) {
    const path = String((field && field.path) || 'output');
    return path.split('.').pop() || path;
  }

  function formatTraceShow(show, options) {
    if (!show || !show.available) {
      return '无 Trace';
    }
    const overview = show.overview || {};
    const mock = show.mock || {};
    const scenario = String(mock.scenario || (options && options.scenario) || '-');
    const lines = [
      'Mock: ' + (mock.user_intent || mock.query || '无 Mock Intent'),
      '场景: ' + scenario,
    ];
    const overviewParts = [];
    if (overview.completion_status) {
      overviewParts.push(String(overview.completion_status));
    }
    overviewParts.push((overview.turn_count ?? 0) + ' 轮');
    if (overview.final_output_turn !== null && overview.final_output_turn !== undefined && overview.final_output_turn !== '') {
      overviewParts.push('最终输出轮 ' + overview.final_output_turn);
    }
    if (overview.stop_reason) {
      overviewParts.push('停止 ' + overview.stop_reason);
    }
    lines.push('概览: ' + overviewParts.join(' · '));
    (show.turns || []).forEach((turn, index) => {
      const item = turn || {};
      const heading = ['T' + (item.turn_index || index + 1), item.status || '-'];
      if (item.runtime_ms !== null && item.runtime_ms !== undefined && item.runtime_ms !== '') {
        heading.push(item.runtime_ms + 'ms');
      }
      lines.push('');
      lines.push(heading.join('  '));
      lines.push('    输入: ' + (item.mock_message || '主展示字段无值'));
      (item.output || []).forEach(field => {
        lines.push('    ' + fieldLabel(field) + ': ' + fieldValueText(field));
      });
    });
    return lines.join('\n');
  }

  function truncateCell(text) {
    const value = String(text ?? '');
    if (value.length <= MAX_EXCEL_CELL_LENGTH) {
      return value;
    }
    return value.slice(0, MAX_EXCEL_CELL_LENGTH - TRUNCATION_MARKER.length) + TRUNCATION_MARKER;
  }

  function cellText(value) {
    if (value === null || value === undefined || value === '') {
      return '';
    }
    if (typeof value === 'string') {
      return truncateCell(value);
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return truncateCell(String(value));
    }
    return truncateCell(JSON.stringify(value, null, 2));
  }

  function sanitizedProjectId(projectId) {
    const value = String(projectId || 'project')
      .trim()
      .replace(/[^A-Za-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '');
    return value || 'project';
  }

  function pad(value) {
    return String(value).padStart(2, '0');
  }

  function timestamp(date) {
    const value = date instanceof Date ? date : new Date(date);
    if (Number.isNaN(value.getTime())) {
      throw new Error('导出时间无效');
    }
    return value.getFullYear()
      + pad(value.getMonth() + 1)
      + pad(value.getDate())
      + '-'
      + pad(value.getHours())
      + pad(value.getMinutes())
      + pad(value.getSeconds());
  }

  function fileName(projectId, exportedAt) {
    return 'verifier-' + sanitizedProjectId(projectId) + '-cases-' + timestamp(exportedAt) + '.xlsx';
  }

  function requireExcelJS(override) {
    const library = override || global.ExcelJS;
    if (!library || typeof library.Workbook !== 'function') {
      throw new Error('本地 Excel 导出组件未加载');
    }
    return library;
  }

  function fillSheet(worksheet, columns, rows, rowHeight) {
    worksheet.columns = columns.map(column => ({...column}));
    worksheet.autoFilter = {from: 'A1', to: lastColumnLetter(columns.length) + '1'};

    const header = worksheet.getRow(1);
    header.height = 24;
    header.font = {bold: true, color: {argb: 'FFFFFFFF'}};
    header.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FF2563EB'}};
    header.alignment = {vertical: 'middle', horizontal: 'left', wrapText: true};

    rows.forEach(item => {
      const rowData = {};
      columns.forEach(column => {
        const value = item && item[column.key];
        rowData[column.key] = typeof value === 'number' ? value : cellText(value);
      });
      const row = worksheet.addRow(rowData);
      if (rowHeight) {
        row.height = rowHeight;
      }
      row.eachCell({includeEmpty: true}, cell => {
        cell.alignment = {vertical: 'top', horizontal: 'left', wrapText: true};
      });
    });
  }

  function createWorkbook(rows, excelJsOverride, detailRows) {
    if (!Array.isArray(rows)) {
      throw new Error('导出数据必须是数组');
    }
    if (detailRows !== undefined && !Array.isArray(detailRows)) {
      throw new Error('扩展轴明细必须是数组');
    }
    const ExcelJS = requireExcelJS(excelJsOverride);
    const workbook = new ExcelJS.Workbook();
    workbook.creator = 'Verifier';
    workbook.created = new Date();

    fillSheet(workbook.addWorksheet(SHEET_NAME, {views: [{state: 'frozen', ySplit: 1}]}), COLUMNS, rows, 60);
    if (detailRows && detailRows.length) {
      fillSheet(workbook.addWorksheet(DETAIL_SHEET_NAME, {views: [{state: 'frozen', ySplit: 1}]}), DETAIL_COLUMNS, detailRows, 0);
    }

    return workbook;
  }

  async function download(options) {
    const settings = options || {};
    const rows = settings.rows || [];
    const exportedAt = settings.exportedAt || new Date();
    const workbook = createWorkbook(rows, settings.ExcelJS, settings.detailRows);
    const buffer = await workbook.xlsx.writeBuffer();
    const BlobType = settings.Blob || global.Blob;
    const URLType = settings.URL || global.URL;
    const documentValue = settings.document || global.document;
    if (!BlobType || !URLType || typeof URLType.createObjectURL !== 'function' || !documentValue) {
      throw new Error('当前浏览器不支持文件下载');
    }

    const name = fileName(settings.projectId, exportedAt);
    const blob = new BlobType([buffer], {type: MIME_TYPE});
    const url = URLType.createObjectURL(blob);
    const anchor = documentValue.createElement('a');
    anchor.href = url;
    anchor.download = name;
    anchor.style.display = 'none';
    documentValue.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
      global.setTimeout(() => URLType.revokeObjectURL(url), 0);
    }
    return {fileName: name, rowCount: rows.length};
  }

  global.CasePoolExporter = Object.freeze({
    COLUMNS,
    DETAIL_COLUMNS,
    DETAIL_SHEET_NAME,
    MAX_EXCEL_CELL_LENGTH,
    TRUNCATION_MARKER,
    cellText,
    createWorkbook,
    download,
    fileName,
    formatTraceShow,
    truncateCell,
  });
})(typeof globalThis === 'undefined' ? window : globalThis);
