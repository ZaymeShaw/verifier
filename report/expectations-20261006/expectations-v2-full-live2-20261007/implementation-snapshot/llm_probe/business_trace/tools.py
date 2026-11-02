"""案卷取证件：目录之外的正文只有通过这里才能读到，每次读都留回执。

为什么需要它：案卷正文平均 50 万字符，整份塞给整理员既贵又逼它「先读完全部再挑」。
改成给目录（有什么、是什么、多大、在哪）+ 这套只读工具后，整理员按自己的问题定位着读；
每条被选中的编号必须能在回执里找到对应的一次读取，「凭摘要猜内容」选不出东西。
价格关键在于会话长度而不是读取次数：所以取件支持一次取多条（collect），把「边逛边拿」的十几轮
往返压成「看目录 → 一次取回要的 → 定稿」，每轮不再重发已经取回的全部正文。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .dossier import (EVIDENCE_FULL_READ_CHARS, EVIDENCE_NODE_CHARS, PREVIEW_CHARS, node_shape, record_body,
                      render_value, resolve_node_path)

# 单次读取上限：超了就返回结构图让模型下钻，绝不静默截断（截断会让模型以为自己看全了）。
# 与视图渲染同口径（EVIDENCE_NODE_CHARS）：读的时候按这个数下钻，下游拿到的也是同一精度。
MAX_READ_CHARS = EVIDENCE_NODE_CHARS
# 下游确实需要整段原文时（整页工具回填、系统提示词），整理员可以申请一次完整读取。
MAX_FULL_READ_CHARS = EVIDENCE_FULL_READ_CHARS
# 一次取件保留足够正文供定位，避免大段工具返回使模型后续请求超时。
MAX_COLLECT_CHARS = 60_000
# 大记录一趟能装下的单个片段上限：再大就只登记路径，让侦探自己决定要不要下钻。
MAX_SLICE_CHARS = 3_000
MAX_SEARCH_HITS = 12
SEARCH_SNIPPET_CHARS = 240
_SEARCH_META_KEYS = {"status", "note", "chars", "ref", "source_id"}
# 算得上「读到正文」的工具：单读与批量取件同口径（结构图不算）。
_BODY_TOOLS = ("dossier_read", "dossier_collect")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _normalize(value: str) -> str:
    return "".join(str(value or "").split())


def _units(path: str, node: Any) -> list[tuple[str, int]]:
    """可单独读取的最小单元（路径 → 字数）：记录按每个字段的 value 切，其他对象按一级键切。"""
    if isinstance(node, Mapping) and isinstance(node.get("fields"), Mapping):
        units = [(f"{path}/fields/{name}/value", len(_text(info["value"])))
                 for name, info in node["fields"].items()
                 if isinstance(info, Mapping) and "value" in info]
        units += [(f"{path}/{key}", len(_text(value))) for key, value in node.items() if key != "fields"]
        return units
    if isinstance(node, Mapping):
        return [(f"{path}/{key}", len(_text(value))) for key, value in node.items()]
    if isinstance(node, list):
        return [(f"{path}/{index}", len(_text(value))) for index, value in enumerate(node)]
    return [(path, len(_text(node)))]


def _smallest_slices(node: Any, budget: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """大记录先装小片段（标量/状态），大正文块只登记路径——按体积排序是机械规则，不作语义取舍。"""
    units = sorted(_units("", node), key=lambda item: (item[1], item[0]))
    kept: dict[str, Any] = {}
    omitted: list[dict[str, Any]] = []
    used = 0
    for path, size in units:
        if size > MAX_SLICE_CHARS or used + size > budget:
            omitted.append({"path": path, "chars": size})
            continue
        try:
            kept[path] = resolve_node_path(node, path)
        except ValueError:
            omitted.append({"path": path, "chars": size})
            continue
        used += size
    return kept, omitted


def _shape(node: Any) -> Any:
    """结构图（与视图渲染共用一份实现）。"""
    return node_shape(node, max_keys=60, preview_chars=PREVIEW_CHARS)


def _leaves(node: Any, path: str = "") -> Any:
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _leaves(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, f"{path}/{index}")
    else:
        yield path, _text(node)


class EvidenceIndex:
    """一个案卷的只读取证接口。所有方法都会往 recorder 里写一条回执。"""

    def __init__(self, dossier: Mapping[str, Any], recorder: list[dict[str, Any]] | None = None,
                 *, max_calls: int | None = None):
        self._dossier = dossier
        self._rows = {row["id"]: row for row in dossier.get("records") or []}
        self._gaps = {gap["id"]: gap for gap in dossier.get("gaps") or []}
        self._sources = {source["id"]: source for source in dossier.get("sources") or []}
        self._contents = dict(dossier.get("contents") or {})
        self._buckets = {bucket: list(dossier.get(bucket) or [])
                         for bucket in ("current", "history", "observed_at_collection")}
        self._cache: dict[str, Any] = {}
        self.receipts: list[dict[str, Any]] = recorder if recorder is not None else []
        # 工具调用次数（不是回执条数）：一次 collect 取十个编号算一次调用。
        self.calls = 0
        self.max_calls = max_calls

    def _begin_call(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise ValueError("案卷取证预算已耗尽；未读材料仍须记为缺证")
        self.calls += 1

    # ---- 编号 → 正文 --------------------------------------------------------

    def knows(self, ident: str) -> bool:
        return ident in self._rows or ident in self._gaps or ident in self._sources or ident in self._contents

    def _body(self, ident: str) -> Any:
        if ident in self._cache:
            return self._cache[ident]
        if ident in self._rows:
            body = record_body(self._dossier, self._rows[ident])
        elif ident in self._contents:
            body = render_value(self._dossier, {"content_ref": ident})
        elif ident in self._gaps:
            body = self._gaps[ident]
        elif ident in self._sources:
            source = self._sources[ident]
            body = {key: render_value(self._dossier, source[key])
                    for key in ("request_and_response", "original_records") if source.get(key) is not None}
        else:
            raise ValueError(f"案卷里没有这个编号: {ident}")
        self._cache[ident] = body
        return body

    @staticmethod
    def _resolve(node: Any, path: str) -> Any:
        return resolve_node_path(node, path)

    def _note(self, receipt: dict[str, Any]) -> None:
        receipt.setdefault("call", self.calls)
        self.receipts.append(receipt)

    # ---- 工具接口 -----------------------------------------------------------

    def read(self, record_id: str, path: str = "", full: bool = False) -> dict[str, Any]:
        """读一条记录的原文（或其中一段）；超过单次上限就返回结构图，用 path 继续下钻。

        读到结构图不等于读到正文：这种回执 alone 不足以支撑引用（见 read_ids）。
        下游确实需要整段（整页工具回填、系统提示词）而下钻也切不开时，用 full=True 申请一次完整读取
        （上限 MAX_FULL_READ_CHARS）：这次回执算读过正文，轴视图会带上整段。
        """
        ident = str(record_id)
        self._begin_call()
        receipt: dict[str, Any] = {"tool": "dossier_read", "id": ident, "path": str(path or "")}
        try:
            node = self._resolve(self._body(ident), path)
        except ValueError as exc:
            receipt["error"] = str(exc)
            self._note(receipt)
            return {"error": str(exc)}
        text = _text(node)
        limit = MAX_FULL_READ_CHARS if full else MAX_READ_CHARS
        receipt["chars"] = len(text)
        if len(text) > limit:
            receipt["shape_only"] = True
        elif full:
            receipt["full"] = True
        self._note(receipt)
        if len(text) <= limit:
            return {"id": ident, "path": str(path or ""), "chars": len(text), "text": text}
        extra = ("再读一次并带 full=true 可以拿到整段正文" if not full
                 else f"整段超过完整读取上限 {MAX_FULL_READ_CHARS} 字，只能下钻取用得到的部分")
        return {"id": ident, "path": str(path or ""), "chars": len(text), "too_large": True,
                "shape": _shape(node),
                "hint": f"本节点 {len(text)} 字，超过单次读取上限 {limit} 字：按 shape 选一支用 path 下钻（如 /fields/output/value），不要假设没读到的部分没有内容。读到结构图不算读到正文，要引用它就必须下钻把正文读出来；{extra}。"}

    def collect(self, ids: Sequence[str]) -> dict[str, Any]:
        """一次取回多个编号的正文：把「逐条取」的多轮往返压成一次取件。

        每条按单次上限渲染（超限给结构图，用 read 下钻）；总量到 MAX_COLLECT_CHARS 就停，
        没取回的编号在 deferred 里明确列回去（不静默丢）。每条都留回执，与单读同口径。
        """
        wanted = [str(item).strip() for item in (ids or []) if str(item).strip()]
        self._begin_call()
        items: list[dict[str, Any]] = []
        deferred: list[str] = []
        unknown: list[str] = []
        used = 0
        for ident in dict.fromkeys(wanted):
            if not self.knows(ident):
                unknown.append(ident)
                continue
            if used >= MAX_COLLECT_CHARS:
                deferred.append(ident)
                continue
            node = self._body(ident)
            text = _text(node)
            if len(text) > MAX_READ_CHARS:
                # 大记录：一趟把装得下的小片段取回来（并逐段留回执），装不下的只登记路径。
                slices, omitted = _smallest_slices(node, min(MAX_READ_CHARS, MAX_COLLECT_CHARS - used))
                if not slices:
                    receipt = {"tool": "dossier_collect", "id": ident, "path": "",
                               "chars": len(text), "shape_only": True}
                    self._note(receipt)
                    items.append({"id": ident, "chars": len(text), "too_large": True, "shape": _shape(node),
                                  "hint": f"本记录 {len(text)} 字，超过单次上限 {MAX_READ_CHARS} 字："
                                            "用 dossier_read 带 path 下钻取用得上的片段；下游确实需要整段时带 full=true。"})
                    continue
                used_local = 0
                for path, value in slices.items():
                    size = len(_text(value))
                    used_local += size
                    self._note({"tool": "dossier_collect", "id": ident, "path": path, "chars": size})
                used += used_local
                items.append({"id": ident, "chars": len(text), "partial": True, "slices": slices,
                              "slice_chars": used_local,
                              "map": {path: size for path, size in _units("", node)},
                              "not_read_here": omitted,
                              "hint": f"本记录 {len(text)} 字，超过单次上限 {MAX_READ_CHARS} 字：slices 是已读到并留了回执的片段"
                                      "（按体积从小到大挑，小字段优先），map 是全部可读单元与字数，"
                                      "not_read_here 里的没读到——确实需要就用 dossier_read 带 path 取。"})
                continue
            if used + len(text) > MAX_COLLECT_CHARS and items:
                deferred.append(ident)
                continue
            used += len(text)
            self._note({"tool": "dossier_collect", "id": ident, "path": "", "chars": len(text)})
            items.append({"id": ident, "chars": len(text), "text": text})
        hint = (f"已取回 {len(items)} 条（{used} 字）。"
                + (f"还有 {len(deferred)} 条因本次取件总量上限未取回，需要就在下一次 collect 里补：{deferred[:8]}。"
                   if deferred else "")
                + (f"不在目录里的编号：{unknown[:8]}。" if unknown else "")
                + "正文已在本会话里：看完直接定稿，不要重复取同一条。")
        return {"items": items, "deferred": deferred, "unknown": unknown, "chars": used, "hint": hint}

    def search(self, query: str, record_id: str = "") -> dict[str, Any]:
        """按关键词在记录正文里定位：返回编号 + 路径 + 片段，供随后 collect/read 精读。"""
        keywords = [word for word in str(query or "").split() if word]
        if not keywords:
            raise ValueError("query 不能为空（空白分隔的关键词）")
        self._begin_call()
        receipt = {"tool": "dossier_search", "query": str(query), "id": str(record_id or "")}
        targets = [str(record_id)] if record_id else [
            row["id"] for row in self._dossier.get("records") or []]
        hits: list[dict[str, Any]] = []
        total = 0
        for target in targets:
            try:
                node = self._body(target)
            except ValueError:
                continue
            for path, text in _leaves(node):
                lowered = text.lower()
                matched = [word for word in keywords if word.lower() in lowered]
                if not matched or path.rsplit("/", 1)[-1] in _SEARCH_META_KEYS:
                    continue
                total += 1
                hits.append({"matched": matched, "id": target, "path": path, "chars": len(text), "text": text})
        hits.sort(key=lambda item: (-len(item["matched"]), item["id"], item["path"]))
        top = hits[:MAX_SEARCH_HITS]
        receipt["hits"] = len(top)
        receipt["total_hits"] = total
        self._note(receipt)
        return {
            "query": str(query), "total_hits": total, "truncated": total > len(top),
            "hits": [{"id": item["id"], "path": item["path"], "chars": item["chars"],
                      "matched": item["matched"], "snippet": _snippet(item["text"], keywords)}
                     for item in top],
            "hint": "命中不代表只有这些：换个词继续找。**片段不算读过**：要引用就必须用 dossier_collect 一次把命中编号全取回正文（可带多条），再定稿。",
        }

    def timeline(self, turn: str = "") -> dict[str, Any]:
        """看顺序骨架：每轮有哪些步骤/调用，以及时间戳未知时的父子与序号关系。"""
        self._begin_call()
        rows: list[dict[str, Any]] = []
        for bucket, nodes in self._buckets.items():
            for node in nodes:
                if turn and node.get("turn") != turn:
                    continue
                rows.append({"bucket": bucket, **{key: node.get(key) for key in
                            ("id", "turn", "kind", "at", "parent_ref", "ordinal", "copy_of")}})
        self._note({"tool": "dossier_timeline", "turn": str(turn or ""), "rows": len(rows)})
        return {"turn": str(turn or ""), "rows": rows,
                "hint": "at=null 表示采集时没记到时刻，这一行不能当作先后顺序；用 parent_ref/ordinal 判断局部顺序。"}

    def verify_quote(self, record_id: str, quote: str, path: str = "") -> dict[str, Any]:
        """逐字核验：引句是否真的出现在该编号（或该路径）的原文里。"""
        self._begin_call()
        receipt = {"tool": "dossier_verify_quote", "id": str(record_id), "path": str(path or "")}
        try:
            node = self._resolve(self._body(str(record_id)), path)
        except ValueError as exc:
            receipt["error"] = str(exc)
            self._note(receipt)
            return {"found": False, "error": str(exc)}
        texts = [text for _path, text in _leaves(node)] if isinstance(node, (Mapping, list)) else [_text(node)]
        found = any(_normalize(quote) and _normalize(quote) in _normalize(text) for text in texts)
        receipt["found"] = found
        self._note(receipt)
        return {"id": str(record_id), "path": str(path or ""), "quote": str(quote), "found": found}

    @property
    def read_ids(self) -> set[str]:
        """有正文读取回执的编号：只有这些才有资格被选进下游轴。

        只读到结构图的不算：如果算，整理员可以“看一眼结构图就把整棵树交给轴”，而轴拿到的正文
        整理员自己没看过（实测就是这个口子把 38.9k 的 session_state 灌进了 4 个轴）。
        """
        return {str(item["id"]) for item in self._body_reads}

    @property
    def shape_only_ids(self) -> set[str]:
        """只读到结构图、没读到正文的编号（单独留痕，好看出整理员在哪里没下钻）。"""
        return {str(item["id"]) for item in self.receipts
                if item.get("tool") in _BODY_TOOLS and item.get("shape_only")}

    @property
    def _body_reads(self) -> list[dict[str, Any]]:
        """算得上「读到正文」的回执（单读与批量取件同口径）。"""
        return [item for item in self.receipts
                if item.get("tool") in _BODY_TOOLS and item.get("chars") is not None
                and not item.get("shape_only") and not item.get("error")]

    @property
    def read_receipts(self) -> list[dict[str, Any]]:
        """留给下游视图的回执：每条是（编号、路径、尺寸、是否只读到结构图），视图据此只渲染真读过的片段。"""
        return [{"id": str(item["id"]), "path": str(item.get("path") or ""),
                 "chars": int(item.get("chars") or 0), "shape_only": bool(item.get("shape_only")),
                 "full": bool(item.get("full"))}
                for item in self.receipts
                if item.get("tool") in _BODY_TOOLS and item.get("chars") is not None
                and not item.get("error")]


def _snippet(text: str, keywords: Sequence[str]) -> str:
    lowered = text.lower()
    positions = [lowered.find(word.lower()) for word in keywords if word.lower() in lowered]
    start = max(0, (min(positions) if positions else 0) - SEARCH_SNIPPET_CHARS // 3)
    return text[start:start + SEARCH_SNIPPET_CHARS]


TOOL_GUIDE = (
    "目录（catalog）只登记有什么、是什么、多大、在哪；正文不在目录里。工作方法分两步，不要边逛边拿："
    "**第一步**：看完目录与各轴 requires，用一次 dossier_collect 把你判断该看的编号**一次性全取回来**"
    "（ids 是数组，可带几十条；总量超上限时返回里会列出 deferred，下一次补取即可）。"
    "**第二步**：看完正文再增删，只对超大节点用 dossier_read 带 path 下钻；确需整段时带 full=true。"
    "每次工具调用都尽量一次带多条/并行发多个调用（一次只发一个调用会把预算耗光）。"
    "**没有正文读取回执的编号一律不能出现在 route 或 suspects 里**：目录摘要、结构图、检索片段都不算读过；"
    "写了没取回的编号会被打回重做（重做一次仍不改就自动剔除，它就不能作为出处）。"
    "节点超过 12000 字会返回 shape 结构图（读到结构图不算读过正文，要引用它就必须下钻或 full=true）；"
    "dossier_search 用于在目录摘要定位不到时找词（命中后同样要 collect 取回正文），"
    "dossier_timeline 看每轮顺序骨架，dossier_verify_quote 逐字核验引句。"
    "引用要精确到你真读的那一段：只读过父编号就写父编号，读的是 a/b 就写 a/b。"
)


def build_dossier_tools(index: EvidenceIndex) -> list:
    """把取证件包成 agno 工具；每次调用由 EvidenceIndex 自己写回执。"""
    from impl.tools.protocol import VerifiableTool, build_agno_tools

    def _collect(ids: list) -> dict:
        return index.collect(list(ids or []))

    def _read(record_id: str, path: str = "", full: bool = False) -> dict:
        return index.read(record_id, path, full)

    def _search(query: str, record_id: str = "") -> dict:
        return index.search(query, record_id)

    def _timeline(turn: str = "") -> dict:
        return index.timeline(turn)

    def _verify(record_id: str, quote: str, path: str = "") -> dict:
        return index.verify_quote(record_id, quote, path)

    return build_agno_tools([
        VerifiableTool(
            tool_id="dossier_collect",
            description="一次取回多个编号的正文（ids 是数组，可一次带几十条）：看完目录后用一次取件把"
                        "你判断要看的编号全取回来，再在会话里决定增删。超大节点返回结构图，"
                        "总量超上限的编号在 deferred 里列回，下一次补取。",
            parameters={"type": "object", "properties": {
                "ids": {"type": "array", "items": {"type": "string"},
                         "description": "目录里的编号列表（records/contents/gaps 的 id）"}},
                "required": ["ids"]},
            execute_fn=_collect,
        ),
        VerifiableTool(
            tool_id="dossier_read",
            description="按编号读案卷原文（可带 path 下钻），用于精读 collect 返回结构图的大节点，或逐字核对某一段。",
            parameters={"type": "object", "properties": {
                "record_id": {"type": "string", "description": "目录里的编号"},
                "path": {"type": "string", "description": "可选，节点内路径，如 /fields/output/value"},
                "full": {"type": "boolean", "description": "可选。下游确实需要整段原文、下钻切不开时置 true 申请完整读取（上限 80000 字），这次回执算读过正文"}},
                "required": ["record_id"]},
            execute_fn=_read,
        ),
        VerifiableTool(
            tool_id="dossier_search",
            description="在目录摘要不足以定位时按关键词在案卷正文里找，返回编号+路径+片段；片段不算读过，"
                        "命中后要用 dossier_collect 一次把命中编号取回正文。",
            parameters={"type": "object", "properties": {
                "query": {"type": "string", "description": "空白分隔的关键词"},
                "record_id": {"type": "string", "description": "可选，只在这条记录里找"}},
                "required": ["query"]},
            execute_fn=_search,
        ),
        VerifiableTool(
            tool_id="dossier_timeline",
            description="按轮次返回顺序骨架（步骤/调用、时间戳、父子与序号）。at=null 表示时刻未知。",
            parameters={"type": "object", "properties": {
                "turn": {"type": "string", "description": "可选，如 turn1"}}, "required": []},
            execute_fn=_timeline,
        ),
        VerifiableTool(
            tool_id="dossier_verify_quote",
            description="逐字核验引句是否真的出现在该编号的原文里（忽略空白）。引用前先核验。",
            parameters={"type": "object", "properties": {
                "record_id": {"type": "string", "description": "目录里的编号"},
                "quote": {"type": "string", "description": "要核验的原文引句"},
                "path": {"type": "string", "description": "可选，节点内路径"}},
                "required": ["record_id", "quote"]},
            execute_fn=_verify,
        ),
    ])
