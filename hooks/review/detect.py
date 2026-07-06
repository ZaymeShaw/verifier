#!/usr/bin/env python3
"""Review Stop Hook — 大活后捕获实施过程中的不确定点。

工作方式：从 transcript_path 文件读取本轮对话的 JSONL 记录，
遍历工具调用以计数成功的 Edit/MultiEdit/Write/NotebookEdit 次数和去重文件路径。

触发条件（两个都满足）：
  1. 成功的 Edit/MultiEdit/Write/NotebookEdit 次数 ≥ MIN_SUCCESSFUL_EDITS
  2. 成功改动的不同文件路径数 ≥ MIN_DISTINCT_FILES

触发后：block 一次，注入 systemMessage 让助理主动披露本轮最没把握的实施细节。

防死循环：若 stop_hook_active=true，直接放行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# =========================
# 阈值配置（顶部变量，方便调）
# =========================
MIN_SUCCESSFUL_EDITS = 5      # 本轮成功 Edit/MultiEdit/Write/NotebookEdit 次数下限
MIN_DISTINCT_FILES = 3        # 本轮成功改动不同文件路径数下限
ENABLED = True                # 总开关，调试时可关
DEBUG_DUMP = False            # True 时把 stdin 原样落盘到 DEBUG_DUMP_PATH，便于核对格式
DEBUG_DUMP_PATH = "/tmp/review-hook-stdin.json"

# 改文件的工具集合
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}

# 哪些工具部分在 tool_use 的 input 里有 file_path
TOOL_FILE_PATH_KEYS = {
    "Edit": "file_path", "MultiEdit": "file_path", "Write": "file_path",
    "NotebookEdit": "notebook_path",
}


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _read_transcript(path: str) -> list[dict]:
    """从 transcript_path 读 JSONL 文件，返回 messages 列表。"""
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    messages: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # JSONL 每行可能是 {"type":"message", "role":"user", "content":[...]}
            # 或直接是 message 行
            msg_type = entry.get("type", "")
            if msg_type == "message" or msg_type == "":
                role = entry.get("role", "")
                if role and role in ("user", "assistant", "system"):
                    messages.append(entry)
            # 也可能是 {"type":"init", ...} 等，跳过
    return messages


def _is_tool_result_success(content: list[dict]) -> bool:
    """看 tool_result 的 content 列表，有 isError 或 error 字符串则失败。"""
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("is_error") or item.get("isError"):
            return False
        text = item.get("text", "")
        if isinstance(text, str):
            t = text.lower()
            if any(k in t for k in ("error", "failed", "not found", "denied", "is_error")):
                return False
        result = item.get("result", "")
        if isinstance(result, str):
            t = result.lower()
            if any(k in t for k in ("error", "failed", "not found", "denied", "is_error")):
                return False
    return True


def _is_user_message(msg: dict) -> bool:
    """判断是否真实用户消息（非 tool_result 回执）。"""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return True
    # 纯 tool_result 的 user 消息不算"真实用户输入"
    if content and all(
        isinstance(c, dict) and c.get("type") == "tool_result" for c in content
    ):
        return False
    return True


def _slice_current_turn(messages: list[dict]) -> list[dict]:
    """切出"本轮"窗口：从最后一条真实用户消息开始到末尾。"""
    if not messages:
        return []
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if _is_user_message(messages[i]):
            last_user_idx = i
            break
    if last_user_idx < 0:
        return messages
    return messages[last_user_idx:]


def _collect_edit_tool_uses(messages: list[dict]) -> list[tuple[str, str, bool]]:
    """从窗口里收集改文件工具调用，返回 [(tool_name, file_path, success), ...]。"""
    # 先用 tool_use_id -> 对应的 result 是否成功，建立映射
    tool_results: dict[str, bool] = {}
    for msg in messages:
        if msg.get("role") != "user":
            continue
        for item in msg.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_result":
                tid = item.get("tool_use_id", "")
                if tid:
                    result_content = item.get("content")
                    if isinstance(result_content, list):
                        tool_results[tid] = _is_tool_result_success(result_content)
                    else:
                        tool_results[tid] = True  # 没有 content 列表就默认成功

    out: list[tuple[str, str, bool]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "tool_use":
                continue
            name = item.get("name", "")
            if name not in EDIT_TOOLS:
                continue
            inp = item.get("input") or {}
            # 不同工具的文件路径字段
            key = TOOL_FILE_PATH_KEYS.get(name, "file_path")
            fpath = inp.get(key) or inp.get("file_path") or inp.get("notebook_path") or ""
            tid = item.get("id", "")
            success = tool_results.get(tid, True)
            out.append((name, str(fpath), success))
    return out


def _load_prompt() -> str:
    """读取注入给助理的 prompt 文本。"""
    p = Path(__file__).parent / "prompt.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return (
            "本轮你做了大量改动。请主动披露本轮实施过程中你最没把握的点："
            "具体到某个改动 + 为什么没把握。若真没有，直说没有，不要硬凑。"
        )


def main() -> int:
    data = _read_stdin()

    if DEBUG_DUMP:
        try:
            Path(DEBUG_DUMP_PATH).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    if not ENABLED:
        return 0

    # 防死循环：block 后 Claude Code 重入会带 stop_hook_active=true
    if data.get("stop_hook_active"):
        return 0

    # 从 transcript_path 读 JSONL
    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        return 0  # 没有 transcript_path，无法计数，静默放行

    messages = _read_transcript(transcript_path)
    if not messages:
        return 0

    # 切本轮，收集工具调用
    window = _slice_current_turn(messages)
    edits = _collect_edit_tool_uses(window)
    successful = [(name, fp) for (name, fp, ok) in edits if ok]
    distinct_files = {fp for (_n, fp) in successful if fp}

    if len(successful) < MIN_SUCCESSFUL_EDITS or len(distinct_files) < MIN_DISTINCT_FILES:
        return 0  # 不达阈值，静默放行

    # 达阈值：block 一次，注入 prompt 让助理主动披露
    prompt = _load_prompt()
    stats = f"本轮统计：成功改文件工具调用 {len(successful)} 次，涉及 {len(distinct_files)} 个不同文件。"
    output = {
        "decision": "block",
        "reason": f"📋 大活回顾：{stats}请在本轮回复末尾主动披露你最没把握的实施细节。",
        "systemMessage": prompt,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())