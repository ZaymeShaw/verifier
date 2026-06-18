from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class NormalizedCaseInteraction:
    case_id: str
    mode: str
    source_case: Dict[str, Any]
    execution_input: Dict[str, Any]
    interaction: Dict[str, Any]
    adapter_payload: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)


def normalize_case_interaction(project_id: str, case: Dict[str, Any], index: int = 0) -> NormalizedCaseInteraction:
    case_id = str(case.get("id") or case.get("case_id") or f"case-{index + 1}")
    interaction = case.get("interaction") if isinstance(case.get("interaction"), dict) else None
    if interaction:
        mode = str(interaction.get("mode") or "single_run")
        normalized_interaction = dict(interaction)
    elif isinstance(case.get("turns"), list):
        mode = "static_turns"
        normalized_interaction = {"mode": mode, "turns": list(case.get("turns") or [])}
    else:
        mode = "single_run"
        normalized_interaction = {"mode": mode}

    execution_input = _execution_input(case, case_id, mode)
    adapter_payload = {
        key: value
        for key, value in case.items()
        if key not in {"id", "case_id", "selected", "source", "status", "expected_intent"}
    }
    return NormalizedCaseInteraction(
        case_id=case_id,
        mode=mode,
        source_case=case,
        execution_input=execution_input,
        interaction=normalized_interaction,
        adapter_payload=adapter_payload,
        policy=dict((normalized_interaction.get("policy") or {}) if isinstance(normalized_interaction.get("policy"), dict) else {}),
    )


def _execution_input(case: Dict[str, Any], case_id: str, mode: str) -> Dict[str, Any]:
    if any(key in case for key in ("input", "output", "reference", "metadata", "scenario")):
        result = {key: case[key] for key in ("input", "output", "reference", "metadata", "scenario") if key in case}
    else:
        result = {
            key: value
            for key, value in case.items()
            if key not in {"id", "case_id", "selected", "source", "status", "expected_intent", "interaction", "mock_agent"}
        }
    if mode == "static_turns" and "turns" in case:
        result["turns"] = case["turns"]
    result["case_id"] = case_id
    return result
