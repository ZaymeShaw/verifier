import json
from pathlib import Path

import pytest

from impl.core import pipeline
from impl.core.mock import mock_case_to_single_turn, parse_mock_case
from impl.core.schema import MockCase
from impl.core.schema import to_public_dict
from impl.core import case_pool
from impl.server.service import case_event, compact_batch_result
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
