"""process_loop：六轴过程评测（父 loop）+ 案卷整理（子 loop）。

真实 LlmClient.complete_step（agno + OpenAILike，流式）打到本地假 OpenAI；父子两层按 system prompt 关键字各走各的脚本。
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from tests.support.expectations import E, PROJECTION

import pytest

from impl.core import context_store, llm_client
from impl.core.config import get_llm_config
from impl.core.llm_client import LlmClient
from impl.core.schema import RunTrace
from impl.core.tool_loop import Abort, Allow, Call, Continue, Deny, Done, Failed, History, ToolLoop
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import PROCESS_AXES, axis_selections, merge_suspects
from impl.projects.llm_probe.process_loop import Analysis, Evaluation, run_case
from impl.projects.llm_probe.process_loop.analysis import SYSTEM as CHILD_SYSTEM
from impl.projects.llm_probe.process_loop.evaluation import SYSTEM as PARENT_SYSTEM
from impl.projects.llm_probe.process_loop.evaluation import AxisCase, axis_case, hooks
from tests.support.fake_openai import FakeOpenAI

SNAPSHOT = Path(__file__).resolve().parents[1] / "report/business-trace-agno-20260913/snapshots/snap-cash-value.json"
CHILD, PARENT = "案卷整理员", "过程评测员"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(context_store, "save_context", lambda record: "")
    monkeypatch.setattr(LlmClient, "_endpoint_probe", staticmethod(lambda _endpoint: True))
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)


def _client(fake: FakeOpenAI) -> LlmClient:
    config = replace(get_llm_config(), api_key="k", base_url=fake.base_url, model="fake-m",
                     fallbacks=(), stream=True, role_policies={})
    client = LlmClient(config=config)
    client._project_id, client._caller = "llm_probe", "process_loop"
    return client


def _dossier() -> dict:
    return build_dossier(SimpleNamespace(turn_records=[]), json.loads(SNAPSHOT.read_text()))


def _cases(dossier: dict) -> dict[str, AxisCase]:
    """子 loop 提交 suspects=[] 时父层会拿到的各轴材料（同一算法预先算好，用来写脚本）。"""
    probe = Analysis(dossier, client=None)
    suspects = merge_suspects(probe.flagged, [], probe.links, PROCESS_AXES)
    output = {"structure": {"suspects": suspects},
              "selections": axis_selections(probe.table["links"], suspects, sorted(probe.gap_ids), PROCESS_AXES)}
    return {axis_id: axis_case(axis_id, dossier, output, None, E, PROJECTION) for axis_id in PROCESS_AXES}


def _payload(case: AxisCase, refs: list[str] = (), drop: int = 0) -> dict:
    groups: dict[str, list[str]] = {}
    for ob_id, link_id in case.pending[drop:]:
        groups.setdefault(ob_id, []).append(link_id)
    return {"reason": f"{case.axis_id} 证据不足", "scope_note": "检查了 turn1 的全部环节",
            "results": [{"obligation_id": ob_id, "link_ids": links, "outcome": "insufficient_evidence",
                         "expectation_ids": [], "matched_link_id": "", "expectation_checks": [], "observed": "两端缺失", "source_refs": [],
                         "input_refs": list(refs), "output_refs": [], "missing": ["原始请求"]}
                        for ob_id, links in groups.items()]}


def _structure(refs: list[str]) -> dict:
    return {"route": [{"action": "读取运行", "purpose": "定位执行", "evidence_refs": refs,
                       "input_refs": [], "output_refs": []}],
            "coverage_note": "原始请求缺失", "suspects": []}


def _tool_results(request: dict) -> list[str]:
    return [str(m.get("content")) for m in request["messages"] if m["role"] == "tool"]


def test_prompts_route_to_exactly_one_role():
    assert CHILD in CHILD_SYSTEM and CHILD not in PARENT_SYSTEM
    assert PARENT in PARENT_SYSTEM and PARENT not in CHILD_SYSTEM


def test_full_run_gates_receipts_and_rejects_until_every_axis_accepted():
    dossier = _dossier()
    cases = _cases(dossier)
    first, second = [r["id"] for r in dossier["records"][:2]]
    intent, model = cases["intent_understanding"], cases["model_capability"]
    child = [
        [("submit_structure", _structure([first]))],          # 引用没读过的编号 → ReceiptGate 拒
        [("dossier_collect", {"ids": [first]})],
        [("submit_structure", _structure([first]))],          # 此前批次读过 → accepted
        "整理完成",
    ]
    others = [(case.tool, _payload(case)) for case in cases.values() if case.axis_id not in {intent.axis_id, model.axis_id}]
    parent = [
        [(intent.tool, _payload(intent))],                    # 整理之前提交 → 拒
        [("trace_analysis", {})],
        [(intent.tool, _payload(intent, refs=[second]))],     # 父层没读过 second → 拒
        [("dossier_collect", {"ids": [second]})],
        [(intent.tool, _payload(intent, refs=[second])), (model.tool, _payload(model, drop=1)), *others],
        [(model.tool, _payload(model))],                      # 漏了一对被拒，补全后接受
        "评测完成",
    ]
    with FakeOpenAI({CHILD: child, PARENT: parent}) as fake:
        report = Evaluation(dossier, _client(fake), expectations=E, projection=PROJECTION, trace_id="t-full").run()
        child_requests, parent_requests = fake.requests_for(CHILD), fake.requests_for(PARENT)

    assert report["status"] == "complete", report.get("reason")
    assert [axis["type_id"] for axis in report["axes"]] == list(PROCESS_AXES)
    assert all(axis["status"] == "succeeded" for axis in report["axes"])
    intent_axis = report["axes"][0]["output"]
    assert intent_axis["unverified_refs"] == []
    assert {r["link_id"] for r in intent_axis["results"]} == {link for _, link in intent.pending}
    analysis = report["trace_analysis"]
    assert analysis["verdict"] in {"complete", "partial"} and first in {r["id"] for r in analysis["structure"]["evidence_audit"]["reads"]}

    denied = [(c["tool"], c["denied"]) for c in report["calls"] if c["denied"]]
    assert denied[0][0] == intent.tool and "依赖 trace_analysis" in denied[0][1]
    assert denied[1][0] == intent.tool and second in denied[1][1] and "此前批次没有正文读取回执" in denied[1][1]
    rejected = [c["tool"] for c in report["calls"] if c["accepted"] is False]
    assert rejected == [model.tool]
    assert "遗漏" in next(c["rejected"] for c in report["calls"] if c["accepted"] is False)
    # 子 loop 第一次提交被拒的理由回到了子模型；父模型只看到整理结果，看不到子 loop 的会话
    assert any("此前批次没有正文读取回执" in text for text in _tool_results(child_requests[1]))
    briefing = json.loads(_tool_results(parent_requests[2])[-1])
    assert briefing["status"] == "accepted" and [a["axis"] for a in briefing["axes"]] == list(PROCESS_AXES)
    assert all("submit_structure" not in text for text in _tool_results(parent_requests[-1]))


def test_analysis_failure_fails_the_case_without_partial_result():
    dossier = _dossier()
    child = ["整理完成"] * 9                                   # 从不提交：8 轮预算耗尽
    parent = [[("trace_analysis", {})], "结束"]
    with FakeOpenAI({CHILD: child, PARENT: parent}) as fake:
        report = Evaluation(dossier, _client(fake), expectations=E, projection=PROJECTION, trace_id="t-fail").run()
    assert report["status"] == "failed"
    assert "案卷整理失败" in report["reason"] and "llm_calls 已达上限 8" in report["reason"]
    assert "axes" not in report and "trace_analysis" not in report


def _gate(cases, calls):
    """与 Evaluation 同一组次序 hook，按 ToolLoop 的合成规则判。"""
    completion, gate = hooks(lambda: cases, list(cases))
    pre = lambda history, call: ToolLoop._pre_tool(history, call, gate['pre_tool'])
    stop = lambda history: ToolLoop._stop(SimpleNamespace(completion_hook=completion, hooks=gate), history, 0)
    return pre, stop, History(calls=calls)


def test_process_hooks_order_once_and_done_list():
    decided = AxisCase("knowledge_data", {}, {}, {("ob", "knowledge_data:turn1"): {}}, [], {})
    open_ = AxisCase("intent_understanding", {}, {}, {}, [("ob", "intent_understanding:turn1")], {})
    cases = {"knowledge_data": decided, "intent_understanding": open_}

    pre, stop, history = _gate(cases, [])
    denied = pre(history, Call(0, "eval_intent_understanding", {}, 0))
    assert isinstance(denied, Deny) and "依赖 trace_analysis" in denied.reason
    assert isinstance(stop(history), Continue) and "trace_analysis" in stop(history).reason

    ok = Call(0, "trace_analysis", {}, 0, result={"status": "accepted", "accepted": True, "axes": []})
    pre, stop, history = _gate(cases, [ok])
    assert isinstance(pre(history, Call(1, "trace_analysis", {}, 1)), Deny)
    assert isinstance(pre(history, Call(1, "eval_intent_understanding", {}, 1)), Allow)
    # 程序已判完的轴不在必做清单里（它的提交由 eval_* 自己打回，见 test_full_run）
    assert stop(history).reason.count("eval_") == 1 and "eval_intent_understanding" in stop(history).reason
    history.calls.append(Call(1, "eval_intent_understanding", {}, 1, result={"accepted": True}))
    assert isinstance(stop(history), Done)
    assert isinstance(pre(history, Call(2, "eval_intent_understanding", {}, 2)), Deny)

    failed = Call(0, "trace_analysis", {}, 0,
                  result={"status": "failed", "loop": "trace_analysis", "reason": "budget", "accepted": False})
    pre, stop, history = _gate(cases, [failed])
    assert isinstance(pre(history, Call(1, "dossier_collect", {}, 1)), Abort)
    assert isinstance(stop(history), Failed) and "案卷整理失败：budget" in stop(history).reason


def test_case_without_process_records_fails_before_any_model_call():
    trace = RunTrace(trace_id="t-empty", project_id="llm_probe", case_id="x",
                     project_fields={"business_trace": {"provider": "agno", "status": "failed"}})
    report = run_case(None, trace, client=object())
    assert report["status"] == "failed" and "没有可整理的过程记录" in report["reason"]


def test_axis_entry_uses_same_session_submission_repair_over_real_sdk(monkeypatch):
    from impl.projects.llm_probe.eval_axes.adapters import trace_analysis
    from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
    dossier = _dossier()
    first, second = [r['id'] for r in dossier['records'][:2]]
    script = [[('dossier_collect', {'ids': [first]})],
              [('submit_structure', _structure([first, second]))],
              [('submit_structure', _structure([first]))], '完成']
    with FakeOpenAI({CHILD: script}) as fake:
        monkeypatch.setattr(trace_analysis, 'axis_llm', lambda *a, **kw: _client(fake))
        # _client is a real LlmClient; usage is normally supplied by AxisLlm.
        monkeypatch.setattr(LlmClient, 'usage', lambda self: {}, raising=False)
        out = trace_analysis.run(
            {'trace': RunTrace(trace_id='t-entry', project_id='llm_probe', case_id='c'),
             'business_trace': json.loads(SNAPSHOT.read_text())},
            ScenarioAxis('trace_analysis', True, '整理'),
            SimpleNamespace(spec=None, trace_id='t-entry', enabled_axes=PROCESS_AXES,
                            ensure_time_left=lambda _: None, expectation_projection=PROJECTION))
        requests = fake.requests_for(CHILD)
    assert not out.failed
    assert len(requests) == out.usage['llm_calls'] == 3
    assert out.output['structure']['route'][0]['evidence_refs'] == [first]
    assert second in _tool_results(requests[2])[-1]
    assert first in _tool_results(requests[2])[0]
    assert [s['accepted'] for s in out.output['structure']['evidence_audit']['submissions']] == [False, True]
