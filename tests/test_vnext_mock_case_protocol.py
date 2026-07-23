import json
from pathlib import Path

import pytest

from impl.core import pipeline
from impl import cli
from impl.core.mock import mock_case_to_single_turn, parse_mock_case
from impl.core.schema import MockCase
from impl.core.schema import to_public_dict
from impl.core import case_pool
from impl.server.service import case_event, compact_batch_result
from impl.server.models import MockBuildIntentRequest, MockCasesRequest, MockDatasetsRequest
from impl.server import service
from impl.server import batch_jobs


ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"id", "project_id", "scenario", "intent", "live_request", "output", "reference"}


def _case():
    return {
        "id": "case-1",
        "project_id": "client_search",
        "scenario": "single_condition",
        "intent": {"user_intent": "找客户", "query": "有子女的客户", "user_context": {}},
        "live_request": {"user_text": "有子女的客户"},
        "output": None,
        "reference": None,
    }


def test_strict_transport_boundary_accepts_only_mock_case():
    parsed = parse_mock_case(_case(), project_id="client_search")
    assert isinstance(parsed, MockCase)
    assert mock_case_to_single_turn(parsed).input == {"user_text": "有子女的客户"}
    with pytest.raises(ValueError, match="MockCase 缺少字段"):
        parse_mock_case({"id": "legacy", "input": {"user_text": "x"}})
    with pytest.raises(ValueError, match="MockCase 包含未知字段"):
        parse_mock_case({**_case(), "status": "pending"})


def test_request_first_case_allows_intent_to_be_absent():
    request_first = {**_case(), "intent": None}
    parsed = parse_mock_case(request_first, project_id="client_search")

    assert parsed.intent is None
    assert mock_case_to_single_turn(parsed).input == {"user_text": "有子女的客户"}
    assert to_public_dict(parsed)["intent"] is None


def test_mock_intent_is_independent_from_live_request():
    parsed = parse_mock_case({
        **_case(),
        "intent": {
            "user_intent": "找客户",
            "query": "有子女的客户",
            "user_context": {},
            "system_understanding": "我知道这个产品可以按自然语言筛选客户",
        },
    })

    public = to_public_dict(parsed)
    assert "live_request" not in public["intent"]
    assert public["intent"]["system_understanding"] == "我知道这个产品可以按自然语言筛选客户"


def test_mock_build_api_accepts_requested_intent_as_a_separate_fact_contract():
    request = MockBuildIntentRequest(
        project="deerflow",
        scenario="clarification",
        requested_intent="开始下月规划，但目标值还没确定",
        intent_labels=["clarification"],
    )

    payload = request.as_dict()
    assert payload["requested_intent"] == "开始下月规划，但目标值还没确定"
    assert payload["intent_labels"] == ["clarification"]


