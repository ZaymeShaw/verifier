import json

import pytest

from impl.core.resources import META_PREFIX, Address, Place, ResourceTable, TYPES, cite

BODY = {"name": "backend.policy.search", "kind": "tool_calls",
        "fields": {"input": {"status": "available", "value": {"query": "伏云平"}},
                   "output": {"status": "available", "value": {"polno": "P260922000005855", "holder": "伏云平",
                                                               "status": "交费有效"}}}}
ADDR = "trace://turn1/records/observations/15"
OUTPUT = ADDR + "/fields/output"
SOURCE = {"record": "turn1/records/observations/15", "fields": {"output": "turn1/records/observations/15/output"}}
IN, OUT = Place("field", "input"), Place("field", "output")


@pytest.fixture
def table():
    t = ResourceTable()
    t.mount(ADDR, "record_set", BODY, name="turn1/records/observations/15", title="backend.policy.search",
            meta={META_PREFIX + "source": SOURCE})
    return t


def run(table, quote, *, scope=None, uri=ADDR):
    return cite(table, uri, quote, scope=scope)


def test_address_parse_and_parent():
    a = Address.parse(ADDR)
    assert (a.scheme, a.path, str(a)) == ("trace", "turn1/records/observations/15", ADDR)
    assert str(a.parent()) == "trace://turn1/records/observations"
    for bad in ["turn1/records/observations/15", ADDR + "#/fields/output"]:
        with pytest.raises(ValueError):
            Address.parse(bad)


def test_mount_builds_mcp_descriptor(table):
    d = table.get(ADDR).descriptor
    text = TYPES["record_set"].text(BODY)
    assert (str(d.uri), d.name, d.title, d.mimeType, d.size) == (
        ADDR, "turn1/records/observations/15", "backend.policy.search", "application/json", len(text.encode()))
    assert d.meta == {META_PREFIX + "source": SOURCE, META_PREFIX + "type": "record_set"}
    assert table.list() == [d]


def test_mount_rejections(table):
    for args in [(ADDR, "record_set", {}), ("trace://x", "nope", {}),
                 (OUTPUT, "record_set", {}),                                   # 与已挂记录的字段模板地址相同
                 ("trace://a b", "record_set", {})]:                           # 不合 RFC 3986
        with pytest.raises(ValueError):
            table.mount(*args, name="x")


def test_templates_declared_by_type(table):
    [t] = table.templates()
    assert (t.uriTemplate, t.mimeType) == ("trace://{+record}/fields/{field}", "application/json")


def test_read_direct_and_template_like_mcp(table):
    [whole] = table.read(ADDR).contents
    assert (str(whole.uri), whole.mimeType, whole.text) == (ADDR, "application/json", TYPES["record_set"].text(BODY))
    [field] = table.read(OUTPUT).contents
    assert str(field.uri) == OUTPUT and field.text == json.dumps(BODY["fields"]["output"], ensure_ascii=False, sort_keys=True)
    assert field.text in whole.text                                          # 字段的文本就是整条记录里那一段
    for missing in ["trace://turn9", "trace://turn1/records", ADDR + "/fields/nope", ADDR + "/other"]:
        with pytest.raises(LookupError):
            table.read(missing)


def test_record_level_quote_in_both_fields_passes_and_reports_both_places(table):
    r = run(table, "伏云平")
    assert r.ok and r.block == ADDR and r.places == (IN, OUT)
    assert {x.node for x in r.regions} == {"/fields/input/value/query", "/fields/output/value/holder"}


def test_field_level_quote_lands_on_that_field_only(table):
    r = run(table, "伏云平", uri=OUTPUT)
    assert r.ok and r.places == (OUT,) and [x.node for x in r.regions] == ["/fields/output/value/holder"]
    assert run(table, "伏云平", uri=ADDR + "/fields/input").places == (IN,)


def test_region_maps_to_canonical_text(table):
    r = run(table, '"polno": "P260922000005855"', uri=OUTPUT)
    [x] = r.regions
    assert x.node == "/fields/output/value/polno"
    # 引号不参与比对，命中区间从第一个参与比对的字符到最后一个（两头的引号不算在内）
    assert TYPES["record_set"].extract(table.get(ADDR), x.start, x.end) == 'polno": "P260922000005855'


def test_record_attribute_is_citable(table):
    r = run(table, "backend.policy.search")
    assert r.ok and r.places == (Place("attribute"),)


def test_repeats_inside_one_resource_all_pass():
    t = ResourceTable()
    body = {**BODY, "fields": {**BODY["fields"], "output": {"status": "available", "value": {"a": "重复值", "b": "重复值"}}}}
    t.mount(ADDR, "record_set", body, name="r")
    r = run(t, "重复值", uri=OUTPUT)
    assert r.ok and len(r.regions) == 2 and r.places == (OUT,)


def test_rejections_in_order(table):
    assert run(table, "x", uri="turn1/records/observations/15").reason == "no_address"   # 只收完整地址
    assert run(table, "x", uri="trace://turn1/records/observations/99").reason == "no_address"
    assert run(table, "x", uri=ADDR + "/fields/nope").reason == "no_address"
    assert run(table, "交费有效", scope=set()).reason == "out_of_scope"
    assert run(table, "交费有效", scope={ADDR}).ok
    miss = run(table, "P260922000005855 已失效")
    assert miss.reason == "not_found" and "P260922000005855" in miss.hint
    other = run(table, "交费有效", uri=ADDR + "/fields/input")                       # 原文在别的字段
    assert other.reason == "not_found" and "/fields/output" in other.hint


def test_not_trace_data_works_the_same():
    """资源层不认识 trace：另一种前缀、另一种来源的记录集照样挂、读、核。"""
    t = ResourceTable()
    t.mount("kb://products/huixiang-2024", "record_set",
            {"title": "惠享版条款", "fields": {"waiting_period": {"status": "available", "value": "等待期 90 天"}}},
            name="huixiang-2024")
    assert [x.uriTemplate for x in t.templates()] == ["kb://{+record}/fields/{field}"]
    r = cite(t, "kb://products/huixiang-2024/fields/waiting_period", "等待期90天")      # 宽容规则：去空白
    assert r.ok and r.places == (Place("field", "waiting_period"),)
    assert cite(t, "kb://products/huixiang-2024", "惠享版条款").places == (Place("attribute"),)


def test_address_is_identity_not_hierarchy():
    """MCP 的地址只要求唯一：上一级路径本身也可以是一个资源，两者互不包含；name 唯一。"""
    table = ResourceTable()
    table.mount("trace://turn1", "record_set", {"fields": {"x": {"value": "请求"}}}, name="turn1")
    table.mount(ADDR, "record_set", BODY, name="turn1/records/observations/14")
    assert table.by_name("turn1").uri == "trace://turn1" and table.by_name("nope") is None
    assert "伏云平" not in table.read("trace://turn1").contents[0].text
    with pytest.raises(ValueError):
        table.mount("trace://other", "record_set", BODY, name="turn1")
    later = ResourceTable()                                                   # 先挂了字段地址，再挂它所属的记录
    later.mount(ADDR + "/fields/output", "record_set", BODY, name="a")
    with pytest.raises(ValueError):
        later.mount(ADDR, "record_set", BODY, name="b")
