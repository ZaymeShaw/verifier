from types import SimpleNamespace

from impl.core.axis_loop.materials import Material, MaterialTable, MaterialUnavailable, Registry
from impl.core.resources import META_PREFIX
from impl.projects.llm_probe_loop.resources import case_trace

ROW = {"id": "turn1/records/observations/15", "ref": "turn1/records/observations/15", "turn": "turn1",
       "kind": "tool_calls", "name": "backend.policy.search", "observation_type": "TOOL", "outcome": "success",
       "fields": {"output": {"status": "available", "ref": "turn1/records/observations/15/output", "value": "保单 P1"},
                  "input": {"status": "missing"}}}
OTHER = {"id": "turn2/records/run", "turn": "turn2", "kind": "runs", "fields": {}}
DOSSIER = {"sources": [{"id": "turn1", "recorder": "Langfuse", "request_and_response": {"request": "查保单"}},
                       {"id": "turn2", "recorder": "Agno", "request_and_response": {"request": "再查"}}],
           "records": [ROW, OTHER], "contents": {}}


def test_every_record_and_turn_source_becomes_a_resource_with_provenance():
    items = {i["name"]: i for i in case_trace.resources(DOSSIER)}
    assert set(items) == {"turn1", "turn2", ROW["id"], OTHER["id"]}             # 各轮、各信息源都挂
    row = items[ROW["id"]]
    assert (row["uri"], row["type"], row["title"], row["description"]) == (
        "trace://turn1/records/observations/15", "record_set", "backend.policy.search", "tool_calls · TOOL · success")
    assert row["body"] == case_trace.record_body(DOSSIER, ROW)                   # 正文 = case.trace.records 那一条
    assert row["meta"] == {META_PREFIX + "source": {"record": ROW["ref"],
                                                    "fields": {"output": "turn1/records/observations/15/output"}}}
    assert items["turn1"]["uri"] == "trace://turn1"
    assert items["turn1"]["body"] == case_trace.source_record(DOSSIER, DOSSIER["sources"][0])


def _table(resources):
    return MaterialTable(Registry([Material("case.x", {}, "x", lambda case, _: DOSSIER, resources=resources)]),
                         SimpleNamespace())


def test_material_mounts_its_resources_once_when_loaded():
    table = _table(case_trace.resources)
    assert len(table.resources) == 0
    table.full("case.x"), table.full("case.x")
    assert len(table.resources) == 4 and table.resources.by_name("turn1").uri == "trace://turn1"


def test_mount_failure_is_material_unavailable():
    table = _table(lambda value: case_trace.resources(value) * 2)               # 同一地址挂两次
    try:
        table.full("case.x")
    except MaterialUnavailable as exc:
        assert "挂资源失败" in str(exc)
    else:
        raise AssertionError("应当取不到")


def test_visible_follows_explicit_resource_uris_and_field_templates():
    from impl.core.axis_loop.visible import Visible
    from impl.core.resources import ResourceTable

    row2 = {**ROW, "fields": {**ROW["fields"], "input": {"status": "available", "value": "入参 P1"}}}
    dossier = {**DOSSIER, "records": [row2, OTHER]}
    table = ResourceTable()
    for item in case_trace.resources(dossier):
        table.mount(item["uri"], item["type"], item["body"], name=item["name"], meta=item.get("meta"))

    # 直接资源 URI：整块与其全部字段可见，未列出的资源 out_of_scope
    full_seen = Visible(table, [f"trace://{ROW['id']}"])
    assert full_seen.uris == {"trace://turn1/records/observations/15"}
    assert full_seen.address(ROW["id"]) == "trace://turn1/records/observations/15"
    assert full_seen.address(ROW["id"] + "/fields/output") == "trace://turn1/records/observations/15/fields/output"
    assert full_seen.address("trace://turn1/records/observations/15/fields/output") == "trace://turn1/records/observations/15/fields/output"
    assert full_seen.cite(ROW["id"] + "/fields/output", "保单 P1").ok
    assert full_seen.cite("turn1", "查保单").reason == "out_of_scope"
    assert full_seen.address("turn9/records/x") is None

    # 模板资源 URI（本应阶段）：仅开放的字段可引，同条记录的未开放字段报 out_of_scope
    field_only = Visible(table, [f"trace://{ROW['id']}/fields/input"])
    assert field_only.cite(ROW["id"] + "/fields/input", "入参 P1").ok
    assert field_only.cite(ROW["id"] + "/fields/output", "保单 P1").reason == "out_of_scope"
    assert field_only.cite(ROW["id"], "保单 P1").reason == "out_of_scope"

