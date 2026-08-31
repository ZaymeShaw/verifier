#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json
from pathlib import Path

def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value

repo = Path.cwd()
sys.path.insert(0, str(repo))
load_dotenv(repo / ".env")
from impl.core.project_loader import load_project
from impl.projects.client_search.catalog import (
    STRONG_HIT_FLOOR, FIELD_INDEX_KEY, build_draft_catalog_registry, hit_strength, search_catalog,
)
from impl.projects.client_search.catalog_embedding import resolve_catalog_embedding_provider
spec = load_project("client_search")
reg = build_draft_catalog_registry(spec)
provider = resolve_catalog_embedding_provider()
qs = ["车牌号", "车牌", "投保日期", "投保", "合家福", "合家欢", "居家临界客户", "铂金", "关爱客户", "金凤", "天气怎么样", "客户平时有什么兴趣爱好", "一年内客户"]
for q in qs:
    hits, _ = search_catalog(reg, q, limit=8, embedding_provider=provider)
    print(f"\nQ={q!r} n={len(hits)}")
    for hit in hits[:8]:
        print(f"  {hit.index_key} {hit.key!r} name={hit.name!r} score={hit.score} ch={list(hit.matched_channels or ())} str={hit_strength(hit.score, hit.matched_channels)}")
        if float(hit.score or 0) >= STRONG_HIT_FLOOR:
            actual, _ = reg.load(hit.index_key, hit.key)
            c = actual.get("content") if isinstance(actual, dict) else actual
            if isinstance(c, dict):
                slim = {k: c[k] for k in ("field","spoken","normalized","value","is_supported","is_supported_explicit","description") if k in c}
                print("   ", json.dumps(slim, ensure_ascii=False)[:300])
