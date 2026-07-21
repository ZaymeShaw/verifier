from types import SimpleNamespace

from impl.projects.client_search.draft.tools import investigation_tools
from impl.projects.client_search.tools.rule_verify import build_rule_verify_tool
from impl.projects.client_search.tools.field_capability import build_field_capability_tool
from impl.projects.client_search.attribute import _build_project_attribute_context
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


def test_rule_verify_returns_only_matching_nested_rules(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "rules:\n"
        "  - name: son\n"
        "    fields: [familyInfo.familyrelation, familyInfo.familyclientsex]\n"
        "  - name: premium\n"
        "    fields: [annPremSegNum]\n",
        encoding="utf-8",
    )
    tool = build_rule_verify_tool("", str(rules))

    result = tool.execute_fn(field="familyInfo.familyclientsex")

    assert result.status == "succeeded"
    assert result.actual["rules"] == {
        "rules": [{"name": "son", "fields": ["familyInfo.familyrelation", "familyInfo.familyclientsex"]}],
    }
    assert "annPremSegNum" not in str(result.actual)


def test_rule_verify_rejects_unfiltered_full_export(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []\n", encoding="utf-8")
    tool = build_rule_verify_tool("", str(rules))

    result = tool.execute_fn()

    assert result.status == "failed"
    assert "full configuration export is not supported" in result.error
    assert tool.parameters["anyOf"] == [
        {"required": ["keyword"]},
        {"required": ["field"]},
    ]
    assert "不传则不按该字段过滤" not in tool.parameters["properties"]["keyword"]["description"]


def test_rule_verify_reports_inconclusive_when_nothing_matches(tmp_path):
    mappings = tmp_path / "mappings.yaml"
    rules = tmp_path / "rules.yaml"
    mappings.write_text("clientAge: age\n", encoding="utf-8")
    rules.write_text("rules:\n  - name: premium\n    field: annPremSegNum\n", encoding="utf-8")
    tool = build_rule_verify_tool(str(mappings), str(rules))

    result = tool.execute_fn(keyword="impossible-keyword")

    assert result.status == "inconclusive"
    assert result.actual["mappings"] == {"note": "no mapping matched keyword 'impossible-keyword'"}
    assert result.actual["rules"] == {"note": "no rule matched keyword 'impossible-keyword'"}


def test_rule_verify_reports_configuration_load_failure(tmp_path):
    malformed = tmp_path / "rules.yaml"
    malformed.write_text("rules: [unterminated", encoding="utf-8")
    tool = build_rule_verify_tool("", str(malformed))

    result = tool.execute_fn(keyword="familyInfo.familyclientsex")

    assert result.status == "failed"
    assert "failed to load enhanced rules" in result.error
    assert result.evidence == ""


def test_field_capability_reports_configuration_load_failure(tmp_path):
    malformed = tmp_path / "fields.yaml"
    malformed.write_text("intents: [unterminated", encoding="utf-8")
    tool = build_field_capability_tool(str(malformed))

    result = tool.execute_fn(field="familyInfo.familyclientsex")

    assert result.status == "failed"
    assert "failed to load field definitions" in result.error


def test_client_search_attribute_requires_counterfactual_replay_for_causal_claims():
    spec = ProjectSpec(project_id="client_search", name="client_search")
    trace = RunTrace(trace_id="trace-1", project_id="client_search", extracted_output={})
    context = _build_project_attribute_context(spec, [], trace, JudgeResult("trace-1", "client_search"))

    assert context["tool_call_limit"] == 8
    assert "最小对照重放" in context["system_prompt_override"]
    assert "静态配置存在或缺失本身不能证明" in context["user_prompt_extras"]["project_attribute_strategy"]["tool_selection_policy"]


def test_case_route_replay_retains_real_match_and_capture_shape(tmp_path, monkeypatch):
    class FakeMatcher:
        def __init__(self):
            self._last_matched_patterns = []

        def _preprocess_query(self, query):
            return query

        async def match(self, query):
            self._last_matched_patterns = [{
                "rule_name": "name",
                "pattern": "姓名是(.+)",
                "matched_text": query,
                "match_type": "regular",
            }]
            return [SimpleNamespace(
                field="searchClientName",
                operator=SimpleNamespace(value="MATCH"),
                value=query.removeprefix("姓名是"),
            )]

    monkeypatch.setattr(
        investigation_tools,
        "load_project",
        lambda project_id: SimpleNamespace(source_project=str(tmp_path)),
    )
    monkeypatch.setattr(
        investigation_tools.importlib,
        "import_module",
        lambda name: SimpleNamespace(Level2EnhancedMatcher=FakeMatcher),
    )

    result = investigation_tools.build_investigation_case_route_replay_tool().execute_fn(
        query="姓名是张伟的人"
    )

    assert result.status == "succeeded"
    assert result.actual["stage"] == "level2_enhanced_matcher"
    assert result.actual["conditions"] == [{
        "field": "searchClientName",
        "operator": "MATCH",
        "value": "张伟的人",
    }]
    assert result.actual["matched_patterns"][0]["capture_groups"] == ["张伟的人"]
    assert "does not execute L1" in result.boundary_limits[1]
