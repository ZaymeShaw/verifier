"""Analysis-owned endpoint delivery; share duplicate bodies, never summarize them.

The batch target bounds grouping, not individual evidence: an indivisible link
larger than the target stays whole and is explicitly marked oversize.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .dossier import VIEW_BUDGET_CHARS, _Contents, expand_content


def _share(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"content_ref"}:
            return {"shared_ref": value["content_ref"].replace("content#", "shared#", 1)}
        return {k: _share(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_share(v) for v in value]
    return value


def _supporting_definitions(rows: Mapping[str, Any], links: list[Mapping[str, Any]]) -> list[str]:
    """Keep applicable declarations with their recorded version provenance."""
    non_model = [link for link in links if link["link_type"] != "model_capability"]
    turns = {link.get("turn") for link in non_model}
    names = {rows[end["ref"]].get("name") for link in non_model for side in ("input", "output")
             for end in link[side] if end["ref"] in rows}
    # Workflow/agent definitions own the branch rules and tool configuration.
    names.update(r.get("name") for r in rows.values() if r.get("kind") == "runs" and r.get("turn") in turns)
    return [ref for ref, row in rows.items() if row.get("kind") == "definitions"
            and row.get("turn") in turns and row.get("name") in names and row.get("name")]


def _source_overlaps(row: Mapping[str, Any], names: set[str]) -> tuple[set[str], dict[str, list[str]]]:
    """Lossless de-duplication inside one record, by recorded source pointer only.

    A field whose source pointer equals an earlier field's is the same body (e.g.
    ``exact_request`` decoded from ``input``): deliver it once. A container field
    (``raw_attributes``) keeps only the keys no delivered named field already carries.
    """
    fields = row.get("fields", {})
    seen, same, carried = {}, set(), {}
    # exact_request is the decoded request; prefer it over a raw copy of the same source.
    for name in sorted(names, key=lambda n: (n != "exact_request", n)):
        src = (fields.get(name) or {}).get("ref")
        if src and src in seen:
            same.add(name)
        elif src:
            seen[src] = name
    for name in names - same:
        src = (fields.get(name) or {}).get("ref")
        if not src:
            continue
        # seen: source pointer -> field name. Children of this container's pointer are
        # bodies another named field already delivers.
        keys = [child_src[len(src) + 1:] for child_src, child in seen.items()
                if child != name and child_src.startswith(src + "/")]
        if keys:
            carried[name] = keys
    return same, carried


def _strings(value: Any) -> list[str]:
    """String leaves, with JSON-in-string envelopes decoded (the same body in two encodings)."""
    if isinstance(value, str):
        try:
            inner = json.loads(value)
        except ValueError:
            return [value]
        return [value, *_strings(inner)] if isinstance(inner, (dict, list)) else [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def model_material(view: Mapping[str, Any]) -> dict[str, Any]:
    """Read-path receipts belong to the audit, not the judge's evidence prompt."""
    return {key: value for key, value in view.items() if key != "reads"}


