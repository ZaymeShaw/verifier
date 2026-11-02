"""Cross-representation linking: reconstructed model inputs, tool pairing, timeline and preview balance."""
from __future__ import annotations

import json

from impl.projects.llm_probe.business_trace import open_reader


def _msg(role, content, **extra):
    return {"role": role, "content": content, **extra}


def snapshot(*, assistant_tokens=((100, 10), (300, 20)), drop_second_llm=False):
    """Agno 3.x shape: the AGENT span has metadata.run_id; its LLM/TOOL spans are siblings under the step span."""
    (in1, out1), (in2, out2) = assistant_tokens
    messages = [
        _msg("system", "rules"),
        _msg("user", "question"),
        _msg("assistant", "", tool_calls=[{"id": "c1"}, {"id": "c2"}], metrics={"input_tokens": in1, "output_tokens": out1}),
        _msg("tool", "first-timeout", tool_call_id="c1"),
        _msg("tool", "second-timeout", tool_call_id="c2"),
        _msg("assistant", "final answer", metrics={"input_tokens": in2, "output_tokens": out2}),
    ]
    tools = [
        {"tool_call_id": "c1", "tool_name": "kb", "tool_args": {"q": "x"}, "result": "first-timeout",
         "metrics": {"start_time": 1000.0}},
        {"tool_call_id": "c2", "tool_name": "kb", "tool_args": {"q": "x"}, "result": "second-timeout",
         "metrics": {"start_time": 1015.0}},
    ]
    llm_spans = [
        {"id": "llm1", "type": "LLM", "name": "model", "start_time": "1970-01-01T00:16:35Z", "duration": 5000,
         "input": "__REDACTED__", "output": "__REDACTED__", "metadata": {"input_tokens": "100", "output_tokens": "10"}},
        {"id": "llm2", "type": "LLM", "name": "model", "start_time": "1970-01-01T00:17:00Z", "duration": 3000,
         "input": "__REDACTED__", "output": "__REDACTED__", "metadata": {"input_tokens": "300", "output_tokens": "20"}},
    ]
    if drop_second_llm:
        llm_spans = llm_spans[:1]
    return {
        "provider": "agno", "status": "succeeded", "association": {"run_id": "w1"},
        "records": {
            "run": {"run_id": "w1", "run_input": "question",
                    "step_results": [{"step_name": "gate", "content": json.dumps({"action": "DIRECT", "reason": "r"})}],
                    "step_executor_runs": [{"run_id": "a1", "parent_run_id": "w1", "messages": messages, "tools": tools,
                                            "session_state": {"budget": {"backend_rpc_calls": 1, "llm_calls": 0}}}]},
            "traces": [{"trace_id": "t1", "run_id": "w1", "tree": [
                {"id": "root", "type": "WORKFLOW", "name": "turn", "start_time": "1970-01-01T00:16:30Z", "spans": [
                    {"id": "gate", "type": "WORKFLOW", "name": "gate.step", "start_time": "1970-01-01T00:16:31Z", "output": "{}"},
                    {"id": "agent-step", "type": "WORKFLOW", "name": "agent.step", "start_time": "1970-01-01T00:16:34Z", "spans": [
                        {"id": "agent", "type": "AGENT", "name": "qa.arun", "start_time": "1970-01-01T00:16:34Z",
                         "metadata": {"run_id": "a1"}},
                        llm_spans[0],
                        {"id": "tool1", "type": "TOOL", "name": "kb", "start_time": "1970-01-01T00:16:40Z",
                         "metadata": {"tool_name": "kb", "parameters": '{"q": "x"}'}},
                        {"id": "tool2", "type": "TOOL", "name": "kb", "start_time": "1970-01-01T00:16:55Z",
                         "metadata": {"tool_name": "kb", "parameters": '{"q": "x"}'}},
                        *llm_spans[1:],
                    ]},
                ]},
            ]}],
        },
    }


def test_each_llm_span_gets_token_verified_reconstructed_input_without_claiming_exact_request():
    reader = open_reader(snapshot())
    calls = reader.list_records("model_calls", run_id="w1")["items"]
    assert [c["reconstructed_input"]["status"] for c in calls] == ["verified", "verified"]
    first, second = calls
    assert first["reconstructed_input"]["message_refs"] == [
        "/records/run/step_executor_runs/0/messages/0", "/records/run/step_executor_runs/0/messages/1"]
    assert len(second["reconstructed_input"]["message_refs"]) == 5
    assert second["reconstructed_input"]["token_check"] == {
        "result": "match", "message_input_tokens": 300, "span_input_tokens": 300,
        "message_output_tokens": 20, "span_output_tokens": 20}
    assert second["output_message_ref"] == "/records/run/step_executor_runs/0/messages/5"
    assert all(c["fields"]["exact_request"]["status"] == "unverified" for c in calls)
    assert all(c["fields"]["input"]["status"] == "redacted" for c in calls)
    assert all(c["agent_run_attribution"] == "single_agent_span_sibling" for c in calls)
    assistant = reader.list_records("messages", run_id="a1")["items"][5]
    assert assistant["model_call_ref"] == second["ref"] and assistant["call_ordinal"] == 1


