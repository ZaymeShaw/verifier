"""Offline file-boundary checks; no model calls and no private workbook fixture."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "scripts/verifier-jevcls"


@pytest.fixture
def pipeline(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("verifier_jevcls_pipeline", ROOT / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parent))
    import jev_build_requests
    return jev_build_requests


def processed(path, records):
    path.write_text("\ufeff" + "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_state_replaced_whole_metadata_excluded_and_ids_safe(builder, tmp_path):
    states = ["用户说：\"你好\"\n第二行 {{KEEP}}", {"code": [1, None, True]}, ["跨项目", {"n": 2}]]
    records = [{"id": f"../../case-{i}", "state": s, "source": "local-only"} for i, s in enumerate(states)]
    source = processed(tmp_path / "processed.jsonl", records)
    target = tmp_path / "requests"
    assert builder.build(source, ROOT / "templates/answer-classification.json", target) == 3
    template = json.loads((target / "template.json").read_text())
    manifest = json.loads((target / "manifest.json").read_text())
    for entry, state in zip(manifest["requests"], states):
        body = json.loads((target / entry["request_file"]).read_text())
        assert set(body) == {"model", "state", "questions"}
        assert body["state"] == state
        assert body["questions"] == template["questions"]
        assert Path(entry["request_file"]).name == entry["request_file"]
    assert template["state"] == {}


@pytest.mark.parametrize("invalid", [
    '{"id":"b"}', '{"id":"b","state":{}}', '{"id":"b","state":true}',
    '{"id":"b","state":{"x":NaN}}', '{"id":"a","state":"重复"}',
    '{"id":"b","state":{"x":1,"x":2}}',
])
def test_late_invalid_record_never_publishes_requests(builder, tmp_path, invalid):
    source = tmp_path / "bad.jsonl"
    source.write_text('{"id":"a","state":"有效"}\n' + invalid, encoding="utf-8")
    target = tmp_path / "requests"
    with pytest.raises(ValueError):
        builder.build(source, ROOT / "templates/answer-classification.json", target)
    assert not target.exists()


@pytest.mark.parametrize("patch", [
    {"decode": {}}, {"model": ""}, {"questions": {}},
    {"questions": {"q": {"type": "choice", "criteria": {}}}},
    {"questions": {"q": {"type": "noul", "criteria": {"yes": "unsupported"}}}},
])
def test_invalid_protocol_fields_rejected(builder, tmp_path, patch):
    template = json.loads((ROOT / "templates/answer-classification.json").read_text())
    template.update(patch)
    template_file = tmp_path / "template.json"
    template_file.write_text(json.dumps(template), encoding="utf-8")
    source = processed(tmp_path / "processed.jsonl", [{"id": "a", "state": "text"}])
    with pytest.raises(ValueError):
        builder.build(source, template_file, tmp_path / "requests")


def test_standard_types_preserve_omitted_fields(builder, tmp_path):
    template = {"model": "jev-latest", "state": {}, "questions": {
        "binary": {"type": "noul"},
        "choice": {"type": "choice", "criteria": {"a": None, "b": {"rule": "描述"}}},
        "score": {"type": "score", "instructions": ["按顺序评分"], "criteria": ["差", "好"]},
    }}
    path = tmp_path / "template.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    source = processed(tmp_path / "processed.jsonl", [{"id": "a", "state": "text"}])
    target = tmp_path / "requests"
    builder.build(source, path, target)
    assert json.loads((target / "000001.json").read_text())["questions"] == template["questions"]


class Sheet:
    def __init__(self, title, rows):
        self.title, self.rows = title, rows

    def iter_rows(self, **kwargs):
        return iter(self.rows)


class Workbook(dict):
    @property
    def sheetnames(self):
        return list(self)

    def close(self):
        pass


@pytest.fixture
def workbook(pipeline, monkeypatch):
    import verifier_excel_to_jev_state as converter
    book = Workbook({
        "用例池候选区": Sheet("用例池候选区", [
            ("ID", "Input / Live Request", "Output / 被评估输出", "Reference", "Judge JSON"),
            ("b", '{"from_trace":{"trace_id":"tr-b"}}', '{"output_text":"B"}', None, '{"status":"not_evaluable"}'),
            ("a", '{"from_trace":{"trace_id":"tr-a"}}', '{"output_text":"A"}', "参考", None),
        ]),
        "评测轴汇总": Sheet("评测轴汇总", [
            ("case_id", "axis_id", "轴级判定", "展示分组", "运行状态", "是否问题 tag", "轴级说明"),
            ("a", "context", "sound", "主要展示", "succeeded", "否", "上下文衔接正确"),
            ("b", "knowledge", "unknown", "主要展示", "succeeded", "是", "缺少条款原文，无法核实。\n需要保留完整理由。"),
            ("b", "secondary", "refuted", "其余分析", "succeeded", "是", "辅助轴理由"),
            ("b", "good", "verified", "主要展示", "succeeded", "否", "已核实"),
            ("b", "broken", None, "主要展示", "failed", "否", "执行失败"),
        ]),
        "扩展轴明细": Sheet("扩展轴明细", [("case_id", "理由"), ("b", "证据不足")]),
    })
    monkeypatch.setattr(converter, "load_workbook", lambda *a, **kw: book)
    return book


def test_excel_joins_by_id_and_preserves_missing_evidence(pipeline, workbook, tmp_path):
    materials = processed(tmp_path / "materials.jsonl", [{"trace_id": "tr-a", "raw": "补充"}, {"trace_id": "tr-b", "raw": None}])
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"case_id_path": "/trace_id", "fields": {"raw": {"path": "/raw", "description": "原始材料"}}}))
    target = tmp_path / "result"
    assert pipeline.run(tmp_path / "source.xlsx", target, ROOT / "templates/answer-classification.json", materials, mapping) == 2
    b, a = [json.loads(line) for line in (target / "processed.jsonl").read_text().splitlines()]
    assert [b["id"], a["id"]] == ["tr-b", "tr-a"]
    assert set(a) == {"id", "state", "source"}
    manifest = json.loads((target / "requests/manifest.json").read_text())
    assert [r["id"] for r in manifest["requests"]] == ["tr-b", "tr-a"]
    assert set(b["state"]) == {"materials", "evaluations", "material_notes"}
    assert b["state"]["materials"]["raw"] == {"description": "原始材料", "present": True, "value": None}
    assert b["state"]["evaluations"]["value"] == [{"axis_id": "knowledge", "tag": "[knowledge:unknown]", "verdict": "unknown", "reason": "缺少条款原文，无法核实。\n需要保留完整理由。"}]
    assert a["state"]["evaluations"]["value"] == []
    assert a["state"]["materials"]["raw"]["value"] == "补充"
    assert a["source"]["row"] == 3


@pytest.mark.parametrize("live_request", [
    '{"body":{"trace_id":"business-request-id"}}',
    '{"from_trace":{"trace_id":""}}',
    '{"from_trace":{"trace_id":"tr-b"}}',
])
def test_missing_or_duplicate_langfuse_id_is_not_replaced(pipeline, workbook, tmp_path, live_request):
    row = list(workbook["用例池候选区"].rows[2])
    row[1] = live_request
    row[4] = '{"trace_id":"verifier-internal-id"}'
    workbook["用例池候选区"].rows[2] = tuple(row)
    target = tmp_path / "result"
    with pytest.raises(ValueError, match="Langfuse"):
        pipeline.run(tmp_path / "source.xlsx", target, ROOT / "templates/answer-classification.json")
    assert not target.exists()


def test_materials_do_not_join_by_excel_case_name(pipeline, workbook, tmp_path):
    materials = processed(tmp_path / "materials.jsonl", [{"trace_id": "a", "raw": "错误关联"}])
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"case_id_path": "/trace_id", "fields": {"raw": {"path": "/raw", "description": "材料"}}}))
    with pytest.raises(ValueError, match="Langfuse"):
        pipeline.run(tmp_path / "source.xlsx", tmp_path / "result",
                     ROOT / "templates/answer-classification.json", materials, mapping)


@pytest.mark.parametrize("failure", ["orphan", "truncated", "bad_json"])
def test_excel_error_does_not_publish_pipeline_output(pipeline, workbook, tmp_path, failure):
    if failure == "orphan":
        workbook["评测轴汇总"].rows.append(("unknown-id", "axis", "bad", "主要展示", "succeeded", "是", "孤立轴"))
    else:
        row = list(workbook["用例池候选区"].rows[2])
        row[1] = '[已因 Excel 单元格 32767 字符上限截断]' if failure == "truncated" else '{broken'
        workbook["用例池候选区"].rows[2] = tuple(row)
    target = tmp_path / "result"
    with pytest.raises(ValueError):
        pipeline.run(tmp_path / "source.xlsx", target, ROOT / "templates/answer-classification.json")
    assert not target.exists()


def test_existing_output_untouched(builder, tmp_path):
    source = processed(tmp_path / "processed.jsonl", [{"id": "a", "state": "text"}])
    target = tmp_path / "requests"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("existing")
    with pytest.raises(ValueError, match="已存在"):
        builder.build(source, ROOT / "templates/answer-classification.json", target)
    assert sentinel.read_text() == "existing"


@pytest.mark.parametrize("suffix", [".json", ".jsonl", ".csv", ".xlsx"])
def test_material_formats_and_pointer_escaping(pipeline, tmp_path, suffix):
    import verifier_excel_to_jev_state as converter
    data = {"trace/id": "tr-a", "a~b": "原文"}
    path = tmp_path / ("materials" + suffix)
    if suffix == ".json":
        path.write_text(json.dumps([data]))
    elif suffix == ".jsonl":
        path.write_text(json.dumps(data) + "\n")
    elif suffix == ".csv":
        path.write_text("trace/id,a~b\ntr-a,原文\n")
    else:
        from openpyxl import Workbook
        book = Workbook(); book.active.append(list(data)); book.active.append(list(data.values())); book.save(path)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"case_id_path": "/trace~1id", "fields": {
        "text": {"path": "/a~0b", "description": "原始文本"},
        "absent": {"path": "/missing", "description": "可选", "required": False}}}))
    result = converter.read_materials(path, mapping)["tr-a"]
    assert result["text"] == {"description": "原始文本", "present": True, "value": "原文"}
    assert result["absent"] == {"description": "可选", "present": False, "value": None}


def test_nested_types_and_missing_required(pipeline, tmp_path):
    import verifier_excel_to_jev_state as converter
    path = processed(tmp_path / "materials.jsonl", [{"trace_id": "tr-a", "payload": {"list": [False, 0, None, ""]}}])
    mapping = tmp_path / "mapping.json"
    config = {"case_id_path": "/trace_id", "fields": {"context": {"path": "/payload/list", "description": "上下文"}}}
    mapping.write_text(json.dumps(config))
    assert converter.read_materials(path, mapping)["tr-a"]["context"]["value"] == [False, 0, None, ""]
    config["fields"]["context"]["path"] = "/payload/missing"
    mapping.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="缺少必需字段"):
        converter.read_materials(path, mapping)


@pytest.mark.parametrize("records", [
    [{"trace_id": "tr-a", "text": "one"}, {"trace_id": "tr-a", "text": "two"}],
    [{"trace_id": "tr-a", "text": "missing case b"}],
    [{"trace_id": " tr-a", "text": "whitespace"}],
])
def test_material_identity_failures_leave_no_output(pipeline, workbook, tmp_path, records):
    materials = processed(tmp_path / "materials.jsonl", records)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"case_id_path": "/trace_id", "fields": {"text": {"path": "/text", "description": "材料"}}}))
    target = tmp_path / "result"
    with pytest.raises(ValueError, match="Langfuse"):
        pipeline.run(tmp_path / "source.xlsx", target, ROOT / "templates/answer-classification.json", materials, mapping)
    assert not target.exists()


def test_pipeline_env_paths_ignore_launch_directory(pipeline, workbook, tmp_path, monkeypatch):
    folder = tmp_path / "workflow"
    folder.mkdir()
    (folder / "input.xlsx").touch()
    (folder / "template.json").write_text((ROOT / "templates/answer-classification.json").read_text())
    (folder / ".env").write_text("INPUT_PATH=input.xlsx\nOUTPUT_DIR=result\nJEV_TEMPLATE_PATH=template.json\nJEV_MODEL=env-selected-model\nMATERIALS_PATH=\nMATERIALS_MAP_PATH=\n")
    monkeypatch.setattr(pipeline, "HERE", folder)
    monkeypatch.setattr(pipeline, "connection_config", lambda config: ("https://example.test/v1/decisions", "test-key", 120, "curl"))
    sent = []
    monkeypatch.setattr(pipeline, "send_requests", lambda *args: sent.append(args))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_PATH", "wrong-file.xlsx")
    pipeline.main([])
    manifest = json.loads((folder / "result/requests/manifest.json").read_text())
    assert manifest["count"] == 2
    assert sent == [(folder / "result", "https://example.test/v1/decisions", "test-key", 120, "curl")]
    assert not (tmp_path / "result").exists()
    assert json.loads((folder / "result/requests/000001.json").read_text())["model"] == "env-selected-model"
    assert json.loads((folder / "result/requests/template.json").read_text())["model"] == "env-selected-model"
    assert manifest["model"] == "env-selected-model"
    assert json.loads((folder / "template.json").read_text())["model"] == "jev-latest"


@pytest.mark.parametrize("missing", ["OUTPUT_DIR", "JEV_TEMPLATE_PATH"])
def test_pipeline_missing_env_path_does_not_publish(pipeline, tmp_path, monkeypatch, capsys, missing):
    (tmp_path / "input.xlsx").touch()
    (tmp_path / "template.json").touch()
    config = {"INPUT_PATH": "input.xlsx", "OUTPUT_DIR": "result", "JEV_TEMPLATE_PATH": "template.json"}
    config.pop(missing)
    (tmp_path / ".env").write_text("\n".join(k + "=" + v for k, v in config.items()))
    monkeypatch.setattr(pipeline, "HERE", tmp_path)
    with pytest.raises(SystemExit) as error:
        pipeline.main([])
    assert error.value.code == 1
    assert missing in capsys.readouterr().err
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize("scope,tags,expected", [
    ("main", "bad", ["[knowledge:unknown]"]),
    ("all", "bad", ["[knowledge:unknown]", "[secondary:refuted]"]),
    ("main", "all", ["[knowledge:unknown]", "[good:verified]"]),
    ("all", "all", ["[knowledge:unknown]", "[secondary:refuted]", "[good:verified]"]),
])
def test_axis_tag_filters(pipeline, workbook, tmp_path, scope, tags, expected):
    target = tmp_path / "result"
    pipeline.run(tmp_path / "input.xlsx", target, ROOT / "templates/answer-classification.json", axes_scope=scope, tags_scope=tags)
    records = [json.loads(line) for line in (target / "processed.jsonl").read_text().splitlines()]
    assert len(records) == 2  # Filtering tags must not drop cases.
    assert [r["tag"] for r in records[0]["state"]["evaluations"]["value"]] == expected
    assert records[0]["state"]["evaluations"]["filters"] == {"axes_scope": scope, "tags_scope": tags, "run_status": "succeeded"}


def test_unused_excel_content_is_not_read_into_state(pipeline, workbook, tmp_path):
    row = list(workbook["用例池候选区"].rows[1])
    row[2] = "[已因 Excel 单元格 32767 字符上限截断]"
    row[4] = "invalid judge json"
    workbook["用例池候选区"].rows[1] = tuple(row)
    workbook["扩展轴明细"].rows.append(("unknown-case", "unused"))
    target = tmp_path / "result"
    pipeline.run(tmp_path / "input.xlsx", target, ROOT / "templates/answer-classification.json")
    text = json.dumps([json.loads(line)["state"] for line in (target / "processed.jsonl").read_text().splitlines()])
    assert "invalid judge" not in text and "unused" not in text and "32767" not in text


@pytest.mark.parametrize("failure", ["missing_sheet", "missing_column", "invalid_scope", "invalid_marker"])
def test_axis_filter_errors_fail_closed(pipeline, workbook, tmp_path, failure):
    if failure == "missing_sheet":
        del workbook["评测轴汇总"]
    elif failure == "missing_column":
        workbook["评测轴汇总"].rows[0] = ("case_id", "axis_id")
    elif failure == "invalid_marker":
        row = list(workbook["评测轴汇总"].rows[1]); row[-2] = "maybe"
        workbook["评测轴汇总"].rows[1] = tuple(row)
    target = tmp_path / "result"
    with pytest.raises(ValueError):
        pipeline.run(tmp_path / "input.xlsx", target, ROOT / "templates/answer-classification.json", axes_scope="typo" if failure == "invalid_scope" else "main")
    assert not target.exists()


@pytest.mark.parametrize("reason", [None, "同一个标签的另一条理由"])
def test_axis_reasons_are_preserved_without_tag_deduplication(pipeline, workbook, tmp_path, reason):
    row = list(workbook["评测轴汇总"].rows[2])
    row[-1] = reason
    workbook["评测轴汇总"].rows.append(tuple(row))
    target = tmp_path / "result"
    pipeline.run(tmp_path / "input.xlsx", target, ROOT / "templates/answer-classification.json")
    values = json.loads((target / "processed.jsonl").read_text().splitlines()[0])["state"]["evaluations"]["value"]
    assert len(values) == 2
    assert values[0]["tag"] == values[1]["tag"]
    assert values[0]["reason"] == "缺少条款原文，无法核实。\n需要保留完整理由。"
    assert values[1]["reason"] == reason


def test_pipeline_overwrites_success_and_removes_stale_files(pipeline, workbook, tmp_path):
    target = tmp_path / "output"
    template = ROOT / "templates/answer-classification.json"
    pipeline.run(tmp_path / "input.xlsx", target, template)
    (target / "requests/stale.json").write_text("old batch")
    row = list(workbook["评测轴汇总"].rows[2]); row[-1] = "本次更新后的理由"
    workbook["评测轴汇总"].rows[2] = tuple(row)
    pipeline.run(tmp_path / "input.xlsx", target, template)
    assert not (target / "requests/stale.json").exists()
    assert json.loads((target / "processed.jsonl").read_text().splitlines()[0])["state"]["evaluations"]["value"][0]["reason"] == "本次更新后的理由"


def test_failed_rebuild_preserves_previous_output(pipeline, workbook, tmp_path):
    target = tmp_path / "output"
    pipeline.run(tmp_path / "input.xlsx", target, ROOT / "templates/answer-classification.json")
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
    bad_template = tmp_path / "invalid.json"
    bad_template.write_text('{"model":"bad"}')
    with pytest.raises(ValueError, match="组装失败"):
        pipeline.run(tmp_path / "input.xlsx", target, bad_template)
    assert before == {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}


def test_output_cannot_contain_input(pipeline, tmp_path):
    target = tmp_path / "output"; target.mkdir()
    source = target / "input.xlsx"; source.write_text("keep")
    with pytest.raises(ValueError, match="不能包含"):
        pipeline.run(source, target, ROOT / "templates/answer-classification.json")
    assert source.read_text() == "keep"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_model_env_rejected_without_replacing_output(pipeline, workbook, tmp_path, monkeypatch, capsys, value):
    (tmp_path / "input.xlsx").touch()
    (tmp_path / "template.json").write_text((ROOT / "templates/answer-classification.json").read_text())
    config = "INPUT_PATH=input.xlsx\nOUTPUT_DIR=output\nJEV_TEMPLATE_PATH=template.json\n"
    if value is not None:
        config += 'JEV_MODEL="' + value + '"\n'
    (tmp_path / ".env").write_text(config)
    output = tmp_path / "output"; output.mkdir(); (output / "keep.txt").write_text("old")
    monkeypatch.setattr(pipeline, "HERE", tmp_path)
    with pytest.raises(SystemExit) as exc:
        pipeline.main([])
    assert exc.value.code == 1
    assert "JEV_MODEL" in capsys.readouterr().err
    assert (output / "keep.txt").read_text() == "old"


def test_curl_sends_manifest_cases_and_stops_after_failure(pipeline, builder, tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = processed(tmp_path / 'processed.jsonl', [
        {'id': name, 'state': '材料'} for name in ['trace1', 'trace2', 'trace3']])
    builder.build(source, ROOT / 'templates/answer-classification.json', tmp_path / 'requests')
    calls = []
    success = {'model': 'jev-model', 'answers': {
        'classification': {'type': 'choice', 'choice': 'T:回答正确', 'confidence': 0.43},
        'needs_review': {'type': 'noul', 'noul': 0.8}},
        'usage': {'input_tokens': 10, 'output_tokens': 4}}

    def fake_curl(args, **kwargs):
        calls.append(args)
        assert 'secret-key' not in ' '.join(args)
        assert 'Authorization: Bearer secret-key' in kwargs['input']
        assert 'https://example.test/v1/decisions' in kwargs['input']
        assert '--location' not in args and '--retry' not in args
        request = Path(args[args.index('--data-binary') + 1][1:])
        assert request.name == f'{len(calls):06d}.json'
        assert json.loads(request.read_text())['state'] == '材料'
        Path(args[args.index('--output') + 1]).write_text(json.dumps(success) if len(calls) == 1 else 'denied')
        return SimpleNamespace(returncode=0, stdout='200' if len(calls) == 1 else '403', stderr='')

    monkeypatch.setattr(pipeline.subprocess, 'run', fake_curl)
    with pytest.raises(ValueError, match='后续请求未发送'):
        pipeline.send_requests(tmp_path, 'https://example.test/v1/decisions', 'secret-key', 12, 'curl')
    results = json.loads((tmp_path / 'classification-results.json').read_text())
    assert len(calls) == len(results) == 2
    assert results[0]['id'] == 'trace1'
    assert results[0]['classification'] == 'T:回答正确' and results[0]['needs_review_score'] == 0.8
    assert results[0]['answers'] == success['answers']
    assert results[1]['success'] is False and results[1]['http_status'] == 403
    assert 'classification' not in results[1]
    assert (tmp_path / 'responses/000002.json').read_text() == 'denied'


@pytest.mark.parametrize('failure', ['timeout', 'invalid_json', 'invalid_choice', 'nan', 'transport'])
def test_sender_never_reports_failed_response_as_classification(pipeline, builder, tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    source = processed(tmp_path / 'processed.jsonl', [{'id': 'trace', 'state': 'text'}])
    builder.build(source, ROOT / 'templates/answer-classification.json', tmp_path / 'requests')

    def fake_curl(args, **kwargs):
        if failure == 'timeout':
            raise pipeline.subprocess.TimeoutExpired(args, 10)
        data = {'model': 'm', 'answers': {
            'classification': {'type': 'choice', 'choice': 'invalid'},
            'needs_review': {'type': 'noul', 'noul': 0.2}},
            'usage': {'input_tokens': 1, 'output_tokens': 1}}
        raw = {'invalid_json': 'not json', 'nan': '{"model":NaN}'}.get(failure, json.dumps(data))
        Path(args[args.index('--output') + 1]).write_text(raw)
        return SimpleNamespace(returncode=28 if failure == 'transport' else 0,
                               stdout='000' if failure == 'transport' else '200', stderr='secret-key')

    monkeypatch.setattr(pipeline.subprocess, 'run', fake_curl)
    with pytest.raises(ValueError, match='调用失败'):
        pipeline.send_requests(tmp_path, 'https://example.test/v1/decisions', 'secret-key', 10, 'curl')
    text = (tmp_path / 'classification-results.json').read_text()
    result = json.loads(text)[0]
    assert result['success'] is False and 'classification' not in result
    assert 'secret-key' not in text


@pytest.mark.parametrize('key,value', [('JEV_API_KEY', ''), ('JEV_API_URL', 'not-a-url'),
    ('JEV_TIMEOUT_SECONDS', 'nan'), ('JEV_TIMEOUT_SECONDS', '0')])
def test_invalid_connection_preserves_previous_output(pipeline, tmp_path, monkeypatch, key, value):
    (tmp_path / 'input.xlsx').touch()
    (tmp_path / 'template.json').touch()
    output = tmp_path / 'output'; output.mkdir(); (output / 'keep').write_text('previous')
    config = {'INPUT_PATH': 'input.xlsx', 'OUTPUT_DIR': 'output', 'JEV_TEMPLATE_PATH': 'template.json',
              'JEV_MODEL': 'm', 'JEV_API_KEY': 'key', 'JEV_API_URL': 'https://example.test/v1/decisions',
              'JEV_TIMEOUT_SECONDS': '120'}
    config[key] = value
    (tmp_path / '.env').write_text('\n'.join(f'{k}={v}' for k, v in config.items()))
    monkeypatch.setattr(pipeline, 'HERE', tmp_path)
    with pytest.raises(SystemExit) as exc:
        pipeline.main([])
    assert exc.value.code == 1
    assert (output / 'keep').read_text() == 'previous'


def test_classification_template_checked_before_replacing_output(pipeline, workbook, tmp_path):
    target = tmp_path / 'output'; target.mkdir(); (target / 'keep').write_text('old')
    template = tmp_path / 'template.json'
    template.write_text(json.dumps({'model': 'm', 'state': {}, 'questions': {'other': {'type': 'noul'}}}))
    with pytest.raises(ValueError, match='classification'):
        pipeline.run(tmp_path / 'input.xlsx', target, template)
    assert (target / 'keep').read_text() == 'old'


def test_successful_batch_exports_labels_and_review(pipeline, workbook, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from openpyxl import load_workbook
    target = tmp_path / 'output'
    pipeline.run(tmp_path / 'input.xlsx', target, ROOT / 'templates/answer-classification.json')
    manifest = json.loads((target / 'requests/manifest.json').read_text())
    def fake_curl(args, **kwargs):
        response = {'model': 'm', 'answers': {
            'classification': {'type': 'choice', 'choice': 'F4:知识缺失'},
            'needs_review': {'type': 'noul', 'noul': 0.8}},
            'usage': {'input_tokens': 1, 'output_tokens': 1}}
        Path(args[args.index('--output') + 1]).write_text(json.dumps(response))
        return SimpleNamespace(returncode=0, stdout='200', stderr='')
    monkeypatch.setattr(pipeline.subprocess, 'run', fake_curl)
    assert pipeline.send_requests(target, 'https://example.test/v1/decisions', 'test-key', 120, 'curl') == 2
    book = load_workbook(target / 'classification-results.xlsx')
    assert list(book.active.values) == [('traceid', '标签', '待复核分数')] + [(r['id'], 'F4:知识缺失', 0.8) for r in manifest['requests']]
    assert book.active.max_column == 3
    book.close()


@pytest.mark.parametrize('input_setting', ['', 'INPUT_PATH=\n', 'INPUT_PATH="  "\n'])
def test_pipeline_without_evaluations_uses_material_ids(pipeline, tmp_path, monkeypatch, input_setting):
    from types import SimpleNamespace
    import verifier_excel_to_jev_state as converter
    from openpyxl import load_workbook
    (tmp_path / 'materials.json').write_text(json.dumps([
        {'traceid': 'trace-z', 'question': '1+1？', 'answer': '2'},
        {'traceid': 'trace-a', 'question': '1+1？', 'answer': '3'}]))
    (tmp_path / 'map.json').write_text(json.dumps({'case_id_path': '/traceid', 'fields': {
        'question': {'path': '/question', 'description': '用户问题'},
        'answer': {'path': '/answer', 'description': '实际回答'}}}))
    (tmp_path / 'template.json').write_text((ROOT / 'templates/answer-classification.json').read_text())
    (tmp_path / '.env').write_text(input_setting + 'MATERIALS_PATH=materials.json\nMATERIALS_MAP_PATH=map.json\n'
        'OUTPUT_DIR=output\nJEV_TEMPLATE_PATH=template.json\nJEV_MODEL=test-model\n'
        'JEV_API_URL=https://example.test/v1/decisions\nJEV_API_KEY=test-key\nJEV_TIMEOUT_SECONDS=120\n'
        'EVAL_AXES_SCOPE=unused\nEVAL_TAGS_SCOPE=unused\n')
    monkeypatch.setattr(pipeline, 'HERE', tmp_path)
    monkeypatch.setattr(pipeline.shutil, 'which', lambda name: 'test-curl')
    def no_excel(*args, **kwargs):
        pytest.fail('No evaluation workbook should be opened')
    monkeypatch.setattr(converter, 'load_workbook', no_excel)
    real_run = pipeline.subprocess.run
    def fake_curl(args, **kwargs):
        if args[0] != 'test-curl':
            return real_run(args, **kwargs)
        body = json.loads(Path(args[args.index('--data-binary') + 1][1:]).read_text())
        assert 'evaluations' not in body['state']
        assert set(body['state']['materials']) == {'question', 'answer'}
        label = 'T:回答正确' if body['state']['materials']['answer']['value'] == '2' else 'F3:回答内容错误'
        response = {'model': 'test-model', 'answers': {
            'classification': {'type': 'choice', 'choice': label},
            'needs_review': {'type': 'noul', 'noul': 0.2}},
            'usage': {'input_tokens': 1, 'output_tokens': 1}}
        Path(args[args.index('--output') + 1]).write_text(json.dumps(response))
        return SimpleNamespace(returncode=0, stdout='200', stderr='')
    monkeypatch.setattr(pipeline.subprocess, 'run', fake_curl)
    pipeline.main([])
    rows = [json.loads(line) for line in (tmp_path / 'output/processed.jsonl').read_text().splitlines()]
    assert [r['id'] for r in rows] == ['trace-z', 'trace-a']
    assert rows[0]['source']['file'] == str(tmp_path / 'materials.json')
    book = load_workbook(tmp_path / 'output/classification-results.xlsx')
    assert list(book.active.values) == [('traceid', '标签', '待复核分数'), ('trace-z', 'T:回答正确', 0.2), ('trace-a', 'F3:回答内容错误', 0.2)]
    book.close()


@pytest.mark.parametrize('input_setting', ['', 'INPUT_PATH=missing.xlsx\n'])
def test_missing_sources_or_configured_missing_excel_preserves_output(pipeline, tmp_path, monkeypatch, input_setting):
    (tmp_path / 'template.json').touch()
    (tmp_path / '.env').write_text(input_setting + 'OUTPUT_DIR=output\nJEV_TEMPLATE_PATH=template.json\n')
    target = tmp_path / 'output'; target.mkdir(); (target / 'keep').write_text('previous')
    monkeypatch.setattr(pipeline, 'HERE', tmp_path)
    with pytest.raises(SystemExit) as exc:
        pipeline.main([])
    assert exc.value.code == 1
    assert (target / 'keep').read_text() == 'previous'


@pytest.mark.parametrize('score', [0, 0.49, 0.5, 1])
def test_review_noul_preserves_original_score(pipeline, score):
    request = json.loads((ROOT / 'templates/answer-classification.json').read_text())
    response = {'model': 'm', 'answers': {
        'classification': {'type': 'choice', 'choice': 'T:回答正确'},
        'needs_review': {'type': 'noul', 'noul': score}},
        'usage': {'input_tokens': 1, 'output_tokens': 1}}
    result = pipeline.classification_result(response, request)
    assert 'needs_review' not in result
    assert result['needs_review_score'] == score
    assert result['classification'] == 'T:回答正确'


@pytest.mark.parametrize('score', [None, True, '0.9', -0.1, 1.1, float('nan'), float('inf')])
def test_invalid_review_score_rejected(pipeline, score):
    request = json.loads((ROOT / 'templates/answer-classification.json').read_text())
    response = {'model': 'm', 'answers': {
        'classification': {'type': 'choice', 'choice': 'T:回答正确'},
        'needs_review': {'type': 'noul', 'noul': score}},
        'usage': {'input_tokens': 1, 'output_tokens': 1}}
    with pytest.raises(ValueError, match='needs_review.noul'):
        pipeline.classification_result(response, request)