def material_view(dossier: Mapping[str, Any], links: list[Mapping[str, Any]],
                  suspects: list[Mapping[str, Any]], *, extra_refs: list[str] = ()) -> dict[str, Any]:
    rows = {r["id"]: r for r in dossier.get("records", [])}
    sources = {r["id"]: r for r in dossier.get("sources", [])}
    contents = dossier.get("contents", {})
    fields: dict[str, set[str]] = {}
    missing, limitations = [], []
    for link in links:
        for side in ("input", "output"):
            ends = link[side]
            if not ends and not link["link_id"].endswith(":none"):
                missing.append({"link_id": link["link_id"], "side": side, "reason": "未记录端点"})
            for end in ends:
                ref, field = end["ref"], end.get("field", "")
                fields.setdefault(ref, set()).add(field)
                row = rows.get(ref)
                info = ((row or {}).get("fields") or {}).get(field)
                known = row is not None or ref in contents or ref in sources
                definition = row and row.get("kind") == "definitions" and field == "definition"
                if definition:
                    fields[ref] = {""}
                if row and row.get("scope") == "observed_at_collection_not_verified_run_version":
                    limitations.append({"link_id": link["link_id"], "ref": ref, "reason": "仅采集时定义，未经核对是否为本次执行版本，不能证明本次模型收到该规则"})
                tool_calls = ((row or {}).get("fields", {}).get("tool_calls") or {})
                tool_only = field == "content" and tool_calls.get("status") == "available" and bool(tool_calls.get("value"))
                if not known or (field and not tool_only and not definition and (not info or "value" not in info or info.get("status") not in {"available", "empty"})):
                    missing.append({"link_id": link["link_id"], "side": side, "ref": ref, "field": field,
                                    "reason": (info or {}).get("note") or "端点正文未记录"})
                # Text alone omits the assistant's tool calls and tool response context.
                if row and row.get("kind") == "messages":
                    fields[ref].update(row.get("fields", {}))
                if row and field == "exact_request":
                    fields[ref].add("invocation_parameters")
    link_ids = {l["link_id"] for l in links}
    for suspect in suspects:
        if suspect.get("link_id") in link_ids:
            for ref in suspect.get("source_refs", []):
                # A model call is judged against its own input. An external suspect
                # source is a lead, not permission to add unseen rules to that input.
                if not suspect["link_id"].startswith("model_capability:"):
                    fields.setdefault(ref, set()).add("")
    for ref in [*extra_refs, *_supporting_definitions(rows, links)]:
        fields.setdefault(ref, set()).add("")
    # Planning and knowledge judge against rules the model actually received that turn:
    # collection-time definitions alone can never be confirmed as this run's version.
    turns = {(l.get("turn") or "").replace("turn", "t", 1) for l in links if l["link_type"] in {"planning_routing", "knowledge_data"}}
    for row in rows.values():
        if turns and row.get("kind") == "model_calls" and (row.get("turn") or "").replace("turn", "t", 1) in turns:
            fields.setdefault(row["id"], set()).add("exact_request")
    details = {"tool_description", "metrics", "start_time", "end_time", "duration_ms", "error", "status", "status_code", "status_message"}
    for ref in list(fields):
        row = rows.get(ref)
        if row and row.get("kind") == "tool_calls":
            fields[ref].update(details.intersection(row.get("fields", {})))
            # A paired TOOL span is the same call captured at another boundary.
            span = rows.get(row.get("span_ref"))
            if span:
                fields.setdefault(span["id"], set()).update(details.intersection(span.get("fields", {})))
    pool = _Contents()
    records, reads, extras = [], [], {}
    delivered: dict[str, str] = {}  # raw body -> record field that already carries it
    standalone = []
    for ref, requested in fields.items():
        row = rows.get(ref)
        if row is None:
            if ref in contents or ref in sources:
                standalone.append(ref)
            continue
        names = set(row.get("fields", {})) if "" in requested else requested
        names &= set(row.get("fields", {}))
        tools_key = "exact_request" in requested
        same, carried = _source_overlaps(row, names)
        if tools_key:  # llm.tools* is delivered below as captured_tool_definitions
            carried.setdefault("raw_attributes", []).append("llm.tools")
        rendered = {k: v for k, v in row.items() if k != "fields"}
        rendered["fields"] = {}
        for name in sorted(names):
            info = dict(row["fields"][name])
            if "value" in info:
                delivered.setdefault(json.dumps(expand_content(info["value"], contents), ensure_ascii=False, sort_keys=True),
                                     f"{ref}/fields/{name}")
            if name in same:
                rendered["fields"][name] = {"status": info.get("status"), "ref": info.get("ref"),
                                            "same_as": next(n for n in names - same if row["fields"][n].get("ref") == info.get("ref"))}
                continue
            if "value" in info:
                value = expand_content(info["value"], contents)
                if name in carried and isinstance(value, dict):
                    covered = tuple(carried[name])
                    # Flattened copies (e.g. llm.input_messages.0.message.content) of text that a
                    # delivered sibling field already contains verbatim are the same body again.
                    siblings = [t for other in names - same - {name} if "value" in row["fields"][other]
                                for t in _strings(expand_content(row["fields"][other]["value"], contents))]
                    dropped = sorted(k for k in value if any(k == c or k.startswith(c + ".") for c in covered)
                                     or (isinstance(value[k], str) and len(value[k]) >= 40
                                         and any(value[k] in t for t in siblings)))
                    if dropped:
                        value = {k: v for k, v in value.items() if k not in dropped}
                        info["omitted_keys_delivered_elsewhere"] = dropped
                reads.append({"id": ref, "path": f"/fields/{name}/value", "chars": len(json.dumps(value, ensure_ascii=False)),
                              "full": True, "shape_only": False})
                # Decode only the transport envelope; every message string, tool
                # result and model output remains byte-for-byte the stored value.
                if name == "exact_request" and isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                    except ValueError:
                        pass
                    else:
                        if isinstance(parsed, (dict, list)):
                            value = parsed
                            info["encoding"] = "JSON request envelope decoded; message values unchanged"
                info["value"] = pool.add(value)
            rendered["fields"][name] = info
        if "exact_request" in requested:
            raw = (row.get("fields", {}).get("raw_attributes") or {}).get("value")
            attrs = expand_content(raw, contents)
            definitions = {k: v for k, v in (attrs or {}).items() if k == "llm.tools" or k.startswith("llm.tools.")} if isinstance(attrs, dict) else {}
            if definitions:
                rendered["captured_tool_definitions"] = pool.add(definitions)
                for key, value in definitions.items():
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    reads.append({"id": ref, "path": f"/fields/raw_attributes/value/{escaped}",
                                  "chars": len(json.dumps(value, ensure_ascii=False)), "full": True,
                                  "shape_only": False})
        records.append(rendered)
    for ref in standalone:
        value = expand_content(contents[ref] if ref in contents else sources[ref], contents)
        # A dossier content that is byte-identical to a delivered field is pointed at, not resent.
        same_field = delivered.get(json.dumps(value, ensure_ascii=False, sort_keys=True))
        extras[ref] = {"same_as": same_field} if same_field else pool.add(value)
        reads.append({"id": ref, "path": "", "full": True, "shape_only": False,
                      "chars": len(json.dumps(value, ensure_ascii=False))})
    return {"format": "axis-materials-v1", "records": _share(records), "contents": _share(extras),
            "shared_contents": {key.replace("content#", "shared#", 1): _share(value)
                                for key, value in pool.values.items()}, "gaps": dossier.get("gaps", []), "missing_endpoints": missing,
            "reads": reads, "excluded": [], "input_limitations": limitations,
            "reading_guide": "分析轴交付的环节材料。shared_ref 递归指向 shared_contents 中的完整正文，仅去重、不摘要、不截断。"
                             "引用 records 的 id 或 contents 的编号；shared_ref 不是独立证据编号。未记录的端点列在 missing_endpoints。"
                             "model_capability 只按该环节实际输入中的信息判；其他调用中出现的信息不代表本次模型知道。"
                             "scope=observed_at_collection_not_verified_run_version 的定义仅是采集时背景；不能据此证明当次收到规则或违反当次配置。"
                             "字段写 same_as 表示正文与同一记录的另一字段为同一来源、已在那里完整交付；"
                             "contents 中写 same_as 表示该编号正文与所指字段逐字相同。两者都不是缺失，可以照常引用原编号。"
                             "omitted_keys_delivered_elsewhere 列出容器字段里因已由其他字段完整交付而省略的键。"}


