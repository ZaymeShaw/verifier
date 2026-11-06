"""案卷的展示：目录、各轴视图、结构图（案卷本身由资源类型 case_trace 组织，spec/alg/resources.md §10.2）。

The complete case file stays the single source. The organizer reads the catalog (what exists, how big,
what it is, where to read) and pulls bodies on demand through the evidence tools
(`business_trace/tools.py`); ``build_axis_view`` then renders exactly the selected material.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from impl.projects.llm_probe_loop.resources.case_trace import _text, record_body, render_value


# 下游轴从目录定位正文，初始视图保持紧凑；大请求在已批准的模型端点
# 实测连接超时，未读到的正文仍可用取证工具按需补查。
VIEW_BUDGET_CHARS = 80_000

# 单条记录的正文上限：读取与视图渲染共用同一个数。
# 不共用就会出现实测到的情形：整理员按 12k 的结构图下钻、只读了几个片段，视图却把 38.9k 整棵子树
# 倒给同一批轴（同一个节点还同时进了 4 个轴）。轴拿到的正文必须是整理员真读过的，否则证据链两头都不闭合。
EVIDENCE_NODE_CHARS = 12_000
# 整理员判断下游确实需要整段时（如整页工具回填、系统提示词）可显式申请一次完整读取，
# 轴视图就带上整段（去留仍由轴视图预算决定）；这个上限只是防止把超大节点整棵倒出。
EVIDENCE_FULL_READ_CHARS = 80_000


def node_shape(node: Any, *, max_keys: int = 60, preview_chars: int = 80) -> Any:
    """结构图：只给键名、尺寸和少量开头，让读者决定下钻到哪一支。"""
    if isinstance(node, Mapping):
        items = list(node.items())
        out = {str(key): node_shape(value, max_keys=max_keys, preview_chars=preview_chars)
               for key, value in items[:max_keys]}
        if len(items) > max_keys:
            out["..."] = f"还有 {len(items) - max_keys} 个键"
        return out
    if isinstance(node, list):
        if not node:
            return {"list": 0}
        head = [node_shape(item, max_keys=max_keys, preview_chars=preview_chars) for item in node[:3]]
        return {"list": len(node), "head": head, "chars": len(_text(node))}
    text = _text(node)
    if len(text) > preview_chars:
        return {"chars": len(text), "head": text[:preview_chars]}
    return node


def resolve_node_path(node: Any, path: str) -> Any:
    """按 /a/b/0/c 走路；路径不存在就报错（不静默给空值，那等于造假）。"""
    current = node
    for part in [piece for piece in str(path or "").split("/") if piece]:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(current, Mapping):
            if part not in current:
                raise ValueError(f"路径不存在: {path}（当前可用的键：{sorted(current)[:20]}）")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"路径不存在: {path}（列表下标越界）") from exc
        else:
            raise ValueError(f"路径不存在: {path}（{part} 之前已是叶子）")
    return current


_RENDER_KEYS = ("name", "copy_of", "parent_ref", "pairing", "representation", "ordinal", "run_id",
                "agent_run_id", "reconstructed_input", "output_message_ref", "has_model_or_tool_spans")


def _render_record(row: Mapping[str, Any], dossier: Mapping[str, Any], *, preview_chars: int | None) -> dict[str, Any]:
    rendered = {"id": row["id"], "kind": row["kind"], "turn": row.get("turn"), "scope": row.get("scope")}
    for key in _RENDER_KEYS:
        if row.get(key) is not None:
            rendered[key] = row[key]
    fields: dict[str, Any] = {}
    for name, info in (row.get("fields") or {}).items():
        field = {"status": info.get("status")}
        if info.get("note"):
            field["note"] = info["note"]
        if "value" in info:
            value = render_value(dossier, info["value"])
            text = _text(value)
            field["chars"] = len(text)
            if preview_chars is None:
                field["value"] = value
            elif preview_chars > 0:
                field["preview"] = text[:preview_chars]
        fields[name] = field
    rendered["fields"] = fields
    return rendered


def dossier_ids(dossier: Mapping[str, Any]) -> set[str]:
    ids = {row["id"] for row in dossier.get("records") or []}
    ids.update(dossier.get("contents") or {})
    ids.update(gap["id"] for gap in dossier.get("gaps") or [])
    ids.update(source["id"] for source in dossier.get("sources") or [])
    return ids


def view_ids(view: Mapping[str, Any]) -> set[str]:
    """Only rendered bodies count as evidence; a pointer or a shape is not a read."""
    ids = {row["id"] for row in view.get("records") or []
           if "fields" in row or row.get("read_paths")}
    ids.update(ident for ident, value in (view.get("contents") or {}).items()
               if not (isinstance(value, Mapping) and value.get("kind") == "evidence_slice")
               or value.get("read_paths"))
    ids.update(gap["id"] for gap in view.get("gaps") or [])
    return ids


def _compact_coverage(entry: Mapping[str, Any]) -> dict[str, Any]:
    """骨架只留「哪一轮、采集状态如何、哪类资料有多少」；详细限制/错误已由 gaps 单独登记。"""
    raw = entry.get("coverage") or {}
    categories: dict[str, Any] = {}
    for name, info in (raw.get("categories") or {}).items():
        if not isinstance(info, Mapping):
            continue
        item = {key: info.get(key) for key in ("count", "status", "copy_count") if info.get(key) is not None}
        if item:
            categories[name] = item
    limited = sorted(name for name, info in (entry.get("limitations") or {}).items()
                     if isinstance(info, Mapping) and info.get("status") not in {"complete", "available", "supported"})
    out: dict[str, Any] = {"turn": entry.get("turn"), "status": entry.get("status")}
    if categories:
        out["categories"] = categories
    if limited:
        out["limited"] = limited
    errors = [str(item)[:200] for item in (entry.get("errors") or [])][:5]
    if errors:
        out["errors"] = errors
    return {key: value for key, value in out.items() if value is not None}


def _coverage_notes(dossier: Mapping[str, Any]) -> list[str]:
    """一行的采集情况：哪一轮采到了、哪一轮失败；目录里就带上，别让整理员对着缺轮次猜。"""
    notes: list[str] = []
    for entry in dossier.get("coverage") or []:
        compact = _compact_coverage(entry)
        note = f"{compact.get('turn') or '?'} {compact.get('status') or '?'}"
        if compact.get("limited"):
            note += "（受限：" + ",".join(compact["limited"]) + "）"
        if compact.get("errors"):
            note += "（错误：" + str(compact["errors"][0])[:80] + "）"
        notes.append(note)
    return notes


def _reads_by_id(structure: Mapping[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """整理阶段留下的读取回执：视图按它决定给下游轴哪些片段。"""
    audit = (structure or {}).get("evidence_audit") if isinstance(structure, Mapping) else None
    reads: dict[str, list[dict[str, Any]]] = {}
    for item in (audit or {}).get("reads") or []:
        if isinstance(item, Mapping) and item.get("id"):
            reads.setdefault(str(item["id"]), []).append(dict(item))
    return reads


def _render_capped_record(row: Mapping[str, Any], dossier: Mapping[str, Any],
                          reads: list[dict[str, Any]]) -> dict[str, Any]:
    """超过单条上限的记录：给整理员逐字读过的那几段 + 其余部分的结构图，绝不再整棵倒出。

    轴只能引用自己看得到的内容，所以未读到的正文必须显式缺席（列在 shape / note 里），
    缺证就以缺证的形式暴露，而不是静默地让轴对没读过的部分下判断。
    """
    body = record_body(dossier, row)
    slices: dict[str, Any] = {}
    omitted: list[str] = []
    for item in reads:
        path = str(item.get("path") or "")
        if item.get("shape_only"):
            omitted.append(path or "/")
            continue
        try:
            value = resolve_node_path(body, path)
        except ValueError:
            omitted.append(path or "/")
            continue
        size = len(_text(value))
        # 整理员显式申请过完整读取的那一段按 full 上限计；其余片段仍受单条上限约束。
        limit = EVIDENCE_FULL_READ_CHARS if item.get("full") else EVIDENCE_NODE_CHARS
        if size > limit:
            omitted.append(f"{path or '/'}（{size} 字，超过单条上限）")
            continue
        slices[path or "/"] = value
    rendered: dict[str, Any] = {
        "id": row["id"], "kind": row["kind"], "turn": row.get("turn"), "scope": row.get("scope"),
        "chars": len(_text(body)), "read_paths": slices, "shape": node_shape(body),
        "note": f"本记录超过单条视图上限 {EVIDENCE_NODE_CHARS} 字：read_paths 是整理阶段逐字读过的片段"
                "（其中整理员申请完整读取的段可超过这个上限），shape 是其余部分的结构与尺寸。"
                "read_paths 之外的正文不在本视图内；需要它才能判断时按缺证处理，不要凭结构图推断内容。",
    }
    if omitted:
        rendered["not_read_here"] = omitted
    return rendered


def build_axis_view(dossier: Mapping[str, Any], selection: Mapping[str, Any], *, budget_chars: int,
                    axis_id: str = "", structure: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Render exactly the organizer's selection for one axis, in the organizer's priority order.

    Material that does not fit the axis budget stays in the case file and is listed as excluded
    so the axis must report it as missing evidence instead of judging unread material.
    """
    contents = dossier.get("contents") or {}
    sources = {source["id"]: source for source in dossier.get("sources") or []}
    rows = {row["id"]: row for row in dossier.get("records") or []}
    gaps = {gap["id"]: gap for gap in dossier.get("gaps") or []}
    reads = _reads_by_id(structure)
    refs = [str(ref) for ref in dict.fromkeys(selection.get("refs") or [])]
    selected_rows: list[dict[str, Any]] = []
    selected_gaps: list[dict[str, Any]] = []
    selected_contents: list[str] = []
    excluded: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    used = 0
    rendered_contents: dict[str, Any] = {}

    def admit(weight: int) -> bool:
        """Admit in the organizer's priority order; never silently drop, always list exclusions."""
        nonlocal used
        if used + weight > budget_chars:
            return False
        used += weight
        return True

    for ref in refs:
        if ref in rows:
            rendered = _render_record(rows[ref], dossier, preview_chars=None)
            if len(_text(rendered)) > EVIDENCE_NODE_CHARS:
                rendered = _render_capped_record(rows[ref], dossier, reads.get(ref, []))
            weight = len(_text(rendered))
            if ref in seen_rows:
                continue
            if not admit(weight):
                excluded.append({"ref": ref, "chars": weight, "reason": "超出本轴视图预算，未纳入"})
                continue
            seen_rows.add(ref)
            selected_rows.append(rendered)
            # 记录字段已经把值内联成原文，不需要再把同一段正文放进 contents（否则同一段进两次 prompt）。
        elif ref in contents or ref in sources:
            if ref in selected_contents:
                continue
            body = (render_value(dossier, {"content_ref": ref}) if ref in contents else
                    {key: render_value(dossier, sources[ref][key])
                     for key in ("request_and_response", "original_records") if sources[ref].get(key) is not None})
            if len(_text(body)) > EVIDENCE_NODE_CHARS:
                slices = {}
                for receipt in reads.get(ref, []):
                    if receipt.get("shape_only"):
                        continue
                    path = str(receipt.get("path") or "")
                    try:
                        value = resolve_node_path(body, path)
                    except ValueError:
                        continue
                    limit = EVIDENCE_FULL_READ_CHARS if receipt.get("full") else EVIDENCE_NODE_CHARS
                    if len(_text(value)) <= limit:
                        slices[path or "/"] = value
                body = {"kind": "evidence_slice", "read_paths": slices, "shape": node_shape(body),
                        "note": "只有 read_paths 是已读正文，其余内容须补查"}
            if admit(len(_text(body))):
                selected_contents.append(ref)
                rendered_contents[ref] = body
            else:
                excluded.append({"ref": ref, "chars": len(_text(body)), "reason": "超出本轴视图预算，未纳入"})
        elif ref in gaps:
            selected_gaps.append(gaps[ref])
        else:
            excluded.append({"ref": ref, "reason": "案卷中没有这个编号"})
    selected_ids = {row["id"] for row in selected_rows} | set(selected_contents) | {g["id"] for g in selected_gaps}
    timeline = {bucket: [node for node in dossier.get(bucket) or [] if node["id"] in selected_ids]
                for bucket in ("current", "history", "observed_at_collection")}
    return {
        "format": "process-dossier-view-v1", "axis": axis_id,
        # 读取回执只用来决定上面渲染哪几段原文；渲染完即离开提示词（它是编号+路径的索引，不是证据，
        # 六轴各带一份会成倍放大输入，实测还会被模型当成输出格式照抄）。
        "structure": {key: value for key, value in (structure or {}).items() if key != "evidence_audit"},
        "records": selected_rows,
        "contents": rendered_contents,
        "model_calls": [call for call in dossier.get("model_calls") or [] if call["id"] in selected_ids],
        "gaps": dossier.get("gaps") or [],
        "coverage": dossier.get("coverage"),
        **timeline,
        "excluded": excluded,
        "reading_guide": "本视图是分析轴按本轴问题从完整案卷中选出的材料，字段值为原始正文，content_ref 指向 contents。"
                         "excluded 里的编号不在初始视图内：需要时用案卷取证工具补读，仍未读到则按缺证处理。"
                         "编号可引用（records/contents 两个清单中的 id，以及 gaps 的 id）。",
    }


