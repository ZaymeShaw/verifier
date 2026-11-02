"""完成后的结果提取策略。只提取 History，不驱动模型或修改完成决定。"""
from __future__ import annotations

from typing import Any, Callable

from .hooks import is_accepted
from .types import Call, History


def last_assistant_text(history: History) -> str:
    for message in reversed(history.messages):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return ""


def take_accepted(*tools: str, accepted: Callable[[Call], bool] = is_accepted) -> Callable[[History], Any]:
    """end：返回每个 tool 最后一次被接受调用的参数；只给一个 tool 时直接返回它的参数。"""

    def end(history: History) -> Any:
        values = {}
        for tool in tools:
            hits = [c for c in history.of(tool) if c.ok and accepted(c)]
            values[tool] = hits[-1].args if hits else None
        return values[tools[0]] if len(tools) == 1 else values

    return end
