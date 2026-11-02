from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from impl.core.schema import RunTrace, to_dict

# 项目层易变字段（点路径）。protocol.md 6.2 的确定性检查将复用同一份列表。
VOLATILE_FIELDS: dict[str, list[str]] = {
    "policy_search": ["session_id", "trace_id"],
    "marketting-planning": ["session_id", "trace_id", "ts"],
    "deerflow": [],
}

DROP_FIELDS = {
    "trace_id",
    "created_at",
    "started_at",
    "finished_at",
    "runtime_ms",
    "elapsed_ms",
    "exchange_id",
    "record_id",
    # 公共/项目配置来源快照随 config.yaml / .env 变化，与多轮执行行为无关。
    "config_fingerprint",
    "config_sources",
}
UUID_PATTERN = re.compile(
    r"(?<![0-9a-f])(?:[0-9a-f]{32}|"
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)
ISO_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?(?![\w:+-])"
)
EPOCH_PATTERN = re.compile(r"(?<!\w)(?:\d{13}|\d{10})(?!\w)")


def canonicalize(
    trace_dict: dict[str, Any] | RunTrace,
    project_id: str = "",
) -> dict[str, Any]:
    source = (
        to_dict(trace_dict) if isinstance(trace_dict, RunTrace) else trace_dict
    )
    volatile = [
        tuple(path.split(".")) for path in VOLATILE_FIELDS.get(project_id, [])
    ]

    def walk(value: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in sorted(value.items()):
                item_path = (*path, key)
                if key in DROP_FIELDS or any(
                    item_path[-len(field) :] == field for field in volatile
                ):
                    continue
                result[key] = walk(item, item_path)
            return result
        if isinstance(value, list):
            return [walk(item, path) for item in value]
        if isinstance(value, str):
            value = UUID_PATTERN.sub("<uuid>", value)
            value = ISO_PATTERN.sub("<iso_ts>", value)
            return EPOCH_PATTERN.sub("<epoch>", value)
        return value

    return walk(source)


def canonical_json(
    trace: dict[str, Any] | RunTrace, project_id: str = ""
) -> str:
    return (
        json.dumps(
            canonicalize(trace, project_id),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--project", default="")
    args = parser.parse_args()
    source = json.loads(args.trace.read_text(encoding="utf-8"))
    print(canonical_json(source, args.project), end="")


if __name__ == "__main__":
    main()
