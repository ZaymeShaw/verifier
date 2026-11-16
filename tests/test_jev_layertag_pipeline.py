"""File and protocol boundaries for business taxonomy tagging; no remote calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1] / "scripts/jev_layertag"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import questions_to_state
    import taxonomy_to_template
    spec = importlib.util.spec_from_file_location("layertag_pipeline", ROOT / "pipeline.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    return pipeline, questions_to_state, taxonomy_to_template


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def mapping(tmp_path):
    return save(tmp_path / "map.json", {
        "case_id_path": "/trace/id", "fields": {
            "user_input": {"path": "/request/question", "description": "用户问题"},
            "history": {"path": "/request/history", "description": "相关历史", "required": False},
        }})


def test_selected_question_only_no_answer_eval_or_id_in_state(modules, tmp_path):
    _, converter, _ = modules
    source = save(tmp_path / "questions.json", [{
        "trace": {"id": "trace-one"}, "request": {"question": "那它的佣金呢？", "history": []},
        "answer": "错误回答", "evaluations": {"classification": "F3"}, "api_key": "not-selected",
    }, {"trace": {"id": "trace-two"}, "request": {"question": "如何报案？"}}])
    target = tmp_path / "processed.jsonl"
    assert converter.convert(source, mapping(tmp_path), target) == 2
    first, second = [json.loads(x) for x in target.read_text().splitlines()]
    assert first["id"] == "trace-one"
    assert set(first["state"]) == {"user_input", "history"}
    assert first["state"]["history"]["present"] is True
    assert second["state"]["history"] == {"description": "相关历史", "present": False, "value": None}
    assert "not-selected" not in target.read_text()
    assert "错误回答" not in target.read_text()


@pytest.mark.parametrize("bad", [
    {"trace": {"id": "same"}, "request": {"question": "重复"}},
    {"trace": {"id": "new"}, "request": {"question": " "}},
    {"trace": {"id": "new"}, "request": {}},
    {"trace": {"id": " new "}, "request": {"question": "问题"}},
    {"trace": {"id": "new"}, "request": {"question": "问题", "history": 42}},
])
def test_bad_late_record_does_not_publish(modules, tmp_path, bad):
    _, converter, _ = modules
    source = save(tmp_path / "questions.json", [
        {"trace": {"id": "same"}, "request": {"question": "问题"}}, bad])
    target = tmp_path / "processed.jsonl"
    with pytest.raises(ValueError):
        converter.convert(source, mapping(tmp_path), target)
    assert not target.exists()


def test_mapping_rejects_answer_field_and_duplicate_json(modules, tmp_path):
    _, converter, _ = modules
    path = mapping(tmp_path)
    value = json.loads(path.read_text())
    value["fields"]["answer"] = {"path": "/answer", "description": "答案"}
    save(path, value)
    with pytest.raises(ValueError, match="不得注入"):
        converter.convert(save(tmp_path / "q.json", {}), path, tmp_path / "out.jsonl")
    with pytest.raises(ValueError, match="重复 JSON"):
        converter.parse_json('{"id":"a","id":"b"}')
    with pytest.raises(ValueError, match="非 JSON"):
        converter.parse_json('{"n": NaN}')


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_tabular_inputs_and_formula_rejection(modules, tmp_path, suffix):
    _, converter, _ = modules
    source = tmp_path / f"q.{suffix}"
    if suffix == "csv":
        source.write_text('编号,问题\na,"如何续费？"\n', encoding="utf-8-sig")
    else:
        book = Workbook()
        book.active.append(["编号", "问题"])
        book.active.append(["a", "如何续费？"])
        book.save(source)
    mapfile = save(tmp_path / "map.json", {"case_id_path": "/编号", "fields": {
        "user_input": {"path": "/问题", "description": "问题"}}})
    assert converter.convert(source, mapfile, tmp_path / "out.jsonl") == 1
    if suffix == "xlsx":
        book.active["B2"] = '=CONCAT("问题")'
        book.save(source)
        with pytest.raises(ValueError, match="公式"):
            converter.convert(source, mapfile, tmp_path / "bad.jsonl")


def taxonomy_book(path):
    from openpyxl.styles import PatternFill
    book = Workbook()
    sheet = book.active
    sheet.title = "分类"
    sheet.append(["场景", "子场景", "一级领域", "二级领域", "三级领域", "明细", None, "复原说明"])
    sheet.append(["问答", "实战", "产品", "产品问答", "佣金", "佣金计算", None, "旁注不是规则"])
    sheet.append([None, None, None, None, None, "佣金查询"])
    for col in "ABCDE":
        sheet.merge_cells(f"{col}2:{col}3")
    sheet["F3"].fill = PatternFill("solid", fgColor="FFF2CC")
    book.save(path)
    return book


def test_taxonomy_uses_merges_groups_scope_and_preserves_review(modules, tmp_path):
    _, _, tax = modules
    source, target = tmp_path / "taxonomy.xlsx", tmp_path / "template.json"
    book = taxonomy_book(source)
    assert tax.compile_template(source, "分类", target, "model") == 1
    template = json.loads(target.read_text())
    labels = tax.catalog_from_template(template)
    key, label = next(iter(labels.items()))
    assert label["scope"] == ["佣金计算", "佣金查询"]
    assert label["review_required"] is True
    assert label["source_rows"] == [2, 3]
    assert "旁注不是规则" not in target.read_text()
    book.active["F2"] = "修改范围描述"
    book.save(source)
    second = tmp_path / "second.json"
    tax.compile_template(source, "分类", second, "model")
    assert next(iter(tax.catalog_from_template(json.loads(second.read_text())))) == key
    book.active.unmerge_cells("E2:E3")
    book.save(source)
    with pytest.raises(ValueError, match="不完整"):
        tax.compile_template(source, "分类", tmp_path / "bad.json", "model")


def test_shipped_taxonomy_covers_all_source_rows_once(modules):
    _, _, tax = modules
    template = json.loads((ROOT / "templates/layer-tagging.json").read_text())
    labels = tax.catalog_from_template(template)
    assert len(labels) == 48
    assert sorted(row for label in labels.values() for row in label["source_rows"]) == list(range(2, 63))
    assert len({tuple(label["path"][level] for level in tax.LEVELS) for label in labels.values()}) == len(labels)


def prepare_sample(pipeline, tmp_path):
    output = tmp_path / "output"
    assert pipeline.prepare(ROOT / "examples/questions.jsonl", ROOT / "examples/questions-map.json",
                            ROOT / "templates/layer-tagging.json", output, model="test-selected-model") == 4
    request = json.loads((output / "requests/000001.json").read_text())
    return output, request


def response_for(request, choice):
    return {"model": "actual-model", "answers": {"classification": {
        "type": "choice", "choice": choice, "confidence": 0.97,
        "probabilities": {key: float(key == choice) for key in request["questions"]["classification"]["criteria"]},
    }}, "usage": {"input_tokens": 123, "output_tokens": 2}}


def test_prepare_full_batch_protocol_and_failure_preserves_previous(modules, tmp_path):
    pipeline, _, _ = modules
    output, request = prepare_sample(pipeline, tmp_path)
    assert set(request) == {"model", "state", "questions"}
    assert request["model"] == "test-selected-model"
    assert set(request["state"]) == {"user_input", "history"}
    marker = output / "keep.txt"
    marker.write_text("old")
    bad = save(tmp_path / "bad.json", [{"id": "x", "question": ""}])
    with pytest.raises(ValueError):
        pipeline.prepare(bad, ROOT / "examples/questions-map.json", ROOT / "templates/layer-tagging.json",
                         output, model="test")
    assert marker.read_text() == "old"
    badtemplate = json.loads((ROOT / "templates/layer-tagging.json").read_text())
    badtemplate["decode"] = {}
    with pytest.raises(ValueError, match="组装失败"):
        pipeline.prepare(ROOT / "examples/questions.jsonl", ROOT / "examples/questions-map.json",
                         save(tmp_path / "invalid-template.json", badtemplate), output, model="test")
    assert marker.read_text() == "old"


@pytest.mark.parametrize("special", ["__review__", "__out_of_scope__", "__multi_intent__"])
def test_special_states_never_become_business_labels(modules, special):
    pipeline, _, _ = modules
    request = json.loads((ROOT / "templates/layer-tagging.json").read_text())
    result = pipeline.classification_result(response_for(request, special), request)
    assert result["classification_status"] == special.strip("_")
    assert result["label_id"] is None and result["candidate_label_id"] is None and result["path"] is None


def test_paths_come_from_catalog_and_unverified_definitions_stay_review(modules):
    pipeline, _, tax = modules
    request = json.loads((ROOT / "templates/layer-tagging.json").read_text())
    labels = tax.catalog_from_template(request)
    for needs_review in [True, False]:
        key, label = next((k, v) for k, v in labels.items() if v["review_required"] is needs_review)
        result = pipeline.classification_result(response_for(request, key), request)
        assert result["candidate_path"] == label["path"]
        assert result["label_id"] == (None if needs_review else key)
        assert result["classification_status"] == ("review" if needs_review else "ready")


@pytest.mark.parametrize("mutation", ["unknown_choice", "missing_probs", "nan_confidence", "negative_usage"])
def test_http_200_with_bad_payload_is_not_success(modules, mutation):
    pipeline, _, _ = modules
    request = json.loads((ROOT / "templates/layer-tagging.json").read_text())
    data = response_for(request, "__review__")
    answer = data["answers"]["classification"]
    if mutation == "unknown_choice":
        answer["choice"] = "invented"
    elif mutation == "missing_probs":
        answer.pop("probabilities")
    elif mutation == "nan_confidence":
        answer["confidence"] = float("nan")
    else:
        data["usage"]["input_tokens"] = -1
    with pytest.raises(ValueError):
        pipeline.classification_result(data, request)


def test_send_persists_partial_results_stops_and_does_not_leak_key(modules, tmp_path, monkeypatch):
    pipeline, _, _ = modules
    output, request = prepare_sample(pipeline, tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert "secret-test-key" not in " ".join(command)
        assert "Authorization: Bearer secret-test-key" in kwargs["input"]
        path = Path(command[command.index("--output") + 1])
        if len(calls) == 1:
            save(path, response_for(request, "__review__"))
            return SimpleNamespace(returncode=0, stdout="200", stderr="")
        path.write_text('{"error":"unavailable"}')
        return SimpleNamespace(returncode=0, stdout="503", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="503"):
        pipeline.send_requests(output, "https://example.invalid", "secret-test-key", 300, "curl")
    results = json.loads((output / "classification-results.json").read_text())
    assert len(calls) == len(results) == 2
    assert results[0]["success"] is True and results[0]["label_id"] is None
    assert results[1]["success"] is False and "classification" not in results[1]
    assert "secret-test-key" not in (output / "classification-results.json").read_text()
    assert not (output / "responses/000003.json").exists()


def test_tampering_rejected_before_send(modules, tmp_path, monkeypatch):
    pipeline, _, _ = modules
    output, _ = prepare_sample(pipeline, tmp_path)
    (output / "requests/000004.json").write_text("{}")
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **kw: pytest.fail("must not send"))
    with pytest.raises(ValueError, match="哈希"):
        pipeline.send_requests(output, "https://example.invalid", "secret", 300, "curl")
    assert not (output / "responses").exists()


def test_env_is_local_and_prepare_only_never_sends(modules, tmp_path, monkeypatch):
    pipeline, _, _ = modules
    folder = tmp_path / "workflow"
    folder.mkdir()
    (folder / ".env").write_text(
        f"INPUT_PATH={ROOT / 'examples/questions.jsonl'}\n"
        f"INPUT_MAP_PATH={ROOT / 'examples/questions-map.json'}\n"
        f"JEV_TEMPLATE_PATH={ROOT / 'templates/layer-tagging.json'}\n"
        "OUTPUT_DIR=out\nJEV_MODEL=local-model\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "HERE", folder)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JEV_MODEL", "wrong-model")
    monkeypatch.setattr(pipeline, "send_requests", lambda *a: pytest.fail("must not send"))
    pipeline.main(["--prepare-only"])
    request = json.loads((folder / "out/requests/000001.json").read_text())
    assert request["model"] == "local-model"
    assert not (tmp_path / "out").exists()


def test_output_cannot_contain_source(modules, tmp_path):
    pipeline, _, _ = modules
    source = save(tmp_path / "q.json", {"id": "x", "question": "问题"})
    with pytest.raises(ValueError, match="不能包含"):
        pipeline.prepare(source, ROOT / "examples/questions-map.json", ROOT / "templates/layer-tagging.json",
                         tmp_path, model="model")
    assert source.exists()
