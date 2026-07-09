#!/usr/bin/env python3
"""Review Stop Hook — 大活后触发可配置动作。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.json"
CONFIG_ARG_PREFIX = "--config="

DEFAULT_CONFIG = {
    "trigger": {
        "enabled": True,
        "successful_tool_names": ["Edit", "MultiEdit", "Write", "NotebookEdit"],
        "min_successful_edit_tools": 5,
        "min_distinct_files": 3,
        "distinct_file_keys": ["file_path", "notebook_path"],
    },
    "action": {
        "title": "大活回顾",
        "prompt": "按配置指令回顾本轮大量改动。",
        "decision": "block",
        "block_reason": "📋 {title}：已触发；行动：{action_preview} {stats}",
    },
    "instructions": {
        "after_action": [
            "不要只复述触发统计；先完成 action，再输出简短结果。",
        ],
    },
    "debug": {
        "dump": False,
        "dump_path": "/tmp/review-hook-stdin.json",
    },
}

EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
TOOL_FILE_PATH_KEYS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}


def _merge_dict(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _resolve_config_path(path_text: str) -> Path:
    p = Path(path_text).expanduser()
    if p.is_absolute():
        return p
    candidates = [Path.cwd() / p, SCRIPT_DIR / p, SCRIPT_DIR / p.name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path.cwd() / p


def _config_path_from_argv() -> Path:
    for i, arg in enumerate(sys.argv[1:], start=1):
        if arg.startswith(CONFIG_ARG_PREFIX):
            return _resolve_config_path(arg[len(CONFIG_ARG_PREFIX):])
        if arg in {"--config", "-c"} and i + 1 < len(sys.argv):
            return _resolve_config_path(sys.argv[i + 1])
    env_path = os.environ.get("REVIEW_HOOK_CONFIG")
    if env_path:
        return _resolve_config_path(env_path)
    return DEFAULT_CONFIG_PATH


def _load_config() -> dict:
    config_path = _config_path_from_argv()
    explicit = config_path != DEFAULT_CONFIG_PATH or any(
        arg.startswith(CONFIG_ARG_PREFIX) or arg in {"--config", "-c"} for arg in sys.argv[1:]
    ) or bool(os.environ.get("REVIEW_HOOK_CONFIG"))
    try:
        user_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        if explicit:
            raise RuntimeError(f"review hook config not readable: {config_path}: {exc}") from exc
        user_cfg = {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"review hook config invalid JSON: {config_path}: {exc}") from exc
    cfg = _merge_dict(DEFAULT_CONFIG, user_cfg)
    cfg["_config_path"] = str(config_path)
    return cfg


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _read_transcript(path: str) -> list[dict]:
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
            msg_type = entry.get("type", "")
            if msg_type == "message" or msg_type == "":
                role = entry.get("role", "")
                if role in ("user", "assistant", "system"):
                    messages.append(entry)
                continue
            nested = entry.get("message")
            if isinstance(nested, dict):
                role = nested.get("role", "")
                if role in ("user", "assistant", "system"):
                    messages.append(nested)
    return messages


def _is_tool_result_success(content: list[dict]) -> bool:
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("is_error") or item.get("isError"):
            return False
        for key in ("text", "result"):
            value = item.get(key, "")
            if isinstance(value, str):
                text = value.lower()
                if any(marker in text for marker in ("error", "failed", "not found", "denied", "is_error")):
                    return False
    return True


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text")
        if isinstance(value, str):
            texts.append(value)
    return "\n".join(texts)


def _is_synthetic_context_message(msg: dict) -> bool:
    text = _message_text(msg).strip()
    if not text:
        return False
    if text.startswith("<system-reminder>") and "</system-reminder>" in text:
        return True
    return (
        "This session is being continued from a previous conversation that ran out of context." in text
        and "Summary:" in text
        and "Continue the conversation from where it left off" in text
    )


def _is_user_message(msg: dict) -> bool:
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, list) and content and all(
        isinstance(item, dict) and item.get("type") == "tool_result" for item in content
    ):
        return False
    if _is_synthetic_context_message(msg):
        return False
    return True


def _slice_current_turn(messages: list[dict]) -> list[dict]:
    if not messages:
        return []
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if _is_user_message(messages[i]):
            last_user_idx = i
            break
    return messages if last_user_idx < 0 else messages[last_user_idx:]


def _collect_edit_tool_uses(messages: list[dict], tool_names: set[str], file_keys: list[str]) -> list[tuple[str, str, bool]]:
    tool_results: dict[str, bool] = {}
    for msg in messages:
        if msg.get("role") != "user":
            continue
        for item in msg.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            tool_id = item.get("tool_use_id", "")
            if not tool_id:
                continue
            result_content = item.get("content")
            tool_results[tool_id] = _is_tool_result_success(result_content) if isinstance(result_content, list) else True

    out: list[tuple[str, str, bool]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = item.get("name", "")
            if name not in tool_names:
                continue
            inp = item.get("input") or {}
            default_key = TOOL_FILE_PATH_KEYS.get(name, "file_path")
            file_path = inp.get(default_key) or ""
            for key in file_keys:
                file_path = file_path or inp.get(key) or ""
            success = tool_results.get(item.get("id", ""), True)
            out.append((name, str(file_path), success))
    return out


def _compact_text(text: str, limit: int = 90) -> str:
    one_line = " ".join(str(text).split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"


def _build_action_prompt(action: dict) -> list[str]:
    prompt = str(action.get("prompt") or "按配置要求执行。").strip()
    return ["## 2. 行动 action", prompt]


def _build_review_prompt(config: dict, stats: str, files: list[str]) -> str:
    action = config.get("action") or {}
    instructions = config.get("instructions") or {}
    title = str(action.get("title") or "大活回顾")

    parts: list[str] = [
        f"# {title}",
        "",
        "Stop hook 已触发。下面配置只有四块：触发、行动、指令、debug；本轮先执行 action。",
        "不要把触发统计当成审查结果，也不要只总结本轮改动。",
        "",
        "## 1. 触发 trigger",
        stats,
        "",
        "本轮改动涉及文件：",
        "\n".join(f"- `{path}`" for path in files[:50]) or "- （未收集到路径）",
        "",
        *_build_action_prompt(action),
    ]

    after_action = instructions.get("after_action") or []
    if after_action:
        parts.append("\n## 3. 指令 instructions")
        parts.append("\n### after_action")
        parts.extend(f"- {item}" for item in after_action)

    debug = config.get("debug") or {}
    parts.extend(
        [
            "",
            "## 4. debug",
            f"- dump: {str(bool(debug.get('dump'))).lower()}",
            f"- config: `{config.get('_config_path', '')}`",
            "",
            "## 输出要求",
            "先完成 action，再按 instructions 补充；结果要短、具体、可复查。",
        ]
    )
    return "\n".join(parts)


def main() -> int:
    data = _read_stdin()
    try:
        config = _load_config()
    except RuntimeError as exc:
        output = {
            "decision": "block",
            "reason": f"📋 Review hook 配置错误：{exc}",
            "systemMessage": f"Review hook 配置错误，无法执行：{exc}\n请先修复 hooks/review 的配置文件。",
        }
        print(json.dumps(output, ensure_ascii=False))
        return 0

    debug = config.get("debug") or {}
    if debug.get("dump"):
        try:
            Path(str(debug.get("dump_path") or "/tmp/review-hook-stdin.json")).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    trigger = config.get("trigger") or {}
    if not trigger.get("enabled", True):
        return 0
    if data.get("stop_hook_active"):
        return 0

    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        return 0

    messages = _read_transcript(transcript_path)
    if not messages:
        return 0

    window = _slice_current_turn(messages)
    tool_names = set(trigger.get("successful_tool_names") or EDIT_TOOLS)
    file_keys = [str(key) for key in (trigger.get("distinct_file_keys") or ["file_path", "notebook_path"])]
    edits = _collect_edit_tool_uses(window, tool_names, file_keys)
    successful = [(name, file_path) for (name, file_path, ok) in edits if ok]
    distinct_files = sorted({file_path for (_name, file_path) in successful if file_path})

    min_successful = int(trigger.get("min_successful_edit_tools", 5))
    min_files = int(trigger.get("min_distinct_files", 3))
    if len(successful) < min_successful or len(distinct_files) < min_files:
        return 0

    stats = f"本轮统计：成功改文件工具调用 {len(successful)} 次，涉及 {len(distinct_files)} 个不同文件。"
    action = config.get("action") or {}
    title = action.get("title", "大活回顾")
    action_prompt = str(action.get("prompt") or "按配置要求执行。").strip()
    action_preview = _compact_text(action_prompt)
    reason_template = str(action.get("block_reason") or "📋 {title}：已触发；行动：{action_preview}。{stats}")
    reason = reason_template.format(
        title=title,
        stats=stats,
        action_preview=action_preview,
        config=config.get("_config_path", ""),
    )
    output = {
        "decision": str(action.get("decision") or "block"),
        "reason": reason,
        "systemMessage": _build_review_prompt(config, stats, distinct_files),
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
