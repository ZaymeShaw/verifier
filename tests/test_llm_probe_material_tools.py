"""llm_probe 资料工具箱（孵化）：格式处理器、outline/search/read、locator 核验、目录式展开。"""
from __future__ import annotations

import pytest

from impl.core.materials_store import expand_material_uris_with_catalog
from impl.projects.llm_probe.material_tools import (
    build_material_tools,
    outline,
    parse_locator,
    quote_in_text,
    read,
    search,
    verify_quote,
)

SAMPLE = ("llm_probe", "client-search-match-rule")
BIG = ("llm_probe", "field_definitions_args")
TOKEN = "{material://llm_probe/client-search-match-rule}"


# ---------------------------------------------------------------------------
# 格式处理器与 outline


def test_outline_yaml_lists_id_entries_with_line_locators() -> None:
    result = outline(*BIG)
    assert result["format"] == "yaml"
    labels = [item["label"] for item in result["entries"]]
    assert any(label == "intents/name_exact" for label in labels)
    entry = next(item for item in result["entries"] if item["label"] == "intents/name_exact")
    start, end = parse_locator(entry["locator"])
    body = read(*BIG, entry["locator"] if end - start < 120 else f"L{start}-L{start + 119}")
    assert "name_exact" in body["text"]


def test_outline_markdown_uses_headings() -> None:
    result = outline(*SAMPLE)
    assert result["format"] == "markdown"
    assert any("姓名匹配口径" in item["label"] for item in result["entries"])


def test_outline_unknown_format_degrades_honestly(monkeypatch) -> None:
    import impl.projects.llm_probe.material_tools as mt

    monkeypatch.setattr(mt, "read_content", lambda p, m: "第一行没有结构\n第二行也没有\n" * 150)
    result = mt.outline("llm_probe", "whatever")
    assert result["format"] == "text"
    assert "尚无结构化切片方案" in result["note"]
    assert result["entries"], "行块地图必须存在"


# ---------------------------------------------------------------------------
# 词法检索 + 精读 + locator


def test_search_returns_line_locators() -> None:
    result = search(*SAMPLE, "等值匹配")
    assert result["total_line_hits"] >= 1
    snippet = result["snippets"][0]
    assert "等值匹配" in snippet["text"]
    start, end = parse_locator(snippet["locator"])
    assert read(*SAMPLE, snippet["locator"])["text"] == snippet["text"]
    assert start >= 1 and end >= start


def test_search_rejects_empty_query() -> None:
    with pytest.raises(ValueError):
        search(*SAMPLE, "   ")


def test_read_validates_locator() -> None:
    with pytest.raises(ValueError):
        read(*SAMPLE, "L0-L3")
    with pytest.raises(ValueError):
        read(*SAMPLE, "L5-L3")
    with pytest.raises(ValueError):
        read(*SAMPLE, "L1-L500")
    with pytest.raises(ValueError):
        read(*SAMPLE, "10-20")
    with pytest.raises(ValueError):
        read(*SAMPLE, "L10000-L10001")


# ---------------------------------------------------------------------------
# 引用机械核验


def test_verify_quote_roundtrip() -> None:
    hit = search(*SAMPLE, "等值匹配")
    locator = hit["snippets"][0]["locator"]
    quote = "姓名全值等值匹配"
    assert verify_quote(*SAMPLE, locator, quote) is True
    assert verify_quote(*SAMPLE, locator, "资料里没有这句话") is False


def test_quote_in_text_ignores_whitespace() -> None:
    assert quote_in_text("等值 匹配", "……姓名全值等值匹配……")
    assert not quote_in_text("", "任何文本")


# ---------------------------------------------------------------------------
# 工具箱构建：范围守卫 + 回执


def test_build_material_tools_scope_guard_and_receipts() -> None:
    recorder: list = []
    tools = build_material_tools(
        [{"id": SAMPLE[1], "project_id": SAMPLE[0], "uri": f"material://{SAMPLE[0]}/{SAMPLE[1]}",
          "title": "样例", "description": "", "size_chars": 100, "sha256": "abc"}],
        recorder,
    )
    names = {tool.name for tool in tools}
    assert names == {"material_outline", "material_search", "material_read"}

    search_tool = next(tool for tool in tools if tool.name == "material_search")
    hit = search_tool.entrypoint(material_id=SAMPLE[1], query="等值匹配")
    assert hit["snippets"]
    guard = search_tool.entrypoint(material_id="not-in-catalog", query="等值")
    assert "error" in guard

    outline_tool = next(tool for tool in tools if tool.name == "material_outline")
    skeleton = outline_tool.entrypoint(material_id=SAMPLE[1])
    assert skeleton["entries"]

    read_tool = next(tool for tool in tools if tool.name == "material_read")
    slice_result = read_tool.entrypoint(material_id=SAMPLE[1], locator=hit["snippets"][0]["locator"])
    assert slice_result["text"]

    assert [item["tool"] for item in recorder] == [
        "material_search", "material_search", "material_outline", "material_read",
    ]
    assert recorder[0]["returned_locators"]
    assert recorder[1]["error"]


def test_build_material_tools_empty_catalog_is_empty() -> None:
    assert build_material_tools([], []) == []


# ---------------------------------------------------------------------------
# 目录式展开（core 协议件）


def test_expand_with_catalog_inlines_small_material() -> None:
    expanded, catalog = expand_material_uris_with_catalog(f"边界见 {TOKEN}")
    assert catalog == []
    assert "姓名全值等值匹配" in expanded


def test_expand_with_catalog_moves_oversized_material_to_catalog(monkeypatch) -> None:
    import impl.core.materials_store as ms

    monkeypatch.setattr(ms, "REFERENCE_EXPAND_BUDGET_CHARS", 10)
    expanded, catalog = expand_material_uris_with_catalog(f"边界见 {TOKEN}", budget=10)
    assert len(catalog) == 1
    assert catalog[0]["id"] == "client-search-match-rule"
    assert "[大资料未内联]" in expanded
    assert "姓名全值等值匹配" not in expanded


def test_expand_with_catalog_still_rejects_bad_refs() -> None:
    with pytest.raises(ValueError):
        expand_material_uris_with_catalog("见 material://llm_probe/bare-uri")
    with pytest.raises(ValueError):
        expand_material_uris_with_catalog("见 {material://llm_probe/no-such-material}")


def test_boundary_save_accepts_oversized_material(monkeypatch) -> None:
    """保存期：boundary 引大资料不拒写（检索式消费）；capability 照旧拒。"""
    import impl.core.materials_store as ms
    from impl.core.capability_store import validate_entry

    monkeypatch.setattr(ms, "REFERENCE_EXPAND_BUDGET_CHARS", 10)
    clean = validate_entry("my-api", {"capability": "检索客户", "boundary": TOKEN})
    assert clean["boundary"] == TOKEN
    with pytest.raises(ValueError):
        validate_entry("my-api", {"capability": f"字段口径见 {TOKEN}"})
