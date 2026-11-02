"""llm_probe 资料工具箱（孵化实现；成熟且有第二个消费项目后再评估晋升 core）。

设计合同（impl/protocols/materials.md「Material toolbox」）：
- 工具只读、逐调用出回执（receipt）、只准查传入范围内的资料；
- locator 统一为行区间 ``L<start>-L<end>``——结构骨架条目也翻译成行区间，
  机械核验的底座不挑格式；
- 格式处理器按格式触发（python / yaml / markdown / 行块兜底），只认格式不认项目；
- 没有结构化切片方案的格式诚实降级：行块地图 + 词法检索，outline 会明说。
"""
from __future__ import annotations

import ast
import re
from typing import Any, Callable, Dict, List, Mapping, Sequence

from impl.core.materials_store import read_content

MAX_OUTLINE_ENTRIES = 200
MAX_SEARCH_HITS = 8
SEARCH_CONTEXT_LINES = 3
MAX_SNIPPET_CHARS = 6_000
MAX_READ_LINES = 120
MAX_VERIFY_LINES = 400

_LOCATOR = re.compile(r"^L(\d+)(?:-L(\d+))?$")
_TOP_KEY = re.compile(r"^([A-Za-z_][\w.-]*):")
_LIST_ID = re.compile(r"^(\s+)-\s+(?:id|name|field|key|slot_id)\s*:\s*(\S+)")
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
# 大常量（dict 字面量）跨度超过单次精读上限时，按顶层 key 展开二级条目。
_PY_CONST_SPLIT_LINES = MAX_READ_LINES
_PY_DOC_LABEL_CHARS = 40


def material_uri(project_id: str, material_id: str) -> str:
    return f"material://{project_id}/{material_id}"


def parse_locator(fragment: str) -> tuple[int, int]:
    """解析 ``L<start>-L<end>``（或单行 ``L<n>``）为 1 起始闭区间。"""
    match = _LOCATOR.fullmatch(str(fragment or "").strip())
    if not match:
        raise ValueError(f"locator 必须形如 L12-L34: {fragment!r}")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if start < 1 or end < start:
        raise ValueError(f"locator 区间非法: {fragment!r}")
    return start, end


def _slice(lines: Sequence[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : min(end, len(lines))])


# ---------------------------------------------------------------------------
# 格式处理器：识别 + 骨架。只认格式，不认项目（治理规则，见 materials.md）。


def _parse_python(lines: Sequence[str]) -> ast.Module | None:
    """能被解析且含 def/class/import 节点才算 Python 源码；排除偶然合法的纯字面量文本。"""
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError):
        return None
    structural = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
    if any(isinstance(node, structural) for node in tree.body):
        return tree
    return None


def _detect_format(lines: Sequence[str]) -> str:
    # Python 优先：`X: int = 1` 像 yaml 顶层键、`# 注释` 像 markdown 标题，必须先于形状匹配排除。
    if _parse_python(lines) is not None:
        return "python"
    for line in lines:
        if _TOP_KEY.match(line):
            return "yaml"
    for line in lines:
        if _HEADING.match(line):
            return "markdown"
    return "text"


def _py_assign_targets(node: ast.AST) -> str:
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        return ", ".join(names)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ""


