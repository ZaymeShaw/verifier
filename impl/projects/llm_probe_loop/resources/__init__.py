"""资源层·登记的类型（spec/alg/resources.md §10.1）：源数据的组织方式，正文长相复用框架的记录集。"""
from . import case_trace

REGISTRY = {"case_trace": case_trace}

__all__ = ["REGISTRY", "case_trace"]
