"""Mock source loader for draft skill.

把 config.mock_source 的 iteration_cases / unseen_cases 转成 case 列表，
让 compare 脚本只接收 case 列表，不直接依赖 config 结构。

spec/draft/draft.md 八要求数据分层：
- iteration_cases：参与 loop 的 case。
- unseen_cases：未见对照 case，只在 promotion 前跑，检测泛化退化。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union


def load_mock_source(mock_source: Union[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    if isinstance(mock_source, str):
        # 兼容旧格式：单个路径视为 iteration_cases
        cases = _load_cases_from_source(mock_source)
        return {"iteration_cases": cases, "unseen_cases": []}
    if not isinstance(mock_source, dict):
        raise TypeError(f"mock_source must be str or dict, got {type(mock_source)}")
    iteration = mock_source.get("iteration_cases")
    unseen = mock_source.get("unseen_cases")
    if not iteration:
        raise ValueError("mock_source.iteration_cases is required")
    iteration_cases = _load_cases_from_source(iteration) if iteration else []
    unseen_cases = _load_cases_from_source(unseen) if unseen else []
    return {"iteration_cases": iteration_cases, "unseen_cases": unseen_cases}


def _load_cases_from_source(source: Union[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if isinstance(source, list):
        return source
    if isinstance(source, str):
        # 路径解析：json 文件或 Python fixture 模块
        if source.endswith(".json"):
            import json
            from pathlib import Path
            return json.loads(Path(source).read_text(encoding="utf-8"))
        if source.endswith(".py"):
            import importlib.util
            spec = importlib.util.spec_from_file_location("mock_cases", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loader = getattr(module, "load_cases", None)
            if loader is None:
                raise AttributeError(f"fixture {source} must define load_cases()")
            return loader()
    raise TypeError(f"mock_source cases must be list, .json path, or .py fixture, got {type(source)}")