def _py_doc_suffix(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return ""
    doc = ast.get_docstring(node) or ""
    first = next((line.strip() for line in doc.splitlines() if line.strip()), "")
    return f" — {first[:_PY_DOC_LABEL_CHARS]}" if first else ""


def _py_dict_key_label(key: ast.AST | None) -> str:
    if key is None:
        return "**"
    if isinstance(key, ast.Constant):
        return repr(key.value)
    if isinstance(key, ast.Name):
        return key.id
    return type(key).__name__


def _py_const_entries(name: str, value: ast.AST, start: int, end: int) -> List[Dict[str, Any]]:
    """dict 字面量超单次精读上限时按顶层 key 切二级条目，让模型能一步选中要读的段。"""
    if not isinstance(value, ast.Dict) or end - start + 1 <= _PY_CONST_SPLIT_LINES:
        return []
    keyed = [(k, v) for k, v in zip(value.keys, value.values)]
    entries: List[Dict[str, Any]] = []
    for position, (key, item) in enumerate(keyed):
        key_start = getattr(key, "lineno", None) or item.lineno
        # 值的末行；到下一个 key 起始前一行为止，避免把下一项吞进来。
        item_end = getattr(item, "end_lineno", None) or key_start
        if position + 1 < len(keyed):
            next_key, next_item = keyed[position + 1]
            next_start = getattr(next_key, "lineno", None) or next_item.lineno
            item_end = min(item_end, max(key_start, next_start - 1))
        entries.append({"label": f"  {name}[{_py_dict_key_label(key)}]", "start": key_start, "end": item_end})
    return entries


def _python_outline(lines: Sequence[str]) -> List[Dict[str, Any]]:
    """模块顶层 def/class/常量为一级条目，类方法与大 dict 常量的 key 为二级；行区间取自 AST。"""
    tree = _parse_python(lines)
    if tree is None:
        return []
    entries: List[Dict[str, Any]] = []
    for node in tree.body:
        end = getattr(node, "end_lineno", None) or node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entries.append({"label": f"def {node.name}{_py_doc_suffix(node)}", "start": node.lineno, "end": end})
        elif isinstance(node, ast.ClassDef):
            entries.append({"label": f"class {node.name}{_py_doc_suffix(node)}", "start": node.lineno, "end": end})
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    member_end = getattr(member, "end_lineno", None) or member.lineno
                    entries.append({
                        "label": f"  def {node.name}.{member.name}{_py_doc_suffix(member)}",
                        "start": member.lineno,
                        "end": member_end,
                    })
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            name = _py_assign_targets(node)
            if not name or node.value is None:
                continue
            entries.append({"label": f"const {name}", "start": node.lineno, "end": end})
            entries.extend(_py_const_entries(name, node.value, node.lineno, end))
    return entries


def _yaml_outline(lines: Sequence[str]) -> List[Dict[str, Any]]:
    """顶层键 + 带稳定身份键（id/name/field/…）的列表项，行区间由相邻标记推出。"""
    markers: List[tuple[int, int, str, int]] = []  # (line_idx0, level, label, indent)
    current_top = ""
    for idx, line in enumerate(lines):
        top = _TOP_KEY.match(line)
        if top:
            current_top = top.group(1)
            markers.append((idx, 0, current_top, 0))
            continue
        item = _LIST_ID.match(line)
        if item:
            label = f"{current_top}/{item.group(2)}" if current_top else item.group(2)
            markers.append((idx, 1, label, len(item.group(1))))
    entries: List[Dict[str, Any]] = []
    for position, (idx, level, label, indent) in enumerate(markers):
        end = len(lines)
        for next_idx, next_level, _next_label, next_indent in markers[position + 1 :]:
            if next_level < level or (next_level == level and (level == 0 or next_indent == indent)):
                end = next_idx
                break
        entries.append({"label": label, "start": idx + 1, "end": end})
    return entries


def _markdown_outline(lines: Sequence[str]) -> List[Dict[str, Any]]:
    markers: List[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        match = _HEADING.match(line)
        if match:
            markers.append((idx, len(match.group(1)), match.group(2).strip()))
    entries: List[Dict[str, Any]] = []
    for position, (idx, depth, title) in enumerate(markers):
        end = len(lines)
        for next_idx, next_depth, _title in markers[position + 1 :]:
            if next_depth <= depth:
                end = next_idx
                break
        entries.append({"label": title, "start": idx + 1, "end": end})
    return entries


def _line_block_outline(lines: Sequence[str], block: int = 200) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for start in range(1, len(lines) + 1, block):
        end = min(start + block - 1, len(lines))
        first = next((l.strip() for l in lines[start - 1 : end] if l.strip()), "")
        entries.append({"label": first[:48] or f"块 L{start}", "start": start, "end": end})
    return entries


def outline(project_id: str, material_id: str) -> Dict[str, Any]:
    """资料骨架：格式处理器按格式触发；无结构化切片方案时诚实降级为行块地图。"""
    lines = read_content(project_id, material_id).splitlines()
    detected = _detect_format(lines)
    note = ""
    if detected == "python":
        raw = _python_outline(lines)
        note = "Python 源码：条目是顶层 def/class/常量（类方法、大 dict 常量的 key 为二级）。常量表可直接精读；函数体是实现而非声明，据其推断能力空间时注意默认分支与动态分发。"
    elif detected == "yaml":
        raw = _yaml_outline(lines)
    elif detected == "markdown":
        raw = _markdown_outline(lines)
    else:
        raw = _line_block_outline(lines)
        note = "该格式尚无结构化切片方案：仅行块地图可用，请配合 material_search 词法检索导航。"
    truncated = len(raw) > MAX_OUTLINE_ENTRIES
    entries = [
        {
            "label": item["label"],
            "locator": f"L{item['start']}-L{item['end']}",
            "preview": lines[item["start"] - 1].strip()[:60],
        }
        for item in raw[:MAX_OUTLINE_ENTRIES]
    ]
    result: Dict[str, Any] = {
        "material": material_uri(project_id, material_id),
        "format": detected,
        "total_lines": len(lines),
        "entries": entries,
        "truncated": truncated,
    }
    if note:
        result["note"] = note
    if truncated:
        result["note"] = (result.get("note", "") + " 骨架条目超上限已截断，请用 material_search 缩小范围。").strip()
    return result


# ---------------------------------------------------------------------------
# 词法检索 + 精读（全格式通用：只假设「是文本」）。


def search(
    project_id: str,
    material_id: str,
    query: str,
    *,
    max_hits: int = MAX_SEARCH_HITS,
    context_lines: int = SEARCH_CONTEXT_LINES,
) -> Dict[str, Any]:
    """关键词（空白分隔，OR 命中、多词优先）→ 带行区间 locator 的片段。"""
    keywords = [item for item in str(query or "").split() if item]
    if not keywords:
        raise ValueError("query 不能为空（空白分隔的关键词）")
    lines = read_content(project_id, material_id).splitlines()
    scored: List[tuple[int, int, List[str]]] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        matched = [word for word in keywords if word.lower() in lowered]
        if matched:
            scored.append((len(matched), index, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    top = sorted(scored[: max(1, max_hits)], key=lambda item: item[1])

    windows: List[Dict[str, Any]] = []
    for _, index, matched in top:
        start = max(0, index - context_lines)
        end = min(len(lines) - 1, index + context_lines)
        if windows and start <= windows[-1]["end"] + 1:
            windows[-1]["end"] = max(windows[-1]["end"], end)
            windows[-1]["keywords"].update(matched)
        else:
            windows.append({"start": start, "end": end, "keywords": set(matched)})

    snippets: List[Dict[str, Any]] = []
    total_chars = 0
    truncated = False
    for window in windows:
        text = "\n".join(lines[window["start"] : window["end"] + 1])
        if total_chars + len(text) > MAX_SNIPPET_CHARS:
            truncated = True
            break
        total_chars += len(text)
        snippets.append({
            "locator": f"L{window['start'] + 1}-L{window['end'] + 1}",
            "keywords": sorted(window["keywords"]),
            "text": text,
        })
    return {
        "material": material_uri(project_id, material_id),
        "query": query,
        "total_line_hits": len(scored),
        "snippets": snippets,
        "truncated": truncated or len(scored) > len(top),
    }


def read(project_id: str, material_id: str, locator: str) -> Dict[str, Any]:
    """按行区间 locator 精读，单次上限 MAX_READ_LINES 行。"""
    start, end = parse_locator(locator)
    if end - start + 1 > MAX_READ_LINES:
        raise ValueError(f"单次最多读 {MAX_READ_LINES} 行，请缩小区间: L{start}-L{end}")
    lines = read_content(project_id, material_id).splitlines()
    if start > len(lines):
        raise ValueError(f"起始行超出正文范围（共 {len(lines)} 行）: L{start}")
    end = min(end, len(lines))
    return {
        "material": material_uri(project_id, material_id),
        "locator": f"L{start}-L{end}",
        "total_lines": len(lines),
        "text": _slice(lines, start, end),
    }


# ---------------------------------------------------------------------------
# 引用机械核验（产出时合同：核验发生在结论产出时，不回溯历史存档）。


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def quote_in_text(quote: str, text: str) -> bool:
    normalized = _normalize(quote)
    return bool(normalized) and normalized in _normalize(text)


def verify_quote(project_id: str, material_id: str, locator: str, quote: str) -> bool:
    """回读 locator 处的资料原文，核验引句逐字（忽略空白）包含其中。"""
    start, end = parse_locator(locator)
    if end - start + 1 > MAX_VERIFY_LINES:
        return False
    lines = read_content(project_id, material_id).splitlines()
    if start > len(lines):
        return False
    return quote_in_text(quote, _slice(lines, start, min(end, len(lines))))


# ---------------------------------------------------------------------------
# 工具箱构建：范围守卫 + 回执。任何守「只读+出回执+范围受限」合同的工具都可加入。


def build_material_tools(
    catalog: Sequence[Mapping[str, Any]],
    recorder: List[Dict[str, Any]],
) -> list:
    """按资料目录构建三件套 VerifiableTool；每次调用把回执写进 recorder。"""
    if not catalog:
        return []
    from impl.tools.protocol import VerifiableTool, build_agno_tools

    allowed = {str(item.get("id")): str(item.get("project_id")) for item in catalog}

    def _guard(material_id: str) -> str:
        project_id = allowed.get(str(material_id))
        if not project_id:
            raise ValueError(f"material_id 必须是目录里的资料之一: {sorted(allowed)}")
        return project_id

    def _record(receipt: Dict[str, Any]) -> None:
        recorder.append(receipt)

    def _run(tool: str, material_id: str, args: Dict[str, Any], fn: Callable[[], Dict[str, Any]], locators_of: Callable[[Dict[str, Any]], List[str]]) -> Dict[str, Any]:
        receipt: Dict[str, Any] = {"tool": tool, "material_id": str(material_id), **args}
        try:
            result = fn()
        except ValueError as exc:
            receipt["error"] = str(exc)
            _record(receipt)
            return {"error": str(exc)}
        receipt["returned_locators"] = locators_of(result)
        _record(receipt)
        return result

    def _outline(material_id: str) -> dict:
        return _run(
            "material_outline", material_id, {},
            lambda: outline(_guard(material_id), material_id),
            lambda r: [item["locator"] for item in r.get("entries", [])][:20],
        )

    def _search(material_id: str, query: str) -> dict:
        return _run(
            "material_search", material_id, {"query": str(query)},
            lambda: search(_guard(material_id), material_id, query),
            lambda r: [item["locator"] for item in r.get("snippets", [])],
        )

    def _read(material_id: str, locator: str) -> dict:
        return _run(
            "material_read", material_id, {"locator": str(locator)},
            lambda: read(_guard(material_id), material_id, locator),
            lambda r: [r.get("locator", "")],
        )

    return build_agno_tools([
        VerifiableTool(
            tool_id="material_outline",
            description="看资料骨架：返回条目菜单（label + 行区间 locator）。先看骨架再选条目精读；无结构格式会降级为行块地图并明说。",
            parameters={
                "type": "object",
                "properties": {
                    "material_id": {"type": "string", "description": "目录里的资料 id"},
                },
                "required": ["material_id"],
            },
            execute_fn=_outline,
        ),
        VerifiableTool(
            tool_id="material_search",
            description="词法检索：空白分隔关键词，返回命中片段和行区间 locator。未命中不代表资料没写，可换词重试。",
            parameters={
                "type": "object",
                "properties": {
                    "material_id": {"type": "string", "description": "目录里的资料 id"},
                    "query": {"type": "string", "description": "空白分隔的关键词"},
                },
                "required": ["material_id", "query"],
            },
            execute_fn=_search,
        ),
        VerifiableTool(
            tool_id="material_read",
            description="按行区间 locator（如 L43-L79，须复制工具返回的 locator）精读资料原文，单次最多 120 行。",
            parameters={
                "type": "object",
                "properties": {
                    "material_id": {"type": "string", "description": "目录里的资料 id"},
                    "locator": {"type": "string", "description": "行区间 locator，形如 L43-L79"},
                },
                "required": ["material_id", "locator"],
            },
            execute_fn=_read,
        ),
    ])