def prepare_axis_materials(dossier: Mapping[str, Any], links: list[Mapping[str, Any]],
                           suspects: list[Mapping[str, Any]], *, extra_refs: list[str] = (),
                           target_chars: int = VIEW_BUDGET_CHARS) -> list[dict[str, Any]]:
    """Partition between links, never through an actual request or output.

    The selected extra refs ride along with every batch, so the target bounds only the
    link-specific material on top of them; otherwise a large shared selection would force
    one link per batch and resend the same shared bodies each time.
    """
    shared = len(json.dumps(model_material(material_view(dossier, [], suspects, extra_refs=extra_refs)),
                            ensure_ascii=False))
    batches, pending = [], []
    for link in links:
        candidate = pending + [link]
        view = material_view(dossier, candidate, suspects, extra_refs=extra_refs)
        if pending and len(json.dumps(model_material(view), ensure_ascii=False)) - shared > target_chars:
            batches.append({"links": pending, "view": material_view(dossier, pending, suspects, extra_refs=extra_refs)})
            pending = [link]
        else:
            pending = candidate
    if pending:
        batches.append({"links": pending, "view": material_view(dossier, pending, suspects, extra_refs=extra_refs)})
    for batch in batches:
        batch["chars"] = len(json.dumps(model_material(batch["view"]), ensure_ascii=False))
        batch["oversize"] = batch["chars"] - shared > target_chars
    return batches
