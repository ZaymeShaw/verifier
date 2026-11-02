"""Link enumeration uses only Agno structure and states relations, never verdicts."""
import json

from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES, build_links


def row(ident, kind, fields, **meta):
    return {"id": ident, "kind": kind, "turn": "turn1", "scope": "current", "run_id": "agent-run",
            "fields": {k: {"status": "available", "value": v} for k, v in fields.items()}, **meta}


def dossier():
    error = '{"execution":{"status":"ERROR","code":"X","retryable":false}}'
    return {
        "sources": [{"id": "turn1"}], "contents": {}, "gaps": [],
        "records": [
            row("run", "runs", {"input": "question"}),
            row("s0", "steps", {"output": "prepared"}, parent_ref="run", name="prepare"),
            row("s1", "steps", {"output": "routed"}, parent_ref="run", name="route"),
            row("s1/a", "steps", {"output": "agent out"}, parent_ref="s1", name="agent"),
            row("span-s1", "steps", {"input": "context: prepared"}, name="route.aexecute", representation="span"),
            row("t0", "tool_calls", {"arguments": {"b": 1, "a": [2, 1]}, "result": error,
                                     "metrics": {"start_time": 1, "end_time": 2}}, name="lookup"),
            row("t1", "tool_calls", {"arguments": {"a": [2, 1], "b": 1}, "result": error,
                                     "metrics": {"start_time": 3, "end_time": 4}}, name="lookup"),
            row("t2", "tool_calls", {"arguments": {"a": [1, 2], "b": 1}, "result": error,
                                     "metrics": {"start_time": 5, "end_time": 6}}, name="lookup"),
            row("t1-span", "tool_calls", {"arguments": {"a": [2, 1], "b": 1}}, name="lookup", persisted_ref="t1"),
            row("m-tool", "messages", {"content": error}, role="tool", tool_call_ref="t0"),
            row("m-out", "messages", {"content": "answer"}, role="assistant"),
            row("stored", "final_output", {"output": '{"answer":"x","trace_id":"T"}'}),
            row("delivered", "delivered_output", {"output": {"output_text": '{"answer": "x"}'}}),
            row("old", "tool_calls", {"arguments": {}}, name="lookup", scope="history"),
        ],
        "model_calls": [
            {"id": "call1", "turn": "turn1", "scope": "current", "output_message_ref": "m-out",
             "reconstructed_input": {"status": "verified", "message_refs": ["m-tool"]}},
            {"id": "call2", "turn": "turn1", "scope": "current", "exact_request": {"status": "available"},
             "reconstructed_input": {"status": "verified", "message_refs": ["m-tool"]}},
        ],
    }


def by_id(links):
    return {link["link_id"]: link for link in links["links"]}


def test_links_cover_each_type_with_both_ends_and_facts_only():
    links = by_id(build_links(dossier()))
    assert links["intent_understanding:turn1"]["input"] == [{"ref": "run", "field": "input"}]
    step = links["context_memory:step:s0→s1"]
    assert step["output"] == [{"ref": "span-s1", "field": "input"}]
    assert step["facts"] == {"next_input_recorded": True, "contains": True}
    assert links["planning_routing:branch:s1"]["facts"] == {"executed": ["agent"]}
    # Exact span request wins over reconstruction; reconstruction is labelled as such.
    assert links["model_capability:call2"]["input"] == [{"ref": "call2", "field": "exact_request"}]
    assert links["model_capability:call1"]["facts"] == {"input_source": "verified"}
    # A tool result reaching the model is recorded once, at its first model input.
    transfers = [k for k in links if k.startswith("context_memory:tool→model")]
    assert transfers == ["context_memory:tool→model:t0→call1"] and links[transfers[0]]["facts"] == {"contains": True}
    assert links["context_memory:deliver:turn1"]["facts"] == {"vs_stored": {"changed": [], "dropped": ["trace_id"], "added": []}}
    for link in links.values():
        assert not {"verdict", "status", "outcome"} & set(link["facts"])


def test_repeat_uses_canonical_arguments_and_skips_copies_and_history():
    links = by_id(build_links(dossier()))
    assert {k for k in links if k.startswith("tool_execution:")} == {"tool_execution:t0", "tool_execution:t1", "tool_execution:t2"}
    repeat = links["planning_routing:repeat:t1"]
    assert repeat["facts"] == {"tool": "lookup", "repeat_of": "t0", "started_after_prior_ended": True,
                               "same_result": True}
    # List order is meaning: a different order is a different call.
    assert "planning_routing:repeat:t2" not in links


def test_axis_filter_keeps_only_its_link_types():
    data = dossier()
    for axis_id, types in AXIS_LINK_TYPES.items():
        links = build_links(data, axis_id=axis_id)
        assert set(links["types"]) == set(types)
        assert {link["link_type"] for link in links["links"]} <= set(types)
    json.dumps(build_links(data), ensure_ascii=False)


def test_reconstructed_model_input_includes_its_agents_tool_definitions():
    data = dossier()
    data["records"] += [
        row("helper-run", "runs", {}, parent_ref="run", name="helper", run_id="helper-run"),
        row("def/helper", "definitions", {}, name="helper", definition_type="component"),
        row("def/helper/tools/0", "definitions", {}, name="lookup", definition_type="tool"),
        row("def/other/tools/0", "definitions", {}, name="lookup", definition_type="tool"),
    ]
    data["model_calls"][0]["reconstructed_input"]["run_id"] = "helper-run"
    links = by_id(build_links(data))
    # Agno sends the agent's tool schemas with every request; persisted messages alone miss them.
    assert links["model_capability:call1"]["input"] == [{"ref": "m-tool", "field": "content"},
                                         {"ref": "def/helper/tools/0", "field": "definition"}]
    assert links["model_capability:call2"]["input"] == [{"ref": "call2", "field": "exact_request"}]


