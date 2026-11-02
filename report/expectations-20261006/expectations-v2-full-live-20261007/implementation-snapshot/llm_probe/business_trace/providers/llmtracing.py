"""llmtracing 业务 Trace provider：按显式 X-Eval-* 头从中转日志切出本次业务请求的模型调用。

关联方式 A（spec/adapter/business-trace-llmtracing.md §2）：verifier 生成 execution_id 经请求头交给被测系统，
被测系统透传到模型请求，llmtracing 中转把它写进事件级 JSONL。这里只按 execution_id 切片，
不用时间窗、lane 或正文相似度归属。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROVIDER = "llmtracing"
_ID_CHARS = re.compile(r"[^A-Za-z0-9._:-]")
_ID_MAX = 128
# 单次 collect 最多读入的增量字节；共享中转上别的调用方也在写同一文件，超出即判失败而不是无界读。
_MAX_SCAN_BYTES = 256 * 1024 * 1024
_OUTCOMES = ("success", "failure")
_CHAT = "chat_completions"
_PROCESS_RUN_ID = f"verifier-{uuid.uuid4().hex[:12]}"

HEADER_RUN = "X-Eval-Run-Id"
HEADER_CASE = "X-Eval-Case-Id"
HEADER_EXECUTION = "X-Eval-Execution-Id"


def describe() -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "title": "llmtracing 模型中转",
        "summary": "每次业务请求携带 X-Eval-Run/Case/Execution-Id 头，被测系统透传到模型请求；"
                   "响应后从中转 JSONL 日志按 execution_id 切出本次全部模型调用（请求上下文、tools、参数、响应、usage、耗时）。",
        "requirements": "被测系统必须把三个 X-Eval-* 头透传到它发出的模型请求，并经 llmtracing 中转。",
        "evaluation": {
            "view": "transcript",
            "source": "frozen_snapshot",
            "summary": "快照确定性重建为一份按位置编号的线性对话稿，过程六轴直接读全文判定，不经案卷/环节表",
            "exact_model_request": "中转收到的请求消息、tools 与参数；上游实际请求可能经中转策略调整",
        },
        "default_config": {
            "log_path": "/abs/path/to/llmtracing/llm_gateway/logs/llm_calls.jsonl",
            "settle_timeout_seconds": 30,
            "poll_interval_seconds": 1,
            "quiet_seconds": 3,
        },
    }


def _number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"business_trace.config.{field} 必须是数字") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"business_trace.config.{field} 必须在 {minimum:g}–{maximum:g} 之间")
    return number


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    log_path = value.get("log_path")
    if not isinstance(log_path, str) or not Path(log_path).is_absolute():
        raise ValueError("business_trace.config.log_path 必须是中转 JSONL 日志的绝对路径")
    return {
        "log_path": log_path,
        "settle_timeout_seconds": _number(value.get("settle_timeout_seconds", 30), "settle_timeout_seconds", minimum=0, maximum=600),
        "poll_interval_seconds": _number(value.get("poll_interval_seconds", 1), "poll_interval_seconds", minimum=0, maximum=10),
        "quiet_seconds": _number(value.get("quiet_seconds", 3), "quiet_seconds", minimum=0, maximum=120),
    }


def check_connection(config: Mapping[str, Any]) -> dict[str, Any]:
    clean = validate_config(config)
    path = Path(clean["log_path"])
    if not path.is_file():
        raise FileNotFoundError(f"中转日志不存在: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"中转日志不可读: {path}")
    stat = path.stat()
    return {
        "ok": True,
        "provider": PROVIDER,
        "log_path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _clean_id(value: Any, fallback: str) -> str:
    text = _ID_CHARS.sub("_", str(value or "").strip())[:_ID_MAX]
    return text or fallback


def prepare(config: Mapping[str, Any], *, case_id: Any = "", run_id: Any = "") -> dict[str, Any]:
    """发业务请求前：生成本次投递 ID 与请求头，并记下日志当前末尾作为读取起点。"""
    clean = validate_config(config)
    path = Path(clean["log_path"])
    execution_id = uuid.uuid4().hex
    run = _clean_id(run_id, _PROCESS_RUN_ID)
    case = _clean_id(case_id, execution_id)
    return {
        "headers": {HEADER_RUN: run, HEADER_CASE: case, HEADER_EXECUTION: execution_id},
        "association": {
            "method": "explicit_headers",
            "run_id": run,
            "case_id": case,
            "execution_id": execution_id,
            "log_path": str(path),
            "log_offset": path.stat().st_size if path.is_file() else 0,
        },
    }


def read_calls(path: Path, *, start_offset: int, execution_id: str) -> tuple[list[dict[str, Any]], int]:
    """从 start_offset 读完整行，按 call_id 合并本 execution_id 的事件；返回 (calls, 已消费到的字节偏移)。

    只消费以换行结尾的行：中转可能正在写最后一行。事件原样保存，不改写字段。
    """
    size = path.stat().st_size
    if size < start_offset:
        raise RuntimeError("log_truncated: 中转日志在采集期间变短")
    if size - start_offset > _MAX_SCAN_BYTES:
        raise RuntimeError(f"log_scan_limit: 增量 {size - start_offset} 字节超过上限 {_MAX_SCAN_BYTES}")
    with path.open("rb") as source:
        source.seek(start_offset)
        data = source.read(size - start_offset)
    end = data.rfind(b"\n") + 1
    needle = execution_id.encode()
    calls: dict[str, dict[str, Any]] = {}
    for line in data[:end].splitlines():
        if needle not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("execution_id") != execution_id:
            continue
        call_id = str(event.get("call_id") or "")
        if not call_id:
            continue
        slot = calls.setdefault(call_id, {"call_id": call_id, "execution_id": execution_id, "case_id": event.get("case_id")})
        name = event.get("event")
        if name == "pre_api_call":
            slot["pre"] = event
        elif name == "first_frame":
            slot["first_frame"] = event
        elif name in _OUTCOMES:
            slot["outcome"] = event
    ordered = sorted(calls.values(), key=lambda c: str((c.get("pre") or c.get("outcome") or {}).get("ts") or ""))
    return ordered, start_offset + end


def limitations(calls: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """这份快照固定看不到什么：评测据此区分"没发生"与"看不到"。"""
    protocols: dict[str, int] = {}
    for call in calls:
        pre = call.get("pre") if isinstance(call.get("pre"), Mapping) else {}
        outcome = call.get("outcome") if isinstance(call.get("outcome"), Mapping) else {}
        protocol = str(pre.get("protocol") or outcome.get("protocol") or "unknown")
        protocols[protocol] = protocols.get(protocol, 0) + 1
    non_chat = {p: n for p, n in protocols.items() if p != _CHAT}
    out = {
        "visibility": {"status": "partial", "reason": "只包含经 llmtracing 中转且带本次 execution_id 的模型调用；"
                       "业务内部非模型步骤（路由、闸门、直连后端、结果组装）、工具在业务侧的执行细节、session/memory 不可见"},
        "unattributed_calls": {"status": "unverified", "reason": "被测系统未透传 X-Eval-* 头的模型调用落为未归属，不在本快照中"},
        "post_response_calls": {"status": "unverified", "reason": "业务响应返回后才发起的模型调用只在 quiet 窗口内被等待，不能证明没有"},
        "upstream_request": {"status": "unverified", "reason": "记录的是中转收到的请求；上游实际请求可能经 thinking 策略与 drop_params 调整"},
        "tool_call_parsing": ({"status": "partial", "reason": f"仅解析 {_CHAT} 的工具调用；其他协议只保留原文",
                               "protocols": non_chat} if non_chat else {"status": "complete", "protocols": protocols}),
    }
    if not calls:
        out["no_calls"] = {"status": "unverified", "reason": "未切到任何模型调用：可能业务本轮未调用模型，也可能透传失效"}
    return out


def _open_calls(calls: list[Mapping[str, Any]]) -> list[str]:
    return [c["call_id"] for c in calls if "outcome" not in c]


def collect(config: Mapping[str, Any], *, request: Mapping[str, Any], response: Any,
            association: Mapping[str, Any] | None = None,
            clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    clean = validate_config(config)
    base = {
        "schema_version": 1,
        "provider": PROVIDER,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "association": dict(association or {}),
        "coverage": {},
        "records": {"calls": []},
        "refs": [],
        "errors": [],
    }
    if not association or not association.get("execution_id"):
        return base | {"status": "failed", "errors": ["association_missing: 请求前未执行 prepare，无法按 execution_id 切片"]}
    execution_id = str(association["execution_id"])
    case_id = str(association.get("case_id") or "")
    path = Path(clean["log_path"])
    try:
        start = int(association.get("log_offset") or 0)
        deadline = clock() + clean["settle_timeout_seconds"]
        last_change = clock()
        seen = -1
        while True:
            calls, consumed = read_calls(path, start_offset=start, execution_id=execution_id)
            now = clock()
            if len(calls) != seen:
                seen, last_change = len(calls), now
            settled = not _open_calls(calls) and now - last_change >= clean["quiet_seconds"]
            if settled or now >= deadline:
                break
            sleep(clean["poll_interval_seconds"])
    except Exception as exc:
        return base | {"status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}
    errors = []
    mismatched = sorted({str(c.get("case_id")) for c in calls if case_id and c.get("case_id") not in (None, case_id)})
    if mismatched:
        errors.append(f"case_id_mismatch: execution_id 属于 {', '.join(mismatched)}，预期 {case_id}")
    open_calls = _open_calls(calls)
    if open_calls:
        errors.append(f"calls_unfinished: {', '.join(open_calls)}")
    missing_pre = [c["call_id"] for c in calls if "pre" not in c]
    if missing_pre:
        errors.append(f"pre_api_call_missing: {', '.join(missing_pre)}")
    snapshot = base | {
        "status": "failed" if mismatched else ("partial" if open_calls or missing_pre else "succeeded"),
        "association": base["association"] | {"log_offset_end": consumed, "matched_call_count": len(calls)},
        "records": {"calls": calls},
        "refs": [{"kind": "gateway_call", "id": c["call_id"], "log_path": str(path)} for c in calls],
        "errors": errors,
    }
    snapshot["fingerprint"] = hashlib.sha256(
        json.dumps(snapshot["records"], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    snapshot["coverage"] = {"calls": len(calls), "limitations": limitations(calls)}
    return snapshot


__all__ = [
    "HEADER_CASE", "HEADER_EXECUTION", "HEADER_RUN",
    "check_connection", "collect", "describe", "limitations", "prepare", "read_calls", "validate_config",
]