# 目录摘要里嵌入的正文开头上限（只够判断「这条是什么」，不足以替代正文）。
PREVIEW_CHARS = 80
# 单条摘要里每个片段的开头长度与整条摘要上限。
CATALOG_SNIPPET_CHARS = 48
CATALOG_SUMMARY_CHARS = 120
# 状态快照要把时限/工具耗时这类内层短标量写在摘要里，所以留更宽的额度。
CATALOG_STATE_SUMMARY_CHARS = 220
# 目录文本预算：超出就压缩深嵌正文行 → 按 kind 折叠明细 → 最后一档只留编号（编号一个都不能丢）。
CATALOG_BUDGET_CHARS = 48_000
# 折叠顺序：先折「采集时点的配置/状态副本」，原始记录明细最后折。
CATALOG_FOLD_ORDER = ("definitions", "sessions", "memories", "checkpoints", "events", "requirements",
                      "references", "artifacts", "states")


def _field(fields: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return fields.get(name) or {}


def _snippet(fields: Mapping[str, Any], name: str, *, limit: int = CATALOG_SNIPPET_CHARS) -> str:
    return " ".join(str(_field(fields, name).get("preview") or "").split())[:limit]


def _chars(fields: Mapping[str, Any], name: str) -> int:
    return int(_field(fields, name).get("chars") or 0)


def _short_label(row: Mapping[str, Any]) -> str:
    """记录的一行身份：目录条目与外置正文的「宿主」共用同一套叫法。"""
    kind = str(row.get("kind") or "")
    if kind == "messages":
        return f"消息#{row.get('ordinal')} {row.get('role') or ''}".strip()
    if kind == "runs":
        return f"运行 {row.get('name') or ''}".strip()
    if kind == "steps":
        return f"步骤 {row.get('name') or ''}".strip()
    if kind == "tool_calls":
        return f"工具 {row.get('name') or ''}".strip()
    if kind == "model_calls":
        return "模型调用"
    if kind == "reasoning":
        return "模型推理"
    if kind == "states":
        return "会话状态"
    if kind == "sessions":
        return "会话快照"
    if kind == "definitions":
        return f"定义 {row.get('name') or ''}".strip()
    if kind in {"final_output", "delivered_output"}:
        return "调用方实收输出" if kind == "delivered_output" else "运行落库输出"
    return kind or "记录"


_STATE_HINT_TIERS = (("ceiling", "timeout", "deadline"),
                    ("tool_metrics", "tool_call_counts"),
                    ("latency", "duration", "elapsed"),
                    ("limit", "tool"))


def _state_highlights(fields: Mapping[str, Any], *, limit: int = 3) -> list[str]:
    """状态快照里的短标量（时限/工具耗时/计数）：只提取现成字段，不解读含义。

    实测教训：只写「顶层键 budget/route」时，侦探不会去取这个几万字的状态快照，
    而工具耗时与时限上限就在里面——下游工具轴因此报缺证。
    """

    def rank(name: str) -> int:
        for tier, words in enumerate(_STATE_HINT_TIERS):
            if any(word in name for word in words):
                return tier
        return len(_STATE_HINT_TIERS)

    scored: list[tuple[int, int, int, str, str]] = []
    for name, info in fields.items():
        if "." not in name:
            continue
        preview = " ".join(str(info.get("preview") or "").split())
        if not preview or len(preview) > 80:
            continue
        tier = rank(name)
        # 工具耗时/计数表本身就是 JSON，不能当「没用的 JSON 片段」排下去；其余字段优先给非 JSON 开头。
        blob = 0 if (tier <= 1 or not preview.startswith(("{", "["))) else 1
        scored.append((tier, blob, len(preview), name, preview[:40]))
    scored.sort()
    return [f"{name}={preview}" for _, _, _, name, preview in scored[:limit]]


def _entry_summary(row: Mapping[str, Any], fields: Mapping[str, Any], *,
                   host: Mapping[str, Any] | None = None, body: Any = None) -> str:
    """按类别从结构化字段提取一行语义摘要：只提取（名字/状态/耗时/大小/引用关系/正文开头），不总结不评判。"""
    kind = str(row.get("kind") or "")
    parts: list[str] = []
    if kind == "runs":
        parts = [f"运行 {row.get('name') or ''}", _snippet(fields, "status", limit=24)]
        if _snippet(fields, "input"):
            parts.append("输入：" + _snippet(fields, "input", limit=32))
        parts.append(f"输出 {_chars(fields, 'output')} 字")
    elif kind == "steps":
        parts = [f"步骤 {row.get('name') or ''}", f"success={_snippet(fields, 'success', limit=8)}"]
        if row.get("executor_name"):
            parts.append(f"executor={row['executor_name']}")
        parts.append(f"输出 {_chars(fields, 'output')} 字")
        if _snippet(fields, "output"):
            parts.append("开头：" + _snippet(fields, "output"))
    elif kind == "messages":
        who = str(row.get("role") or "")
        parts = [f"消息#{row.get('ordinal')} {who}".strip(), f"{_chars(fields, 'content')} 字"]
        if str(_field(fields, "from_history").get("preview") or "").strip() == "true":
            parts.append("[历史注入]")
        if _snippet(fields, "content"):
            parts.append("开头：" + _snippet(fields, "content"))
    elif kind == "reasoning":
        parts = ["模型推理", f"{_chars(fields, 'text')} 字"]
        if _snippet(fields, "text"):
            parts.append("开头：" + _snippet(fields, "text"))
    elif kind == "tool_calls":
        parts = [f"工具 {row.get('name') or ''}"]
        if _snippet(fields, "arguments", limit=40):
            parts.append("参数 " + _snippet(fields, "arguments", limit=40))
        parts.append(f"返回 {_chars(fields, 'result')} 字")
        parts.append(f"error={_snippet(fields, 'error', limit=8)}")
    elif kind == "states":
        top = sorted(name for name in fields if "." not in name)
        parts = ["会话状态（持久化快照，不是变化日志）", "顶层键 " + "/".join(top)]
        highlights = _state_highlights(fields)
        if highlights:
            parts.append("含 " + " · ".join(highlights))
    elif kind == "model_calls":
        parts = [f"模型调用 {_snippet(fields, 'model', limit=32) or row.get('name') or ''}",
                 _snippet(fields, "status", limit=8),
                 f"输入 {_snippet(fields, 'input_tokens', limit=8)} tok",
                 f"输出 {_snippet(fields, 'output_tokens', limit=8)} tok",
                 f"{_snippet(fields, 'duration_ms', limit=8)} ms"]
        reconstructed = (row.get("reconstructed_input") or {}).get("status")
        if reconstructed:
            parts.append(f"重建输入 {reconstructed}")
    elif kind == "sessions":
        parts = ["会话快照（采集时点）", f"{sum(int(i.get('chars') or 0) for i in fields.values())} 字",
                 "含 " + "/".join(sorted(fields))]
    elif kind == "definitions":
        parts = [f"定义 {row.get('name') or ''}（{row.get('definition_type') or 'definition'}）",
                 f"{sum(int(i.get('chars') or 0) for i in fields.values())} 字"]
    elif kind in {"final_output", "delivered_output"}:
        parts = [_short_label(row), f"{_chars(fields, 'output')} 字"]
        if _snippet(fields, "output"):
            parts.append("开头：" + _snippet(fields, "output"))
    elif kind == "content":
        text = _text(body)
        if host:
            where = f"{host.get('label')} 的 {host.get('path')} 正文" if host.get("path") else f"{host.get('label')} 的正文"
            extra = f"（共 {host['count']} 处引用）" if int(host.get("count") or 1) > 1 else ""
            if int(host.get("depth") or 0) > 0:
                # 深嵌正文块（在另一块正文里）：取回宿主那一块时自然就能拿到，这里只留编号与去处。
                parent = host.get("parent") or host.get("host")
                where = f"{host.get('label')} 的 {host.get('path')}" if host.get("path") else str(host.get("label"))
                parts = [f"{where}（嵌在 {parent} 里，取回它即可读到）"]
            else:
                parts = [where + extra]
                head = " ".join(text.split())[:CATALOG_SNIPPET_CHARS]
                if head:
                    parts.append("开头：" + head)
        else:
            parts = ["未被记录字段引用的正文块"]
            head = " ".join(text.split())[:CATALOG_SNIPPET_CHARS]
            if head:
                parts.append("开头：" + head)
    elif kind == "source":
        body_map = row.get("request_and_response") or {}
        parts = ["本轮原始请求与响应", f"{len(_text(body_map))} 字"]
    elif kind == "gap":
        parts = [f"缺口（{row.get('status') or 'gap'}）", str(row.get("reason") or "")[:80]]
    else:
        parts = [kind]
        for name, info in fields.items():
            if str(info.get("preview") or "").strip():
                parts.append(f"{name}={_snippet(fields, name, limit=24)}")
                break
    # scope 标记已在目录行上（_catalog_line），摘要里不重复。
    if row.get("copy_of"):
        parts.append(f"与 {row['copy_of']} 同源副本")
    if row.get("problems"):
        parts.append("字段异常 " + ",".join(f"{k}×{v}" for k, v in sorted(row["problems"].items())))
    limit = CATALOG_STATE_SUMMARY_CHARS if kind == "states" else CATALOG_SUMMARY_CHARS
    return " | ".join(part for part in parts if part)[:limit]


def _content_hosts(dossier: Mapping[str, Any]) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[tuple[str, str]]]]:
    """内容块的外置寄存是棵树：这里建「子 → 父」与「直接宿主」两张表，供目录写宿主语义摘要。"""

    def refs_in(value: Any, path: str) -> list[tuple[str, str]]:
        if isinstance(value, Mapping):
            if set(value) == {"content_ref"}:
                return [(str(value["content_ref"]), path)]
            found: list[tuple[str, str]] = []
            for key, child in value.items():
                found.extend(refs_in(child, f"{path}/{key}"))
            return found
        if isinstance(value, list):
            found = []
            for index, child in enumerate(value):
                found.extend(refs_in(child, f"{path}/{index}"))
            return found
        return []

    roots: dict[str, list[tuple[str, str]]] = {}
    parents: dict[str, list[tuple[str, str]]] = {}
    for row in dossier.get("records") or []:
        for name, info in (row.get("fields") or {}).items():
            if "value" not in info:
                continue
            for ident, path in refs_in(info["value"], f"fields/{name}"):
                roots.setdefault(ident, []).append((str(row["id"]), path))
    for source in dossier.get("sources") or []:
        for name in ("request_and_response", "original_records"):
            for ident, path in refs_in(source.get(name), name):
                roots.setdefault(ident, []).append((str(source["id"]), path))
    for ident, body in (dossier.get("contents") or {}).items():
        for child, path in refs_in(body, ""):
            if child != ident:
                parents.setdefault(child, []).append((str(ident), path))
    return roots, parents


