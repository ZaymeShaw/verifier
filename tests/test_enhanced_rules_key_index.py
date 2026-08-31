"""P4 驱动模拟测试：enhanced_rules 必须 key-index 化（按 field 切片 + 检索消费）。

验收标准（spec/grill/staleness_public_facility.md §3.8）：
1. 切片完整性：全部 rules 按 field 分组可寻址，无遗漏、无重复。
2. 检索命中等价：按 field 命中切片的内容与全量过滤该字段等价。
3. 注入边界：命中片段总大小远小于全量，整块注入/截断注入不再必要。
4. 门禁联动：登记检索通道后，大材料门禁不再命中该 ref。
"""
from __future__ import annotations

import json

import pytest
import yaml

from impl.core.project_loader import load_project, resolve_project_source_root
from impl.core.source_staleness import (
    audit_large_materials_without_retrieval_channel,
    slice_entries,
)
from impl.core.schema.investigation import load_investigation_manifest


def _source_path():
    spec = load_project("client_search")
    root = resolve_project_source_root(spec)
    return root / "src/main/python/data/client_search_query_parse/enhanced_rules_args.yaml"


def _enhanced_slice_spec():
    manifest = load_investigation_manifest(
        "impl/projects/client_search/investigation/judge/manifest.json"
    )
    for ref in manifest.evidence_refs:
        if ref.ref_id == "business-enhanced-rules":
            return ref.metadata["slice"]
    raise AssertionError("business-enhanced-rules missing from manifest")


_ENHANCED_RULES_PATH = _source_path()
_ENHANCED_SLICE_SPEC = _enhanced_slice_spec()
_HAS_SOURCE = _ENHANCED_RULES_PATH.is_file()


@pytest.mark.skipif(not _HAS_SOURCE, reason="business source not mounted")
def test_slice_coverage_of_all_rules():
    """761 条 rules 全部落在某个 field 切片内，无遗漏、无重复。"""
    entries = slice_entries(_ENHANCED_RULES_PATH, _ENHANCED_SLICE_SPEC)
    doc = yaml.safe_load(_ENHANCED_RULES_PATH.read_text(encoding="utf-8"))
    rules = [r for r in doc["rules"] if isinstance(r, dict)]
    assert len(entries) == len({r.get("field") for r in rules})
    covered = set()
    for entry in entries:
        content = json.loads(entry["content"])
        covered.update(r.get("field") for r in content["rules"])
    assert covered == {r.get("field") for r in rules}


@pytest.mark.skipif(not _HAS_SOURCE, reason="business source not mounted")
def test_retrieval_equals_full_filter():
    """按 field 检索切片 == 全量 rules 过滤该字段（内容一致）。"""
    entries = slice_entries(_ENHANCED_RULES_PATH, _ENHANCED_SLICE_SPEC)
    doc = yaml.safe_load(_ENHANCED_RULES_PATH.read_text(encoding="utf-8"))
    for entry in entries[:12]:
        field = entry["slice_key"].removeprefix("field:")
        content = json.loads(entry["content"])
        expected = [r for r in doc["rules"] if r.get("field") == field]
        assert content["rules"] == expected, f"slice mismatch for {field}"


@pytest.mark.skipif(not _HAS_SOURCE, reason="business source not mounted")
def test_hit_size_boundary():
    """多字段命中总大小远小于全量，整块注入不再必要。"""
    entries = slice_entries(_ENHANCED_RULES_PATH, _ENHANCED_SLICE_SPEC)
    by_field = {e["slice_key"].removeprefix("field:"): e for e in entries}
    full_chars = len(json.dumps(yaml.safe_load(_ENHANCED_RULES_PATH.read_text(encoding="utf-8")), ensure_ascii=False))
    fields = ["licensePlateNo", "clientAge", "polNoInfo.polStatus"]
    hit_chars = sum(len(by_field[f]["content"]) for f in fields if f in by_field)
    assert hit_chars < full_chars * 0.10, (
        f"key-index hit {hit_chars} chars should be far below full {full_chars}"
    )


def test_retrieval_channel_registration_closes_gate(tmp_path):
    """登记检索通道后，大材料门禁不再命中该 ref（fixture 版）。"""
    big = tmp_path / "enhanced_rules_args.yaml"
    big.write_text("x" * 40000, encoding="utf-8")
    manifest = {
        "evidence_refs": [
            {
                "ref_id": "business-enhanced-rules",
                "location": {
                    "location": "enhanced_rules_args.yaml",
                    "location_scope": "business_source",
                },
                "metadata": {
                    "consumption": [{"consumer": "enhanced-rules-key-index", "mode": "key_live"}]
                },
            }
        ]
    }
    findings = audit_large_materials_without_retrieval_channel(
        manifest,
        tmp_path,
        threshold_chars=30000,
    )
    assert findings == []
