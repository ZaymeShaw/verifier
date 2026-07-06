from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_registry_module():
    path = Path(__file__).with_name("fixture_check_registry.py")
    spec = importlib.util.spec_from_file_location("fixture_check_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


registry = _load_registry_module()


@pytest.mark.parametrize("check", registry.FIXTURE_CHECKS, ids=lambda item: item.name)
def test_registered_fixture_check_runs(check):
    check.run()
