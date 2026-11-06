"""资源类型登记（spec/alg/resources.md §3）：类型全部由框架提供、与业务无关。试点只有记录集。"""
from .record_set import RecordSet

TYPES = {RecordSet.name: RecordSet()}

__all__ = ["TYPES", "RecordSet"]
