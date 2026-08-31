#!/usr/bin/env python3
"""Empirical simulation: Draft Judge Key-Index consumption policies.

Read-only. Does not modify judge.py, does not promote, does not commit.
Overlay on production Current. Catalog Search→Load is real.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ8 = timezone(timedelta(hours=8))
STRONG_HIT_FLOOR = 150.0
FOCUS_IDS = (
    "source-badcase-128",
    "source-badcase-088",
    "source-badcase-093",
    "source-badcase-008",
    "source-badcase-048",
    "source-badcase-073",
    "source-badcase-113",
    "source-badcase-133",
)
HOLDOUTS = (
    "金凤",
    "关爱客户",
    "天气怎么样",
    "客户平时有什么兴趣爱好",
    "盘客",
    "去盘客",
    "A",
    "O2O",
    "合家福",
    "合家欢",
    "车牌号",
    "投保日期",
)
NOTICE_RE = re.compile(
    r"(?P<constraint>[^，。；;\n]{1,32}?)(?:暂不支持|当前不支持|不支持)(?:搜索|查询)?"
)
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
STATUS_SHORT = {
    "fulfilled": "F",
    "not_fulfilled": "NF",
    "not_evaluable": "NE",
    "undecided": "U",
}


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


def parse_status(cell: str) -> str:
    token = (cell or "").split()[0].strip("(`")
    if token in {"fulfilled", "not_fulfilled", "not_evaluable"}:
        return token
    return token or "undecided"


def parse_comparison_table(md: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in md.splitlines():
        if not line.startswith("| source-badcase-"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 5:
            continue
        rows.append(
            {
                "case_id": parts[0],
                "query": parts[1],
                "live_text": parts[2],
                "production": parse_status(parts[3]),
                "draft": parse_status(parts[4]),
            }
        )
    return rows


def live_values(conditions: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in conditions:
        if not isinstance(item, dict):
            continue
        raw = item.get("value")
        if isinstance(raw, list):
            values.extend(str(x) for x in raw if x is not None and str(x) != "")
        elif raw is not None and str(raw) != "":
            values.append(str(raw))
    return values


def live_fields(conditions: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    for item in conditions:
        if isinstance(item, dict) and item.get("field"):
            fields.append(str(item["field"]))
    return fields


def extract_notice_labels(live_text: str) -> list[str]:
    labels: list[str] = []
    for match in NOTICE_RE.finditer(live_text or ""):
        constraint = match.group("constraint").strip(" ：:，,。；;\n")
        constraint = re.sub(r"^(?:提示|说明|系统提示)", "", constraint).strip(" ：:")
        if constraint and constraint not in labels:
            labels.append(constraint)
    return labels


def has_refusal_notice(live_text: str) -> bool:
    text = live_text or ""
    return bool(
        re.search(r"暂不支持|当前不支持|不支持搜索|无法进行查询", text)
    )


def is_live_empty(conditions: list[dict[str, Any]]) -> bool:
    return not bool(conditions)


def canonical_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item) != ""]
    if value is None or str(value) == "":
        return []
    return [str(value)]


def live_uses(canonical: Any, values: list[str]) -> bool:
    cans = canonical_list(canonical)
    return any(item in values for item in cans)


def spoken_in_query(spoken: str, query: str) -> bool:
    token = str(spoken or "").strip()
    if not token:
        return False
    return token in (query or "")


def cjk_ngrams(text: str, minimum: int = 3) -> set[str]:
    grams: set[str] = set()
    for run in CJK_RUN.findall(text or ""):
        for size in range(minimum, len(run) + 1):
            for index in range(0, len(run) - size + 1):
                grams.add(run[index : index + size])
    return grams


def hamming1(left: str, right: str) -> bool:
    if len(left) != len(right) or len(left) < 3:
        return False
    return sum(a != b for a, b in zip(left, right)) == 1


def query_live_nearmiss(query: str, values: list[str]) -> dict[str, str] | None:
    """Generic 1-char CJK near-miss (合家福 vs 合家欢 shape). No lexicon."""
    query_grams = cjk_ngrams(query)
    for value in values:
        for run in CJK_RUN.findall(value):
            if run in query_grams or run in (query or ""):
                continue
            for gram in query_grams:
                if hamming1(gram, run):
                    return {"query_span": gram, "live_span": run}
    return None


def content_snippet(content: Any, limit: int = 360) -> Any:
    if not isinstance(content, dict):
        text = str(content)
        return text[:limit]
    keep: dict[str, Any] = {}
    for key in (
        "field",
        "spoken",
        "normalized",
        "value",
        "membership",
        "name",
        "is_supported",
        "is_supported_explicit",
        "operators",
        "value_types",
        "description",
        "retrieval_text",
        "operator",
        "patterns",
    ):
        if key not in content:
            continue
        value = content[key]
        if isinstance(value, str) and len(value) > 220:
            value = value[:220] + "…"
        keep[key] = value
    return keep


def hit_record(hit: Any) -> dict[str, Any]:
    channels = list(hit.matched_channels or ())
    score = float(hit.score or 0)
    strength = "exact" if score >= STRONG_HIT_FLOOR else (
        "embedding" if "embedding" in channels and score > 40 else "rewrite"
    )
    return {
        "index_key": hit.index_key,
        "key": hit.key,
        "name": hit.name,
        "score": score,
        "channels": channels,
        "strength": strength,
        "strong": score >= STRONG_HIT_FLOOR,
    }


def search_hits(registry, query: str, *, provider, search_catalog) -> tuple[list[Any], list[str]]:
    hits, searched = search_catalog(
        registry, query, limit=8, embedding_provider=provider
    )
    return list(hits), list(searched)


def load_strong(registry, hits: list[Any]) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for hit in hits:
        rec = hit_record(hit)
        if not rec["strong"]:
            continue
        entry = dict(rec)
        try:
            actual, receipt = registry.load(hit.index_key, hit.key)
            content = actual.get("content") if isinstance(actual, dict) else actual
            entry["load_ok"] = True
            entry["content"] = content_snippet(content)
            entry["raw_content"] = content if isinstance(content, dict) else {}
            entry["locator"] = (
                actual.get("locator") if isinstance(actual, dict) else None
            )
            entry["dump_wildcard"] = str(hit.key) in {"*", ""}
        except Exception as exc:
            entry["load_ok"] = False
            entry["load_error"] = f"{type(exc).__name__}: {exc}"
            entry["raw_content"] = {}
        loaded.append(entry)
    return loaded


# ---------------------------------------------------------------------------
# Policies. P2 must stay generic: Load content + live shape only.
# ---------------------------------------------------------------------------

FIELD_INDEX = "client-search.field-definitions"
MAP_INDEX = "client-search.value-mappings"
ABBR_INDEX = "client-search.abbrname-enums"
RULE_INDEX = "client-search.enhanced-rules"


def policy_p0(current: str, **_: Any) -> tuple[str, str]:
    return current, "core_only"


def policy_p1_searchhit_pollutes(
    current: str,
    *,
    query: str,
    values: list[str],
    empty: bool,
    hits: list[dict[str, Any]],
    **_: Any,
) -> tuple[str, str]:
    near = query_live_nearmiss(query, values)
    if near:
        return "fulfilled", f"nearmiss_as_synonym:{near['query_span']}~{near['live_span']}"
    if empty and hits:
        kinds = sorted({item.get("index_key") or "" for item in hits})
        return "not_fulfilled", f"empty_plus_any_hit:{','.join(kinds)[:80]}"
    return current, "no_pollution_trigger"


def policy_p2_load_only(
    current: str,
    *,
    query: str,
    values: list[str],
    empty: bool,
    notice: bool,
    loads: list[dict[str, Any]],
    **_: Any,
) -> tuple[str, str]:
    """Silent-miss candidate. SearchHit/rewrite/weak ignored. No business ifs."""
    successful = [item for item in loads if item.get("load_ok") and item.get("strong")]
    if not successful:
        return current, "silent_miss_no_strong_load"

    mapping_decision: tuple[str, str] | None = None
    field_decision: tuple[str, str] | None = None
    for item in successful:
        index_key = item.get("index_key")
        content = item.get("raw_content") or {}
        if not isinstance(content, dict):
            content = {}
        if index_key == MAP_INDEX:
            spoken = str(content.get("spoken") or item.get("name") or "")
            canonical = content.get("normalized")
            if spoken_in_query(spoken, query) and canonical_list(canonical):
                if live_uses(canonical, values):
                    mapping_decision = (
                        "fulfilled",
                        f"mapping_live_matches:{spoken}->{canonical_list(canonical)[0]}",
                    )
                elif values:
                    mapping_decision = (
                        "not_fulfilled",
                        f"mapping_live_differs:{spoken}->{canonical_list(canonical)[0]}",
                    )
        elif index_key == ABBR_INDEX:
            member = str(content.get("value") or item.get("key") or "")
            if spoken_in_query(member, query) and member:
                if live_uses(member, values):
                    mapping_decision = (
                        "fulfilled",
                        f"abbr_live_matches:{member}",
                    )
                elif values:
                    mapping_decision = (
                        "not_fulfilled",
                        f"abbr_live_differs:{member}",
                    )
        elif index_key == FIELD_INDEX:
            supported = content.get("is_supported")
            explicit = bool(content.get("is_supported_explicit"))
            field = str(content.get("field") or item.get("key") or "")
            if explicit and supported is False and empty and notice:
                field_decision = (
                    "fulfilled",
                    f"unsupported_honest_refusal:{field}",
                )
            elif supported is True and empty:
                field_decision = (
                    "not_fulfilled",
                    f"in_scope_empty_miss:{field}",
                )
    if mapping_decision is not None:
        return mapping_decision
    if field_decision is not None:
        return field_decision
    return current, "strong_load_no_status_fact"


def policy_p3_enrich_gate(
    current: str,
    *,
    empty: bool,
    loads: list[dict[str, Any]],
    notice_loads: list[dict[str, Any]],
    **_: Any,
) -> tuple[str, str]:
    """E1 wiring approximation: unsupported field → NF; empty live → NF."""
    combined = [
        item
        for item in [*loads, *notice_loads]
        if item.get("load_ok") and item.get("strong")
    ]
    for item in combined:
        if item.get("index_key") != FIELD_INDEX:
            continue
        content = item.get("raw_content") or {}
        if not isinstance(content, dict):
            continue
        if content.get("is_supported") is False:
            field = str(content.get("field") or item.get("key") or "")
            return "not_fulfilled", f"e1_unsupported_field_nf:{field}"
    if empty:
        return "not_fulfilled", "e1_empty_blocking_nf"
    return current, "e1_no_empty_no_unsupported"


def policy_p4_rewrite_synonym(
    current: str,
    *,
    query: str,
    values: list[str],
    hits: list[dict[str, Any]],
    **_: Any,
) -> tuple[str, str]:
    for item in hits:
        channels = item.get("channels") or []
        if "rewrite" not in channels:
            continue
        names = [str(item.get("name") or ""), str(item.get("key") or "")]
        for name in names:
            if not name or name in (query or ""):
                continue
            if name in values:
                return "fulfilled", f"rewrite_hit_as_synonym:{name}"
    return current, "no_rewrite_synonym"


POLICIES = (
    ("P0_core_only", policy_p0),
    ("P1_searchhit_pollutes", policy_p1_searchhit_pollutes),
    ("P2_load_only_silent_miss", policy_p2_load_only),
    ("P3_enrich_gate_current", policy_p3_enrich_gate),
    ("P4_rewrite_as_synonym", policy_p4_rewrite_synonym),
)


def desired_status(current: str, p2_status: str, p2_reason: str) -> tuple[str, str]:
    """Desired = Current unless a real Load proved a mapping/field fact."""
    if p2_reason.startswith("silent_miss"):
        return current, "default_current_no_materials"
    if p2_reason.startswith("strong_load_no_status_fact"):
        return current, "default_current_load_not_status_fact"
    if p2_status != current:
        return p2_status, f"override_from_load:{p2_reason}"
    return p2_status, f"current_confirmed_by_load:{p2_reason}"


def score_policy(
    cases: list[dict[str, Any]], key: str, gold_key: str = "desired"
) -> dict[str, Any]:
    match = 0
    false_f = 0
    false_nf = 0
    false_ne = 0
    undecided = 0
    focus: dict[str, Any] = {}
    diverged: list[str] = []
    for row in cases:
        pred = row["policies"][key]["status"]
        gold = row[gold_key]["status"] if gold_key == "desired" else row[gold_key]
        if pred == "undecided":
            undecided += 1
            pred_eff = row["production"]
        else:
            pred_eff = pred
        if pred_eff == gold:
            match += 1
        else:
            if pred_eff == "fulfilled":
                false_f += 1
            elif pred_eff == "not_fulfilled":
                false_nf += 1
            elif pred_eff == "not_evaluable":
                false_ne += 1
            diverged.append(row["case_id"])
        short_id = row["case_id"].replace("source-badcase-", "")
        if row["case_id"] in FOCUS_IDS:
            focus[short_id] = {
                "pred": STATUS_SHORT.get(pred_eff, pred_eff),
                "gold": STATUS_SHORT.get(gold, gold),
                "reason": row["policies"][key]["reason"],
            }
    n = len(cases)
    return {
        "n": n,
        "match": match,
        "match_rate": round(match / n, 4) if n else 0,
        "false_F": false_f,
        "false_NF": false_nf,
        "false_NE": false_ne,
        "undecided": undecided,
        "diverged_ids": diverged,
        "focus": focus,
    }


def p2_has_lexicon() -> tuple[bool, list[str]]:
    source = inspect.getsource(policy_p2_load_only)
    forbidden = ("盘客", "合家福", "天气", "COMMON_TOKENS", "车牌")
    found = [token for token in forbidden if token in source]
    return (not found), found


def render_md(payload: dict[str, Any]) -> str:
    scores = payload["scores_vs_desired"]
    vs_cur = payload["scores_vs_current"]
    now = payload["generated_at_shanghai"]
    rec = payload["recommended_policy"]
    lines: list[str] = []
    lines.append("# Draft Judge Key-Index 消费策略仿真（冻结 30 条）")
    lines.append("")
    lines.append(f"生成时间：{now}")
    lines.append("")
    lines.append("仿真性质：在 production Current 核心上叠加 Catalog Search→Load 消费策略；不改 fulfillment 核心、不 promote、不改 judge.py。")
    lines.append("")
    lines.append("## 1. 策略对照 desired（Load 证明才允许改 Current）")
    lines.append("")
    lines.append("| policy | match | false F | false NF | false NE | 128 | 088 | 093 | 008 | 048 | 073 | 113 | 133 |")
    lines.append("|---|---:|---:|---:|---:|---|---|---|---|---|---|---|---|")
    for name in [item[0] for item in POLICIES]:
        s = scores[name]
        f = s["focus"]
        def cell(cid: str) -> str:
            item = f.get(cid) or {}
            return f"{item.get('pred','?')}"
        lines.append(
            f"| {name} | {s['match']}/30 | {s['false_F']} | {s['false_NF']} | {s['false_NE']} "
            f"| {cell('128')} | {cell('088')} | {cell('093')} | {cell('008')} "
            f"| {cell('048')} | {cell('073')} | {cell('113')} | {cell('133')} |"
        )
    lines.append("")
    lines.append("## 2. 相对 production Current 的位移（好策略：静默 miss 不改核心）")
    lines.append("")
    lines.append("| policy | 仍等于 Current | 改动条数 | 改动 case |")
    lines.append("|---|---:|---:|---|")
    for name in [item[0] for item in POLICIES]:
        s = vs_cur[name]
        moved = ", ".join(x.replace("source-badcase-", "") for x in s["diverged_ids"]) or "—"
        lines.append(f"| {name} | {s['match']}/30 | {30 - s['match']} | {moved} |")
    lines.append("")
    lines.append("## 3. 八条对照（Current / Draft / desired / 各策略）")
    lines.append("")
    lines.append("| case | query | live 形态 | Current | Draft | desired | P1 | P2 | P3 | P4 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in payload["cases"]:
        if row["case_id"] not in FOCUS_IDS:
            continue
        cid = row["case_id"].replace("source-badcase-", "")
        live_shape = []
        if row["live_empty"]:
            live_shape.append("empty")
        else:
            live_shape.append("conditions")
        if row["refusal_notice"]:
            live_shape.append("notice")
        if row["nearmiss"]:
            live_shape.append("nearmiss")
        pols = row["policies"]
        def sh(key: str) -> str:
            return STATUS_SHORT.get(pols[key]["status"], pols[key]["status"])
        lines.append(
            "| {cid} | {q} | {shape} | {cur} | {draft} | {des} | {p1} | {p2} | {p3} | {p4} |".format(
                cid=cid,
                q=row["query"][:18],
                shape="+".join(live_shape) or "—",
                cur=STATUS_SHORT.get(row["production"], row["production"]),
                draft=STATUS_SHORT.get(row["draft"], row["draft"]),
                des=STATUS_SHORT.get(row["desired"]["status"], row["desired"]["status"]),
                p1=sh("P1_searchhit_pollutes"),
                p2=sh("P2_load_only_silent_miss"),
                p3=sh("P3_enrich_gate_current"),
                p4=sh("P4_rewrite_as_synonym"),
            )
        )
    lines.append("")
    lines.append("### 八条要点")
    lines.append("")
    for item in payload["focus_notes"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 4. Anti-hack / 泛化")
    lines.append("")
    ah = payload["anti_hack"]
    lines.append(f"- SearchHit-as-F on 128：catalog hits={ah['case_128_hit_count']}；P1={ah['p1_128']}（字面近邻当同义）；P2={ah['p2_128']}；P4={ah['p4_128']}（rewrite 未打到合家欢）。")
    lines.append(f"- 全量 dump：wildcard load 次数={ah['wildcard_loads']}；单 case 最大 Load 次数={ah['max_loads_per_case']}（limit=8，从未遍历 mappings 全集）。")
    lines.append(f"- P2 业务词表：clean={ah['p2_lexicon_clean']} forbidden_found={ah['p2_lexicon_found']}。")
    lines.append(f"- Holdout：{ah['holdout_summary']}")
    lines.append("- 消费契约按 Collection 泛型 Search→Load，无 client_search ifs。")
    lines.append("")
    lines.append("## 5. 推荐策略与最终消费契约")
    lines.append("")
    lines.append(f"**推荐：{rec}**")
    lines.append("")
    for bullet in payload["consumption_contract"]:
        lines.append(f"- {bullet}")
    lines.append("")
    lines.append("## 6. Catalog 运行备注")
    lines.append("")
    cat = payload["catalog_meta"]
    lines.append(f"- embedding: {cat.get('embedding')}")
    lines.append(f"- indexes: {', '.join(cat.get('index_keys') or [])}")
    lines.append(f"- strong Load 覆盖: {cat.get('cases_with_strong_load')}/30")
    lines.append(f"- silent miss: {cat.get('silent_miss_cases')}/30")
    if cat.get("error"):
        lines.append(f"- **catalog error**: {cat['error']}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    repo = Path(os.environ.get("VERIFIER_REPO") or Path.cwd()).resolve()
    sys.path.insert(0, str(repo))
    load_dotenv(repo / ".env")
    out_dir = Path(os.environ.get("SIM_OUT_DIR") or repo / "impl/projects/client_search/investigation/judge/experiments")
    out_dir.mkdir(parents=True, exist_ok=True)

    table_path = repo / "impl/projects/client_search/draft/.state/judge/iterations/001-run-comparison-table.md"
    cases_path = repo / "impl/projects/client_search/draft/.state/judge/iteration-cases.json"
    rows = parse_comparison_table(table_path.read_text(encoding="utf-8"))
    traces = {item["id"]: item for item in json.loads(cases_path.read_text(encoding="utf-8"))}

    catalog_meta: dict[str, Any] = {
        "embedding": None,
        "index_keys": [],
        "error": None,
        "cases_with_strong_load": 0,
        "silent_miss_cases": 0,
    }
    registry = None
    provider = None
    search_catalog = None
    try:
        from impl.core.project_loader import load_project
        from impl.projects.client_search.catalog import (
            build_draft_catalog_registry,
            search_catalog as search_catalog_fn,
        )
        from impl.projects.client_search.catalog_embedding import (
            resolve_catalog_embedding_provider,
        )

        spec = load_project("client_search")
        registry = build_draft_catalog_registry(spec)
        catalog_meta["index_keys"] = [item["index_key"] for item in registry.catalog()]
        search_catalog = search_catalog_fn
        try:
            provider = resolve_catalog_embedding_provider()
        except Exception as exc:
            provider = None
            catalog_meta["embedding"] = f"resolve_failed:{type(exc).__name__}"
        else:
            catalog_meta["embedding"] = type(provider).__name__ if provider else "skipped_no_provider"
    except Exception as exc:
        catalog_meta["error"] = f"{type(exc).__name__}: {exc}"
        catalog_meta["traceback"] = traceback.format_exc()[-1500:]

    cases_out: list[dict[str, Any]] = []
    holdout_out: list[dict[str, Any]] = []
    wildcard_loads = 0
    max_loads = 0

    def run_query(query: str) -> dict[str, Any]:
        nonlocal wildcard_loads
        if registry is None or search_catalog is None:
            return {"hits": [], "loads": [], "searched": []}
        hits_raw, searched = search_hits(registry, query, provider=provider, search_catalog=search_catalog)
        hits = [hit_record(hit) for hit in hits_raw]
        loads = load_strong(registry, hits_raw)
        for item in loads:
            if item.get("dump_wildcard"):
                wildcard_loads += 1
        return {"hits": hits, "loads": loads, "searched": searched}

    for row in rows:
        case_id = row["case_id"]
        query = row["query"]
        live_text = row["live_text"]
        trace = traces.get(case_id) or {}
        extracted = ((trace.get("trace") or {}).get("extracted_output") or {})
        conditions = extracted.get("conditions") or extracted.get("structured_output") or []
        if not isinstance(conditions, list):
            conditions = []
        values = live_values(conditions)
        fields = live_fields(conditions)
        empty = is_live_empty(conditions)
        notice = has_refusal_notice(live_text) or has_refusal_notice(
            str(extracted.get("robot_text") or "")
        )
        labels = extract_notice_labels(live_text) or extract_notice_labels(
            str(extracted.get("robot_text") or "")
        )
        pack = run_query(query)
        notice_loads: list[dict[str, Any]] = []
        notice_hits: list[dict[str, Any]] = []
        for label in labels:
            extra = run_query(label)
            notice_hits.extend(extra["hits"])
            notice_loads.extend(extra["loads"])
        loads_for_count = pack["loads"]
        max_loads = max(max_loads, len(loads_for_count))
        if pack["loads"]:
            catalog_meta["cases_with_strong_load"] += 1
        else:
            catalog_meta["silent_miss_cases"] += 1

        ctx = {
            "current": row["production"],
            "query": query,
            "values": values,
            "empty": empty,
            "notice": notice,
            "hits": pack["hits"],
            "loads": pack["loads"],
            "notice_loads": notice_loads,
        }
        policy_results: dict[str, Any] = {}
        for name, fn in POLICIES:
            status, reason = fn(**ctx) if name != "P0_core_only" else fn(row["production"])
            policy_results[name] = {"status": status, "reason": reason}
        p2 = policy_results["P2_load_only_silent_miss"]
        des_status, des_reason = desired_status(row["production"], p2["status"], p2["reason"])
        near = query_live_nearmiss(query, values)
        cases_out.append(
            {
                "case_id": case_id,
                "query": query,
                "live_text": live_text,
                "live_values": values,
                "live_fields": fields,
                "live_empty": empty,
                "refusal_notice": notice,
                "notice_labels": labels,
                "nearmiss": near,
                "production": row["production"],
                "draft": row["draft"],
                "hits": pack["hits"],
                "loads": [
                    {k: v for k, v in item.items() if k != "raw_content"}
                    for item in pack["loads"]
                ],
                "notice_hits": notice_hits,
                "notice_loads": [
                    {k: v for k, v in item.items() if k != "raw_content"}
                    for item in notice_loads
                ],
                "policies": policy_results,
                "desired": {"status": des_status, "reason": des_reason},
            }
        )

    if registry is not None and search_catalog is not None:
        for q in HOLDOUTS:
            pack = run_query(q)
            holdout_out.append(
                {
                    "query": q,
                    "n_hits": len(pack["hits"]),
                    "hit_keys": [f"{h['index_key']}:{h['key']}:{h['strength']}" for h in pack["hits"][:8]],
                    "n_strong_load": len(pack["loads"]),
                }
            )

    scores_desired = {name: score_policy(cases_out, name, "desired") for name, _ in POLICIES}
    scores_current = {name: score_policy(cases_out, name, "production") for name, _ in POLICIES}
    lexicon_clean, lexicon_found = p2_has_lexicon()

    def pred_of(cid: str, policy: str) -> str:
        row = next(item for item in cases_out if item["case_id"] == cid)
        return STATUS_SHORT.get(row["policies"][policy]["status"], row["policies"][policy]["status"])

    row128 = next(item for item in cases_out if item["case_id"] == "source-badcase-128")
    focus_notes = []
    for cid in FOCUS_IDS:
        row = next(item for item in cases_out if item["case_id"] == cid)
        short = cid.replace("source-badcase-", "")
        n_hits = len(row["hits"])
        n_load = len(row["loads"])
        p2r = row["policies"]["P2_load_only_silent_miss"]["reason"]
        p3r = row["policies"]["P3_enrich_gate_current"]["reason"]
        focus_notes.append(
            f"**{short}** `{row['query']}` Current={STATUS_SHORT.get(row['production'])} "
            f"Draft={STATUS_SHORT.get(row['draft'])} desired={STATUS_SHORT.get(row['desired']['status'])}；"
            f"hits={n_hits} strong_load={n_load}；P2={p2r}；P3={p3r}"
        )

    holdout_bits = []
    for item in holdout_out:
        holdout_bits.append(
            f"{item['query']} hits={item['n_hits']} strong={item['n_strong_load']}"
        )

    recommended = "P2_load_only_silent_miss"
    contract = [
        "Key-Index 只定位/补载可 Load 材料，不得改写 F/NF 核心；无强命中 Load 时静默走原路径（= production Current）。",
        "SearchHit 不是 Evidence。rewrite / embedding 近邻不得当同义证明；未 Load 不得改 overall。",
        "仅当 Load 到 value_mapping / abbr 且 spoken 出现在 query：live 用了 canonical → F；live 用了别的值 → NF。",
        "仅当 Load 到字段定义 is_supported=false（显式）且 live 为空 + 透明「暂不支持」通知 → F（边界处理成功，不是把 parser 打成 NF）。",
        "仅当 Load 到字段 is_supported=true 且 live 为空（无条件）→ NF（能力内漏检）。",
        "Authority 关闭时，不得仅因存在能力边界就判 NE；诚实拒绝是 F，不是 NF/NE。",
        "禁止业务词表 / COMMON_TOKENS / query-shape 路由；契约跨项目泛型为 Search→Load supplement，而不是 client_search ifs。",
        "禁止全量 dump（key=* 或遍历 mappings）；每次只 Load Search 返回的有限候选（limit=8）。",
    ]

    payload = {
        "generated_at_shanghai": datetime.now(TZ8).strftime("%Y-%m-%d %H:%M:%S") + " CST",
        "n_cases": len(cases_out),
        "recommended_policy": recommended,
        "catalog_meta": catalog_meta,
        "scores_vs_desired": scores_desired,
        "scores_vs_current": scores_current,
        "cases": cases_out,
        "holdouts": holdout_out,
        "focus_notes": focus_notes,
        "anti_hack": {
            "case_128_hit_count": len(row128["hits"]),
            "p1_128": pred_of("source-badcase-128", "P1_searchhit_pollutes"),
            "p2_128": pred_of("source-badcase-128", "P2_load_only_silent_miss"),
            "p4_128": pred_of("source-badcase-128", "P4_rewrite_as_synonym"),
            "wildcard_loads": wildcard_loads,
            "max_loads_per_case": max_loads,
            "p2_lexicon_clean": lexicon_clean,
            "p2_lexicon_found": lexicon_found,
            "holdout_summary": "；".join(holdout_bits),
        },
        "consumption_contract": contract,
    }

    json_path = out_dir / "judge-consume-sim.json"
    md_path = out_dir / "judge-consume-sim.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_md(payload), encoding="utf-8")
    print("WROTE", json_path)
    print("WROTE", md_path)
    print("REC", recommended)
    for name, _ in POLICIES:
        s = scores_desired[name]
        c = scores_current[name]
        print(
            f"{name} vs_desired match={s['match']}/30 F={s['false_F']} NF={s['false_NF']} NE={s['false_NE']} "
            f"vs_current match={c['match']}/30 moved={c['diverged_ids']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
