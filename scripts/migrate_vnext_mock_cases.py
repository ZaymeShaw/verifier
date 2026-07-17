#!/usr/bin/env python3
"""Deterministically migrate persisted legacy cases to the VNext MockCase shape."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CASE_FIELDS = {"id", "project_id", "scenario", "intent", "live_request", "output", "reference"}
NON_USER_CONTEXT_FIELDS = {"expected_intent", "reason", "source", "status", "expected_quality"}


def migrate_case(value: dict[str, Any], project_id: str) -> dict[str, Any]:
    if CASE_FIELDS.issubset(value):
        case = {key: value[key] for key in ("id", "project_id", "scenario", "intent", "live_request", "output", "reference")}
        intent = dict(case.get("intent") or {})
        context = dict(intent.get("user_context") or {})
        intent["user_context"] = {key: item for key, item in context.items() if key not in NON_USER_CONTEXT_FIELDS}
        case["intent"] = intent
        return case
    if "input" not in value or "id" not in value:
        return value
    request = value.get("input")
    if not isinstance(request, dict):
        raise ValueError(f"case {value.get('id')} input must be an object")
    metadata = dict(value.get("metadata") or {})
    user_intent = str(value.get("user_intent") or value.get("expected_intent") or metadata.get("expected_intent") or "")
    query = str(request.get("query") or request.get("user_text") or request.get("question") or user_intent)
    user_context = dict(metadata.get("user_context") or {}) if isinstance(metadata.get("user_context"), dict) else {}
    return {
        "id": str(value["id"]),
        "project_id": str(value.get("project_id") or project_id),
        "scenario": str(value.get("scenario") or ""),
        "intent": {"user_intent": user_intent, "query": query, "user_context": user_context},
        "live_request": request,
        "output": value.get("output"),
        "reference": value.get("reference"),
    }


def migrate_node(value: Any, project_id: str) -> Any:
    if isinstance(value, list):
        return [migrate_node(item, project_id) for item in value]
    if not isinstance(value, dict):
        return value
    if CASE_FIELDS.issubset(value) or ("id" in value and "input" in value):
        return migrate_case(value, project_id)
    migrated = {key: migrate_node(item, project_id) for key, item in value.items()}
    if isinstance(migrated.get("cases"), list):
        if "case_count" in migrated:
            migrated["case_count"] = len(migrated["cases"])
    return migrated


def migrate_file(path: Path, project_id: str) -> None:
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    migrated = migrate_node(data, project_id)
    rendered = json.dumps(migrated, ensure_ascii=False, indent=2) + "\n"
    if migrated != data:
        path.write_text(rendered, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for root in args.paths:
        paths = sorted(path for path in root.rglob("*.json") if path.name not in {"index.json", "index_upload_batches.json"}) if root.is_dir() else [root]
        for path in paths:
            migrate_file(path, args.project_id)


if __name__ == "__main__":
    main()
