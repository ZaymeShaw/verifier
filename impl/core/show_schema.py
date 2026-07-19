from __future__ import annotations

import importlib
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Iterable, List, Optional


_SEGMENT = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>-?\d+)\])?$")


@dataclass(frozen=True)
class ShowSchema:
    input_fields: list[str]
    output_fields: list[str]

    def __post_init__(self) -> None:
        for name, values in (("input_fields", self.input_fields), ("output_fields", self.output_fields)):
            if not isinstance(values, list) or not values or not all(isinstance(item, str) and item.strip() for item in values):
                raise ValueError(f"ShowSchema.{name} 必须是非空 list[str]")
            if len(set(values)) != len(values):
                raise ValueError(f"ShowSchema.{name} 不允许重复路径")
            for path in values:
                parse_path(path)


def parse_path(path: str) -> list[tuple[str, Optional[int]]]:
    parts: list[tuple[str, Optional[int]]] = []
    for raw in str(path or "").split("."):
        match = _SEGMENT.fullmatch(raw)
        if not match:
            raise ValueError(f"非法 Show Schema 路径: {path}")
        index = match.group("index")
        parts.append((match.group("name"), int(index) if index is not None else None))
    if not parts:
        raise ValueError("Show Schema 路径不能为空")
    return parts


def select_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for name, index in parse_path(path):
        if is_dataclass(current):
            current = asdict(current)
        if not isinstance(current, dict) or name not in current:
            return False, None
        current = current[name]
        if index is not None:
            if not isinstance(current, list) or not current:
                return False, None
            resolved = index if index >= 0 else len(current) + index
            if resolved < 0 or resolved >= len(current):
                return False, None
            current = current[resolved]
    return True, current


def load_show_schema(project_id: str) -> Optional[ShowSchema]:
    if project_id == "fixture-project":
        return ShowSchema(input_fields=["query"], output_fields=["query_logic", "conditions"])
    try:
        module = importlib.import_module(f"impl.projects.{project_id}.show_schema")
    except ModuleNotFoundError as exc:
        if exc.name == f"impl.projects.{project_id}.show_schema":
            return None
        raise
    schema = getattr(module, "SHOW_SCHEMA", None)
    if not isinstance(schema, ShowSchema):
        raise TypeError(f"{project_id}.show_schema.SHOW_SCHEMA 必须是 ShowSchema")
    return schema


def _resolve_ref(root: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    ref = node.get("$ref") if isinstance(node, dict) else None
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node
    current: Any = root
    for part in ref[2:].split("/"):
        current = current.get(part) if isinstance(current, dict) else None
    return current if isinstance(current, dict) else node


def validate_schema_paths(show: ShowSchema, request_schema: Dict[str, Any], output_schema: Dict[str, Any]) -> None:
    for label, paths, root in (
        ("input_fields", show.input_fields, request_schema),
        ("output_fields", show.output_fields, output_schema),
    ):
        for position, path in enumerate(paths):
            node = root
            for name, index in parse_path(path):
                node = _resolve_ref(root, node)
                properties = node.get("properties") if isinstance(node, dict) else None
                if not isinstance(properties, dict) or name not in properties:
                    raise ValueError(f"ShowSchema.{label} 路径不属于项目 schema: {path}")
                node = _resolve_ref(root, properties[name])
                if index is not None:
                    if node.get("type") != "array" or not isinstance(node.get("items"), dict):
                        raise ValueError(f"ShowSchema.{label} 对非数组使用下标: {path}")
                    node = _resolve_ref(root, node["items"])
            node = _resolve_ref(root, node)
            node_type = node.get("type")
            if position == 0 and (node_type in ("object", "array") if isinstance(node_type, str) else any(item in {"object", "array"} for item in node_type) if isinstance(node_type, list) else False):
                raise ValueError(f"ShowSchema.{label} 第一项必须是标量: {path}")


def _project_fields(value: Any, paths: Iterable[str]) -> List[Dict[str, Any]]:
    result = []
    for path in paths:
        found, selected = select_path(value, path)
        result.append({"path": path, "found": found, "value": selected if found else None})
    return result


def build_show_projection(trace: Any) -> Dict[str, Any]:
    schema = load_show_schema(str(getattr(trace, "project_id", "") or ""))
    if schema is None:
        return {"available": False, "reason": "missing_show_schema"}
    intent = getattr(trace, "mock_intent", None)
    mock = asdict(intent) if is_dataclass(intent) else dict(intent or {}) if isinstance(intent, dict) else None
    records = list(getattr(trace, "turn_records", None) or [])
    if not records:
        records = [{
            "turn_index": 1,
            "request": getattr(trace, "normalized_request", {}) or {},
            "raw_response": getattr(trace, "raw_response", None),
            "extracted_output": getattr(trace, "extracted_output", {}) or {},
            "call_status": getattr(trace, "status", ""),
            "runtime_ms": None,
            "error": getattr(trace, "error", None),
            "mock_message": "",
        }]
    turns = []
    for index, record in enumerate(records, start=1):
        record = record if isinstance(record, dict) else {}
        exchanges = list(record.get("live_exchanges") or [])
        exchange_summary = []
        for exchange in exchanges:
            item = asdict(exchange) if is_dataclass(exchange) else dict(exchange or {}) if isinstance(exchange, dict) else {}
            exchange_summary.append({
                "sequence": item.get("sequence"),
                "method": item.get("method"),
                "url": item.get("url"),
                "status_code": item.get("status_code"),
                "carries_live_request": bool(item.get("carries_live_request")),
                "contributes_raw_response": bool(item.get("contributes_raw_response")),
                "error": item.get("error"),
            })
        mock_message = str(record.get("mock_message") or "")
        source = "trace"
        if not mock_message:
            found, derived = select_path(record.get("request") or {}, schema.input_fields[0])
            mock_message = str(derived) if found and derived is not None else ""
            source = "derived" if mock_message else "missing"
        turns.append({
            "turn_index": int(record.get("turn_index") or index),
            "mock_message": mock_message,
            "mock_message_source": source,
            "input": _project_fields(record.get("request") or {}, schema.input_fields),
            "output": _project_fields(record.get("extracted_output") or {}, schema.output_fields),
            "status": str(record.get("call_status") or ""),
            "runtime_ms": record.get("runtime_ms"),
            "error": record.get("error"),
            # 核心视图只展示高密度传输摘要；完整请求/响应仍保留在原始 Trace JSON。
            "live_exchange_summary": exchange_summary,
        })
    return {
        "available": True,
        "input_fields": list(schema.input_fields),
        "output_fields": list(schema.output_fields),
        "mock": mock,
        "overview": {
            "status": str(getattr(trace, "status", "") or ""),
            "completion_status": str(getattr(trace, "completion_status", "") or ""),
            "execution_error": str(getattr(trace, "error", "") or ""),
            "interaction_controller_status": str(getattr(trace, "interaction_controller_status", "not_run") or "not_run"),
            "interaction_controller_error": str(getattr(trace, "interaction_controller_error", "") or ""),
            "interaction_mode": str(getattr(trace, "interaction_mode", "") or ""),
            "turn_count": len(turns),
            "stop_reason": str(getattr(trace, "stop_reason", "") or ""),
            "final_output_turn": getattr(trace, "final_output_turn", None),
        },
        "final_output": _project_fields(getattr(trace, "extracted_output", {}) or {}, schema.output_fields),
        "reference": _project_fields(getattr(trace, "reference_contract", {}) or {}, schema.output_fields),
        "turns": turns,
    }