def _content_host(ident: str, roots: Mapping[str, list[tuple[str, str]]],
                  parents: Mapping[str, list[tuple[str, str]]], labels: Mapping[str, str],
                  *, max_depth: int = 6) -> dict[str, Any] | None:
    """向上走到最近的宿主记录：把「这是一块正文」变成「这是谁的什么字段的正文」。"""
    frontier = [(ident, "", 0)]
    seen = {ident}
    while frontier:
        current, suffix, depth = frontier.pop(0)
        if current in roots:
            host_id, path = roots[current][0]
            parent = parents.get(ident, [(None, "")])[0][0] if depth > 0 else None
            return {"host": host_id, "label": labels.get(host_id, host_id),
                    "path": (path + suffix).lstrip("/"), "count": len(roots[current]), "depth": depth,
                    "parent": parent}
        if depth >= max_depth:
            continue
        for parent, path in parents.get(current, []):
            if parent in seen:
                continue
            seen.add(parent)
            frontier.append((parent, path + suffix, depth + 1))
    # 宿主也是内容块：深嵌正文只留编号与去处，明细在宿主那一块里。
    if parents.get(ident):
        parent = parents[ident][0][0]
        return {"host": parent, "label": labels.get(parent, parent), "path": "",
                "count": len(parents[ident]), "depth": 1, "parent": parent}
    return None


