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
            return {"shared_ref": value["content_ref"]}
        return {k: _share(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_share(v) for v in value]
    return value


def _supporting_definitions(rows: Mapping[str, Any], links: list[Mapping[str, Any]]) -> list[str]:
    """Keep applicable declarations with their recorded version provenance."""
    non_model = [link for link in links if link["link_type"] != "μ"]
    turns = {link.get("turn") for link in non_model}
    names = {rows[end["ref"]].get("name") for link in non_model for side in ("input", "output")
             for end in link[side] if end["ref"] in rows}
    # Workflow/agent definitions own the branch rules and tool configuration.
    names.update(r.get("name") for r in rows.values() if r.get("kind") == "runs" and r.get("turn") in turns)
    return [ref for ref, row in rows.items() if row.get("kind") == "definitions"
            and row.get("turn") in turns and row.get("name") in names and row.get("name")]


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
                if not suspect["link_id"].startswith("μ:"):
                    fields.setdefault(ref, set()).add("")
    for ref in [*extra_refs, *_supporting_definitions(rows, links)]:
        fields.setdefault(ref, set()).add("")
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
    for ref, requested in fields.items():
        row = rows.get(ref)
        if row is None:
            if ref in contents or ref in sources:
                value = expand_content(contents[ref] if ref in contents else sources[ref], contents)
                extras[ref] = pool.add(value)
                reads.append({"id": ref, "path": "", "full": True, "shape_only": False,
                              "chars": len(json.dumps(value, ensure_ascii=False))})
            continue
        names = set(row.get("fields", {})) if "" in requested else requested
        rendered = {k: v for k, v in row.items() if k != "fields"}
        rendered["fields"] = {}
        for name in sorted(names):
            if name not in row.get("fields", {}):
                continue
            info = dict(row["fields"][name])
            if "value" in info:
                value = expand_content(info["value"], contents)
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
    return {"format": "axis-materials-v1", "records": _share(records), "contents": _share(extras),
            "shared_contents": _share(pool.values), "gaps": dossier.get("gaps", []), "missing_endpoints": missing,
            "reads": reads, "excluded": [], "input_limitations": limitations,
            "reading_guide": "分析轴交付的环节材料。shared_ref 递归指向 shared_contents 中的完整正文，仅去重、不摘要、不截断。"
                             "引用 records 的 id 或 contents 的编号；shared_ref 不是独立证据编号。未记录的端点列在 missing_endpoints。"
                             "μ 只按该环节实际输入中的信息判；其他调用中出现的信息不代表本次模型知道。"
                             "scope=observed_at_collection_not_verified_run_version 的定义仅是采集时背景；不能据此证明当次收到规则或违反当次配置。"}


def prepare_axis_materials(dossier: Mapping[str, Any], links: list[Mapping[str, Any]],
                           suspects: list[Mapping[str, Any]], *, extra_refs: list[str] = (),
                           target_chars: int = VIEW_BUDGET_CHARS) -> list[dict[str, Any]]:
    """Partition between links, never through an actual request or output."""
    batches, pending = [], []
    for link in links:
        candidate = pending + [link]
        view = material_view(dossier, candidate, suspects, extra_refs=extra_refs)
        if pending and len(json.dumps(model_material(view), ensure_ascii=False)) > target_chars:
            batches.append({"links": pending, "view": material_view(dossier, pending, suspects, extra_refs=extra_refs)})
            pending = [link]
        else:
            pending = candidate
    if pending:
        batches.append({"links": pending, "view": material_view(dossier, pending, suspects, extra_refs=extra_refs)})
    for batch in batches:
        batch["chars"] = len(json.dumps(model_material(batch["view"]), ensure_ascii=False))
        batch["oversize"] = batch["chars"] > target_chars
    return batches
