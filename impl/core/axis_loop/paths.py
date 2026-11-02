"""点路径：`a.b[].c`，可带元素筛选 `a[id=x,y]` 与字段投影 `{x, y}`（spec/alg/axis_loop.md §4.2、§7.2）。

写法沿用 eval_axes 的 item_path：`列表[]` 表示对列表逐项往下取；`列表[字段=值1,值2]` 表示只取这个字段
等于这些值的元素再逐项往下取（分发脚本按它给每份子 loop 列选择）。
三件事：对值取数（extract / values）、按选择裁剪但保留结构（prune，给代码看）、对 JSON Schema 做静态检查。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Sequence

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_SEGMENT = re.compile(rf"({_NAME})(?:\[(?:({_NAME})=([^\[\]]*))?\])?")


@dataclass(frozen=True)
class Segment:
    key: str
    each: bool                      # 带 [] 或 [字段=…]：这一层是列表，逐项往下
    where: str = ""                 # 筛选字段
    values: tuple[str, ...] = ()    # 筛选取值

    def keep(self, item: Any) -> bool:
        return not self.where or (isinstance(item, Mapping) and str(item.get(self.where)) in self.values)

    def __str__(self) -> str:
        if self.where:
            return f"{self.key}[{self.where}={','.join(self.values)}]"
        return self.key + ("[]" if self.each else "")


@dataclass(frozen=True)
class Path:
    segments: tuple[Segment, ...]
    fields: tuple[str, ...] = ()  # 末尾投影；空 = 取整个值

    def __str__(self) -> str:
        text = ".".join(map(str, self.segments))
        if self.fields:
            text = (text + "." if text else "") + "{" + ", ".join(self.fields) + "}"
        return text


def _split(text: str) -> list[str]:
    """按 . 切段，[] 与 {} 里的 . 不切（筛选值里常有 t1.user 这种）。"""
    parts, depth, current = [], 0, []
    for ch in text:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "." and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p for p in parts if p != ""] if text else []


def parse(text: str) -> Path:
    """`a.b[].c` / `a[id=x,y].c` / `a[].{x, y}` / `` → Path。写法不对抛 ValueError。"""
    raw = str(text or "").strip()
    parts = _split(raw)
    fields: tuple[str, ...] = ()
    if parts and parts[-1].startswith("{"):
        inner = parts.pop()
        if not inner.endswith("}"):
            raise ValueError(f"字段投影写法不对：{text!r}")
        fields = tuple(f.strip() for f in inner[1:-1].split(","))
        if not fields or any(not re.fullmatch(_NAME, f) for f in fields):
            raise ValueError(f"字段投影写法不对：{text!r}")
    segments = []
    for part in parts:
        match = _SEGMENT.fullmatch(part)
        if not match:
            raise ValueError(f"路径写法不对：{text!r}（段 {part!r}）")
        key, where, values = match.group(1), match.group(2) or "", match.group(3)
        each = part.endswith("]")
        vals = tuple(v.strip() for v in values.split(",") if v.strip()) if where else ()
        if where and not vals:
            raise ValueError(f"元素筛选至少写一个取值：{text!r}")
        segments.append(Segment(key, each, where, vals))
    return Path(tuple(segments), fields)


def _project(value: Any, fields: Sequence[str]) -> Any:
    if not fields or not isinstance(value, Mapping):
        return value
    return {f: value.get(f) for f in fields}


def extract(value: Any, path: Path) -> Any:
    """按路径取出一份保持形状的值：经过 `[]` 的层仍是列表（筛选后只剩匹配的元素）；末尾按投影裁字段。缺的键取 None。"""

    def walk(current: Any, rest: Sequence[Segment]) -> Any:
        if not rest:
            return _project(current, path.fields)
        head, tail = rest[0], rest[1:]
        child = current.get(head.key) if isinstance(current, Mapping) else None
        if head.each:
            return [walk(item, tail) for item in (child if isinstance(child, list) else []) if head.keep(item)]
        return walk(child, tail)

    return walk(value, path.segments)


def values(value: Any, path: Path) -> list[Any]:
    """按路径取出的全部末端值，摊平成一个列表（校验比集合时用）。"""
    out: list[Any] = []

    def flatten(item: Any, depth: int) -> None:
        if depth and isinstance(item, list):
            for entry in item:
                flatten(entry, depth - 1)
        else:
            out.append(item)

    flatten(extract(value, path), sum(s.each for s in path.segments))
    return out


def prune(value: Any, path: Path) -> Any:
    """按选择裁剪但保留原结构：只应用元素筛选，不投影、不下钻（代码按原结构的路径读）。"""

    def walk(current: Any, rest: Sequence[Segment]) -> Any:
        if not rest or not isinstance(current, Mapping):
            return current
        head, tail = rest[0], rest[1:]
        if head.key not in current:
            return current
        child = current[head.key]
        if head.each and isinstance(child, list):
            child = [walk(item, tail) for item in child if head.keep(item)]
        elif not head.each:
            child = walk(child, tail)
        return {**current, head.key: child}

    return walk(value, path.segments)


def _resolve(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    # 只认本仓库生成的 schema 形状：object.properties / array.items；不展开 $ref。
    return schema if isinstance(schema, Mapping) else {}


def check_schema(schema: Mapping[str, Any], path: Path) -> Optional[str]:
    """路径在 schema 里走得通吗；走不通返回原因。"""
    current = _resolve(schema)
    for segment in path.segments:
        props = current.get("properties") if isinstance(current.get("properties"), Mapping) else {}
        if segment.key not in props:
            return f"{path}：{segment.key} 不在 schema 里（可用：{', '.join(sorted(props)) or '无'}）"
        current = _resolve(props[segment.key])
        if segment.each:
            if current.get("type") != "array":
                return f"{path}：{segment.key} 不是列表，不能写 []"
            current = _resolve(current.get("items"))
            if segment.where:
                item_props = current.get("properties") if isinstance(current.get("properties"), Mapping) else {}
                if segment.where not in item_props:
                    return f"{path}：筛选字段 {segment.where} 不在 {segment.key} 的元素里"
        elif current.get("type") == "array" and segment is not path.segments[-1]:
            return f"{path}：{segment.key} 是列表，往下取要写 {segment.key}[]"
    if path.fields:
        props = current.get("properties") if isinstance(current.get("properties"), Mapping) else {}
        missing = [f for f in path.fields if f not in props]
        if missing:
            return f"{path}：投影字段 {missing} 不在 schema 里（可用：{', '.join(sorted(props)) or '无'}）"
    return None
