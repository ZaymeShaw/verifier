"""llm_probe Adapter：只加载角色模块。"""
from __future__ import annotations

from impl.core.adapter_v2 import ProjectAdapter


class Adapter(ProjectAdapter):
    metadata_fields = set()

    def _load_attribute(self):
        from impl.projects.llm_probe.attribute import LlmProbeAttribute
        return LlmProbeAttribute(self.spec)

    def _load_judge(self):
        from impl.projects.llm_probe.judge import LlmProbeJudge
        return LlmProbeJudge(self.spec)

    def _load_live(self):
        from impl.projects.llm_probe.live import LlmProbeLive
        return LlmProbeLive(self.spec)

    def _load_mock(self):
        from impl.projects.llm_probe.mock import LlmProbeMock
        return LlmProbeMock(self.spec)
