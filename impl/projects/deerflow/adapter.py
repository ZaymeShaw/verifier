"""deerflow 项目的 Adapter（scaffold 生成，待填充）。

继承 ProjectAdapter（来自 impl.core.adapter_v2），只做加载和暴露，不承载业务逻辑。
合规检查要求：adapter 只允许 _load_* 方法，禁止业务方法（build_*/normalize_* 等）。
"""
from __future__ import annotations

from impl.core.adapter_v2 import ProjectAdapter


class Adapter(ProjectAdapter):
    """deerflow 项目 Adapter（scaffold 待填充）。"""

    metadata_fields = set()

    def _load_attribute(self):
        from impl.projects.deerflow.attribute import DeerflowAttribute
        return DeerflowAttribute(self.spec)

    def _load_judge(self):
        from impl.projects.deerflow.judge import DeerflowJudge
        return DeerflowJudge(self.spec)

    def _load_live(self):
        from impl.projects.deerflow.live import DeerflowLive
        return DeerflowLive(self.spec, self)

    def _load_mock(self):
        from impl.projects.deerflow.mock import DeerflowMock
        return DeerflowMock(self.spec)
