"""spec/mock/protocol.md 阶段 3：Session 工具仓库 + 4.10 自动导出 + ReplayDriver 回放。

用 policy_search happy golden 的 live cassette 离线驱动一场 text 模式会话，
然后把导出的 transcript seed 经 ReplayDriver 重放（同一 cassette 再放一次）。
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest

from impl.core import session_store
from impl.core.session_store import SessionStore
from tests.support import cassette

GOLDEN = Path(__file__).parent / "golden" / "policy_search" / "happy"


@pytest.fixture
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(session_store, "sessions_dir", lambda project_id: tmp_path / project_id / "sessions")

    def write_json(path: Path, payload: Dict[str, Any]) -> None:
        # 注册的 artifact family 只认 impl/data/*/sessions；测试写到 tmp，绕过 family writer，
        # 但保留 family 形状校验 + 真实 writer 的 payload 归一化（防裸路径字段逃过离线测试）。
        from impl.core.active_artifacts import _session_export_payload
        from impl.core.portable_artifact import PortableArtifactWriter

        _session_export_payload(None, path, payload)  # type: ignore[arg-type]
        PortableArtifactWriter().validate(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(session_store, "_write_json", write_json)
    monkeypatch.setenv("VERIFIER_CASSETTE", "replay")
    monkeypatch.setenv("VERIFIER_CASSETTE_DIR", str(GOLDEN))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def _replay_cassette():
    cassette.uninstall()
    return cassette.install()


def test_cli_style_session_exports_multi_turn_trace_and_replayable_seed(isolated_store, tmp_path: Path) -> None:
    store = SessionStore()
    _replay_cassette()
    try:
        opened = store.open("policy_search", mode="text", run_id="r1", scenario="clarification_reply")
        session_id = opened["session_id"]
        assert opened["event"] == "session.opened"
        assert opened["supports_history_injection"] is True

        with pytest.raises(KeyError):
            store.send("not-opened", {"type": "text", "text": "x"})

        store.intent(session_id, user_intent="筛选保额不低于50万的保单", source="seeded")
        first = store.send(session_id, {"type": "text", "text": "保额的保单"})
        assert first["event"] == "live.response"
        assert first["turn_index"] == 1
        second = store.send(session_id, {"type": "text", "text": "50万以上"})
        assert second["event"] == "live.response"

        with pytest.raises(ValueError):
            store.send(session_id, {"type": "request", "payload": {"x": 1}})  # text 模式禁 request 级

        closed = store.close(session_id, "goal_satisfied")
        cassette.assert_exhausted()
    finally:
        cassette.uninstall()

    assert closed["event"] == "session.closed"
    assert closed["stop_reason"] == "goal_satisfied"
    assert closed["completion_status"] == "completed"
    assert closed["driver_health"]["counts_toward_live_quality"] is True
    assert closed["candidate_file"].endswith("mock_cases-r1.json")

    export = store.export_of("policy_search", session_id)
    trace = export["trace"]
    assert trace["execution_mode"] == "interactive_intent"
    assert trace["interaction_mode"] == "interactive_intent"
    assert len(trace["turn_records"]) == 2
    assert trace["turn_records"][0]["mock_message"] == "保额的保单"
    assert trace["turn_records"][1]["request"]["extra_input_params"]["args"]["contexts"][0]["content"] == "保额的保单"
    assert [item["role"] for item in trace["conversation_transcript"]] == ["user", "assistant", "user", "assistant"]
    assert trace["conversation_summary"]["stop_reason"] == "goal_satisfied"
    assert trace["intent_history"] == [
        {"turn_index": 0, "user_intent": "筛选保额不低于50万的保单", "user_context": {}, "source": "seeded"}
    ]
    assert trace["diverged_at_turn"] is None

    # 落盘 payload 不含裸路径（portable artifact 契约）；候选文件位置由响应给出。
    on_disk = json.loads((tmp_path / "policy_search" / "sessions" / f"{session_id}.json").read_text(encoding="utf-8"))
    assert "candidate_file" not in on_disk
    assert export["run_id"] == "r1"
    assert export["candidate_file"].endswith("mock_cases-r1.json")
    seed_case = export["seed_case"]
    assert seed_case["seed"]["level"] == "transcript"
    assert [turn["message"]["text"] for turn in seed_case["seed"]["turns"]] == ["保额的保单", "50万以上"]
    # v2 §4：seed case 写候选文件（同 id 覆盖），不进 case pool；用户审后手动拷入 mock_cases.json。
    candidate_path = tmp_path / "policy_search" / "mock_cases-r1.json"
    candidate_cases = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert [case["id"] for case in candidate_cases] == [session_id]
    assert candidate_cases[0]["seed"]["level"] == "transcript"

    # 5.2：seed 经 ReplayDriver 重放（同一 cassette 再放一次，live 未变 → 无分叉），trace 可判。
    from impl.core.interaction_protocol import normalize_case_interaction
    from impl.core.mock import mock_case_to_single_turn, parse_mock_case

    stored = parse_mock_case(candidate_cases[0], project_id="policy_search")
    runtime_case = mock_case_to_single_turn(stored)
    normalized = normalize_case_interaction("policy_search", runtime_case, 0)
    assert normalized.mode == "interactive_intent"

    from impl.core.trace import trace_from_live
    from impl.core.project_loader import load_adapter, load_project

    _replay_cassette()
    try:
        live = load_adapter(load_project("policy_search")).live()
        replayed = trace_from_live(live, normalized)
        cassette.assert_exhausted()
    finally:
        cassette.uninstall()
    assert replayed.execution_mode == "interactive_intent"
    assert len(replayed.turn_records) == 2
    assert replayed.stop_reason == "goal_satisfied"
    assert replayed.completion_status == "completed"
    assert replayed.diverged_at_turn is None
    assert replayed.intent_history[0]["user_intent"] == "筛选保额不低于50万的保单"
    assert replayed.session_id.startswith("replay-")
    assert replayed.turn_records[1]["request"]["extra_input_params"]["policySearchParseArgs"]["query"] == "50万以上"


def test_replay_marks_divergence_when_recorded_output_differs(isolated_store) -> None:
    from impl.core.interaction_protocol import normalize_case_interaction
    from impl.core.mock import mock_case_to_single_turn, parse_mock_case
    from impl.core.project_loader import load_adapter, load_project
    from impl.core.trace import trace_from_live

    case = {
        "id": "seed-div",
        "project_id": "policy_search",
        "scenario": "clarification_reply",
        "live_request": {},
        "intent": None,
        "output": None,
        "reference": None,
        "seed": {
            "level": "transcript",
            "mode": "replay",
            "stop_reason": "goal_satisfied",
            "turns": [
                {"turn_index": 1, "message": {"type": "text", "text": "保额的保单"}, "extracted_output": {"status": "SOMETHING_ELSE"}},
                {"turn_index": 2, "message": {"type": "text", "text": "50万以上"}, "extracted_output": {}},
            ],
            "intent_history": [],
        },
    }
    normalized = normalize_case_interaction("policy_search", mock_case_to_single_turn(parse_mock_case(case)), 0)
    _replay_cassette()
    try:
        replayed = trace_from_live(load_adapter(load_project("policy_search")).live(), normalized)
    finally:
        cassette.uninstall()
    assert replayed.diverged_at_turn == 1
    assert len(replayed.turn_records) == 2


def test_budget_reaper_closes_hung_harness(isolated_store) -> None:
    store = SessionStore()
    _replay_cassette()
    try:
        opened = store.open("policy_search", mode="text", budget={"turn_wait_timeout_ms": 1})
        session_id = opened["session_id"]
        store.send(session_id, {"type": "text", "text": "保额的保单"})
        import time

        time.sleep(0.01)
        assert store.reap() == [session_id]
    finally:
        cassette.uninstall()
    export = store.export_of("policy_search", session_id)
    assert export["stop_reason"] == "driver_timeout"
    assert export["completion_status"] == "incomplete"
    assert export["driver_health"]["counts_toward_live_quality"] is False
    with pytest.raises(ValueError):
        store.send(session_id, {"type": "text", "text": "50万以上"})
