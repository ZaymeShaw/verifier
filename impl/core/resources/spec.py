"""地址与资源结构（spec/alg/resources.md §1、§2）。

地址 = MCP 资源的 ``uri``（RFC 3986）：``<前缀>://<路径>``，路径是层级（``/`` 分隔）。
资源有两种形式（MCP）：直接资源（挂载时登记、列表里看得到）与模板资源（资源类型声明地址形状、读时现取）。
JSON Pointer（RFC 6901）只在内部用：记一块正文里某个节点的位置，不出现在地址里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.types import Resource

_SEP = "://"
META_PREFIX = "local.verifier/"   # 我们在 MCP ``_meta`` 里的键名前缀（反向域名写法，local 不与真实域名冲突）
TYPE_KEY = META_PREFIX + "type"


@dataclass(frozen=True)
class Address:
    scheme: str
    path: str

    @classmethod
    def parse(cls, text: str) -> "Address":
        if _SEP not in text:
            raise ValueError(f"不是资源地址（缺 {_SEP}）：{text!r}")
        if "#" in text:
            raise ValueError(f"资源地址不带 #（要更细就用模板资源的地址）：{text!r}")
        scheme, path = text.split(_SEP, 1)
        if not scheme or not path.strip("/"):
            raise ValueError(f"资源地址缺前缀或路径：{text!r}")
        return cls(scheme, path.strip("/"))

    def parent(self) -> "Address | None":
        head, _, _ = self.path.rpartition("/")
        return Address(self.scheme, head) if head else None

    def __str__(self) -> str:
        return f"{self.scheme}{_SEP}{self.path}"


def pointer_join(base: str, key: Any) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{base}/{token}"


def pointer_tokens(pointer: str) -> list[str]:
    if not pointer:
        return []
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer.split("/")[1:]]


@dataclass(frozen=True)
class Block:
    """一块资源 = 描述（MCP ``Resource``）+ 正文。

    能读、能引的全部在正文里（读取时由资源类型序列化成 ``text``）；描述只作目录标签，不能引；
    只给程序用的附加信息（资源类型名、类型参数）放描述的 ``_meta``，键名带 ``META_PREFIX``。
    """
    descriptor: Resource
    body: Any

    @property
    def uri(self) -> str:
        return str(self.descriptor.uri)

    @property
    def type(self) -> str:
        return self.descriptor.meta[TYPE_KEY]

    def meta(self, key: str, default: Any = None) -> Any:
        return (self.descriptor.meta or {}).get(META_PREFIX + key, default)
