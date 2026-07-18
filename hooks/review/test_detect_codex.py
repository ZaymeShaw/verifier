#!/usr/bin/env python3
"""detect-codex.py 的 Codex transcript 离线测试。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DETECT = SCRIPT_DIR / "detect-codex.py"


def turn_context(turn_id: str) -> dict:
    return {"type": "turn_context", "payload": {"turn_id": turn_id}}


def patch_call(call_id: str, files: list[str], *, code_mode: bool = True) -> dict:
    patch = "*** Begin Patch\\n" + "".join(f"*** Update File: {path}\\n@@\\n-old\\n+new\\n" for path in files) + "*** End Patch"
    if code_mode:
        payload = {"type": "custom_tool_call", "name": "exec", "call_id": call_id, "input": f'const patch = "{patch}"; await tools.apply_patch(patch);'}
    else:
        payload = {"type": "function_call", "name": "apply_patch", "call_id": call_id, "arguments": {"command": patch}}
    return {"type": "response_item", "payload": payload}


def patch_result(call_id: str, success: bool = True) -> dict:
    output = "Done!" if success else "Invalid patch: patch failed"
    return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id, "output": output}}


def run(entries: list[dict], *, turn_id: str = "turn-new", active: bool = False) -> dict | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        transcript = Path(tmpdir) / "rollout.jsonl"
        transcript.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(DETECT), "--config", str(SCRIPT_DIR / "config-code-check.json")],
            input=json.dumps({"turn_id": turn_id, "transcript_path": str(transcript), "stop_hook_active": active}),
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout.strip() else None


def assert_case(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"✅ {name}")


old = [turn_context("turn-old")]
for index in range(5):
    old += [patch_call(f"old-{index}", [f"old-{index}.py"]), patch_result(f"old-{index}")]

few = [turn_context("turn-new")]
for index in range(2):
    few += [patch_call(f"few-{index}", [f"few-{index}.py"]), patch_result(f"few-{index}")]
assert_case("只统计当前 turn", run(old + few) is None)

enough = [turn_context("turn-new")]
for index in range(5):
    enough += [patch_call(f"ok-{index}", [f"file-{index % 3}.py"], code_mode=index != 4), patch_result(f"ok-{index}")]
result = run(enough)
assert_case("5 次成功且 3 个文件触发", result is not None and result.get("decision") == "block")
assert_case("完整 action 位于 Codex reason", "/check skill" in result.get("reason", ""))
assert_case("统计写入续跑提示", "成功 apply_patch 调用 5 次" in result.get("reason", ""))

failed = [turn_context("turn-new")]
for index in range(5):
    failed += [patch_call(f"bad-{index}", [f"bad-{index}.py"]), patch_result(f"bad-{index}", success=index > 0)]
assert_case("失败调用不计数", run(failed) is None)

assert_case("stop_hook_active 防止重复触发", run(enough, active=True) is None)
print("\n--- Codex review hook 测试全部通过 ---")
