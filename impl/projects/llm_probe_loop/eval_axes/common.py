"""评测轴结果的状态与失败分类（报告与判官共用；取值同 llm_probe，前端与汇总照读）。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# 失败原因前缀：前端「补跑执行失败」按它挑（同 llm_probe 的 eval_axes）。
FAILURE_ENVIRONMENT = "[运行环境]"
FAILURE_AXIS = "[轴实现]"


class AxisRequestFailed(RuntimeError):
    """请求层失败：complete_json 对鉴权/限流/网络等请求错误返回 {"error", "raw_text"} 而不抛异常。"""

    def __init__(self, error: str, raw_text: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.raw_text = raw_text


def raise_for_error_payload(raw: Any) -> None:
    """complete_json 请求层失败返回 error dict（不抛异常）；把它当模型输出会伪装成格式错误。"""
    if isinstance(raw, Mapping) and "error" in raw:
        raise AxisRequestFailed(str(raw["error"]), str(raw.get("raw_text") or ""))
