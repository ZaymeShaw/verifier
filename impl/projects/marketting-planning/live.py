from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from impl.core.live_protocol import RealServiceLive
from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveMultiTurnState, LiveRequest, MultiTurnCase, ProjectSpec, RunTrace, SingleTurnCase


def _attach_request(raw: Any, request: dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        return {**raw, "_normalized_request": request}
    return {"raw": raw, "_normalized_request": request}


def _live_request_body(request: LiveRequest | dict[str, Any]) -> dict[str, Any]:
    payload = request.normalized_request if isinstance(request, LiveRequest) else request
    query = str(payload.get("query") or "")
    contexts = []
    for turn in payload.get("turns") or []:
        content = str(turn.get("content") or turn.get("query") or "")
        role = str(turn.get("role") or "user")
        if not content or content == query:
            continue
        contexts.append({"role": role, "query": content if role == "user" else "", "answer": content if role != "user" else ""})
    session_id = str(payload.get("session_id") or "")
    return {
        "session_id": session_id,
        "trace_id": str(payload.get("case_id") or session_id or f"trace-{int(time.time() * 1000)}"),
        "org_id": str((payload.get("metadata") or {}).get("org_id") or "eval-org"),
        "user_text": query,
        "extra_input_params": {
            "agent_args": {"conversation_id": session_id, "message": {"content": query, "content_type": "text"}},
            "args": {"extensions": {}, "contexts": contexts},
        },
    }


def deliver_raw_response(spec: ProjectSpec, request: LiveRequest) -> Any:
    body = json.dumps(_live_request_body(request), ensure_ascii=False).encode("utf-8")
    url = str(spec.api.get("base_url") or "").rstrip("/") + "/" + str(spec.api.get("endpoint") or "").lstrip("/")
    api_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(spec.api.get("method") or "POST").upper())
    with urllib.request.urlopen(api_request, timeout=float(spec.api.get("timeout") or 120)) as response:
        return _attach_request(response.read().decode("utf-8"), request.normalized_request)


def _request_from_raw(raw: Any) -> dict[str, Any]:
    return dict(raw.get("_normalized_request") or {}) if isinstance(raw, dict) else {}


def _raw_payload(raw: Any) -> Any:
    if isinstance(raw, dict) and "raw" in raw:
        return raw.get("raw")
    return raw


