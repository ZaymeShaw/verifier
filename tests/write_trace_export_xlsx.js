const fs = require("fs");
const path = require("path");
const vm = require("vm");

const frontend = path.resolve(__dirname, "../impl/frontend");
const outPath = process.argv[2];
if (!outPath) {
  throw new Error("usage: node write_trace_export_xlsx.js <out.xlsx>");
}

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  Blob: class {},
  URL: {createObjectURL() { return "blob:x"; }, revokeObjectURL() {}},
  document: {createElement() { return {style: {}, click() {}, remove() {}}; }, body: {appendChild() {}}},
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(frontend, "vendor/exceljs.min.js"), "utf8"), sandbox);
vm.runInContext(fs.readFileSync(path.join(frontend, "case_pool_export.js"), "utf8"), sandbox);

const exporter = sandbox.CasePoolExporter;
if (typeof exporter.formatTraceShow !== "function") {
  throw new Error("formatTraceShow is not a function");
}
const lastKeys = exporter.COLUMNS.slice(-2).map((column) => column.key);
if (lastKeys.join(",") !== "carrierPlacement,evalAxes") {
  throw new Error("expected 裁决 then 扩展轴结论 as the last export columns, got " + lastKeys.join(","));
}

const show = {
  available: true,
  mock: {
    user_intent: "上一轮只点名保额，本轮用金额短答补槽",
    query: "保额的保单",
    scenario: "clarification_reply",
  },
  overview: {
    completion_status: "completed",
    turn_count: 2,
    final_output_turn: 2,
    stop_reason: "goal_satisfied",
  },
  turns: [
    {
      turn_index: 1,
      mock_message: "保额的保单",
      status: "succeeded",
      runtime_ms: 2475,
      output: [
        {path: "status", found: true, value: "UNSUPPORTED"},
        {path: "message", found: true, value: "“保额”缺少必要的条件，请补充后重试"},
        {path: "query", found: true, value: "保额的保单"},
        {path: "filter", found: true, value: null},
      ],
    },
    {
      turn_index: 2,
      mock_message: "50万以上",
      status: "succeeded",
      runtime_ms: 26,
      output: [
        {path: "status", found: true, value: "SUCCESS"},
        {path: "message", found: true, value: "解析成功"},
        {path: "query", found: true, value: "50万以上"},
        {path: "filter", found: true, value: {type: "PREDICATE", node_id: "n0", field: "sum_ins", operator: "GTE", value: 500000}},
      ],
    },
  ],
};

const rows = [{
  id: "policy-search-rich-0003",
  source: "test",
  executionMode: "多轮",
  scenario: "clarification_reply",
  input: {query: "保额的保单"},
  output: {status: "SUCCESS"},
  reference: null,
  status: "fulfilled",
  judgeSummary: "ok",
  judgeJson: null,
  attributionSummary: "尚未归因",
  attributeJson: null,
  traceSummary: exporter.formatTraceShow(show),
  carrierPlacement: "",
  evalAxes: "[truthfulness:refuted×1] [truthfulness:verified×1]\n[fulfillment:not_fulfilled]",
}];

// Exercise the page's real row builder before writing XLSX, including its shared visibility rule.
const summarySource = fs.readFileSync(path.join(frontend, "summary.html"), "utf8");
for (const name of ["tableRow", "inferCaseScenario", "carrierPlacementText", "evalAxesRows", "axisShown", "exportEvalAxesSummaryRows", "exportEvalAxesDetailRows"]) {
  const start = summarySource.indexOf("function " + name + "(");
  const end = summarySource.indexOf("\nfunction ", start);
  if (start < 0 || end < 0) {throw new Error("Missing page function: " + name);}
  vm.runInContext(summarySource.slice(start, end), sandbox);
}
const view = {
  id: "policy-search-rich-0003", scenario: "clarification_reply", trace: {status: "ok"},
  judge: {overall_fulfillment: {status: "fulfilled"}, reasoning_summary: "条款一致"},
  stage_timings: {live_ms: 6200, judge_ms: 40100, carrier_ms: 100},
  eval_axes_summary: [
    {axis_id: "truthfulness-run", type_id: "truthfulness", title: "真实性", status: "succeeded", verdict: "refuted", text: "轴级原文：发现不符说法", llm_model: "deepseek", llm_calls: 3, tool_calls: 11, elapsed_ms: 60400,
      items: [{value: "refuted", key: "犹豫期是二十天", reason: "知识库原文为十五日",
        citations: [{source: "es://clause_kb", ref: "xx_hesitation#clause_text", note: "本产品犹豫期为十五日"}]}]},
    {type_id: "analysis", display: "collapsed", status: "succeeded", items: [
      {value: "a", key: "对象甲", reason: "分析甲全文"},
      {value: "b", key: "对象乙", reason: "分析乙全文"},
    ]},
    {type_id: "failed_analysis", display: "collapsed", status: "failed", text: "运行失败原因"},
    {type_id: "expanded_analysis", display: "expanded", status: "succeeded", text: "显式展开说明"},
    {type_id: "disabled_axis", status: "disabled", text: "未启用"},
  ],
};
const axisRows = sandbox.exportEvalAxesSummaryRows(view);
const detailRows = sandbox.exportEvalAxesDetailRows(view);

exporter.createWorkbook(rows, sandbox.ExcelJS, axisRows, detailRows).xlsx.writeBuffer().then((buf) => {
  fs.writeFileSync(outPath, Buffer.from(buf));
}).catch((err) => {
  console.error(err);
  process.exit(1);
});
