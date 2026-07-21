from __future__ import annotations

from impl.core.adapter_v2 import ProjectAdapter
from impl.core.schema import ProjectSpec
from impl.projects.client_search.mock import ClientSearchMock


class Adapter(ProjectAdapter):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def _load_live(self):
        from impl.projects.client_search.live import ClientSearchLive
        return ClientSearchLive(self.spec)

    def _load_mock(self):
        return ClientSearchMock(self.spec)

    def _load_judge(self):
        from impl.projects.client_search.judge import ClientSearchJudge
        return ClientSearchJudge(self.spec)

    def _load_attribute(self):
        from impl.projects.client_search.attribute import ClientSearchAttribute

        return ClientSearchAttribute(self.spec, self)