def test_model_output_end_uses_span_output_when_message_content_not_saved():
    """持久化助手消息常不存正文；输出端不得指向空字段，改用 span 记录的输出。"""
    d = dossier()
    d["records"] = [r for r in d["records"] if r["id"] != "m-out"] + [
        {**row("m-out", "messages", {}, role="assistant"),
         "fields": {"content": {"status": "missing", "note": "本记录没有保存此字段"}}}]
    d["model_calls"][0]["output"] = {"status": "available", "value": "answer"}
    assert by_id(build_links(d))["model_capability:call1"]["output"] == [{"ref": "call1", "field": "output"}]
    d["model_calls"][0]["output"] = {"status": "missing"}
    assert by_id(build_links(d))["model_capability:call1"]["output"] == [{"ref": "m-out", "field": "content"}]


def test_step_ends_use_step_span_when_step_results_not_saved():
    """Agno 的 step_results 常不存步骤输出；端点改用同一步骤 span 记录的输出，同名 span 不唯一时不配。"""
    d = dossier()
    unsaved = {"output": {"status": "missing", "note": "本记录没有保存此字段"}}
    d["records"] = [{**r, "fields": unsaved} if r["id"] in {"s0", "s1"} else r for r in d["records"]] + [
        row("span-s0", "steps", {"output": "prepared"}, name="prepare.aexecute", representation="span")]
    d["records"][[r["id"] for r in d["records"]].index("span-s1")]["fields"]["output"] = {"status": "available", "value": "routed"}
    links = by_id(build_links(d))
    step = links["context_memory:step:s0→s1"]
    assert step["input"] == [{"ref": "span-s0", "field": "output"}] and step["facts"]["contains"] is True
    assert links["intent_understanding:turn1"]["output"][0] == {"ref": "span-s0", "field": "output"}
    assert {"ref": "span-s1", "field": "output"} in links["planning_routing:path:turn1"]["output"]
    assert links["planning_routing:branch:s1"]["output"] == [{"ref": "span-s1", "field": "output"}]
    assert links["context_memory:deliver:turn1"]["input"] == [{"ref": "span-s1", "field": "output"}]
    d["records"].append(row("span-s0b", "steps", {"output": "again"}, name="prepare.aexecute", representation="span"))
    assert by_id(build_links(d))["context_memory:step:s0→s1"]["input"] == [{"ref": "s0", "field": "output"}]


def test_agent_task_end_uses_agent_span_when_run_input_not_saved():
    d = dossier()
    d["records"] += [{**row("agent", "runs", {}, parent_ref="run", run_id="agent-run"),
                      "fields": {"input": {"status": "missing", "note": "本记录没有保存此字段"}}},
                     {**row("span-agent", "steps", {"input": "task"}, name="helper.arun", representation="span"),
                      "agent_run_id": "agent-run"}]
    d["records"][0]["run_id"] = "workflow-run"
    d["records"][[r["id"] for r in d["records"]].index("m-out")]["run_id"] = "agent-run"
    assert by_id(build_links(d))["context_memory:input:call1"]["input"] == [{"ref": "span-agent", "field": "input"}]



def test_intent_link_covers_the_expression_up_to_its_turn():
    """意图环节（spec/alg/process-axes.md §8）：第 N 轮 = 第 1..N 轮的用户原文 → 截至本轮的全部步骤产出、
    Agent 收到的任务与各次模型调用发出的工具调用，不只看本轮第一个步骤和第一次决策。"""
    def at(turn, ident, kind, fields, **meta):
        return {**row(f"{turn}/{ident}", kind, fields, **meta), "turn": turn}
    records, calls = [], []
    for turn in ("turn1", "turn2"):
        records += [at(turn, "run", "runs", {"input": f"{turn} question"}),
                    at(turn, "s0", "steps", {"output": "gate"}, parent_ref=f"{turn}/run", name="gate"),
                    at(turn, "s1", "steps", {"output": "agent"}, parent_ref=f"{turn}/run", name="agent"),
                    at(turn, "agent", "runs", {"input": "task"}, parent_ref=f"{turn}/s1", run_id=f"{turn}-agent"),
                    at(turn, "m1", "messages", {"tool_calls": ["lookup A"]}, role="assistant"),
                    at(turn, "m2", "messages", {"tool_calls": ["lookup B"]}, role="assistant")]
        calls += [{"id": f"{turn}/c{k}", "turn": turn, "scope": "current", "output_message_ref": f"{turn}/m{k}"} for k in (1, 2)]
    links = by_id(build_links({"sources": [{"id": "turn1"}, {"id": "turn2"}], "contents": {}, "gaps": [],
                               "records": records, "model_calls": calls}, axis_id="intent_understanding"))
    expressed = lambda turn: [(f"{turn}/s0", "output"), (f"{turn}/s1", "output"), (f"{turn}/agent", "input"),
                              (f"{turn}/m1", "tool_calls"), (f"{turn}/m2", "tool_calls")]
    ends = lambda link, side: [(e["ref"], e["field"]) for e in link[side]]
    assert ends(links["intent_understanding:turn1"], "input") == [("turn1/run", "input")]
    assert ends(links["intent_understanding:turn1"], "output") == expressed("turn1")
    assert ends(links["intent_understanding:turn2"], "input") == [("turn1/run", "input"), ("turn2/run", "input")]
    assert ends(links["intent_understanding:turn2"], "output") == expressed("turn1") + expressed("turn2")