def _list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _last_response_frame(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        if "code" in data and "data" in data:
            return data
        events = data.get("events") or data.get("event_stream") or data.get("sse_events") or []
        for event in reversed(events if isinstance(events, list) else []):
            payload = event.get("data") if isinstance(event, dict) else None
            if isinstance(payload, dict) and "code" in payload and "data" in payload:
                return payload
        return data
    if isinstance(data, str):
        frames: list[dict[str, Any]] = []
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                parsed = json.loads(line.split(":", 1)[1].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                frames.append(parsed)
        if frames:
            return frames[-1]
    return {}


def _extract_events(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, str):
        events = []
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                events.append({"event": line.split(":", 1)[1].strip()})
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    parsed = {"text": payload}
                if events and "data" not in events[-1]:
                    events[-1]["data"] = parsed
                else:
                    events.append({"event": parsed.get("event") if isinstance(parsed, dict) else "data", "data": parsed})
        return events
    if isinstance(data, dict):
        events = data.get("events") or data.get("event_stream") or data.get("sse_events") or []
        if isinstance(events, list):
            return [event if isinstance(event, dict) else {"event": str(event)} for event in events]
    return []


_CARD_CODE_PATH_TYPE_MAP: dict[str, str] = {
    "TEAM_PROFILE_ANALYSIS": "premium_growth",
    "TEAM_REACH_MEASUREMENT": "premium_growth",
    "CUSTOMER_PROFILE_ANALYSIS": "customer_growth",
    "CUSTOMER_REACH_MEASUREMEN": "customer_growth",
    "PRODUCT_PROFILE_ANALYSIS": "product_mix",
    "PRODUCT_REACH_MEASUREMENT": "product_mix",
}


_BUSINESS_EVIDENCE_KEYS = {
    "target_value",
    "targetValue",
    "target",
    "dimension",
    "dimensions",
    "decomposition",
    "recommendation",
    "recommendations",
    "action",
    "actions",
    "constraint",
    "constraints",
    "unit",
    "basis",
    "current_value",
    "currentValue",
    "forecast_value",
    "forecastValue",
    "achievement_rate",
    "achievementRate",
    "fieldKey",
    "required",
}


def _compact_value(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return str(value)[:300] if value is not None else None
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in _BUSINESS_EVIDENCE_KEYS or depth > 0:
                compact[str(key)] = _compact_value(item, depth + 1)
            if len(compact) >= 12:
                break
        return compact
    if isinstance(value, list):
        return [_compact_value(item, depth + 1) for item in value[:8]]
    if isinstance(value, str):
        return value[:300]
    return value


def _business_evidence(card: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for source in (card, card.get("card_data"), card.get("data"), card.get("business_evidence")):
        if not isinstance(source, dict):
            continue
        for key in _BUSINESS_EVIDENCE_KEYS:
            if key in source and source[key] not in (None, "", [], {}):
                evidence[str(key)] = _compact_value(source[key], 1)
    return evidence


def _card_summary(card: dict[str, Any]) -> dict[str, Any]:
    explicit = card.get("path_type") or card.get("type")
    if not explicit:
        card_code = str(card.get("card_code") or card.get("code") or "")
        explicit = _CARD_CODE_PATH_TYPE_MAP.get(card_code)
    return {
        "path_type": str(explicit or "unknown"),
        "card_code": str(card.get("card_code") or card.get("code") or ""),
        "card_name": str(card.get("card_name") or card.get("name") or ""),
        "fallback": bool(card.get("fallback")),
        "forecast_value": card.get("forecast_value"),
        "achievement_rate": card.get("achievement_rate"),
        "business_evidence": _business_evidence(card),
    }


def _card_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    extra = data.get("extra_output_params") if isinstance(data.get("extra_output_params"), dict) else payload.get("extra_output_params")
    if isinstance(extra, dict) and isinstance(extra.get("card_result"), dict):
        return extra["card_result"]
    if isinstance(payload.get("card_result"), dict):
        return payload["card_result"]
    return {}


def _extract_cards(data: Any) -> list[dict[str, Any]]:
    cards = []
    if isinstance(data, dict):
        raw_cards = data.get("cards") or data.get("card_summary") or data.get("planning_cards") or []
        if not raw_cards and isinstance(data.get("data"), dict):
            raw_cards = data["data"].get("cards") or []
        for card in _list(raw_cards):
            if isinstance(card, dict):
                cards.append(_card_summary(card))
    for event in _extract_events(data):
        payload = event.get("data") if isinstance(event, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("card"), dict):
            cards.append(_card_summary(payload["card"]))
        card_result = _card_result(payload)
        if card_result:
            for card in _list(card_result.get("card_list")):
                if isinstance(card, dict):
                    cards.append(_card_summary(card))
    unique = []
    seen = set()
    for card in cards:
        marker = (
            card.get("path_type"),
            card.get("card_code"),
            card.get("card_name"),
            json.dumps(card.get("forecast_value"), ensure_ascii=False, sort_keys=True),
            json.dumps(card.get("achievement_rate"), ensure_ascii=False, sort_keys=True),
            json.dumps(card.get("business_evidence"), ensure_ascii=False, sort_keys=True),
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(card)
    return unique


def _extract_stage(data: Any, events: list[dict[str, Any]], cards: list[dict[str, Any]]) -> str:
    stages = {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"}
    if isinstance(data, dict) and data.get("stage") in stages:
        return str(data.get("stage"))
    names = [str(event.get("event") or event.get("name") or "") for event in events]
    joined = " ".join(names).lower()
    card_codes = {str(card.get("card_code") or "") for card in cards}
    intent_values = set()
    for event in events:
        payload = event.get("data") if isinstance(event, dict) else None
        if isinstance(payload, dict):
            inner_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            extras = inner_data.get("extra_output_params") if isinstance(inner_data.get("extra_output_params"), dict) else {}
            intent_val = str(inner_data.get("intent") or extras.get("intent") or "")
            if intent_val:
                intent_values.add(intent_val)
    if card_codes & {"ASK_TARGET_VALUE", "ACHIEVE_PATH_TYPE_QUESTION"}:
        return "clarification"
    if "clarification" in joined or "clarify" in joined:
        return "clarification"
    if "non_agent" in joined or "reject" in joined or intent_values & {"4001"}:
        return "non_agent"
    if "fallback" in joined or intent_values & {"nbev_planning_fallback"}:
        return "fallback"
    if cards or "planning" in joined or "card" in joined:
        return "planning"
    if "intent" in joined:
        return "intent"
    return "unknown"


def _canonical_event_names(names: list[str], spec: ProjectSpec) -> list[str]:
    aliases = spec.frontend_extensions.get("event_aliases") or {}
    alias_to_canonical = {}
    for canonical_name, raw_names in aliases.items():
        for raw_name in _list(raw_names):
            alias_to_canonical[str(raw_name).lower()] = str(canonical_name)
    canonical = []
    for name in names:
        normalized = str(name or "")
        mapped = alias_to_canonical.get(normalized.lower(), normalized)
        if not canonical or canonical[-1] != mapped:
            canonical.append(mapped)
    return canonical


def _is_non_business_tail_event(raw_name: str, canonical_name: str) -> bool:
    name = (canonical_name or raw_name or "").lower()
    return name in {"", "data", "ping", "heartbeat", "keepalive", "message"}


def _event_summary(events: list[dict[str, Any]], spec: ProjectSpec, business_completed: bool = False) -> dict[str, Any]:
    names = [str(event.get("event") or event.get("name") or "data") for event in events]
    canonical_names = _canonical_event_names(names, spec)
    counts = {name: names.count(name) for name in sorted(set(names))}
    canonical_counts = {name: canonical_names.count(name) for name in sorted(set(canonical_names))}
    final = names[-1] if names else ""
    canonical_final = canonical_names[-1] if canonical_names else ""
    terminal_events = set(spec.frontend_extensions.get("terminal_events") or ["done", "complete", "completed", "card_end"])
    protocol_completed = False
    for index, (raw_name, canonical_name) in enumerate(zip(names, canonical_names)):
        if raw_name not in terminal_events and canonical_name not in terminal_events:
            continue
        tail = list(zip(names[index + 1:], canonical_names[index + 1:]))
        protocol_completed = all(_is_non_business_tail_event(raw_tail, canonical_tail) for raw_tail, canonical_tail in tail)
    completed = protocol_completed and business_completed
    return {
        "names": canonical_names,
        "raw_names": names,
        "canonical_names": canonical_names,
        "counts": canonical_counts,
        "raw_counts": counts,
        "final_event": canonical_final or final,
        "raw_final_event": final,
        "protocol_completed": protocol_completed,
        "business_completed": business_completed,
        "completed": completed,
    }


def _session_summary(data: Any, raw_response: Any = None) -> dict[str, Any]:
    session = data.get("session") if isinstance(data, dict) and isinstance(data.get("session"), dict) else {}
    request = _request_from_raw(raw_response if raw_response is not None else data)
    missing_fields = _list(session.get("missing_fields"))
    if not missing_fields:
        for event in _extract_events(data):
            card_result = _card_result(event.get("data") if isinstance(event, dict) else None)
            for card in _list(card_result.get("card_list")):
                if isinstance(card, dict) and isinstance(card.get("card_data"), dict) and card["card_data"].get("required"):
                    field_key = card["card_data"].get("fieldKey")
                    if field_key and field_key not in missing_fields:
                        missing_fields.append(field_key)
    evidence_declared = isinstance(session, dict) and any(key in session for key in ("required_fields", "accumulated_fields", "missing_fields"))
    evidence_status = "declared" if evidence_declared else "missing"
    return {
        "session_id": str(session.get("session_id") or request.get("session_id") or ""),
        "required_fields": _list(session.get("required_fields") or ((request.get("reference") or {}).get("session_requirements") or {}).get("required_fields")),
        "accumulated_fields": dict(session.get("accumulated_fields") or {}),
        "missing_fields": missing_fields,
        "evidence_declared": evidence_declared,
        "evidence_status": evidence_status,
    }


def _extract_fallback(data: Any, cards: list[dict[str, Any]], raw_response: Any = None) -> dict[str, Any]:
    raw = data.get("fallback") if isinstance(data, dict) else None
    request = _request_from_raw(raw_response if raw_response is not None else data)
    boundary = request.get("boundary") or {}
    if isinstance(raw, dict):
        return {"used": bool(raw.get("used")), "allowed": bool(raw.get("allowed") or boundary.get("allow_fallback")), "reason": str(raw.get("reason") or "")}
    return {"used": False, "allowed": bool(boundary.get("allow_fallback")), "reason": ""}


def _extract_errors(data: Any, events: list[dict[str, Any]]) -> list[str]:
    errors = []
    if isinstance(data, dict):
        for key in ("error", "errors", "message"):
            value = data.get(key)
            if isinstance(value, str) and value:
                errors.append(value[:300])
            elif isinstance(value, list):
                errors.extend(str(item)[:300] for item in value)
    for event in events:
        name = str(event.get("event") or "").lower()
        if "error" in name:
            errors.append(str(event.get("data") or name)[:300])
    return errors


def _intent_fields(frame_body: dict[str, Any]) -> dict[str, str]:
    extra = frame_body.get("extra_output_params") if isinstance(frame_body.get("extra_output_params"), dict) else {}
    return {"intent": str(extra.get("intent") or frame_body.get("intent") or ""), "intent_name": str(extra.get("intent_name") or frame_body.get("intent_name") or "")}


def _turn_input_for_index(request: LiveRequest, index: int, fallback: dict[str, Any]) -> dict[str, Any]:
    turns = request.normalized_request.get("turns") if isinstance(request.normalized_request, dict) else request.turns
    if isinstance(turns, list) and index < len(turns) and isinstance(turns[index], dict):
        return dict(turns[index])
    return fallback


def extract_output(raw_response: Any, request: LiveRequest | None = None, spec: ProjectSpec | None = None, index: int | None = None) -> dict[str, Any]:
    data = _raw_payload(raw_response)
    frame = _last_response_frame(data)
    body = frame.get("data") if isinstance(frame.get("data"), dict) else {}
    events = _extract_events(data)
    cards = _extract_cards(data)
    stage = _extract_stage(data, events, cards)
    intent = _intent_fields(body)
    output = {
        "code": int(frame.get("code") or 0),
        "msg": str(frame.get("msg") or ""),
        "robot_text": str(body.get("robot_text") or ""),
        "end_flag": int(body.get("end_flag") or 0),
        "intent": intent.get("intent") or "",
        "intent_name": intent.get("intent_name") or "",
        "stage": stage,
        "event_summary": _event_summary(events, spec, business_completed=bool(cards or body.get("robot_text"))),
        "card_summary": cards,
        "session_summary": _session_summary(data, raw_response),
        "fallback": _extract_fallback(data, cards, raw_response),
        "errors": _extract_errors(data, events),
    }
    if index is not None and request is not None:
        output["turn_index"] = index
        output["input_turn"] = _turn_input_for_index(request, index, {})
    if index is None and request is not None:
        turn_index = max(len(request.turns or []) - 1, 0)
        output["turn_index"] = turn_index
        output["input_turn"] = _turn_input_for_index(request, turn_index, {})
        return {"turns": [output]}
    return output


def _application_boundary(request: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    boundary = dict(request.get("boundary") or {}) if isinstance(request.get("boundary"), dict) else {}
    fallback = output.get("fallback") or {}
    return {"dependency_status": boundary.get("dependency_status") or boundary.get("external_dependency") or "available", "allow_fallback": bool(boundary.get("allow_fallback") or boundary.get("fallback_allowed")), "fallback_used": bool(fallback.get("used")), "judge_scope": "system_responsibility_with_declared_external_boundary", "excluded_evidence": _list(boundary.get("excluded_evidence"))}


def _latest_turn_output(extracted_output: dict[str, Any]) -> dict[str, Any]:
    turns = extracted_output.get("turns") if isinstance(extracted_output, dict) else None
    if isinstance(turns, list) and turns and isinstance(turns[-1], dict):
        return turns[-1]
    return extracted_output if isinstance(extracted_output, dict) else {}


def application_boundary(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None, request: LiveRequest | dict[str, Any] | None = None, spec: ProjectSpec | None = None) -> dict[str, Any]:
    normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
    latest_output = _latest_turn_output(extracted_output or {})
    return _application_boundary(normalized_request or {}, latest_output)


def build_execution_trace(input_data: dict[str, Any], request: dict[str, Any], raw_response: Any, extracted_output: dict[str, Any], spec: ProjectSpec | None = None) -> list[ExecutionTraceEvent]:
    latest = extracted_output.get("turns", [{}])[-1] if isinstance(extracted_output.get("turns"), list) and extracted_output.get("turns") else extracted_output
    expected_stage = request.get("expected_stage") or (request.get("reference") or {}).get("expected_stage")
    path_types = _list(request.get("expected_path_types"))
    actual_path_types = [card.get("path_type") for card in latest.get("card_summary") or [] if card.get("path_type")]
    fallback = latest.get("fallback") or {}
    return [
        ExecutionTraceEvent(stage="request_normalization", status="ok" if request.get("turns") else "suspicious", evidence={"turn_count": len(request.get("turns") or []), "session_id": request.get("session_id")}),
        ExecutionTraceEvent(stage="intent_recognition", status="ok" if latest.get("stage") in {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"} else "suspicious", evidence={"actual_stage": latest.get("stage"), "expected_stage": expected_stage}),
        ExecutionTraceEvent(stage="field_clarification", status="ok" if latest.get("stage") != "clarification" or expected_stage == "clarification" else "suspicious", evidence=latest.get("session_summary")),
        ExecutionTraceEvent(stage="session_merge", status="ok" if request.get("session_id") else "suspicious", evidence={"shared_session": request.get("shared_session"), "session_id": request.get("session_id")}),
        ExecutionTraceEvent(stage="path_dispatch", status="ok" if not path_types or set(path_types).issubset(set(actual_path_types)) else "failed", evidence={"expected_path_types": path_types, "actual_path_types": actual_path_types}),
        ExecutionTraceEvent(stage="planning_function", status="ok" if latest.get("stage") != "planning" or actual_path_types else "suspicious", evidence={"card_count": len(latest.get("card_summary") or [])}),
        ExecutionTraceEvent(stage="result_assembly", status="ok", evidence={"summary_keys": list(latest.keys())}),
        ExecutionTraceEvent(stage="sse_generation", status="ok" if (latest.get("event_summary") or {}).get("completed") else "not_verified", evidence=latest.get("event_summary")),
        ExecutionTraceEvent(stage="live_output_extraction", status="ok", evidence={"compact_summary_only": True, "fallback_used": fallback.get("used")}),
    ]


def project_fields(raw_response: Any | None = None, extracted_output: dict[str, Any] | None = None, request: LiveRequest | dict[str, Any] | None = None, spec: ProjectSpec | None = None, application_boundary: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_request = request.normalized_request if isinstance(request, LiveRequest) else request
    normalized_request = normalized_request if isinstance(normalized_request, dict) else {}
    output = extracted_output if isinstance(extracted_output, dict) else {}
    latest = _latest_turn_output(output)
    planning_summary = {key: latest.get(key) for key in ("stage", "event_summary", "card_summary", "session_summary", "fallback", "errors")}
    return {
        "scenario": normalized_request.get("scenario") or "",
        "case_id": normalized_request.get("case_id") or "",
        "session_id": normalized_request.get("session_id") or "",
        "shared_session": bool(normalized_request.get("shared_session")),
        "expected_stage": normalized_request.get("expected_stage"),
        "expected_path_types": _list(normalized_request.get("expected_path_types")),
        "expected_cards": _list(normalized_request.get("expected_cards")),
        "planning_summary": planning_summary,
        "application_boundary": application_boundary or {},
        "compact_summary_only": True,
    }


def provided_output_raw(case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
    input_data = dict(case.input or {})
    for key in ("raw_response", "response", "output"):
        if key in input_data:
            return _attach_request(input_data[key], request.normalized_request)
    return _attach_request({}, request.normalized_request)


def _normalize_turns(turns: Any) -> List[Dict[str, Any]]:
    if not isinstance(turns, list):
        return []
    normalized = []
    for item in turns:
        if isinstance(item, dict):
            normalized.append({"role": str(item.get("role") or "user"), "content": str(item.get("content") or item.get("query") or item.get("text") or ""), **({"output": item.get("output")} if "output" in item else {})})
        else:
            normalized.append({"role": "user", "content": str(item)})
    return normalized


def _last_user_content(turns: List[Dict[str, Any]]) -> str:
    for turn in reversed(turns):
        if turn.get("role") == "user" and turn.get("content"):
            return str(turn.get("content"))
    return ""


def _extract_query(input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
    for value in (
        input_data.get("query"),
        _last_user_content(turns),
    ):
        if isinstance(value, dict):
            value = value.get("content") or value.get("query") or value.get("text")
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _current_turn(turns: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    if turns:
        for turn in reversed(turns):
            if turn.get("role") == "user" and turn.get("content"):
                return turn
        return turns[-1]
    return {"role": "user", "content": str(query)} if query else {}


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return False


def _normalize_boundary(boundary: Any) -> Dict[str, Any]:
    data = dict(boundary or {}) if isinstance(boundary, dict) else {}
    return {"dependency_status": data.get("dependency_status") or data.get("external_dependency") or "available", "allow_fallback": bool(data.get("allow_fallback") or data.get("fallback_allowed")), "excluded_evidence": _list(data.get("excluded_evidence")), "notes": str(data.get("notes") or "")}


def _normalize_reference(reference: Any, input_data: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    ref = dict(reference or {}) if isinstance(reference, dict) else {}
    if input_data.get("expected_stage") and "expected_stage" not in ref:
        ref["expected_stage"] = input_data.get("expected_stage")
    if input_data.get("expected_path_types") and "required_path_types" not in ref:
        ref["required_path_types"] = _list(input_data.get("expected_path_types"))
    if input_data.get("expected_cards") and "required_cards" not in ref:
        ref["required_cards"] = _list(input_data.get("expected_cards"))
    if "allow_fallback" not in ref and isinstance(input_data.get("boundary"), dict):
        ref["allow_fallback"] = bool(input_data["boundary"].get("allow_fallback"))
    if scenario and "scenario" not in ref:
        ref["scenario"] = scenario
    return ref


def _infer_scenario(input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
    text = " ".join([str(input_data.get("query") or input_data.get("user_intent") or "")] + [str(turn.get("content") or "") for turn in turns])
    if any(word in text for word in ["缺", "补充", "澄清"]):
        return "clarification"
    if any(word in text for word in ["诗", "天气", "闲聊"]):
        return "non_agent_intent"
    if any(word in text for word in ["不可用", "兜底", "fallback"]):
        return "fallback_data_unavailable"
    if len(turns) > 1:
        return "multi_turn_field_accumulation"
    return "execution_planning"


def build_request(case: SingleTurnCase | MultiTurnCase, project_id: str) -> Dict[str, Any]:
    input_data = dict(case.input or {})
    turns = _normalize_turns(input_data.get("turns"))
    query = _extract_query(input_data, turns)
    if not turns and query:
        turns = [{"role": "user", "content": str(query)}]
    elif turns and not query:
        query = _last_user_content(turns)
    case_id = str(case.id or input_data.get("case_id") or input_data.get("id") or f"marketing-case-{int(time.time() * 1000)}")
    shared_session = _bool(input_data.get("shared_session"))
    declared_session = input_data.get("session_id")
    session_id = str(declared_session) if shared_session and declared_session else f"eval-{case_id}"
    scenario = str(input_data.get("scenario") or case.scenario or _infer_scenario(input_data, turns))
    boundary = _normalize_boundary(input_data.get("boundary") or {})
    case_reference = case.reference if isinstance(case.reference, dict) else {}
    reference = _normalize_reference(input_data.get("reference") or case_reference or {}, input_data, scenario)
    first_user_turn = next((turn.get("content") for turn in turns if turn.get("role") == "user" and turn.get("content")), "")
    current_turn = _current_turn(turns, query)
    return {
        "case_id": case_id,
        "session_id": session_id,
        "shared_session": shared_session,
        "user_intent": str(input_data.get("user_intent") or query or first_user_turn or scenario),
        "query": str(query or current_turn.get("content") or ""),
        "turns": turns,
        "current_turn": current_turn,
        "scenario": scenario,
        "expected_stage": input_data.get("expected_stage") or reference.get("expected_stage"),
        "expected_path_types": _list(input_data.get("expected_path_types") or reference.get("required_path_types")),
        "expected_cards": _list(input_data.get("expected_cards") or reference.get("required_cards")),
        "metadata": dict(input_data.get("metadata") or {}),
        "boundary": boundary,
        "reference": reference,
        "project_id": project_id,
    }


def _interactive_assistant_content(output: Dict[str, Any]) -> str:
    stage = output.get("stage") or "unknown"
    missing_fields = _list((output.get("session_summary") or {}).get("missing_fields"))
    cards = [card.get("path_type") for card in output.get("card_summary") or [] if card.get("path_type")]
    parts = [f"stage={stage}"]
    if missing_fields:
        parts.append("missing=" + ",".join(str(item) for item in missing_fields))
    if cards:
        parts.append("cards=" + ",".join(str(item) for item in cards))
    return " · ".join(parts)


def _interactive_turn_trace(turn_index: int, user_input: Dict[str, Any], output: Dict[str, Any], expectations: List[Dict[str, Any]]) -> Dict[str, Any]:
    expectation = next((item for item in expectations if int(item.get("turn") or 0) == turn_index), {})
    stage = output.get("stage") or "unknown"
    missing_fields = _list((output.get("session_summary") or {}).get("missing_fields"))
    path_evidence = [card.get("path_type") for card in output.get("card_summary") or [] if card.get("path_type")]
    failures = []
    if expectation.get("stage") and expectation.get("stage") != stage:
        failures.append("stage")
    expected_missing = _list(expectation.get("missing_fields"))
    if expected_missing and not missing_fields:
        failures.append("missing_fields_absent")
    for path_type in _list(expectation.get("required_path_types")):
        if path_type not in path_evidence:
            failures.append(f"path_type:{path_type}")
    return {
        "turn_index": turn_index,
        "user_input": {"query": str(user_input.get("query") or "")},
        "stage": stage,
        "missing_fields": missing_fields,
        "path_evidence": path_evidence,
        "card_evidence": [{"path_type": card.get("path_type"), "card_code": card.get("card_code"), "card_name": card.get("card_name")} for card in output.get("card_summary") or []],
        "judge_verdict": "incorrect" if failures else "correct",
        "error_summary": failures,
    }


def _interactive_final_verdict(turn_traces: List[Dict[str, Any]], stop_reason: str) -> str:
    if any(turn.get("judge_verdict") == "incorrect" for turn in turn_traces):
        return "incorrect"
    if stop_reason != "intent_resolved":
        return "uncertain"
    return "correct"


class MarketingPlanningLive(RealServiceLive):
    """marketting-planning 项目 Live 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter=None):
        super().__init__(spec)
        self._adapter = adapter
        self._mock_agent_instance = None

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        return build_request(case, self.spec.project_id)

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        return provided_output_raw(case, request)

    def deliver_real(self, request: LiveRequest) -> Any:
        import time as _time
        start = _time.time()
        try:
            raw_response = deliver_raw_response(self.spec, request)
            call_status = "succeeded"
            call_error = None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raw_response = None
            call_status = "failed"
            call_error = f"marketing-planning service unavailable: {exc}"
        extracted_output = {"turns": [extract_output(raw_response, request, self.spec, max(len(request.turns or []) - 1, 0))]} if call_status == "succeeded" else {}
        latest_output = extracted_output["turns"][-1] if extracted_output.get("turns") else {}
        app_boundary = _application_boundary(request.normalized_request, latest_output)
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status=call_status,
            raw_response=raw_response,
            call_error=call_error,
            runtime_ms=int((_time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output, self.spec) if call_status == "succeeded" else [],
            project_fields=project_fields(raw_response, extracted_output, request, self.spec, app_boundary) if call_status == "succeeded" else {},
            application_boundary=app_boundary,
            interaction_mode="interactive_intent" if request.turns else "single_turn",
        )

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        return extract_output(raw_response, request, self.spec, max(len(request.turns or []) - 1, 0))

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        return project_fields(raw_response, extracted_output, request, self.spec, application_boundary)

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        return _application_boundary(request.normalized_request, extracted_output.get("turns", [-1])[-1] if extracted_output.get("turns") else {})

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        return build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output, self.spec)

    def build_interactive_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        mock_agent_turn = self._mock_agent_next_turn(case, previous_turns)
        if mock_agent_turn is not None:
            return mock_agent_turn
        user_intent = case.get("user_intent") if isinstance(case.get("user_intent"), dict) else {}
        goal = str(user_intent.get("goal") or case.get("query") or case.get("user_intent") or "")
        if not previous_turns:
            return {"query": goal, "turn_index": 1}
        missing_fields = []
        for turn in previous_turns:
            missing_fields.extend(_list(turn.get("missing_fields")))
        if "target_value" in missing_fields:
            return {"query": str(user_intent.get("target_value") or ""), "turn_index": len(previous_turns) + 1}
        if "path_types" in missing_fields:
            return {"query": "、".join(str(item) for item in _list(user_intent.get("path_type_intent"))), "turn_index": len(previous_turns) + 1}
        return {"query": goal, "turn_index": len(previous_turns) + 1}

    def _mock_agent_next_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            from impl.core.mock_agent import MockAgent, load_live_schema
            if load_live_schema(self.spec.project_id) is None:
                return None
            if not self._mock_agent_instance:
                self._mock_agent_instance = MockAgent(self.spec)
            live_feedback = {}
            if previous_turns:
                last = previous_turns[-1] if isinstance(previous_turns[-1], dict) else {}
                live_feedback = {"missing_fields": _list(last.get("missing_fields")), "stage": last.get("stage")}
            return self._mock_agent_instance.next_turn(case, previous_turns, live_feedback)
        except Exception:
            return None

    def run_interactive(self, case) -> Dict[str, Any]:
        source_case = dict(case.source_case or {})
        interaction = dict(case.interaction or {})
        policy = dict(case.policy or {})
        max_turns = max(1, int(policy.get("max_turns") or 4))
        turn_expectations = interaction.get("turn_expectations") or []
        turn_outputs = source_case.get("turn_outputs") if isinstance(source_case.get("turn_outputs"), list) else []
        transcript: List[Dict[str, Any]] = []
        turn_traces: List[Dict[str, Any]] = []
        stop_reason = "max_turns"
        session_id = f"interactive-{case.case_id}"
        start = time.time()
        raw_responses: List[Any] = []

        for _ in range(max_turns):
            next_turn = self.build_interactive_turn(source_case, turn_traces)
            transcript.append({"role": "user", "content": str(next_turn.get("query") or "")})
            request_input = {
                "case_id": case.case_id,
                "session_id": session_id,
                "shared_session": True,
                "query": next_turn.get("query"),
                "turns": transcript,
                "scenario": source_case.get("scenario") or "interactive_intent",
                "reference": source_case.get("reference") or {},
            }
            request = LiveRequest(
                project_id=self.spec.project_id,
                raw_input=request_input,
                case_id=case.case_id,
                normalized_request=self.build_request(SingleTurnCase(id=case.case_id, input=request_input)),
                execution_mode="live_service",
                session_id=session_id,
                turns=transcript,
            )
            if len(turn_traces) < len(turn_outputs):
                raw = self.deliver_provided(SingleTurnCase(id=case.case_id, input={"output": turn_outputs[len(turn_traces)]}), request)
            else:
                candidate = self.deliver_real(request)
                raw = candidate.raw_response if isinstance(candidate, LiveExecutionResult) else candidate
            raw_responses.append(raw)
            extracted_result = self.extract_output(raw, request)
            turns = extracted_result.get("turns") if isinstance(extracted_result, dict) else None
            extracted = turns[-1] if isinstance(turns, list) and turns and isinstance(turns[-1], dict) else extracted_result
            turn_trace = _interactive_turn_trace(len(turn_traces) + 1, next_turn, extracted, turn_expectations)
            turn_traces.append(turn_trace)
            transcript.append({"role": "assistant", "content": _interactive_assistant_content(extracted), "stage": extracted.get("stage") or "unknown", "extracted_summary": turn_trace.get("error_summary") or turn_trace.get("judge_verdict") or ""})
            if extracted.get("stage") == "planning" and not (extracted.get("session_summary") or {}).get("missing_fields"):
                stop_reason = "intent_resolved"
                break

        final_stage = turn_traces[-1].get("stage") if turn_traces else "unknown"
        final_verdict = _interactive_final_verdict(turn_traces, stop_reason)
        conversation_summary = {
            "turn_count": len(turn_traces),
            "final_stage": final_stage,
            "stop_reason": stop_reason,
        }
        final_output = {
            "stage": final_stage,
            "conversation_summary": conversation_summary,
            "turn_results": turn_traces,
            "final_turn": turn_traces[-1] if turn_traces else {},
        }
        trace = RunTrace(
            trace_id=f"interactive-{case.case_id}",
            project_id=self.spec.project_id,
            case_id=case.case_id,
            input=source_case,
            normalized_request={"case_id": case.case_id, "interaction_mode": "interactive_intent", "max_turns": max_turns, "policy": policy, "user_intent": source_case.get("user_intent") or source_case.get("input", {}).get("user_intent") or {}},
            raw_response={"turn_responses": raw_responses},
            extracted_output=final_output,
            execution_mode="interactive_intent",
            output_source="interactive_adapter",
            scenario=str(source_case.get("scenario") or "interactive_intent"),
            reference_contract=dict(source_case.get("reference") or {}),
            project_fields={},
            execution_trace=[
                ExecutionTraceEvent(stage="interactive_turn", status=turn.get("judge_verdict"), evidence={"turn_index": turn.get("turn_index"), "stage": turn.get("stage"), "missing_fields": turn.get("missing_fields")})
                for turn in turn_traces
            ],
            status="ok" if final_verdict == "correct" else "error",
            interaction_mode="interactive_intent",
            multi_turn_input={"user_intent": source_case.get("user_intent") or source_case.get("input", {}).get("user_intent") or {}, "policy": policy, "conversation_summary": conversation_summary},
            error="" if final_verdict == "correct" else "interactive intent incomplete",
        )
        trace.stop_reason = stop_reason
        trace.conversation_summary = conversation_summary
        live_result = LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=case.case_id,
            session_id=session_id,
            raw_input=source_case,
            normalized_request=trace.normalized_request,
            call_status="succeeded",
            raw_response={"turn_responses": raw_responses},
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=final_output,
            output_source="interactive_adapter",
            execution_trace=list(trace.execution_trace or []),
            project_fields={},
            interaction_mode="interactive_intent",
            multi_turn_state=LiveMultiTurnState(session_id=session_id, turn_index=len(turn_traces), transcript=transcript, accumulated_fields=final_output, missing_fields=_list((turn_traces[-1] if turn_traces else {}).get("missing_fields")), stop_reason=stop_reason),
        )
        trace.live_result = live_result
        judge = {
            "trace_id": trace.trace_id,
            "project_id": self.spec.project_id,
            "reasoning_summary": f"interactive_intent final_stage={final_stage}, stop_reason={stop_reason}",
        }
        attribute = {
            "trace_id": trace.trace_id,
            "project_id": self.spec.project_id,
            "case_id": case.case_id,
            "root_cause_hypothesis": "" if final_verdict == "correct" else "系统回复未满足当前 interactive_intent 的 turn_expectations 或未在 max_turns 内完成。",
        }
        return {"case_id": case.case_id, "execution_mode": "interactive_intent", "output_source": live_result.output_source, "trace": trace, "judge": judge, "attribute": attribute}
