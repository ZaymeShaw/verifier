"""资源与引用（spec/alg/resources.md）：地址、规范文本、资源类型（长相）、资源表、引用核对。

资源的描述、模板与读取结果用 MCP 的数据结构（``mcp.types``）；规范文本的区间、引用核对是在其上的扩展。
不认识任何项目、信息源、材料：资源由声明了资源的材料挂进来（axis_loop 材料表，§10.3）。
"""
from .cite import CiteResult, Region, cite
from .mount import ResourceTable
from .spec import META_PREFIX, Address, Block
from .types import TYPES
from .types.record_set import Place

__all__ = ["Address", "Block", "CiteResult", "META_PREFIX", "Region", "ResourceTable", "Place", "TYPES", "cite"]