def build_catalog(dossier: Mapping[str, Any], *, preview_chars: int = PREVIEW_CHARS) -> dict[str, Any]:
    """Index-only rendering of the case file: what exists, how big, what it is, where to read it.

    Bodies stay exactly where they are (records.fields.value / contents); the catalog carries a
    one-line program-generated summary per citable number (name/status/size/referrers/first words)
    and never rewrites evidence. Every number the case file can be cited by stays listed, so a
    reader reaches any of them through list -> collect/read.
    """
    stamps: dict[str, Any] = {}
    for bucket in ("current", "history", "observed_at_collection"):
        for node in dossier.get(bucket) or []:
            stamps.setdefault(node.get("id"), node.get("at"))
    rows = list(dossier.get("records") or [])
    labels = {str(row["id"]): _short_label(row) for row in rows}
    labels.update({str(source["id"]): "本轮原始请求响应" for source in dossier.get("sources") or []})
    labels.update({str(gap["id"]): "缺口" for gap in dossier.get("gaps") or []})
    contents = dict(dossier.get("contents") or {})
    roots, parents = _content_hosts(dossier)
    entries: list[dict[str, Any]] = []
    for row in rows:
        rendered = _render_record(row, dossier, preview_chars=preview_chars)
        fields = rendered.get("fields") or {}
        available = sum(1 for info in fields.values() if str(info.get("status")) == "available")
        problems: dict[str, int] = {}
        for info in fields.values():
            key = str(info.get("status"))
            if key != "available":
                problems[key] = problems.get(key, 0) + 1
        entry: dict[str, Any] = {
            "id": row["id"], "kind": row["kind"], "turn": row.get("turn"),
            "chars": sum(int(info.get("chars") or 0) for info in fields.values()),
            "fields": f"{available}/{len(fields)}",
        }
        if row.get("copy_of"):
            entry["copy_of"] = row["copy_of"]
        if row.get("scope") == "history":
            entry["scope"] = "history"
        if problems:
            entry["problems"] = problems
        if stamps.get(row["id"]) is not None:
            entry["at"] = stamps[row["id"]]
        entry["summary"] = _entry_summary({**row, **entry}, fields)
        entries.append(entry)
    for ident, body in contents.items():
        host = _content_host(ident, roots, parents, labels)
        entry = {"id": ident, "kind": "content", "turn": None, "chars": len(_text(body))}
        if host:
            entry["host"] = host["host"]
            entry["host_path"] = host["path"]
            entry["depth"] = host["depth"]
            if host.get("parent"):
                entry["parent"] = host["parent"]
        entry["summary"] = _entry_summary(entry, {}, host=host, body=body)
        entries.append(entry)
    for source in dossier.get("sources") or []:
        entry = {"id": source["id"], "kind": "source", "turn": source.get("turn"), "chars": 0,
                 "request_and_response": source.get("request_and_response")}
        entry["summary"] = _entry_summary(entry, {})
        entries.append(entry)
    for gap in dossier.get("gaps") or []:
        entry = {"id": gap["id"], "kind": "gap", "turn": None, "chars": 0,
                 "status": gap.get("status"), "reason": str(gap.get("reason") or "")}
        entry["summary"] = _entry_summary(entry, {})
        entries.append(entry)
    kinds: dict[str, dict[str, Any]] = {}
    for entry in entries:
        info = kinds.setdefault(str(entry["kind"]), {"count": 0, "chars": 0})
        info["count"] += 1
        info["chars"] += int(entry.get("chars") or 0)
    return {
        "format": "process-dossier-catalog-v1",
        "budget_chars": CATALOG_BUDGET_CHARS,
        "stats": {"records": len(rows), "contents": len(contents),
                  "dossier_chars": len(json.dumps(dossier, ensure_ascii=False))},
        "coverage": _coverage_notes(dossier),
        "entries": entries,
        "kinds": kinds,
        "reading_guide": "目录每条 = 编号 + 一行程序摘要（名字/状态/大小/宿主/开头），只登记有什么、是什么、多大、在哪；"
                         "正文不在目录里，要用工具按编号取（可一次取多个）。摘要里的「开头：」是正文首句，不是全文。"
                         "content#N 是外置寄存的正文块，摘要里的宿主说明它属于哪条记录的哪个字段。",
    }