def test_mock_build_service_forwards_requested_intent(monkeypatch):
    captured = {}

    def _build(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return {}

    monkeypatch.setattr(service.pipeline, "mock_build_intent", _build)
    service.mock_build_intent({
        "project": "deerflow",
        "scenario": "clarification",
        "requested_intent": "开始下月规划，但目标值还没确定",
    })

    assert captured["project_id"] == "deerflow"
    assert captured["requested_intent"] == "开始下月规划，但目标值还没确定"


def test_mock_pool_requests_bound_frontend_dataset_size():
    assert MockCasesRequest(project="deerflow").count == 1
    assert MockDatasetsRequest(project="deerflow").count == 1
    assert MockDatasetsRequest(project="deerflow", count=500).count == 500
    with pytest.raises(ValueError):
        MockCasesRequest(project="deerflow", count=501)


def test_mock_dataset_service_forwards_requested_count(monkeypatch):
    captured = {}

    def _datasets(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return []

    monkeypatch.setattr(service.pipeline, "persisted_mock_datasets", _datasets)
    service.mock_datasets({"project": "deerflow", "count": 500})

    assert captured == {"project_id": "deerflow", "count": 500}


def test_mock_datasets_load_persisted_fixtures_without_dynamic_generation(monkeypatch):
    fixtures = [_case(), {**_case(), "id": "case-2", "scenario": "clarification"}]
    monkeypatch.setattr(pipeline, "_fixture_mock_cases", lambda project_id: fixtures)
    monkeypatch.setattr(
        pipeline,
        "generate_mock_cases",
        lambda *args, **kwargs: pytest.fail("loading a persisted dataset must not call MockAgent"),
    )

    datasets = pipeline.persisted_mock_datasets("deerflow", count=500)

    assert [case["id"] for dataset in datasets for case in dataset["cases"]] == [
        "case-1",
        "case-2",
    ]


def test_save_mock_cases_accepts_canonical_live_request(tmp_path):
    target = tmp_path / "mock_cases.json"
    case = {
        **_case(),
        "intent": {
            "user_intent": "查找有子女的客户群体",
            "query": "帮我找一下家里有孩子的客户",
            "user_context": {"role": "客户经理"},
            "system_understanding": "知道可以用自然语言找客户",
            "scenario": "single_condition",
        },
    }

    result = pipeline.save_mock_cases(
        "client_search",
        [case],
        output_path=str(target),
    )

    assert result["save_count"] == 1
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved[0]["live_request"] == {"user_text": "有子女的客户"}
    assert saved[0]["intent"] == case["intent"]


def test_save_mock_cases_preserves_request_first_intent_none(tmp_path):
    target = tmp_path / "mock_cases.json"

    pipeline.save_mock_cases(
        "client_search",
        [{**_case(), "intent": None}],
        output_path=str(target),
    )

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved[0]["intent"] is None


def test_save_mock_cases_migrates_legacy_runtime_case(tmp_path):
    target = tmp_path / "mock_cases.json"

    pipeline.save_mock_cases(
        "client_search",
        [{
            "id": "legacy-case",
            "scenario": "single_condition",
            "user_intent": "找客户",
            "input": {"user_text": "有子女的客户"},
        }],
        output_path=str(target),
    )

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved[0]["id"] == "legacy-case"
    assert saved[0]["project_id"] == "client_search"
    assert saved[0]["live_request"] == {"user_text": "有子女的客户"}


@pytest.mark.parametrize(
    "case, error",
    [
        ({**_case(), "project_id": "deerflow"}, "与请求项目 client_search 不一致"),
        ({**_case(), "unexpected": True}, "MockCase 包含未知字段"),
        ({**_case(), "live_request": {}}, "input 不符合 REQUEST_SCHEMA"),
    ],
)
def test_save_mock_cases_rejects_invalid_canonical_cases(tmp_path, case, error):
    target = tmp_path / "mock_cases.json"

    with pytest.raises(ValueError, match=error):
        pipeline.save_mock_cases(
            "client_search",
            [case],
            output_path=str(target),
        )

    assert not target.exists()


def test_save_mock_cases_skip_invalid_writes_only_valid_canonical_cases(tmp_path):
    target = tmp_path / "mock_cases.json"

    result = pipeline.save_mock_cases(
        "client_search",
        [_case(), {**_case(), "id": "invalid", "live_request": {}}],
        output_path=str(target),
        skip_invalid=True,
    )

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert [case["id"] for case in saved] == ["case-1"]
    assert result["save_count"] == 1
    assert result["invalid_count"] == 1


def test_mock_cases_cli_saves_generated_canonical_case(monkeypatch, tmp_path):
    target = tmp_path / "mock_cases.json"
    emitted = []
    monkeypatch.setattr(pipeline, "mock_cases", lambda *_args, **_kwargs: [_case()])
    monkeypatch.setattr(cli, "emit", emitted.append)

    cli.main([
        "mock-cases",
        "--project", "client_search",
        "--count", "1",
        "--save", str(target),
    ])

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved[0]["live_request"] == {"user_text": "有子女的客户"}
    assert emitted[0]["save_count"] == 1


def test_mock_dataset_build_path_keeps_configured_source_and_scenario_count(monkeypatch):
    captured = {}

    def _cases(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return [_case()]

    monkeypatch.setattr(pipeline, "mock_cases", _cases)

    datasets = pipeline.mock_datasets(
        "client_search",
        count=3,
        cases_per_scenario=2,
    )

    assert captured == {
        "project_id": "client_search",
        "count": 3,
        "cases_per_scenario": 2,
    }
    assert datasets[0]["cases"][0]["id"] == "case-1"


def test_mock_dataset_service_normalizes_nested_cases_at_public_boundary(monkeypatch):
    calls = []
    monkeypatch.setattr(
        service.pipeline,
        "persisted_mock_datasets",
        lambda project_id, count: calls.append((project_id, count)) or [{
            "dataset_id": "client_search_single_condition",
            "name": "single condition",
            "dimension_type": "single_condition",
            "description": "fixture dataset",
            "cases": [_case()],
            "case_count": 99,
        }],
    )

    response = service.mock_datasets({"project": "client_search", "count": 1})
    public = to_public_dict(response)

    assert calls == [("client_search", 1)]
    assert public["datasets"][0]["case_count"] == 1
    assert set(public["datasets"][0]["cases"][0]) == FIELDS
    assert public["datasets"][0]["cases"][0]["output"] is None
    assert public["datasets"][0]["cases"][0]["reference"] is None


@pytest.mark.parametrize(
    "project_id",
    ["QA", "client_search", "marketting-planning-intent", "marketting-planning"],
)
def test_fixture_project_datasets_expose_complete_vnext_cases(project_id):
    public = to_public_dict(service.mock_datasets({"project": project_id, "count": 1}))

    assert public["datasets"]
    nested_cases = [
        case
        for dataset in public["datasets"]
        for case in dataset["cases"]
    ]
    assert nested_cases
    assert all(set(case) == FIELDS for case in nested_cases)


def test_mock_services_default_to_one_case(monkeypatch):
    captured = []
    monkeypatch.setattr(
        service.pipeline,
        "mock_cases",
        lambda project_id, count: captured.append(("cases", project_id, count)) or [],
    )
    monkeypatch.setattr(
        service.pipeline,
        "persisted_mock_datasets",
        lambda project_id, count: captured.append(("datasets", project_id, count)) or [],
    )

    service.mock_cases({"project": "deerflow"})
    service.mock_datasets({"project": "deerflow"})

    assert captured == [
        ("cases", "deerflow", 1),
        ("datasets", "deerflow", 1),
    ]


def test_summary_separates_one_dynamic_case_from_three_persisted_cases():
    html = (ROOT / "impl" / "frontend" / "summary.html").read_text(encoding="utf-8")

    assert "post('/api/mock_cases',{project:project(),count:1})" in html
    assert "post('/api/mock_datasets',{project:project(),count:3})" in html
    assert "post('/api/mock_datasets',{project:project(),count:500})" not in html
    assert "post('/api/mock_datasets',{project:project(),count:1})" not in html


def test_deerflow_frontend_dataset_limit_returns_first_three_business_cases():
    datasets = pipeline.persisted_mock_datasets("deerflow", count=3)

    assert [dataset["dimension_type"] for dataset in datasets] == ["open_world_user"]
    assert sum(dataset["case_count"] for dataset in datasets) == 3


def test_mock_cases_api_source_is_canonical_mock_case():
    cases = pipeline._fixture_mock_cases("client_search")
    assert cases
    assert all(set(case) == FIELDS for case in cases)
    assert all(case["project_id"] == "client_search" for case in cases)
    public = to_public_dict(parse_mock_case(cases[0]))
    assert "user_context" in public["intent"]
    if "extra_input_params" in cases[0]["live_request"]:
        assert "extra_input_params" in public["live_request"]


def test_batch_event_and_final_run_carry_same_request_identity():
    identity = {"job_id": "job", "request_index": 0, "request_key": "job:0", "request_case_id": "case-1"}
    run = {"case_id": "case-1", "trace": {"trace_id": "t", "project_id": "client_search", "input": {}, "normalized_request": {}}, "error": "boom"}
    event = case_event(0, run, identity)
    assert {key: event[key] for key in identity} == identity

    batch = {"project_id": "client_search", "total": 1, "runs": [run], "cluster": None, "check": None, "table": None, "fallbacks": []}
    final = compact_batch_result(batch, [identity])
    assert {key: final["runs"][0][key] for key in identity} == identity


def test_batch_start_validates_before_creating_job():
    before = set(batch_jobs.BATCH_JOBS)
    with pytest.raises(ValueError, match="MockCase 缺少字段"):
        batch_jobs.start_batch({"project": "client_search", "cases": [{"id": "legacy", "input": {}}]})
    assert set(batch_jobs.BATCH_JOBS) == before


def test_duplicate_case_ids_still_receive_distinct_request_keys(monkeypatch):
    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(batch_jobs.threading, "Thread", NoopThread)
    first = _case()
    second = {**_case(), "live_request": {"user_text": "另一条输入"}}
    started = batch_jobs.start_batch({"project": "client_search", "cases": [first, second]})
    assert [item["request_case_id"] for item in started["requests"]] == ["case-1", "case-1"]
    assert len({item["request_key"] for item in started["requests"]}) == 2
    batch_jobs.BATCH_JOBS.pop(started["job_id"], None)


def test_root_client_search_cases_are_vnext_mock_cases():
    found = 0

    def walk(value):
        nonlocal found
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if "live_request" in value and "id" in value:
                found += 1
                assert set(value) == FIELDS
            else:
                for item in value.values():
                    walk(item)

    for path in (ROOT / "data" / "client_search").glob("*.json"):
        walk(json.loads(path.read_text(encoding="utf-8")))
    assert found > 1000


def test_saved_case_pool_api_preserves_nullable_mock_case_fields():
    pools = case_pool.list_case_pools("client_search")
    assert pools
    loaded = to_public_dict(case_pool.load_case_pool("client_search", pools[0]["id"]))
    assert loaded["cases"]
    assert set(loaded["cases"][0]) == FIELDS
    assert "output" in loaded["cases"][0]
    assert "reference" in loaded["cases"][0]
