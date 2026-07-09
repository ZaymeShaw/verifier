#!/usr/bin/env python3
"""测试 detect.py 的 transcript 读取 + 切片 + 计数逻辑。

模拟 Claude Code 真实流程：
  1. 构造 JSONL transcript 文件（模拟 transcript_path 指向的文件）
  2. 构造 Stop hook stdin JSON（含 transcript_path 字段）
  3. 通过 subprocess 调 detect.py，传入 stdin，验证触发/不触发

需要临时 JSONL 文件，测试结束后自动清理。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DETECT = SCRIPT_DIR / "detect.py"


def _run_detect(stdin_data: dict) -> dict | None:
    """通过 subprocess 调 detect.py，传入 JSON stdin，返回 stdout JSON 或 None。"""
    proc = subprocess.run(
        [sys.executable, str(DETECT)],
        input=json.dumps(stdin_data, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=5,
    )
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        print(f"  [WARN] 非 JSON 输出: {out}")
        return None


def make_jsonl_entry(role: str, content: list[dict]) -> dict:
    """构造一条 JSONL 行（与 Claude Code transcript 格式一致）。"""
    return {"type": "message", "role": role, "content": content}


def make_tool_use(name: str, tool_id: str, file_path: str, **extra) -> dict:
    """构造一个 assistant 的 tool_use 消息。"""
    inp = {"file_path": file_path, **extra}
    if name == "NotebookEdit":
        inp["notebook_path"] = file_path
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tool_id, "name": name, "input": inp}
        ],
    }


def make_tool_result(tool_id: str, success: bool) -> dict:
    """构造一个 user 的 tool_result 消息。"""
    if success:
        content = "文件已更新。"
    else:
        content = "Error: old_string not found in file"
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": [{"type": "text", "text": content}]}
        ],
    }


def make_user_message(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def write_transcript(tmpdir: str, entries: list[dict]) -> str:
    """写 JSONL 文件，返回路径。"""
    path = Path(tmpdir) / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(path)


def run_case(tag: str, entries: list[dict], expect_block: bool, expect_desc: str, **kwargs):
    with tempfile.TemporaryDirectory() as tmpdir:
        transcript_path = write_transcript(tmpdir, entries)
        stdin = {
            "session_id": "test-session",
            "transcript_path": transcript_path,
            "cwd": str(SCRIPT_DIR),
            "stop_hook_active": kwargs.get("stop_hook_active", False),
        }
        result = _run_detect(stdin)
        blocked = result is not None and result.get("decision") == "block"
        status = "✅" if blocked == expect_block else "❌"
        print(f"{status} {tag}")
        if blocked != expect_block:
            print(f"   期望 block={expect_block}，实际 block={blocked}")
            if result:
                print(f"   实际输出: {json.dumps(result, ensure_ascii=False)[:200]}")
        elif blocked:
            reason = result.get("reason", "") if result else ""
            print(f"   触发: {reason[:120]}")
        else:
            print(f"   静默放行")


# =========================
# 测试用例
# =========================

# 1. 不达阈值：只有 2 次成功 Edit，改 2 个文件
run_case(
    "1. 不达阈值（2次/2文件）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "改一下 a.py 和 b.py"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=False,
    expect_desc="2次成功，2个文件，都不过阈值",
)

# 2. 达阈值：6 次成功 Edit，改 4 个不同文件
run_case(
    "2. 达阈值（6次/4文件）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "重构整个项目"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t6", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t6", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="6次成功，4个文件，都过阈值",
)

# 3. 失败重试不算
run_case(
    "3. 失败不算（5成功+3失败，3文件）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "改多个文件"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "a.py", "old_string": "wrong"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "Error: old_string not found"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "b.py", "old_string": "wrong"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "Error: failed"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Write", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t6", "name": "Edit", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t6", "content": [{"type": "text", "text": "Error: denied"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t7", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t7", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t8", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t8", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="5成功+3失败，3文件，成功够、文件够 → 触发",
)

# 4. 够次数但文件不够（6次/2文件）
run_case(
    "4. 够次数文件不够（6次/2文件）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "反复改同一个文件"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t6", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t6", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=False,
    expect_desc="6次成功但只2个文件，不过文件数阈值",
)

# 5. 跨轮：上一轮有改动，本轮只有 2 次
run_case(
    "5. 跨轮切片（本轮2次，不触发）",
    [
        # 上一轮
        make_jsonl_entry("user", [{"type": "text", "text": "上一轮：改很多文件"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_old1", "name": "Edit", "input": {"file_path": "x.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_old1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_old2", "name": "Edit", "input": {"file_path": "y.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_old2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_old3", "name": "Edit", "input": {"file_path": "z.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_old3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_old4", "name": "Write", "input": {"file_path": "w.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_old4", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_old5", "name": "Edit", "input": {"file_path": "v.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_old5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        # 本轮
        make_jsonl_entry("user", [{"type": "text", "text": "本轮：小修"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_new1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_new1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t_new2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t_new2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=False,
    expect_desc="上一轮5次3文件，本轮只有2次，切片后不触发",
)

# 6. MultiEdit 和 NotebookEdit 也计入
run_case(
    "6. MultiEdit/NotebookEdit 计入",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "各种方式改文件"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "MultiEdit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "NotebookEdit", "input": {"notebook_path": "nb.ipynb"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "单元格已替换。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Write", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "e.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="5次成功（MultiEdit/NotebookEdit/Edit/Write），5个文件",
)

# 7. 防死循环：stop_hook_active=true
run_case(
    "7. 防死循环（stop_hook_active=true）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "大改动"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "e.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=False,
    expect_desc="够阈值但 stop_hook_active=true，放行",
    stop_hook_active=True,
)

# 8. 全是失败
run_case(
    "8. 全是失败",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "改很多但全都失败"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "Error: failed"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "Error: not found"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "Error: denied"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "Error: failed"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "e.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "Error: failed"}]}]),
    ],
    expect_block=False,
    expect_desc="5次全部失败，成功0次，不触发",
)

# 9. 无真实用户消息（全是 tool_result 链）
run_case(
    "9. 无真实用户消息",
    [
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Write", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "e.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="无真实用户消息，兜底返回全部，5次成功5文件 → 触发",
)

# 10. 边界：刚好 5 次成功 + 3 文件
run_case(
    "10. 边界（刚好5次/3文件）",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "刚好到阈值"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="刚好5次成功，3文件，触发",
)
# 11. 自动压缩 summary 不切断本轮工具统计
run_case(
    "11. 自动压缩 summary 不切断统计",
    [
        make_jsonl_entry("user", [{"type": "text", "text": "大改动，过程中触发自动压缩"}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "b.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry(
            "user",
            [
                {
                    "type": "text",
                    "text": "This session is being continued from a previous conversation that ran out of context.\n\nSummary:\nEarlier edits happened.\n\nContinue the conversation from where it left off without asking the user any further questions.",
                }
            ],
        ),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": "c.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t3", "content": [{"type": "text", "text": "文件已写入。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "d.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t4", "content": [{"type": "text", "text": "文件已更新。"}]}]),
        make_jsonl_entry("assistant", [{"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "e.py"}}]),
        make_jsonl_entry("user", [{"type": "tool_result", "tool_use_id": "t5", "content": [{"type": "text", "text": "文件已更新。"}]}]),
    ],
    expect_block=True,
    expect_desc="自动压缩 summary 不算真实用户消息，压缩前后5次成功5文件 → 触发",
)


print("\n--- 全部测试完成 ---")