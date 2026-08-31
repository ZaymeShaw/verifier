#!/usr/bin/env python3
"""Dump Draft Catalog Search/Load for frozen 30 + notice labels + holdouts."""
from __future__ import annotations
import json, os, re, sys
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

def parse_table(md: str):
    rows = []
    for line in md.splitlines():
        if not line.startswith("| source-badcase-"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        def status(cell: str) -> str:
            return cell.split()[0].strip("(`")
        rows.append({
            "case_id": parts[0], "query": parts[1], "live": parts[2],
            "production": status(parts[3]), "draft": status(parts[4]),
        })
    return rows

NOTICE_RE = re.compile(r"(?P<c>[^，。；;\n]{1,32}?)(?:暂不支持|当前不支持|不支持)(?:搜索|查询)?")
KEEP = ("field","spoken","normalized","value","membership","is_supported","is_supported_explicit","description","operators","value_types")
HOLDOUTS = ["金凤","关爱客户","天气怎么样","客户平时有什么兴趣爱好","盘客","去盘客","A","O2O","合家福","合家欢","车牌号","投保日期"]

def labels_of(text: str):
    out = []
    for m in NOTICE_RE.finditer(text or ""):
        c = m.group("c").strip(" ：:，,。；;\n")
        c = re.sub(r"^(?:提示|说明|系统提示)", "", c).strip(" ：:")
        if c and c not in out:
            out.append(c)
    return out

def slim(content):
    if not isinstance(content, dict):
        return str(content)[:300]
    d = {}
    for k in KEEP:
        if k in content:
            v = content[k]
            if isinstance(v, str) and len(v) > 220:
                v = v[:220] + "…"
            d[k] = v
    return d

def pack_search(registry, search_catalog, provider, STRONG, hit_strength, query):
    hits, searched = search_catalog(registry, query, limit=8, embedding_provider=provider)
    recs, loads = [], []
    for hit in hits:
        rec = {
            "index_key": hit.index_key, "key": hit.key, "name": hit.name,
            "score": float(hit.score or 0), "channels": list(hit.matched_channels or ()),
            "strength": hit_strength(hit.score, hit.matched_channels),
        }
        recs.append(rec)
        if rec["score"] < STRONG:
            continue
        try:
            actual, _ = registry.load(hit.index_key, hit.key)
            content = actual.get("content") if isinstance(actual, dict) else actual
            loads.append({**rec, "load_ok": True, "content": slim(content),
                          "locator": actual.get("locator") if isinstance(actual, dict) else None})
        except Exception as exc:
            loads.append({**rec, "load_ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return recs, loads, list(searched)

def main() -> int:
    repo = Path.cwd()
    sys.path.insert(0, str(repo))
    load_dotenv(repo / ".env")
    table_path = repo / "impl/projects/client_search/draft/.state/judge/iterations/001-run-comparison-table.md"
    cases_path = repo / "impl/projects/client_search/draft/.state/judge/iteration-cases.json"
    out_path = repo / "impl/projects/client_search/investigation/judge/experiments/catalog-hits-dump.json"
    rows = parse_table(table_path.read_text(encoding="utf-8"))
    traces = {c["id"]: c for c in json.loads(cases_path.read_text(encoding="utf-8"))}
    from impl.core.project_loader import load_project
    from impl.projects.client_search.catalog import (
        STRONG_HIT_FLOOR, build_draft_catalog_registry, hit_strength, search_catalog,
    )
    from impl.projects.client_search.catalog_embedding import resolve_catalog_embedding_provider
    spec = load_project("client_search")
    registry = build_draft_catalog_registry(spec)
    try:
        provider = resolve_catalog_embedding_provider()
    except Exception:
        provider = None
    cases = []
    for row in rows:
        extracted = ((traces.get(row["case_id"]) or {}).get("trace") or {}).get("extracted_output") or {}
        conds = extracted.get("conditions") or extracted.get("structured_output") or []
        if not isinstance(conds, list):
            conds = []
        values, fields = [], []
        for item in conds:
            if not isinstance(item, dict):
                continue
            if item.get("field"):
                fields.append(str(item["field"]))
            raw = item.get("value")
            if isinstance(raw, list):
                values.extend(str(x) for x in raw if x is not None and str(x) != "")
            elif raw is not None and str(raw) != "":
                values.append(str(raw))
        robot = str(extracted.get("robot_text") or "")
        labs = labels_of(row["live"]) or labels_of(robot)
        hits, loads, searched = pack_search(registry, search_catalog, provider, STRONG_HIT_FLOOR, hit_strength, row["query"])
        nh, nl = [], []
        for lab in labs:
            h, l, _ = pack_search(registry, search_catalog, provider, STRONG_HIT_FLOOR, hit_strength, lab)
            nh.extend(h); nl.extend(l)
        cases.append({
            **row, "live_values": values, "live_fields": fields, "conditions": conds,
            "live_empty": not bool(conds), "notice_labels": labs,
            "hits": hits, "loads": loads, "notice_hits": nh, "notice_loads": nl,
            "searched": searched,
        })
        print("CASE", row["case_id"], "hits", len(hits), "loads", len(loads), "labels", labs)
    holdouts = []
    for q in HOLDOUTS:
        hits, loads, _ = pack_search(registry, search_catalog, provider, STRONG_HIT_FLOOR, hit_strength, q)
        holdouts.append({"query": q, "hits": hits, "loads": loads})
        print("HOLD", q, "hits", len(hits), "loads", len(loads))
    payload = {
        "embedding": type(provider).__name__ if provider else None,
        "index_keys": [x["index_key"] for x in registry.catalog()],
        "cases": cases, "holdouts": holdouts,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out_path, "n", len(cases))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
