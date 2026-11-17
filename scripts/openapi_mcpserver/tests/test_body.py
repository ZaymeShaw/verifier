import copy

import pytest

from curl_mcp.body import merge, resolve
from curl_mcp.config import Settings, validate_environment


def settings(fields):
    return Settings.model_validate({"operations": {"query": {
        "url": "https://example.invalid/query", "auth": None, "inject_body": fields,
    }}})


def test_nested_fields_preserve_query_and_replace_configured_values():
    template = {
        "source": "askbob", "session_id": "${session_id}",
        "extra": {"queryArgs": {"agent": "${env.AGENT}", "time": "${time_utc8}"}},
        "items": ["${env.AGENT}", 1, False, None], "empty": {},
    }
    original = copy.deepcopy(template)
    settings(template)
    body = {"extra": {"queryArgs": {"query": "customer", "agent": "untrusted"}},
            "items": ["old"], "empty": {"old": True}}
    fields = resolve(template, {"session_id": "session", "time_utc8": "time"}, {"AGENT": "007"})
    merge(body, fields)
    assert body == {
        "source": "askbob", "session_id": "session",
        "extra": {"queryArgs": {"query": "customer", "agent": "007", "time": "time"}},
        "items": ["007", 1, False, None], "empty": {},
    }
    body["items"].append("changed")
    assert template == original


def test_nested_environment_requirements_are_checked_before_startup():
    config = settings({"nested": {"user": "${env.USER_ID}"}, "list": ["${env.AGENT}"]})
    with pytest.raises(ValueError, match="Missing environment variables: AGENT, USER_ID"):
        validate_environment(config, {"AGENT": " "})
    validate_environment(config, {"USER_ID": "user", "AGENT": "007"})
    with pytest.raises(ValueError, match="Missing environment variable: AGENT"):
        resolve(config.operations["query"].inject_body, {}, {"USER_ID": "user"})


@pytest.mark.parametrize("value", ["${env.}", "${unknown}", "prefix-${session_id}", "${env.KEY"])
def test_invalid_placeholders_are_rejected_when_loading(value):
    with pytest.raises(ValueError, match="whole-value"):
        settings({"nested": [value]})


def test_old_pointer_configuration_is_rejected():
    with pytest.raises(ValueError, match="not JSON pointers"):
        settings({"/user_id": {"source": "env", "name": "USER_ID"}})


def test_resolved_environment_value_is_not_evaluated_again():
    assert resolve("${env.KEY}", {}, {"KEY": "${unknown}"}) == "${unknown}"


def test_nested_injection_rejects_non_object_target():
    with pytest.raises(ValueError, match="non-object"):
        merge({"extra": "text"}, {"extra": {"agent": "007"}})
