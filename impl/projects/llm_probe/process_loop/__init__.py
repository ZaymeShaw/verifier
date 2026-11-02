"""分析轴（案卷整理）的 ToolLoop：Analysis 子 loop 与其取证工具。

六轴评判已改为本应 / 实际两次调用（eval_axes/adapters/process_expected.py），不再走 ToolLoop。
"""
from .analysis import Analysis

__all__ = ["Analysis"]
