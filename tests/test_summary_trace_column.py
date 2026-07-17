from pathlib import Path


SUMMARY_HTML = Path(__file__).resolve().parents[1] / "impl" / "frontend" / "summary.html"


def _summary_source() -> str:
    return SUMMARY_HTML.read_text(encoding="utf-8")


def test_case_pool_keeps_output_reference_adjacent_and_puts_trace_last():
    source = _summary_source()

    assert (
        "<th>Output / 被评估输出</th><th>Reference</th><th>状态</th>"
        "<th>Score / Judge</th><th>归因摘要</th><th>Trace</th>"
    ) in source
    assert "<td class=\"case-output\">'+renderOutputCell(v)+'</td><td class=\"case-reference\">'+renderReferenceCell(v)+'</td>" in source
    assert "<td class=\"case-trace\">'+renderTraceCell(v)+'</td></tr>" in source


def test_trace_cell_uses_only_current_case_trace_and_is_collapsed():
    source = _summary_source()
    start = source.index("function renderTraceCell(item)")
    end = source.index("\nfunction ", start + 1)
    renderer = source[start:end]

    assert "const trace=item.trace;" in renderer
    assert "frontend_view" not in renderer
    assert "run_trace_summary" not in renderer
    assert "<details><summary>展开完整 Trace</summary>" in renderer
    assert "escapeHtml(JSON.stringify(trace,null,2))" in renderer
    assert "无 Trace" in renderer


def test_output_cell_renders_only_schema_shaped_item_output():
    source = _summary_source()
    start = source.index("function renderOutputCell(item)")
    end = source.index("\nfunction ", start + 1)
    renderer = source[start:end]

    assert "formatJsonCell(item.output,1800)" in renderer
    assert "item.trace" not in renderer
    assert "interactionSummary" not in renderer
    assert "judge" not in renderer
    assert "outputSummary" not in renderer
    assert "function renderInteractiveOutput" not in source
    assert "function caseOutput" not in source


def test_input_cell_renders_actual_live_schema_request_without_frontend_field_inference():
    source = _summary_source()
    start = source.index("function caseInputPayload(item)")
    end = source.index("\nfunction ", source.index("function renderInputCell(item)") + 1)
    renderer = source[start:end]

    assert "item.trace?.input || item.live_request" in renderer
    assert "formatJsonCell(input,1800)" in renderer
    assert "displayInputText" not in source[source.index("function renderCasePool()"):source.index("\nfunction outputSummary")]
    assert "Input / Live Request" in source


def test_output_and_reference_share_json_formatting():
    source = _summary_source()

    assert "formatJsonCell(item.output,1800)" in source
    assert "formatJsonCell(ref,1800)" in source
    assert "function inputReference(item){return item.reference || null;}" in source


def test_trace_column_is_wide_enough_for_full_trace_json():
    source = _summary_source()

    assert ".case-trace{min-width:720px;max-width:900px" in source
    assert ".case-output,.case-reference{min-width:420px;max-width:520px" in source


def test_case_pool_empty_rows_span_new_trace_column():
    source = _summary_source()

    assert source.count('colspan="12"') == 2
    assert 'colspan="11"' not in source


def test_batch_results_are_not_matched_by_input_content():
    source = _summary_source()
    assert "function resultMatchesCase" not in source
    assert "function comparableInput" not in source
    assert "function inputCandidates" not in source
    assert "批量结果与当前用例输入不一致" not in source


def test_frontend_requires_vnext_mock_case_transport_shape():
    source = _summary_source()
    start = source.index("function normalizeCase(item,index,source)")
    end = source.index("\nfunction ", start + 1)
    normalizer = source[start:end]

    assert "'id','project_id','scenario','intent','live_request','output','reference'" in normalizer
    assert "不是 VNext MockCase" in normalizer


def test_case_without_run_evidence_cannot_keep_imported_status():
    source = _summary_source()
    start = source.index("function sanitizeCaseResult(item)")
    end = source.index("\nfunction ", start + 1)
    sanitizer = source[start:end]

    assert "if(!hasStoredResult(item))" in sanitizer
    assert "status:'pending'" in sanitizer
    assert "error:null" in sanitizer


def test_real_row_error_counts_as_run_evidence_and_is_not_reset_to_pending():
    source = _summary_source()
    start = source.index("function hasStoredResult(item)")
    end = source.index("\nfunction ", start + 1)
    detector = source[start:end]

    assert "item.status==='error' && item.error" in detector


def test_selected_cases_show_running_and_surface_batch_failure():
    source = _summary_source()
    start = source.index("async function runSelectedCases()")
    end = source.index("\nfunction renderClusterSummary", start + 1)
    runner = source[start:end]

    assert "selectedIndexes=new Set" in runner
    assert "status:'running',error:null" in runner
    assert "selectedIndexes.has(index) && item.status==='running'" in runner
    assert runner.count("renderCasePool();") >= 2


def test_case_status_shows_running_and_row_error_details():
    source = _summary_source()
    start = source.index("function renderCaseStatus(item)")
    end = source.index("\nfunction ", start + 1)
    renderer = source[start:end]

    assert "['running','error'].includes(item.status)" in renderer
    assert "item.error" in renderer
    assert "error-text" in renderer
    assert "<td>'+renderCaseStatus(v)+'</td>" in source


def test_batch_submission_sends_only_mock_case_fields():
    source = _summary_source()
    assert "function transportCase(item){return {id:item.id,project_id:item.project_id,scenario:item.scenario,intent:item.intent,live_request:item.live_request,output:item.output??null,reference:item.reference??null};}" in source
    assert "cases:selected.map(transportCase)" in source


def test_batch_merge_uses_protocol_request_key():
    source = _summary_source()
    start = source.index("function applyRunToCase(item,run,eventStatus)")
    end = source.index("\nfunction ", start + 1)
    merger = source[start:end]

    assert "caseResults[item.request_key]=run" in merger
    assert "output:" not in merger
    assert "reference:" not in merger
    assert "resultMatchesCase" not in merger
    assert "const latestByRequest={};" in source
    assert "latestByRequest[item.request_key]" in source
    assert "runsByRequest[item.request_key]" in source


def test_request_keys_bind_by_submission_index_not_case_id():
    source = _summary_source()
    runner = source[source.index("async function runSelectedCases()"):source.index("\nfunction renderClusterSummary")]

    assert "selectedEntries.map((entry,index)" in runner
    assert "started.requests?.[index]?.request_key" in runner
    assert "requestByCase" not in runner


def test_active_batch_is_persisted_and_resumed_after_reload():
    source = _summary_source()

    assert "safeSetSessionJson(scopedKey('activeBatch'),active)" in source
    assert "async function resumeActiveBatch()" in source
    assert "resumeActiveBatch();" in source
    assert "sessionStorage.removeItem(scopedKey('activeBatch'))" in source


def test_persisted_case_pool_keeps_mock_case_separate_from_run_results():
    source = _summary_source()
    light = source[source.index("function lightCase(item)"):source.index("\nfunction conversationDetail")]

    assert "case:transportCase(item)" in light
    assert "trace:item.trace" not in light
    assert "judge:item.judge" not in light
    assert "let caseResults={};" in source


def test_judge_card_collapsed_json_renderer_is_defined():
    source = _summary_source()

    assert "function collapsedJson(title,value)" in source
    assert "collapsedJson('缺失/错误/多余'" in source
    assert "escapeHtml(JSON.stringify(content,null,2))" in source
