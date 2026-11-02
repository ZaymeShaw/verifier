"""验收流水线（spec/alg/axis_loop.md §5.3）：一次提交依次过 schema → 标准校验 → 自定义校验 → 合成。

任一步不过就拒，并把这一步的全部原因交回给模型。合成出错或合成结果不合 schema 是评测器自己的 bug：
抛 SynthesisError，由调用方中止整个 loop，不打回给模型（demand/axis_loop.md §3.2.8）。

分条交（per_item）：分项单独交、单独验收；同一分项再交就替换前一次（改错只重交那一条）。
收尾交 verdict / reason 等模型填的部分，own 里带上全部已接受分项，再跑收尾的校验与合成。

说明回合（§5.3 第 6 步）：合成出的 x-explain 字段和上一次回给模型的不同，就先不收，回给模型看；
相同（模型看过这份结论后再交）才收下。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from jsonschema import Draft202012Validator

from . import checks as standard
from .definitions import FILL_PROGRAM, SUBMIT_PER_ITEM, Code, Work
from .view import TaskView

STAGE_ITEM, STAGE_FINAL = "item", "final"


class SynthesisError(RuntimeError):
    """合成程序出错或结果不合 schema：评测器 bug。"""


@dataclass
class Submissions:
    """一个任务（或一次子 loop 调用）的提交状态。"""

    items: dict[str, Mapping[str, Any]] = field(default_factory=dict)  # item_id → 分项（含 item_key）
    result: Optional[Mapping[str, Any]] = None                         # 被接受的完整结果
    explained: Optional[Mapping[str, Any]] = None                      # 上一次回给模型看的程序结论

    def reset(self) -> None:
        self.items.clear()
        self.result = None
        self.explained = None


@dataclass(frozen=True)
class Outcome:
    accepted: bool
    reasons: tuple[str, ...] = ()
    result: Optional[Mapping[str, Any]] = None  # 收尾被接受时的完整结果
    explain: Optional[Mapping[str, Any]] = None  # 说明回合：先不收，回给模型看的程序结论


def schema_errors(schema: Mapping[str, Any], payload: Any) -> list[str]:
    validator = Draft202012Validator(_strip_fill(schema))
    out = []
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        where = ".".join(str(p) for p in error.absolute_path) or "（顶层）"
        out.append(f"{where}: {error.message}")
    return out


def _strip_fill(schema: Any) -> Any:
    if isinstance(schema, Mapping):
        return {k: _strip_fill(v) for k, v in schema.items() if k not in ("x-fill", "x-explain")}
    if isinstance(schema, list):
        return [_strip_fill(v) for v in schema]
    return schema


def _pick(value: Any, keys: Any) -> Any:
    """x-explain 为键列表时只回这些键：对象取键，对象列表逐个取。"""
    if keys is True:
        return value
    if isinstance(value, Mapping):
        return {k: value[k] for k in keys if k in value}
    if isinstance(value, list):
        return [_pick(v, keys) for v in value]
    return value


def explain_text(task: str, shown: Mapping[str, Any]) -> str:
    """说明回合回给模型的话（§5.3 第 6 步）。"""
    body = json.dumps(shown, ensure_ascii=False, indent=1)
    return (f"submit（{task}）先不收：程序按你交的内容算出了下面的结论。\n{body}\n"
            "reason 写最终结论为什么是这样，包括程序算出的部分；认为程序结果、或它依据的上游结论不对，"
            "在 reason 里写明依据挑战（结论不会因此改）。改好再交一次。")


def part_work(work: Work) -> Work:
    """分发出去的一份：只交模型填的字段、只跑自定义校验，不合成（合成在各份收齐后对整个轴做一次）。"""
    props = {k: v for k, v in (work.output.get("properties") or {}).items() if work.fill(k) != FILL_PROGRAM}
    required = [k for k in work.output.get("required") or [] if k in props]
    return replace(work, output={**work.output, "properties": props, "required": required},
                   code=Code(check=work.code.check))


def item_payload_schema(work: Work) -> dict[str, Any]:
    """分项提交的 schema：分项编号由 submit 的 item_id 给，不在 payload 里重复写。"""
    schema = work.item_schema()
    key = work.item_key
    return {**schema, "properties": {k: v for k, v in (schema.get("properties") or {}).items() if k != key},
            "required": [k for k in schema.get("required") or [] if k != key]}


def _run_checks(work: Work, stage: str, view: TaskView, scope: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    for use in work.checks:
        if use.params.get("on", STAGE_FINAL) == stage:
            problems += standard.run(use.name, use.params, view, scope)
    return problems


def submit(work: Work, state: Submissions, payload: Any, item_id: Optional[str],
           make_view: Callable[[str, Mapping[str, Any]], TaskView]) -> Outcome:
    """make_view(stage, own) 由调用方按白名单与调用记录组装视图。"""
    if not isinstance(payload, Mapping):
        return Outcome(False, ("payload 必须是 JSON 对象",))
    per_item = work.submit == SUBMIT_PER_ITEM
    if item_id is not None and not per_item:
        return Outcome(False, (f"{work.id} 一次交齐，不能带 item_id",))
    if item_id is not None:
        if not isinstance(item_id, str) or not item_id.strip():
            return Outcome(False, ("item_id 必须是非空字符串",))
        scope = {**payload, work.item_key: item_id}
        problems = schema_errors(item_payload_schema(work), dict(payload))
        if not problems:
            view = make_view(STAGE_ITEM, scope)
            problems = _run_checks(work, STAGE_ITEM, view, scope)
            if not problems and work.code.check:
                problems = list(work.code.check(view) or [])
        if problems:
            return Outcome(False, tuple(problems))
        state.items[item_id] = scope
        state.result = None  # 分项变了，收尾要重交
        return Outcome(True)

    own = dict(payload)
    problems = schema_errors(work.model_schema(), own)
    if per_item:
        own[work.items_field] = list(state.items.values())
    if not problems:
        view = make_view(STAGE_FINAL, own)
        problems = _run_checks(work, STAGE_FINAL, view, own)
        if not problems and work.code.check:
            problems = list(work.code.check(view) or [])
    if problems:
        return Outcome(False, tuple(problems))
    result = dict(own)
    if work.program_fields:
        try:
            filled = work.code.synthesize(view)
        except Exception as exc:  # 合成出错：评测器 bug
            raise SynthesisError(f"{work.id}: synth.py 出错：{type(exc).__name__}: {exc}") from exc
        if not isinstance(filled, Mapping) or set(filled) != set(work.program_fields):
            got = sorted(filled) if isinstance(filled, Mapping) else type(filled).__name__
            raise SynthesisError(f"{work.id}: synth.py 必须恰好返回程序填的字段 {list(work.program_fields)}，得到 {got}")
        result.update(filled)
    full = schema_errors(work.output, result)
    if full:
        raise SynthesisError(f"{work.id}: 完整结果不合输出 schema：" + "；".join(full[:5]))
    shown = {name: _pick(result[name], keys) for name, keys in work.explained_fields.items()}
    if shown and shown != state.explained:
        state.explained = shown
        return Outcome(False, explain=shown)
    state.result = result
    return Outcome(True, result=result)
