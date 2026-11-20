"""侦探交的发现：环节编号在表里、新环节有端点、位置地址存在且都是读过的（spec/alg/axis_loop.md §12.2.2、resources.md §10.6–§11）。"""
import json

from impl.projects.llm_probe_loop.process_axes import TRACE, _uri_pair, check_analysis


def _field_from_path(path: str) -> str:
    parts = [p for p in str(path or "").strip("/").split("/") if p]
    return parts[1] if len(parts) >= 2 and parts[0] == "fields" else ""


def _read_targets(view) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = {(r, "") for r in (view.resources.inlined if view.resources is not None else ())}
    for c in view.calls:
        if c.tool != "read_material" or c.is_error:
            continue
        parsed = None
        if c.text:
            try:
                parsed = json.loads(c.text)
            except ValueError:
                parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
            for item in parsed["records"]:
                if isinstance(item, dict) and "error" not in item and item.get("id"):
                    rid = str(item["id"])
                    path = str(item.get("path") or "").strip("/")
                    targets.add((rid, _field_from_path(path) if path.startswith("fields/") else ""))
        else:
            arg_field = _field_from_path(str(c.args.get("path") or ""))
            for raw in c.args.get("ids") or ():
                rec, fld = _uri_pair(str(raw))
                targets.add((rec, fld or arg_field))
    return targets


def check(view):
    return check_analysis(view.materials[TRACE], view.own, _read_targets(view))
