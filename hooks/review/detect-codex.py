#!/usr/bin/env python3
"""Codex Review Stop Hook — 一轮大量文件修改后触发配置动作。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import detect as claude_detect


PATCH_FILE_RE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: ([^\\\r\n\"]+)")
FAILURE_MARKERS = (
    "script failed",
    "iserror\":true",
    "is_error\":true",
    "permission denied",
    "patch failed",
    "invalid patch",
)


def _read_transcript(path: str) -> list[dict[str, Any]]:
    transcript = Path(path).expanduser()
    if not transcript.is_file():
        return []
    entries: list[dict[str, Any]] = []
    with transcript.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _entry_turn_id(entry: dict[str, Any]) -> str:
    payload = entry.get("payload") or {}
    if entry.get("type") == "turn_context":
        return str(payload.get("turn_id") or "")
    metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
    return str(metadata.get("turn_id") or payload.get("turn_id") or "")


def _slice_turn(entries: list[dict[str, Any]], turn_id: str) -> list[dict[str, Any]]:
    """取指定 turn；缺少 turn_id 时退回最后一个 turn_context 后的记录。"""
    starts = [
        index
        for index, entry in enumerate(entries)
        if entry.get("type") == "turn_context"
        and (not turn_id or _entry_turn_id(entry) == turn_id)
    ]
    if starts:
        start = starts[-1]
        end = len(entries)
        for index in range(start + 1, len(entries)):
            if entries[index].get("type") == "turn_context":
                end = index
                break
        return entries[start:end]
    if turn_id:
        matching = [entry for entry in entries if _entry_turn_id(entry) == turn_id]
        if matching:
            return matching
    return entries


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _apply_patch_count(payload: dict[str, Any], text: str) -> int:
    name = str(payload.get("name") or "")
    if name == "apply_patch":
        return 1
    if name == "exec":
        return text.count("tools.apply_patch(")
    return 0


def _result_success(output: str) -> bool:
    lowered = output.lower().replace(" ", "")
    return not any(marker.replace(" ", "") in lowered for marker in FAILURE_MARKERS)


def _collect_apply_patch_uses(entries: list[dict[str, Any]]) -> list[tuple[list[str], bool]]:
    results: dict[str, bool] = {}
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload") or {}
        if payload.get("type") not in {"function_call_output", "custom_tool_call_output"}:
            continue
        call_id = str(payload.get("call_id") or "")
        if call_id:
            results[call_id] = _result_success(_payload_text(payload, "output"))

    uses: list[tuple[list[str], bool]] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload") or {}
        if payload.get("type") not in {"function_call", "custom_tool_call"}:
            continue
        text = _payload_text(payload, "input") or _payload_text(payload, "arguments")
        count = _apply_patch_count(payload, text)
        if not count:
            continue
        files = [match.strip() for match in PATCH_FILE_RE.findall(text) if match.strip()]
        success = results.get(str(payload.get("call_id") or ""), True)
        for _ in range(count):
            uses.append((files, success))
    return uses


def _codex_reason(config: dict, stats: str, files: list[str]) -> str:
    """Codex 用 reason 作为 Stop 后自动续跑的新用户提示。"""
    return claude_detect._build_review_prompt(config, stats, files)


def main() -> int:
    data = claude_detect._read_stdin()
    try:
        config = claude_detect._load_config()
    except RuntimeError as exc:
        print(json.dumps({"decision": "block", "reason": f"Review hook 配置错误：{exc}"}, ensure_ascii=False))
        return 0

    trigger = config.get("trigger") or {}
    if not trigger.get("enabled", True) or data.get("stop_hook_active"):
        return 0
    transcript_path = str(data.get("transcript_path") or "")
    if not transcript_path:
        return 0

    entries = _slice_turn(_read_transcript(transcript_path), str(data.get("turn_id") or ""))
    uses = _collect_apply_patch_uses(entries)
    successful = [files for files, ok in uses if ok]
    distinct_files = sorted({path for files in successful for path in files})

    min_successful = int(trigger.get("min_successful_edit_tools", 5))
    min_files = int(trigger.get("min_distinct_files", 3))
    if len(successful) < min_successful or len(distinct_files) < min_files:
        return 0

    stats = f"本轮统计：成功 apply_patch 调用 {len(successful)} 次，涉及 {len(distinct_files)} 个不同文件。"
    action = config.get("action") or {}
    output = {
        "decision": str(action.get("decision") or "block"),
        "reason": _codex_reason(config, stats, distinct_files),
        "systemMessage": f"{action.get('title', '大活回顾')}：已触发。{stats}",
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
