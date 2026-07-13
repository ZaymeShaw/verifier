from __future__ import annotations

import importlib.util
from pathlib import Path

from impl.core.adapter_v2 import ProjectAdapter
from impl.core.schema import ProjectSpec


class Adapter(ProjectAdapter):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)
    def _load_live(self):
        path = Path(self.spec.root) / "live.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_live", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingIntentLive(self.spec)

    def _load_mock(self):
        path = Path(self.spec.root) / "mock.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_mock", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingIntentMock(self.spec)

    def _load_judge(self):
        path = Path(self.spec.root) / "judge.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_judge", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingIntentJudge(self.spec)

    def _load_attribute(self):
        path = Path(self.spec.root) / "attribute.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_attribute", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingIntentAttribute(self.spec)

    def _load_tools(self):
        path = Path(self.spec.root) / "tools.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_tools", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingIntentTools(self.spec)
