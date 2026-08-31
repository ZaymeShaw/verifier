#!/usr/bin/env python3
"""Probe Draft Catalog Search/Load on frozen 30 queries. Read-only."""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4] if False else None

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

def parse_table(md: str):
    rows = []
    for line in md.splitlines():
        if not line.startswith("| source-badcase-"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        case_id, query, live, prod, draft = parts[:5]
        def status(cell: str) -> str:
            token = cell.split()[0].strip("(`")
            return token
        rows.append({
            "case_id": case_id,
            "query": query,
            "live": live,
            "production": status(prod),
            "draft": status(draft),
        })
    return rows

def main() -> int:
    repo = Path(os.environ.get("VERIFIER_REPO") or Path.cwd())
    sys.path.insert(0, str(repo))
    load_dotenv(repo / ".env")
    table_path = repo / "impl/projects/client_search/draft/.state/judge/iterations/001-run-comparison-table.md"
    cases_path = repo / "impl/projects/client_search/draft/.state/judge/iteration-cases.json"
    rows = parse_table(table_path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(cases_path.read_text(encoding="utf-8"))}
    print("TABLE_N", len(rows))
    print("CASES_N", len(cases))
    from impl.core.project_loader import load_project
    spec = load_project("client_search")
    keys = ("field_definitions", "enhanced_rules", "value_mappings", "abbrname_enums")
    for k in keys:
        p = spec.source_path(k)
        exists = bool(p) and Path(p).is_file()
        print("SOURCE", k, exists, p)
    from impl.projects.client_search.catalog import (
        STRONG_HIT_FLOOR,
        build_draft_catalog_registry,
        hit_strength,
        search_catalog,
    )
    from impl.projects.client_search.catalog_embedding import (
        resolve_catalog_embedding_provider,
    )
    registry = build_draft_catalog_registry(spec)
    catalog = registry.catalog()
    print("CATALOG", [x["index_key"] for x in catalog])
    provider = None
    try:
        provider = resolve_catalog_embedding_provider()
    except Exception as exc:
        print("EMBED_RESOLVE_ERR", type(exc).__name__, str(exc)[:200])
        provider = None
    print("EMBED_PROVIDER", type(provider).__name__ if provider else None)
    # Focus queries first
    focus = [
        "合家福客户", "7月盘客", "贵C826N1", "孤儿单", "158****5078",
        "2025年6月份投保的新客户名单，", "东莞何叶玩具制品有限公司", "中银保信",
        "在职单", "续保", "盘客",
    ]
    for q in focus:
        hits, searched = search_catalog(registry, q, limit=8, embedding_provider=provider)
        print(f"\nQ={q!r} n_hits={len(hits)} searched={len(searched)}")
        for hit in hits:
            ch = list(hit.matched_channels or ())
            print(f"  hit {hit.index_key} key={hit.key!r} name={hit.name!r} score={hit.score} ch={ch} strength={hit_strength(hit.score, hit.matched_channels)}")
            if float(hit.score or 0) >= STRONG_HIT_FLOOR:
                try:
                    actual, receipt = registry.load(hit.index_key, hit.key)
                    content = actual.get("content") if isinstance(actual, dict) else actual
                    if isinstance(content, dict):
                        slim = {k: content[k] for k in list(content)[:12]}
                    else:
                        slim = str(content)[:240]
                    print(f"    LOAD ok keys={list(content) if isinstance(content, dict) else type(content)} slim={json.dumps(slim, ensure_ascii=False)[:400]}")
                except Exception as exc:
                    print(f"    LOAD FAIL {type(exc).__name__}: {exc}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
