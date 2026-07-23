from __future__ import annotations

import importlib.util

from impl.core.adapter_v2 import ProjectAdapter
from impl.core.schema import ProjectSpec


class Adapter(ProjectAdapter):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def _load_live(self):
        path = self.spec.project_package_path(
            "live.py", field_path="adapter.live", expected_type="file"
        )
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_live", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningLive(self.spec, self)

    def _load_mock(self):
        path = self.spec.project_package_path(
            "mock.py", field_path="adapter.mock", expected_type="file"
        )
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_mock", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningMock(self.spec)

    def _load_judge(self):
        path = self.spec.project_package_path(
            "judge.py", field_path="adapter.judge", expected_type="file"
        )
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_judge", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningJudge(self.spec, self)

    def _load_attribute(self):
        path = self.spec.project_package_path(
            "attribute.py", field_path="adapter.attribute", expected_type="file"
        )
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_attribute", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningAttribute(self.spec, self)
