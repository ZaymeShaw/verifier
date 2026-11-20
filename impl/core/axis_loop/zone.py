"""Loop 级公共资源管理区（spec/alg/resources.md §11）：显式接收 URI、增量开放、按类型渲染与门禁读取。

每个 Loop 实例持有一个 ``ResourceZone``：
- 任务解锁时，``_LoopGate`` 按轴定义 ``resources`` 点路径从 ``MaterialTable`` 取出 URI 列表，调用 ``push(uris)``；
- ``push`` 强校验每条 URI 在 ``ResourceTable`` 中真实存在，对比本 Loop 已开放范围算出新增 ``delta``：
  未超 ``inline_chars`` 时调资源类型的 ``present`` 嵌入唯一正文，超限时调 ``catalog_entry`` 输出统一目录；
- ``Reader`` 通过 ``ResourceZone`` 读取与搜索当前已开放的资源（未开放的资源或字段严格拒读，保证防污染）。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Optional

from impl.core.resources import Address, Block, ResourceTable, TYPES

from . import paths
from .acceptance import SynthesisError
from .materials import MaterialTable, parse_entry
from .text import dump

ZONE_NAME = "resources"


def resolve_uris(table: MaterialTable, entries: Sequence[str], axis_id: str = "") -> list[str]:
    """按轴定义 ``resources`` 的点路径从 ``MaterialTable`` 取出去重保序的 URI 列表。"""
    out: list[str] = []
    seen: set[str] = set()
    for text in entries:
        entry = parse_entry(text)
        root = table.full(entry.name, axis_id)
        if root is None:
            continue
        for item in paths.values(root, entry.path):
            if item is None:
                continue
            if not isinstance(item, str) or not item.strip():
                raise SynthesisError(f"{text}: resources 路径产出的必须是合法 URI 字符串，得到 {item!r}")
            uri = item.strip()
            if uri not in seen:
                seen.add(uri)
                out.append(uri)
    return out


def format_task_resources(table: ResourceTable, uris: Sequence[str]) -> list[str]:
    """任务卡里展示的本任务可见资源清单：写成与引用格式一致的短名（``记录编号`` 或 ``记录编号/fields/字段名``）。"""
    by_block: dict[str, Optional[list[str]]] = {}
    names: dict[str, str] = {}
    for uri in uris:
        part = table.part(uri)
        if part is None:
            raise SynthesisError(f"资源不存在：{uri!r}")
        block, node = part
        kind = TYPES[block.type]
        if node and kind.slice(block.body, node) is None:
            raise SynthesisError(f"模板资源字段不存在：{uri!r}")
        short = block.descriptor.name
        names[block.uri] = short
        if not node:
            by_block[block.uri] = None
        elif block.uri not in by_block or by_block[block.uri] is not None:
            fname = kind.field_name(node) if hasattr(kind, "field_name") else node.lstrip("/")
            cur = by_block.setdefault(block.uri, [])
            if cur is not None and fname and fname not in cur:
                cur.append(fname)
    rendered: list[str] = []
    for block_uri, fields in by_block.items():
        short = names[block_uri]
        if fields is None:
            rendered.append(short)
        elif len(fields) == 1:
            rendered.append(f"{short}/fields/{fields[0]}")
        else:
            rendered.append(f"{short}/fields/{{{', '.join(sorted(fields))}}}")
    return rendered


class ResourceZone:
    """一个 Loop 实例的公共资源管理区。"""

    def __init__(self, table: ResourceTable, inline_chars: int) -> None:
        self.table = table
        self.inline_chars = inline_chars
        self._order: list[str] = []
        self._whole: set[str] = set()
        self._fields: dict[str, set[str]] = {}
        self._inlined_whole: set[str] = set()
        self._inlined_fields: dict[str, set[str]] = {}
        self._wave = 0

    @property
    def has_open(self) -> bool:
        return bool(self._order)

    @property
    def inlined_names(self) -> frozenset[str]:
        inlined_uris = self._inlined_whole | {u for u, fs in self._inlined_fields.items() if fs}
        return frozenset(
            block.descriptor.name for u in inlined_uris if (block := self.table.get(u)) is not None
        )

    def push(self, uris: Iterable[str]) -> str:
        """向本 Loop 公共区推送一批 URI，返回本轮需要放到消息顶部的【resources】文本（无新增时返回空串）。"""
        batch_order: list[Block] = []
        batch_seen: set[str] = set()
        batch_whole: set[str] = set()
        batch_fields: dict[str, set[str]] = {}

        for raw in uris:
            try:
                part = self.table.part(str(raw))
            except ValueError as exc:
                raise SynthesisError(f"资源地址不合法：{raw!r}（{exc}）") from exc
            if part is None:
                raise SynthesisError(f"推送的资源未挂载：{raw!r}")
            block, node = part
            kind = TYPES[block.type]
            if node and kind.slice(block.body, node) is None:
                raise SynthesisError(f"推送的模板资源字段不存在：{raw!r}")
            if block.uri not in batch_seen:
                batch_seen.add(block.uri)
                batch_order.append(block)
            if not node:
                batch_whole.add(block.uri)
            elif block.uri not in batch_whole:
                fname = kind.field_name(node) if hasattr(kind, "field_name") else ""
                if fname:
                    batch_fields.setdefault(block.uri, set()).add(fname)
                else:
                    batch_whole.add(block.uri)

        delta: list[tuple[Block, Optional[set[str]]]] = []
        for block in batch_order:
            u = block.uri
            if u in self._whole:
                continue
            if u not in self._order:
                self._order.append(u)
            if u in batch_whole:
                prev = self._fields.pop(u, set())
                self._whole.add(u)
                if not prev:
                    delta.append((block, None))
                else:
                    all_f = set((block.body.get("fields") or {}).keys()) if isinstance(block.body, Mapping) else set()
                    rem = all_f - prev
                    delta.append((block, rem if rem else None))
            else:
                req = batch_fields.get(u, set())
                cur = self._fields.setdefault(u, set())
                added = req - cur
                if added:
                    cur |= added
                    delta.append((block, set(added)))

        if not delta:
            return ""

        self._wave += 1
        title = f"【{ZONE_NAME}】" if self._wave == 1 else f"【{ZONE_NAME}（本轮新增开放）】"
        presented = [TYPES[b.type].present(b, f) for b, f in delta]
        body_text = dump({"records": presented})
        if len(body_text) <= self.inline_chars:
            for b, f in delta:
                if f is None:
                    self._inlined_whole.add(b.uri)
                else:
                    self._inlined_fields.setdefault(b.uri, set()).update(f)
            guide = "公共资源区：以下资源正文已直接完整给出，无需再调 read_material 重读；各任务仅可引用自身「可见资源」列出的编号。"
            return f"{title}\n{guide}\n{body_text}"

        catalog = [TYPES[b.type].catalog_entry(b, f) for b, f in delta]
        payload = {
            "说明": (f"公共资源正文合计 {len(body_text)} 字（超过内联上限 {self.inline_chars} 字），这里给统一目录；"
                    f"用 read_material(name={ZONE_NAME!r}, ids=[...]) 按 id 取正文，或 search_material(name={ZONE_NAME!r}, query=...) 按关键词找"),
            "catalog": catalog,
            "records": len(catalog),
        }
        return f"{title}\n{dump(payload)}"

    def open_signature(self, block_uri: str) -> str:
        if block_uri in self._whole:
            return "*"
        if block_uri in self._fields:
            return ",".join(sorted(self._fields[block_uri]))
        return ""

    def already_inlined(self, block_uri: str, req_field: str = "") -> bool:
        if block_uri in self._inlined_whole:
            return True
        if block_uri in self._whole:
            return False
        opened = self._fields.get(block_uri) or set()
        inlined = self._inlined_fields.get(block_uri) or set()
        if req_field:
            return req_field in inlined
        return bool(opened) and opened <= inlined

    def resolve_open(self, ident: str) -> tuple[Optional[Block], Optional[dict[str, Any]], str, Optional[str]]:
        """解析 ``ids`` 里的一项（支持短名 ``obs/13``、``obs/13/fields/x`` 或完整 URI ``trace://...``）。
        返回 ``(block, presented_record_dict, sub_path, error)``。未开放的资源或字段严格报错拦截。
        """
        raw = str(ident or "").strip()
        block: Optional[Block] = None
        req_field = ""
        if "://" in raw:
            try:
                part = self.table.part(raw)
            except ValueError:
                part = None
            if part is not None:
                block, node = part
                kind = TYPES[block.type]
                req_field = kind.field_name(node) if (node and hasattr(kind, "field_name")) else ""
        else:
            block = self.table.by_name(raw)
            if block is None and "/fields/" in raw:
                rec_name, _, field_part = raw.rpartition("/fields/")
                cand = self.table.by_name(rec_name)
                if cand is not None and field_part:
                    block, req_field = cand, field_part
        if block is None:
            return None, None, "", "没有这个编号"
        if block.uri not in self._whole and block.uri not in self._fields:
            return block, None, "", "该资源不在当前已开放范围"
        open_fields: Optional[set[str]] = None if block.uri in self._whole else set(self._fields.get(block.uri, set()))
        if req_field:
            if open_fields is not None and req_field not in open_fields:
                return block, None, "", f"字段 {req_field!r} 不在当前已开放范围"
            raw_fields = (block.body.get("fields") or {}) if isinstance(block.body, Mapping) else {}
            if req_field not in raw_fields:
                return block, None, "", f"记录里没有字段 {req_field!r}"
        record = TYPES[block.type].present(block, open_fields)
        sub_path = f"fields/{req_field}" if req_field else ""
        return block, record, sub_path, None

    def iter_open_records(self) -> list[dict[str, Any]]:
        """供 ``search_material`` 遍历当前已开放的全部资源视图（未开放字段绝不进入）。"""
        out: list[dict[str, Any]] = []
        for u in self._order:
            block = self.table.get(u)
            if block is None:
                continue
            open_fields = None if u in self._whole else set(self._fields.get(u, set()))
            out.append(TYPES[block.type].present(block, open_fields))
        return out
