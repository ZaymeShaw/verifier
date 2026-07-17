from __future__ import annotations

import argparse
import json
from typing import Any

from impl.core.schema.fixture import load_fixture
from impl.core.schema.occam import field_role

FLOW_FIXTURES = [
    ("1. case -> live_run 输入 SingleTurnCase", "impl.core.schema.mock.SingleTurnCase", "SingleTurnCase"),
    ("2. _build_live_request 输出 LiveRequest", "impl.core.schema.live.LiveRequest", "LiveRequest"),
    ("3. execute_live 输出 EXTRACT_OUTPUT_SCHEMA", "impl.core.live_protocol.ProjectLive", "ProjectLive"),
    ("4. trace_from_live 输出 RunTrace", "impl.core.schema.trace.RunTrace", "RunTrace"),
    ("5. judge 输出 JudgeResult", "impl.core.schema.judge.JudgeResult", "JudgeResult"),
    ("6. attribute 输出 AttributeResult", "impl.core.schema.attribute.AttributeResult", "AttributeResult"),
    ("7. frontend/table 输出 TraceTableRow", "impl.core.schema.table.TraceTableRow", "TraceTableRow"),
]


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def fixture_flow_payload(*, include_roles: bool = False) -> list[dict[str, Any]]:
    result = []
    for title, class_path, schema_name in FLOW_FIXTURES:
        payload = load_fixture(class_path, as_dict=True)
        if include_roles and isinstance(payload, dict):
            payload = {key: {"role": field_role(schema_name, key), "value": value} for key, value in payload.items()}
        result.append({"title": title, "class_path": class_path, "payload": payload})
    return result


def print_fixture_flow(*, limit: int = 3500, include_roles: bool = False) -> None:
    for item in fixture_flow_payload(include_roles=include_roles):
        print("\n" + "=" * 90)
        print(item["title"])
        print(item["class_path"])
        print("=" * 90)
        text = json.dumps(item["payload"], ensure_ascii=False, indent=2)
        print(_truncate(text, limit))


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the core schema fixture flow as JSON blocks.")
    parser.add_argument("--limit", type=int, default=3500, help="Maximum characters to print per fixture block. Use 0 for no limit.")
    parser.add_argument("--roles", action="store_true", help="Annotate top-level fields with Occam roles: canonical, derived_alias, legacy_alias, view_only, etc.")
    args = parser.parse_args()
    print_fixture_flow(limit=args.limit, include_roles=args.roles)


if __name__ == "__main__":
    main()