def catalog_ids(catalog: Mapping[str, Any]) -> set[str]:
    return {str(entry["id"]) for entry in catalog.get("entries") or []}


def _catalog_line(entry: Mapping[str, Any]) -> str:
    scope = " [历史轮]" if entry.get("scope") == "history" else ""
    return f"{entry['id']}{scope} · {int(entry.get('chars') or 0)}字 · {entry.get('summary') or ''}"


def _nested_block_lines(parent: str, entries: Sequence[Mapping[str, Any]], *, per_line: int = 40) -> list[str]:
    """深嵌正文块按直接宿主归并：编号一个不少（分行列出），明细在宿主那一块里。"""
    ids = [str(entry["id"]) for entry in entries]
    lines = [f"{parent} 内的深嵌正文块 {len(ids)} 块（取回 {parent} 就能读到）："]
    for start in range(0, len(ids), per_line):
        lines.append("    " + " ".join(ids[start:start + per_line]))
    return lines


def render_catalog(catalog: Mapping[str, Any], *, budget_chars: int | None = None) -> str:
    """把目录渲染成一段紧凑文本：按轮次/类别分组；超预算就压缩深嵌正文行、再按 CATALOG_FOLD_ORDER 折叠明细。"""
    budget = int(budget_chars or catalog.get("budget_chars") or CATALOG_BUDGET_CHARS)
    entries = [dict(entry) for entry in catalog.get("entries") or []]
    kinds: dict[str, dict[str, Any]] = {}
    for entry in entries:
        info = kinds.setdefault(str(entry["kind"]), {"count": 0, "chars": 0})
        info["count"] += 1
        info["chars"] += int(entry.get("chars") or 0)
    header = [f"案卷目录：{int(catalog.get('stats', {}).get('records') or 0)} 条记录 + "
              f"{int(catalog.get('stats', {}).get('contents') or 0)} 块外置正文；完整案卷 "
              f"{int(catalog.get('stats', {}).get('dossier_chars') or 0)} 字；"
              + " · ".join(f"{kind} {info['count']}" for kind, info in kinds.items())]
    if catalog.get("coverage"):
        header.append("采集：" + " · ".join(str(item) for item in catalog["coverage"]))
    guide = str(catalog.get("reading_guide") or "")
    if guide:
        header.append("说明：" + guide)
    groups: list[tuple[Any, str]] = []
    for entry in entries:
        key = (entry.get("turn"), str(entry["kind"]))
        if key not in groups:
            groups.append(key)

    def render(folded: set[str], ids_only: bool = False) -> list[str]:
        lines: list[str] = list(header)
        for turn, kind in groups:
            group = [entry for entry in entries if (entry.get("turn"), str(entry["kind"])) == (turn, kind)]
            if kind in folded or ids_only:
                lines.append(f"[{turn or '案卷'}] {kind}（{len(group)} 条明细已折叠，编号仍可引用）："
                             + " ".join(str(entry["id"]) for entry in group))
                continue
            lines.append(f"[{turn or '案卷'}] {kind}")
            nested: dict[str, list[Mapping[str, Any]]] = {}
            for entry in group:
                if int(entry.get("depth") or 0) > 0:
                    nested.setdefault(str(entry.get("parent") or entry.get("host") or "?"), []).append(entry)
                    continue
                lines.append("  " + _catalog_line(entry))
            for parent, block in nested.items():
                lines.extend("  " + line for line in _nested_block_lines(parent, block))
        return lines

    def size(lines: list[str]) -> int:
        return sum(len(line) + 1 for line in lines)

    folded: set[str] = set()
    lines = render(folded)
    for kind in CATALOG_FOLD_ORDER:
        if size(lines) <= budget:
            break
        if any(str(entry["kind"]) == kind for entry in entries):
            folded.add(kind)
            lines = render(folded)
    if size(lines) > budget:
        # 最后一档：只留编号（编号一个都不能丢），摘要让位给预算。
        lines = render(folded, ids_only=True)
    return "\n".join(lines)