def test_token_mismatch_and_count_mismatch_are_reported_not_hidden():
    calls = open_reader(snapshot(assistant_tokens=((100, 10), (999, 20))))\
        .list_records("model_calls")["items"]
    assert calls[0]["reconstructed_input"]["status"] == "verified"
    assert calls[1]["reconstructed_input"]["status"] == "mismatch"
    assert calls[1]["reconstructed_input"]["token_check"]["result"] == "mismatch"
    calls = open_reader(snapshot(drop_second_llm=True)).list_records("model_calls")["items"]
    assert len(calls) == 1 and calls[0]["reconstructed_input"]["status"] == "unresolved"
    assert "assistant_messages=2 llm_spans=1" in calls[0]["reconstructed_input"]["reason"]


def test_duplicate_same_argument_tool_calls_are_paired_by_start_time_with_method_recorded():
    reader = open_reader(snapshot())
    persisted = [t for t in reader.list_records("tool_calls", run_id="a1")["items"] if t["representation"] == "api"]
    spans = [t for t in reader.list_records("tool_calls", run_id="w1")["items"] if t["representation"] == "span"]
    assert [t["pairing"]["method"] for t in persisted] == ["name_arguments_and_nearest_start_time", "name_and_arguments"]
    assert persisted[0]["span_ref"] == spans[0]["ref"] and persisted[1]["span_ref"] == spans[1]["ref"]
    assert spans[0]["persisted_ref"] == persisted[0]["ref"] and spans[0]["tool_call_id"] == "c1"
    assert persisted[0]["tool_message_ref"] == "/records/run/step_executor_runs/0/messages/3"
    tool_message = reader.list_records("messages", run_id="a1")["items"][3]
    assert tool_message["tool_call_ref"] == persisted[0]["ref"]
    summary = reader.overview()["invocations"]
    assert summary["tool_calls"] == {"persisted_records": 2, "span_records": 2, "persisted_pairing": {"paired": 2},
                                     "span_pairing": {"paired": 2},
                                     "other_representation_records": {}}
    assert summary["model_calls"]["reconstructed_input"] == {"verified": 2}
    assert {s["name"] for s in summary["steps_without_model_or_tool_spans"]} == {"gate.step"}


def test_unpaired_span_and_persisted_record_are_marked_not_guessed():
    source = snapshot()
    agent_step = source["records"]["traces"][0]["tree"][0]["spans"][1]["spans"]
    agent_step[3]["metadata"]["parameters"] = '{"q": "different"}'
    agent_step[3]["start_time"] = "1970-01-01T00:20:00Z"  # far from any persisted start
    reader = open_reader(source)
    persisted = [t for t in reader.list_records("tool_calls", run_id="a1")["items"] if t["representation"] == "api"]
    spans = [t for t in reader.list_records("tool_calls", run_id="w1")["items"] if t["representation"] == "span"]
    assert persisted[0]["pairing"]["method"] == "name_and_arguments"
    assert persisted[1]["pairing"]["status"] == "unpaired"
    assert spans[1]["pairing"]["status"] == "unpaired" and "persisted_ref" not in spans[1]


def test_timeline_orders_calls_with_links_and_marks_refs_citable():
    reader = open_reader(snapshot())
    timeline = reader.timeline()
    kinds = [(n["kind"], n["name"]) for n in timeline["nodes"]]
    assert kinds == [("steps", "turn"), ("steps", "gate.step"), ("steps", "agent.step"), ("steps", "qa.arun"),
                     ("model_calls", "model"), ("tool_calls", "kb"), ("tool_calls", "kb"), ("model_calls", "model")]
    llm = timeline["nodes"][4]
    assert llm["reconstructed_input"]["status"] == "verified" and llm["token_check"] == "match"
    tool = timeline["nodes"][5]
    assert tool["pairing"]["status"] == "paired" and tool["persisted_ref"].endswith("/tools/0")
    assert timeline["nodes"][3]["has_model_or_tool_spans"] is True
    assert timeline["untimed_records"] == 1  # the api step_result without a timestamp
    only_agent = reader.timeline(run_id="a1")
    assert {n["kind"] for n in only_agent["nodes"]} == {"model_calls", "tool_calls", "steps"}
    assert all(n.get("agent_run_id") == "a1" or n["name"] == "qa.arun" for n in only_agent["nodes"])


def test_step_json_output_and_nested_state_keys_are_discoverable_without_new_facts():
    reader = open_reader(snapshot())
    gate = reader.list_records("steps", run_id="w1")["items"][0]
    assert gate["output_format"] == "json_object_text" and gate["output_keys"] == ["action", "reason"]
    state = reader.list_records("states", run_id="a1")["items"][0]
    assert state["fields"]["budget.llm_calls"]["status"] == "available"
    assert reader.read(state["fields"]["budget.backend_rpc_calls"]["ref"])["text"] == "1"




def test_created_at_at_tool_completion_does_not_override_actual_start():
    source = snapshot()
    tools = source['records']['run']['step_executor_runs'][0]['tools']
    # 第一条记录很晚才创建；如果拿 created_at 配对，会误选第二个 span。
    tools[0]['created_at'] = 1014
    tools[1]['created_at'] = 1016
    reader = open_reader(source)
    calls = reader.list_records('tool_calls')['items']
    api = [c for c in calls if c['representation'] == 'api']
    spans = [c for c in calls if c['representation'] == 'span']
    assert [c['span_ref'] for c in api] == [c['ref'] for c in spans]
    assert [c['pairing']['start_delta_ms'] for c in api] == [0.0, 0.0]
