"""llm_probe Mock：fixture 为主，动态生成只产信封形状。"""
from __future__ import annotations

from typing import Any, Dict

from impl.core.mock_protocol import ProjectMock, SingleTurnMock
from impl.projects.llm_probe.capability import default_capability_ref, load_capability_map, mock_body


class LlmProbeMock(SingleTurnMock, ProjectMock):
    def build_user_intent(self, scenario: str):
        from impl.core.mock_agent import MockAgent, build_spec_from_project

        agent = MockAgent(self.spec)
        build_spec = build_spec_from_project(self.spec, scenario=scenario)
        return MockAgent.intent_output(agent.build_intent(build_spec))

    def build_initial_request(self, intent) -> Dict[str, Any]:
        query = str(getattr(intent, "query", "") or getattr(intent, "user_intent", "") or "")
        mapping = load_capability_map()
        ref = str(getattr(intent, "scenario", "") or "").strip()
        if ref not in mapping:
            ref = default_capability_ref()
        return {
            "body": mock_body(ref, query),
            "method": "POST",
            "capability_ref": ref,
        }
