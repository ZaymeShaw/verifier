"""Optional project display policy. Read only at display/export time, never by evaluation."""
from __future__ import annotations

import json
from collections.abc import Callable

from .capability_store import PROJECT_PATTERN
from .instances import data_root


def load_axis_display(project: str, describe_axes: Callable[[], list[dict]]) -> dict:
    if not PROJECT_PATTERN.fullmatch(project):
        raise ValueError(f"非法 project id: {project!r}")
    path = data_root() / project / "axis_display.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"axes": {}}
    try:
        policy = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"axis_display.json 不是有效 JSON：{exc}") from exc
    if not isinstance(policy, dict) or set(policy) != {"axes"} or not isinstance(policy["axes"], dict):
        raise ValueError('axis_display.json 必须是 {"axes": {轴ID: 配置}}')
    if not policy["axes"]:
        return policy
    types = {axis["type_id"]: axis for axis in describe_axes()}
    for axis_id, config in policy["axes"].items():
        if axis_id not in types:
            raise ValueError(f"axis_display.json：未知轴 {axis_id!r}")
        if not isinstance(config, dict) or set(config) != {"attention_verdicts"}:
            raise ValueError(f"axis_display.json：{axis_id} 只允许 attention_verdicts")
        values = config["attention_verdicts"]
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError(f"axis_display.json：{axis_id}.attention_verdicts 必须是字符串数组")
        if len(set(values)) != len(values):
            raise ValueError(f"axis_display.json：{axis_id}.attention_verdicts 有重复值")
        allowed = {v["value"] for v in types[axis_id]["verdict_enum"]}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"axis_display.json：{axis_id} 未声明 verdict {sorted(unknown)}")
    return policy
