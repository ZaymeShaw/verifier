from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_registry_module():
    path = Path(__file__).with_name("api_check_registry.py")
    spec = importlib.util.spec_from_file_location("api_check_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    registry = _load_registry_module()
    print(json.dumps(registry.visible_api_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
