from __future__ import annotations

from impl.core.adapter_v2 import ProjectAdapter
from impl.core.schema import ProjectSpec


class Adapter(ProjectAdapter):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def _load_live(self):
        from impl.projects.QA.live import QALive

        return QALive(self.spec)

    def _load_mock(self):
        from impl.projects.QA.mock import QAMock

        return QAMock(self.spec)

    def _load_judge(self):
        from impl.projects.QA.judge import QAJudge

        return QAJudge(self.spec)

    def _load_attribute(self):
        from impl.projects.QA.attribute import QAAttribute

        return QAAttribute(self.spec)
