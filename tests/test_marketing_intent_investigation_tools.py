from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "impl"
        / "projects"
        / "marketting-planning-intent"
        / "draft"
        / "tools"
        / "investigation_tools.py"
    )
    spec = importlib.util.spec_from_file_location("marketing_intent_investigation_tools_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rule_replay_reports_the_actual_homepage_rule_match(monkeypatch, tmp_path: Path):
    module = _load_module()
    source = tmp_path / "intent_recognition.py"
    source.write_text("# current business source\n", encoding="utf-8")

    class Result:
        def model_dump(self, mode="json"):
            assert mode == "json"
            return {
                "intent": "customer_portrait",
                "confidence": 1.0,
                "target_value": None,
                "path_types": None,
            }

    intent_module = SimpleNamespace(
        __file__=str(source),
        _HOMEPAGE_RULES=[
            (re.compile(r"客户.*(?:画像|分布)"), SimpleNamespace(value="customer_portrait")),
            (re.compile(r"队伍.*(?:画像|分布)"), SimpleNamespace(value="team_portrait")),
        ],
        try_rule_based_intent=lambda query, contexts: Result(),
    )
    request_module = SimpleNamespace(ContextItem=object)
    monkeypatch.setattr(
        module,
        "_business_modules",
        lambda: (intent_module, SimpleNamespace(), request_module),
    )
    monkeypatch.setattr(
        module,
        "load_project",
        lambda _project_id: SimpleNamespace(source_project=str(tmp_path)),
    )

    tool = module.build_rule_stage_replay_tool()
    result = tool.execute_fn(query="我需要队伍分布，不是客户画像", contexts=[])

    assert result.status == "succeeded"
    assert result.actual["active_branch"] == "homepage_rule"
    assert result.actual["homepage_match"] == {
        "rule_index": 0,
        "pattern": "客户.*(?:画像|分布)",
        "intent": "customer_portrait",
        "matched_text": "客户画像",
        "match_span": [10, 14],
    }
    assert result.actual["source_path"] == str(source)
    assert len(result.actual["source_sha256"]) == 64
